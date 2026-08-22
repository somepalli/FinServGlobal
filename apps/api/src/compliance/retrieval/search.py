"""Run date-scoped dense and lexical retrieval with server-side RRF."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from functools import lru_cache
from typing import Protocol, cast

from pydantic import ValidationError
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import QueryResponse

from compliance.config.settings import Settings, get_settings
from compliance.retrieval.embed import BgeM3Embedder
from compliance.schemas import Clause, QueryEmbedding, RetrievedClause


class SearchError(RuntimeError):
    pass


class _QueryEmbedder(Protocol):
    def embed_query(self, query: str) -> QueryEmbedding: ...


def _timestamp(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _date_conditions(as_of: date) -> list[models.Condition]:
    timestamp = _timestamp(as_of)
    open_ended = models.IsNullCondition(is_null=models.PayloadField(key="effective_to"))
    not_expired = models.FieldCondition(key="effective_to", range=models.Range(gt=timestamp))
    return [
        models.FieldCondition(key="effective_from", range=models.Range(lte=timestamp)),
        models.Filter(should=[not_expired, open_ended]),
    ]


def _match_filter(field: str, values: list[str] | None) -> models.FieldCondition | None:
    if not values:
        return None
    return models.FieldCondition(key=field, match=models.MatchAny(any=values))


def _query_filter(
    as_of: date,
    jurisdictions: list[str] | None,
    frameworks: list[str] | None,
) -> models.Filter:
    conditions = _date_conditions(as_of)
    for condition in (
        _match_filter("jurisdiction", jurisdictions),
        _match_filter("framework", frameworks),
    ):
        if condition is not None:
            conditions.append(condition)
    return models.Filter(must=conditions)


def _payload_clause(payload: Mapping[str, object]) -> Clause:
    values = dict(payload)
    for field in ("effective_from", "effective_to"):
        value = values.get(field)
        if isinstance(value, int):
            values[field] = datetime.fromtimestamp(value, tz=UTC).date()
    try:
        return Clause.model_validate(values)
    except ValidationError as exc:
        raise SearchError(f"invalid clause payload: {exc}") from exc


def _score_by_id(response: QueryResponse) -> dict[str, float]:
    return {str(point.id): point.score for point in response.points}


class HybridSearcher:
    def __init__(
        self,
        client: QdrantClient,
        embedder: _QueryEmbedder,
        settings: Settings,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._settings = settings

    async def search(
        self,
        query: str,
        *,
        as_of: date | None = None,
        jurisdictions: list[str] | None = None,
        frameworks: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedClause]:
        limit = self._settings.retrieval_top_k if top_k is None else top_k
        if limit < 1:
            raise SearchError("top_k must be positive")
        active_date = as_of or date.today()
        embedding = await asyncio.to_thread(self._embedder.embed_query, query)
        query_filter = _query_filter(active_date, jurisdictions, frameworks)
        responses = await asyncio.to_thread(self._query, embedding, query_filter, limit)
        return self._results(*responses)

    def _query(
        self, embedding: QueryEmbedding, query_filter: models.Filter, limit: int
    ) -> tuple[QueryResponse, QueryResponse, QueryResponse]:
        candidate_limit = max(limit, self._settings.retrieval_top_k)
        dense = models.Prefetch(
            query=embedding.dense,
            using="dense",
            filter=query_filter,
            limit=candidate_limit,
        )
        sparse_vector = models.SparseVector(
            indices=embedding.sparse_indices, values=embedding.sparse_values
        )
        sparse = models.Prefetch(
            query=sparse_vector,
            using="sparse",
            filter=query_filter,
            limit=candidate_limit,
        )
        hybrid = self._client.query_points(
            collection_name=self._settings.qdrant_collection,
            prefetch=[dense, sparse],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        dense_scores = self._component_query(
            embedding.dense, "dense", query_filter, candidate_limit
        )
        sparse_scores = self._component_query(
            sparse_vector, "sparse", query_filter, candidate_limit
        )
        return hybrid, dense_scores, sparse_scores

    def _component_query(
        self,
        vector: list[float] | models.SparseVector,
        vector_name: str,
        query_filter: models.Filter,
        limit: int,
    ) -> QueryResponse:
        return self._client.query_points(
            collection_name=self._settings.qdrant_collection,
            query=vector,
            using=vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=False,
        )

    def _results(
        self,
        hybrid: QueryResponse,
        dense: QueryResponse,
        sparse: QueryResponse,
    ) -> list[RetrievedClause]:
        dense_scores = _score_by_id(dense)
        sparse_scores = _score_by_id(sparse)
        results: list[RetrievedClause] = []
        for point in hybrid.points:
            if point.payload is None:
                raise SearchError(f"point {point.id} has no clause payload")
            payload = cast(Mapping[str, object], point.payload)
            results.append(
                RetrievedClause(
                    clause=_payload_clause(payload),
                    dense_score=dense_scores.get(str(point.id), 0.0),
                    sparse_score=sparse_scores.get(str(point.id), 0.0),
                    rerank_score=None,
                )
            )
        return results


@lru_cache(maxsize=1)
def _default_searcher() -> HybridSearcher:
    settings = get_settings()
    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key_value)
    return HybridSearcher(qdrant, BgeM3Embedder(settings), settings)


async def search(
    query: str,
    *,
    as_of: date | None = None,
    jurisdictions: list[str] | None = None,
    frameworks: list[str] | None = None,
    top_k: int | None = None,
) -> list[RetrievedClause]:
    return await _default_searcher().search(
        query,
        as_of=as_of,
        jurisdictions=jurisdictions,
        frameworks=frameworks,
        top_k=top_k,
    )
