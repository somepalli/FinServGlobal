from collections.abc import Sequence
from datetime import date

from compliance.config.settings import Settings
from compliance.retrieval.rerank import BgeReranker
from compliance.schemas import Clause, RetrievedClause


class _FakeRerankerModel:
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        batch_size: int,
        max_length: int,
        normalize: bool,
    ) -> float | Sequence[float]:
        assert batch_size == 4
        assert max_length == 256
        assert normalize
        return [0.95 if "specific" in pair[1] else 0.2 for pair in sentence_pairs]


def _retrieved(clause_id: str, text: str, dense_score: float) -> RetrievedClause:
    clause = Clause(
        clause_id=clause_id,
        doc_id="rbi",
        version="v1",
        jurisdiction="IN",
        framework="RBI",
        clause_path=clause_id.rpartition(":")[2],
        text=text,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    return RetrievedClause(
        clause=clause,
        dense_score=dense_score,
        sparse_score=0.0,
        rerank_score=None,
    )


def test_cross_encoder_changes_retrieval_order() -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        retrieval_top_k=3,
        rerank_top_k=2,
        reranker_batch_size=4,
        reranker_max_length=256,
    )
    initial = [
        _retrieved("rbi:v1:1", "General wording.", 0.9),
        _retrieved("rbi:v1:2", "The specific answer to the query.", 0.5),
        _retrieved("rbi:v1:3", "Other wording.", 0.4),
    ]

    reranked = BgeReranker(settings, model=_FakeRerankerModel()).rerank("specific query", initial)

    assert reranked[0].clause.clause_id == "rbi:v1:2"
    assert reranked[0].rerank_score == 0.95
    assert len(reranked) == 2
