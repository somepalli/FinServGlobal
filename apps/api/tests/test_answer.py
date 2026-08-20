from datetime import date

import pytest
from compliance.config.settings import Settings
from compliance.retrieval.answer import (
    LocalLlmGenerator,
    UnsafeLlmEndpointError,
    build_answer,
)
from compliance.schemas import Clause, RetrievedClause, TextPair


class _Generator:
    def __init__(self, response: str) -> None:
        self._response = response

    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str:
        assert question
        assert clauses
        return self._response


class _ExactSupportScorer:
    def score_pairs(self, pairs: list[TextPair]) -> list[float]:
        return [0.99 if pair.query == pair.passage else 0.1 for pair in pairs]


class _LowSupportScorer:
    def score_pairs(self, pairs: list[TextPair]) -> list[float]:
        return [0.05 for _pair in pairs]


def _settings(**values: object) -> Settings:
    return Settings(database_url="postgresql://u:p@localhost/db", **values)


def _retrieved() -> RetrievedClause:
    clause = Clause(
        clause_id="rbi-kyc:v1:52",
        doc_id="rbi-kyc",
        version="v1",
        jurisdiction="IN",
        framework="RBI",
        clause_path="Chapter VII > 52",
        text="Banks must retain records for five years. Records must remain available.",
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    return RetrievedClause(
        clause=clause,
        dense_score=0.8,
        sparse_score=0.7,
        rerank_score=0.9,
    )


@pytest.mark.asyncio
async def test_citation_quote_is_a_verbatim_source_span() -> None:
    source = _retrieved()
    generated = "Banks must retain records for five years."

    answer = await build_answer(
        "How long must banks retain records?",
        [source],
        _settings(),
        as_of=date(2021, 1, 1),
        generator=_Generator(generated),
        scorer=_ExactSupportScorer(),
    )

    assert answer.synthesised
    assert answer.text == generated
    assert answer.citations
    assert all(citation.quote in source.clause.text for citation in answer.citations)
    assert answer.citations[0].effective_from == source.clause.effective_from
    assert answer.citations[0].effective_to == source.clause.effective_to


@pytest.mark.asyncio
async def test_unanswerable_question_returns_raw_clauses() -> None:
    source = _retrieved()

    answer = await build_answer(
        "What is the capital adequacy ratio for Martian banks?",
        [source],
        _settings(min_citation_support=0.6),
        generator=_Generator("Martian banks must maintain a 900 percent ratio."),
        scorer=_LowSupportScorer(),
    )

    assert not answer.synthesised
    assert "Martian" not in answer.text
    assert source.clause.text in answer.text
    assert answer.citations[0].quote == source.clause.text
    assert answer.citations[0].effective_from == source.clause.effective_from


def test_external_llm_endpoint_is_rejected() -> None:
    settings = _settings(llm_base_url="https://api.example.com/v1")

    with pytest.raises(UnsafeLlmEndpointError, match="internal LLM"):
        LocalLlmGenerator(settings)
