"""Typed, deterministic tools used by the compliance graph."""

import re
from datetime import date
from itertools import combinations
from statistics import fmean
from typing import Protocol

from compliance.config.settings import Settings
from compliance.schemas import (
    Citation,
    CitationValidation,
    ComplianceAssessment,
    CrossReference,
    FrameworkRetrieval,
    FrameworkScope,
    FrameworkTarget,
    RetrievalRequest,
    RetrievedClause,
    RiskRating,
    TransactionFacts,
    TransactionPayload,
)

_REQUIRED_FACTS = (
    "amount",
    "currency",
    "counterparty_type",
    "jurisdictions",
    "instrument",
    "kyc_status",
)
_FRAMEWORKS = {
    "IN": FrameworkTarget(framework="RBI", jurisdiction="IN"),
    "EU": FrameworkTarget(framework="MiFID II", jurisdiction="EU"),
    "US": FrameworkTarget(framework="Basel III", jurisdiction="GLOBAL"),
    "GLOBAL": FrameworkTarget(framework="Basel III", jurisdiction="GLOBAL"),
}
_TERM = re.compile(r"[A-Za-z][A-Za-z-]{4,}")
_IGNORED_TERMS = {
    "about",
    "after",
    "before",
    "being",
    "shall",
    "should",
    "their",
    "these",
    "those",
    "under",
    "which",
}


class SearchTool(Protocol):
    async def search(
        self,
        query: str,
        *,
        as_of: date | None = None,
        jurisdictions: list[str] | None = None,
        frameworks: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedClause]: ...


def extract_transaction(payload: TransactionPayload) -> TransactionFacts:
    missing = [name for name in _REQUIRED_FACTS if getattr(payload, name) is None]
    return TransactionFacts(
        txn_id=payload.txn_id,
        amount=payload.amount,
        currency=payload.currency,
        counterparty_type=payload.counterparty_type,
        jurisdictions=payload.jurisdictions or [],
        instrument=payload.instrument,
        kyc_status=payload.kyc_status,
        missing_fields=missing,
        high_risk_jurisdiction=payload.high_risk_jurisdiction,
        large_exposure_threshold_exceeded=payload.large_exposure_threshold_exceeded,
        appropriateness_assessed=payload.appropriateness_assessed,
        priority_sector_reporting_required=payload.priority_sector_reporting_required,
    )


def classify_frameworks(facts: TransactionFacts) -> FrameworkScope:
    targets: list[FrameworkTarget] = []
    for jurisdiction in facts.jurisdictions:
        target = _FRAMEWORKS[jurisdiction]
        if target not in targets:
            targets.append(target)
    return FrameworkScope(targets=targets)


def retrieval_request(
    facts: TransactionFacts, target: FrameworkTarget, top_k: int
) -> RetrievalRequest:
    values = [
        "transaction",
        str(facts.amount) if facts.amount is not None else "",
        facts.currency or "",
        facts.counterparty_type or "",
        facts.instrument or "",
        "KYC complete" if facts.kyc_status else "KYC incomplete or unknown",
    ]
    return RetrievalRequest(
        query=" ".join(value for value in values if value),
        framework=target.framework,
        jurisdiction=target.jurisdiction,
        top_k=top_k,
    )


async def retrieve_framework(
    request: RetrievalRequest, searcher: SearchTool
) -> FrameworkRetrieval:
    clauses = await searcher.search(
        request.query,
        jurisdictions=[request.jurisdiction],
        frameworks=[request.framework],
        top_k=request.top_k,
    )
    target = FrameworkTarget(
        framework=request.framework,
        jurisdiction=request.jurisdiction,
    )
    return FrameworkRetrieval(target=target, clauses=clauses)


def _terms(text: str) -> set[str]:
    return {term.lower() for term in _TERM.findall(text) if term.lower() not in _IGNORED_TERMS}


def cross_reference_obligations(
    retrievals: list[FrameworkRetrieval],
) -> list[CrossReference]:
    references: list[CrossReference] = []
    for left, right in combinations(retrievals, 2):
        if left.target.framework == right.target.framework:
            continue
        for left_clause in left.clauses:
            for right_clause in right.clauses:
                shared = sorted(_terms(left_clause.clause.text) & _terms(right_clause.clause.text))
                if len(shared) >= 2:
                    references.append(
                        CrossReference(
                            frameworks=[left.target.framework, right.target.framework],
                            clause_ids=[
                                left_clause.clause.clause_id,
                                right_clause.clause.clause_id,
                            ],
                            shared_terms=shared,
                        )
                    )
    return references


