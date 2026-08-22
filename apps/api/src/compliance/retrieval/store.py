"""Manage the Qdrant regulation collection and clause points."""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import QdrantClient, models

from compliance.config.settings import Settings
from compliance.schemas import Clause, ClauseEmbedding

_PAYLOAD_INDEXES = {
    "jurisdiction": models.PayloadSchemaType.KEYWORD,
    "framework": models.PayloadSchemaType.KEYWORD,
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "effective_from": models.PayloadSchemaType.INTEGER,
    "effective_to": models.PayloadSchemaType.INTEGER,
}


class RegulationStoreError(RuntimeError):
    pass


def point_id_for_clause(clause_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"finservglobal:{clause_id}")


def _timestamp(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _payload(clause: Clause) -> dict[str, object]:
    payload = clause.model_dump()
    payload["effective_from"] = _timestamp(clause.effective_from)
    payload["effective_to"] = (
        _timestamp(clause.effective_to) if clause.effective_to is not None else None
    )
    return payload


def _batches[T](items: list[T], size: int) -> Iterable[list[T]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


class RegulationStore:
    def __init__(self, client: QdrantClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._ready = False

    def ensure_collection(self) -> None:
        if self._ready:
            return
        name = self._settings.qdrant_collection
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self._settings.qdrant_dense_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={"sparse": models.SparseVectorParams()},
            )
        for field_name, schema in _PAYLOAD_INDEXES.items():
            self._client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=schema,
                wait=True,
            )
        self._ready = True

    def missing_clause_ids(self, clause_ids: list[str]) -> set[str]:
        missing = set(clause_ids)
        for clause_batch in _batches(clause_ids, self._settings.qdrant_upsert_batch_size):
            records = self._client.retrieve(
                collection_name=self._settings.qdrant_collection,
                ids=[point_id_for_clause(clause_id) for clause_id in clause_batch],
                with_payload=False,
                with_vectors=False,
            )
            present = {str(record.id) for record in records}
            for clause_id in clause_batch:
                if str(point_id_for_clause(clause_id)) in present:
                    missing.discard(clause_id)
        return missing

    def upsert(self, clauses: list[Clause], embeddings: list[ClauseEmbedding]) -> None:
        embedding_by_id = {item.clause_id: item for item in embeddings}
        if len(embedding_by_id) != len(embeddings):
            raise RegulationStoreError("duplicate clause embeddings")
        if set(embedding_by_id) != {clause.clause_id for clause in clauses}:
            raise RegulationStoreError("clauses and embeddings do not align")
        points = [self._point(clause, embedding_by_id[clause.clause_id]) for clause in clauses]
        for point_batch in _batches(points, self._settings.qdrant_upsert_batch_size):
            self._client.upsert(
                collection_name=self._settings.qdrant_collection,
                points=point_batch,
                wait=True,
            )

    def _point(self, clause: Clause, embedding: ClauseEmbedding) -> models.PointStruct:
        if len(embedding.dense) != self._settings.qdrant_dense_size:
            raise RegulationStoreError(
                f"{clause.clause_id}: dense vector has {len(embedding.dense)} "
                f"dimensions; expected {self._settings.qdrant_dense_size}"
            )
        return models.PointStruct(
            id=point_id_for_clause(clause.clause_id),
            vector={
                "dense": embedding.dense,
                "sparse": models.SparseVector(
                    indices=embedding.sparse_indices,
                    values=embedding.sparse_values,
                ),
            },
            payload=_payload(clause),
        )

    def close_version(self, doc_id: str, version: str, effective_to: date) -> None:
        selector = models.Filter(
            must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="version", match=models.MatchValue(value=version)),
            ]
        )
        self._client.set_payload(
            collection_name=self._settings.qdrant_collection,
            payload={"effective_to": _timestamp(effective_to)},
            points=selector,
            wait=True,
        )


def create_store(settings: Settings) -> RegulationStore:
    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key_value)
    return RegulationStore(qdrant, settings)
