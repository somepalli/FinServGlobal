from datetime import UTC, date, datetime, time
from warnings import catch_warnings, simplefilter

import pytest
from compliance.config.settings import Settings
from compliance.retrieval.store import RegulationStore, RegulationStoreError
from compliance.schemas import Clause, ClauseEmbedding
from qdrant_client import QdrantClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://u:p@localhost/db",
        qdrant_dense_size=3,
        qdrant_upsert_batch_size=2,
    )


def _clause(version: str, effective_from: date) -> Clause:
    return Clause(
        clause_id=f"rbi-kyc-md:{version}:1",
        doc_id="rbi-kyc-md",
        version=version,
        jurisdiction="IN",
        framework="RBI",
        clause_path="Chapter I > 1",
        text="A regulated entity must identify its customer.",
        effective_from=effective_from,
        effective_to=None,
    )


def _embedding(clause: Clause) -> ClauseEmbedding:
    return ClauseEmbedding(
        clause_id=clause.clause_id,
        dense=[0.1, 0.2, 0.3],
        sparse_indices=[2, 7],
        sparse_values=[0.75, 0.25],
    )


def _store() -> tuple[QdrantClient, RegulationStore]:
    client = QdrantClient(":memory:")
    store = RegulationStore(client, _settings())
    with catch_warnings():
        simplefilter("ignore", UserWarning)
        store.ensure_collection()
    return client, store


def test_collection_has_named_dense_and_sparse_vectors() -> None:
    client, _store_instance = _store()

    parameters = client.get_collection("regulations").config.params
    assert isinstance(parameters.vectors, dict)
    assert parameters.vectors["dense"].size == 3
    assert parameters.vectors["dense"].distance.value == "Cosine"
    assert parameters.sparse_vectors is not None
    assert "sparse" in parameters.sparse_vectors
    client.close()


def test_upsert_is_idempotent_and_payload_preserves_provenance() -> None:
    client, store = _store()
    clause = _clause("v1", date(2020, 1, 1))

    store.upsert([clause], [_embedding(clause)])
    store.upsert([clause], [_embedding(clause)])

    assert client.count("regulations", exact=True).count == 1
    assert store.missing_clause_ids([clause.clause_id, "missing"]) == {"missing"}
    record = client.scroll("regulations", limit=1, with_payload=True)[0][0]
    assert record.payload is not None
    assert record.payload["clause_path"] == "Chapter I > 1"
    expected = int(datetime.combine(date(2020, 1, 1), time.min, tzinfo=UTC).timestamp())
    assert record.payload["effective_from"] == expected
    assert record.payload["effective_to"] is None
    client.close()


def test_versions_coexist_and_superseded_payload_is_closed() -> None:
    client, store = _store()
    first = _clause("v1", date(2020, 1, 1))
    second = _clause("v2", date(2021, 1, 1))
    store.upsert([first, second], [_embedding(first), _embedding(second)])

    store.close_version("rbi-kyc-md", "v1", second.effective_from)

    assert client.count("regulations", exact=True).count == 2
    records = client.scroll("regulations", limit=10, with_payload=True)[0]
    by_version = {record.payload["version"]: record.payload for record in records if record.payload}
    assert by_version["v1"]["effective_to"] is not None
    assert by_version["v2"]["effective_to"] is None
    client.close()


def test_upsert_rejects_wrong_vector_dimension() -> None:
    client, store = _store()
    clause = _clause("v1", date(2020, 1, 1))
    embedding = _embedding(clause).model_copy(update={"dense": [0.1]})

    with pytest.raises(RegulationStoreError, match="dimensions"):
        store.upsert([clause], [embedding])
    client.close()
