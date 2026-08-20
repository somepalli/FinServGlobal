from datetime import date
from warnings import catch_warnings, simplefilter

import pytest
from compliance.config.settings import Settings
from compliance.retrieval.search import HybridSearcher, SearchError
from compliance.retrieval.store import RegulationStore
from compliance.schemas import Clause, ClauseEmbedding, QueryEmbedding
from qdrant_client import QdrantClient


class _QueryEmbedder:
    def embed_query(self, query: str) -> QueryEmbedding:
        assert query
        return QueryEmbedding(
            dense=[1.0, 0.0, 0.0],
            sparse_indices=[312],
            sparse_values=[1.0],
        )


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://u:p@localhost/db",
        qdrant_dense_size=3,
        retrieval_top_k=10,
        rerank_top_k=8,
    )


def _clause(
    clause_id: str,
    path: str,
    effective_from: date,
    *,
    jurisdiction: str = "IN",
    framework: str = "RBI",
) -> Clause:
    return Clause(
        clause_id=clause_id,
        doc_id=clause_id.split(":")[0],
        version="v1",
        jurisdiction=jurisdiction,
        framework=framework,
        clause_path=path,
        text=f"Source text for {path}.",
        effective_from=effective_from,
        effective_to=None,
    )


def _embedding(clause: Clause, dense: list[float], sparse_index: int) -> ClauseEmbedding:
    return ClauseEmbedding(
        clause_id=clause.clause_id,
        dense=dense,
        sparse_indices=[sparse_index],
        sparse_values=[1.0],
    )


def _searcher(
    clauses: list[Clause], embeddings: list[ClauseEmbedding]
) -> tuple[QdrantClient, HybridSearcher]:
    client = QdrantClient(":memory:")
    settings = _settings()
    store = RegulationStore(client, settings)
    with catch_warnings():
        simplefilter("ignore", UserWarning)
        store.ensure_collection()
    store.upsert(clauses, embeddings)
    return client, HybridSearcher(client, _QueryEmbedder(), settings)


@pytest.mark.asyncio
async def test_clause_number_query_succeeds_where_dense_only_fails() -> None:
    target = _clause("rbi:v1:3.1.2", "Chapter III > 3.1 > 3.1.2", date(2020, 1, 1))
    first = _clause("rbi:v1:9", "Chapter III > 9", date(2020, 1, 1))
    second = _clause("rbi:v1:10", "Chapter III > 10", date(2020, 1, 1))
    clauses = [target, first, second]
    embeddings = [
        _embedding(target, [0.0, 1.0, 0.0], 312),
        _embedding(first, [1.0, 0.0, 0.0], 900),
        _embedding(second, [0.9, 0.1, 0.0], 1000),
    ]
    client, searcher = _searcher(clauses, embeddings)

    dense_only = client.query_points("regulations", query=[1.0, 0.0, 0.0], using="dense", limit=1)
    results = await searcher.search("3.1.2", as_of=date(2021, 1, 1), top_k=1)

    assert dense_only.points[0].payload is not None
    assert dense_only.points[0].payload["clause_id"] != target.clause_id
    assert results[0].clause.clause_id == target.clause_id
    assert results[0].sparse_score > 0
    client.close()


@pytest.mark.asyncio
async def test_as_of_excludes_clauses_that_start_later() -> None:
    current = _clause("rbi:v1:1", "Chapter I > 1", date(2020, 1, 1))
    future = _clause("rbi:v1:2", "Chapter I > 2", date(2022, 1, 1))
    clauses = [current, future]
    embeddings = [
        _embedding(current, [0.8, 0.2, 0.0], 312),
        _embedding(future, [1.0, 0.0, 0.0], 312),
    ]
    client, searcher = _searcher(clauses, embeddings)

    results = await searcher.search("customer", as_of=date(2021, 1, 1))

    assert [result.clause.clause_id for result in results] == [current.clause_id]
    client.close()


@pytest.mark.asyncio
async def test_jurisdiction_framework_and_date_filters_compose() -> None:
    matching = _clause("in-rbi:v1:1", "Chapter I > 1", date(2020, 1, 1))
    wrong_jurisdiction = _clause(
        "eu-rbi:v1:1",
        "Article 1",
        date(2020, 1, 1),
        jurisdiction="EU",
    )
    wrong_framework = _clause(
        "in-mifid:v1:1",
        "Article 1",
        date(2020, 1, 1),
        framework="MiFID II",
    )
    future = _clause("in-rbi:v1:2", "Chapter I > 2", date(2025, 1, 1))
    clauses = [matching, wrong_jurisdiction, wrong_framework, future]
    embeddings = [_embedding(clause, [1.0, 0.0, 0.0], 312) for clause in clauses]
    client, searcher = _searcher(clauses, embeddings)

    results = await searcher.search(
        "customer",
        as_of=date(2021, 1, 1),
        jurisdictions=["IN"],
        frameworks=["RBI"],
    )

    assert [result.clause.clause_id for result in results] == [matching.clause_id]
    client.close()


@pytest.mark.asyncio
async def test_top_k_must_be_positive() -> None:
    client, searcher = _searcher([], [])

    with pytest.raises(SearchError, match="positive"):
        await searcher.search("customer", top_k=0)
    client.close()