def _citations(retrievals: list[FrameworkRetrieval], narrowed: bool) -> list[Citation]:
    clauses = [item for retrieval in retrievals for item in retrieval.clauses]
    selected = clauses[:1] if narrowed else clauses
    return [
        Citation(
            clause_id=item.clause.clause_id,
            clause_path=item.clause.clause_path,
            quote=item.clause.text,
            support=1.0,
            effective_from=item.clause.effective_from,
            effective_to=item.clause.effective_to,
        )
        for item in selected
    ]


def _actions(
    facts: TransactionFacts, scope: FrameworkScope, cross_refs: list[CrossReference]
) -> list[str]:
    actions = [
        f"Review the cited {target.framework} obligations before processing."
        for target in scope.targets
    ]
    if facts.kyc_status is False:
        actions.insert(0, "Resolve KYC before processing the transaction.")
    if facts.high_risk_jurisdiction:
        actions.insert(0, "Apply enhanced due diligence for the high-risk jurisdiction.")
    if facts.large_exposure_threshold_exceeded:
        actions.insert(0, "Escalate the large exposure threshold breach before processing.")
    if facts.appropriateness_assessed is False:
        actions.insert(0, "Complete an appropriateness assessment before offering the product.")
    if facts.priority_sector_reporting_required:
        actions.insert(0, "Report the lending exposure under the priority sector category.")
    actions.extend(
        f"Review the combined obligations cited under {' and '.join(item.frameworks)}."
        for item in cross_refs
    )
    return list(dict.fromkeys(actions))


def _risk_rating(facts: TransactionFacts) -> RiskRating:
    high_risk = (
        facts.kyc_status is False
        or facts.large_exposure_threshold_exceeded is True
        or facts.appropriateness_assessed is False
    )
    risk = RiskRating.HIGH if high_risk else RiskRating.LOW
    return RiskRating.MEDIUM if facts.missing_fields else risk


def assess_compliance(
    facts: TransactionFacts,
    scope: FrameworkScope,
    retrievals: list[FrameworkRetrieval],
    cross_refs: list[CrossReference],
    *,
    narrowed: bool,
) -> ComplianceAssessment:
    unresolved = [f"Provide {field}." for field in facts.missing_fields]
    risk = _risk_rating(facts)
    actions = _actions(facts, scope, cross_refs)
    return ComplianceAssessment(
        txn_id=facts.txn_id,
        risk_rating=risk,
        applicable_regulations=[target.framework for target in scope.targets],
        required_actions=actions,
        citations=_citations(retrievals, narrowed),
        unresolved_questions=unresolved,
        model_version="deterministic-assessment-v1",
        prompt_version="source-actions-v1-narrow" if narrowed else "source-actions-v1",
    )


def validate_assessment(
    assessment: ComplianceAssessment,
    retrievals: list[FrameworkRetrieval],
    settings: Settings,
) -> CitationValidation:
    sources = {
        item.clause.clause_id: item.clause
        for retrieval in retrievals
        for item in retrieval.clauses
    }
    problems: list[str] = []
    for citation in assessment.citations:
        source = sources.get(citation.clause_id)
        if source is None or not citation.quote.strip() or citation.quote not in source.text:
            problems.append(f"Unsupported citation {citation.clause_id}.")
    if assessment.citations:
        mean_support = fmean(item.support for item in assessment.citations)
        if mean_support < settings.min_citation_support:
            problems.append("Mean citation support is below the configured threshold.")
    elif sources and assessment.required_actions:
        problems.append("The assessment has actions without citations.")
    return CitationValidation(valid=not problems, problems=problems)


def fallback_assessment(
    assessment: ComplianceAssessment, validation: CitationValidation
) -> ComplianceAssessment:
    unresolved = [*assessment.unresolved_questions, *validation.problems]
    return assessment.model_copy(
        update={
            "required_actions": [],
            "citations": [],
            "unresolved_questions": unresolved,
            "prompt_version": "source-actions-v1-fallback",
        }
    )
