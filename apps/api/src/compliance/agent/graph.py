"""Build the checkpointed compliance assessment graph."""

import asyncio
import sys
from typing import Literal, Protocol, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import JsonValue

from compliance.agent.tools import (
    SearchTool,
    assess_compliance,
    classify_frameworks,
    cross_reference_obligations,
    extract_transaction,
    fallback_assessment,
    retrieval_request,
    retrieve_framework,
    validate_assessment,
)
from compliance.config.settings import Settings
from compliance.schemas import (
    AuditEventInput,
    CitationValidation,
    ComplianceAssessment,
    CrossReference,
    FrameworkRetrieval,
    FrameworkScope,
    TransactionFacts,
    TransactionPayload,
)

if sys.platform == "win32":
    # Psycopg's async file-descriptor integration is incompatible with Proactor loops.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class AuditTool(Protocol):
    async def write(self, event: AuditEventInput) -> None: ...


class AgentState(TypedDict, total=False):
    payload: TransactionPayload
    facts: TransactionFacts
    scope: FrameworkScope
    retrievals: list[FrameworkRetrieval]
    cross_references: list[CrossReference]
    assessment: ComplianceAssessment
    validation: CitationValidation
    retry_count: int


class _Nodes:
    def __init__(self, searcher: SearchTool, audit: AuditTool, settings: Settings) -> None:
        self._searcher = searcher
        self._audit_writer = audit
        self._settings = settings

    async def _audit(self, txn_id: str, node: str, payload: object) -> None:
        await self._audit_writer.write(
            AuditEventInput(
                actor="compliance-agent",
                action=f"agent.{node}.completed",
                subject_id=txn_id,
                payload=cast(JsonValue, payload),
            )
        )

    async def extract(self, state: AgentState) -> AgentState:
        facts = extract_transaction(state["payload"])
        await self._audit(
            facts.txn_id,
            "extract",
            {"missing_fields": facts.missing_fields},
        )
        return {"facts": facts, "retry_count": 0}

    async def classify(self, state: AgentState) -> AgentState:
        facts = state["facts"]
        scope = classify_frameworks(facts)
        await self._audit(
            facts.txn_id,
            "classify",
            {"frameworks": [item.framework for item in scope.targets]},
        )
        return {"scope": scope}

    async def retrieve(self, state: AgentState) -> AgentState:
        facts = state["facts"]
        requests = [retrieval_request(facts, target) for target in state["scope"].targets]
        retrievals = list(
            await asyncio.gather(
                *(retrieve_framework(request, self._searcher) for request in requests)
            )
        )
        await self._audit(
            facts.txn_id,
            "retrieve",
            {
                "framework_count": len(requests),
                "clause_count": sum(len(item.clauses) for item in retrievals),
            },
        )
        return {"retrievals": retrievals}

    async def cross_reference(self, state: AgentState) -> AgentState:
        references = cross_reference_obligations(state["retrievals"])
        await self._audit(
            state["facts"].txn_id,
            "cross_reference",
            {"reference_count": len(references)},
        )
        return {"cross_references": references}

    async def assess(self, state: AgentState) -> AgentState:
        retry_count = state.get("retry_count", 0)
        assessment = assess_compliance(
            state["facts"],
            state["scope"],
            state["retrievals"],
            state["cross_references"],
            narrowed=retry_count > 0,
        )
        await self._audit(
            assessment.txn_id,
            "assess",
            {"retry_count": retry_count, "risk_rating": assessment.risk_rating.value},
        )
        return {"assessment": assessment}

    async def validate(self, state: AgentState) -> AgentState:
        validation = validate_assessment(
            state["assessment"], state["retrievals"], self._settings
        )
        retry_count = state.get("retry_count", 0)
        update: AgentState = {"validation": validation}
        if not validation.valid and retry_count > 0:
            update["assessment"] = fallback_assessment(state["assessment"], validation)
            update["retry_count"] = retry_count + 1
        elif not validation.valid:
            update["retry_count"] = retry_count + 1
        await self._audit(
            state["facts"].txn_id,
            "validate",
            {"valid": validation.valid, "retry_count": retry_count},
        )
        return update


def _validation_route(state: AgentState) -> Literal["assess", "end"]:
    if state["validation"].valid or state.get("retry_count", 0) > 1:
        return "end"
    return "assess"


def _compile(
    nodes: _Nodes, checkpointer: BaseCheckpointSaver[str] | None
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    graph = StateGraph(AgentState)
    graph.add_node("extract", nodes.extract)
    graph.add_node("classify", nodes.classify)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("cross_reference", nodes.cross_reference)
    graph.add_node("assess", nodes.assess)
    graph.add_node("validate", nodes.validate)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "cross_reference")
    graph.add_edge("cross_reference", "assess")
    graph.add_edge("assess", "validate")
    graph.add_conditional_edges("validate", _validation_route, {"assess": "assess", "end": END})
    return graph.compile(checkpointer=checkpointer)


class ComplianceAgent:
    def __init__(self, graph: CompiledStateGraph[AgentState, None, AgentState, AgentState]) -> None:
        self._graph = graph

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    async def assess(self, payload: TransactionPayload, *, thread_id: str) -> ComplianceAssessment:
        result = await self._graph.ainvoke({"payload": payload}, self._config(thread_id))
        return ComplianceAssessment.model_validate(result["assessment"])

    async def replay(self, thread_id: str) -> ComplianceAssessment:
        snapshot = await self._graph.aget_state(self._config(thread_id))
        if not snapshot.values or "assessment" not in snapshot.values:
            raise LookupError(f"no assessment checkpoint exists for thread {thread_id}")
        return ComplianceAssessment.model_validate(snapshot.values["assessment"])

    def mermaid(self) -> str:
        return self._graph.get_graph().draw_mermaid()


def build_agent(
    searcher: SearchTool,
    audit: AuditTool,
    settings: Settings,
    checkpointer: BaseCheckpointSaver[str] | None,
) -> ComplianceAgent:
    return ComplianceAgent(_compile(_Nodes(searcher, audit, settings), checkpointer))


class PostgresScreeningService:
    def __init__(self, searcher: SearchTool, audit: AuditTool, settings: Settings) -> None:
        self._searcher = searcher
        self._audit = audit
        self._settings = settings

    async def assess(self, payload: TransactionPayload, *, thread_id: str) -> ComplianceAssessment:
        async with AsyncPostgresSaver.from_conn_string(str(self._settings.database_url)) as saver:
            await saver.setup()
            agent = build_agent(self._searcher, self._audit, self._settings, saver)
            return await agent.assess(payload, thread_id=thread_id)

    async def replay(self, thread_id: str) -> ComplianceAssessment:
        async with AsyncPostgresSaver.from_conn_string(str(self._settings.database_url)) as saver:
            agent = build_agent(self._searcher, self._audit, self._settings, saver)
            return await agent.replay(thread_id)
