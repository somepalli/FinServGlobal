import asyncio
import sys
from collections.abc import Awaitable
from types import ModuleType
from typing import Protocol, cast

from openai import AsyncOpenAI

from compliance.config.settings import Settings
from compliance.eval.models import EvaluationCase, EvaluationObservation, EvaluationScores
from compliance.retrieval.answer import UnsafeLlmEndpointError, is_internal_endpoint


class _ScoreResult(Protocol):
    value: object


class _Metric(Protocol):
    def ascore(self, **kwargs: object) -> Awaitable[_ScoreResult]: ...


def _install_vertex_compatibility() -> None:
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    from langchain_core.language_models.chat_models import BaseChatModel

    # RAGAS imports this removed legacy module even when only its OpenAI adapter is used.
    module = ModuleType(module_name)
    module.__dict__["ChatVertexAI"] = BaseChatModel
    sys.modules[module_name] = module


def _metrics(client: AsyncOpenAI, settings: Settings) -> tuple[_Metric, _Metric, _Metric, _Metric]:
    _install_vertex_compatibility()
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    llm = llm_factory(
        settings.eval_judge_model,
        provider="openai",
        client=client,
        temperature=0.0,
        max_tokens=2048,
    )
    embeddings = OpenAIEmbeddings(client=client, model=settings.eval_embedding_model)
    return cast(
        tuple[_Metric, _Metric, _Metric, _Metric],
        (
            Faithfulness(llm),
            AnswerRelevancy(llm, embeddings, strictness=1),
            ContextPrecision(llm),
            ContextRecall(llm),
        ),
    )


def _number(result: _ScoreResult) -> float:
    if not isinstance(result.value, (int, float)):
        raise TypeError("RAGAS metric returned a non-numeric score")
    return float(result.value)


class RagasJudge:
    def __init__(self, settings: Settings) -> None:
        if not is_internal_endpoint(settings.llm_base_url):
            raise UnsafeLlmEndpointError("evaluation data may only be sent to an internal LLM")
        client = AsyncOpenAI(base_url=settings.llm_base_url, api_key="local-client-token")
        self._faithfulness, self._relevance, self._precision, self._recall = _metrics(
            client, settings
        )

    async def score(
        self, case: EvaluationCase, observation: EvaluationObservation
    ) -> EvaluationScores:
        contexts = observation.retrieved_contexts
        faithfulness, relevance, precision, recall = await asyncio.gather(
            self._faithfulness.ascore(
                user_input=case.question,
                response=observation.response,
                retrieved_contexts=contexts,
            ),
            self._relevance.ascore(user_input=case.question, response=observation.response),
            self._precision.ascore(
                user_input=case.question,
                reference=case.reference_answer,
                retrieved_contexts=contexts,
            ),
            self._recall.ascore(
                user_input=case.question,
                reference=case.reference_answer,
                retrieved_contexts=contexts,
            ),
        )
        return EvaluationScores(
            faithfulness=_number(faithfulness),
            answer_relevance=_number(relevance),
            context_precision=_number(precision),
            context_recall=_number(recall),
        )
