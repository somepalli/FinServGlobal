# ADR-001: Vector database selection

Date: 2026-08-21
Status: Accepted

## Context

I need hybrid retrieval, not dense similarity alone. A question containing a
literal clause reference such as "Basel III paragraph 52" must preserve that
lexical signal while still matching semantically related text. `ClauseEmbedding`
and `QueryEmbedding` in `apps/api/src/compliance/schemas.py` therefore carry one
dense vector plus sparse indices and values from the same BGE-M3 pass.

Effective-date and jurisdiction filtering are correctness requirements. Postgres
owns version lineage, but retrieval must exclude clauses outside the requested
date before ranking. `apps/api/src/compliance/retrieval/store.py` mirrors clause
metadata into Qdrant and indexes `jurisdiction`, `framework`, `doc_id`,
`effective_from`, and `effective_to`. The two date fields are UTC timestamps so
`apps/api/src/compliance/retrieval/search.py` can apply range filters server-side.

## Decision

Use Qdrant with one `regulations` collection and two named vectors:

- `dense`: 1024 dimensions with cosine distance.
- `sparse`: BGE-M3 lexical weights.

`HybridSearcher` prefetches both vector results under the same metadata filter
and combines them with reciprocal rank fusion. It also issues component queries
so each `RetrievedClause` retains its dense and sparse scores.

## Alternatives considered

- **pgvector.** Keeping retrieval beside the transactional tables would remove a
  stateful service. It has no first-class sparse vector matching equivalent to
  this design, so lexical retrieval would become a separate PostgreSQL mechanism
  rather than using both BGE-M3 outputs in one query path.
- **Milvus.** It can support this retrieval pattern at much larger scale. Its
  coordinator and query-node topology is more operational work than five source
  documents and roughly ten thousand daily queries warrant.
- **Weaviate.** This was the closest alternative. Qdrant won because the code can
  express named dense and sparse vectors, RRF, and typed payload range filters
  through one self-hosted service and a small Python client surface. The choice
  is about the implemented query shape, not a claim that Weaviate lacks those
  general capabilities.

## Consequences

- Qdrant is another stateful system beside Postgres. The current Helm chart runs
  one replica in `deploy/helm/templates/qdrant-statefulset.yaml`, so this is not
  a highly available topology.
- Payload metadata duplicates authoritative Postgres data. To reduce drift,
  `apps/api/src/compliance/ingest/run.py` commits the document and clauses to
  Postgres before it calls `RegulationStore.upsert`.
- Filtering and fusion stay inside Qdrant, avoiding application-side merging.
  Recovery still needs a reindex path from Postgres because Qdrant is derived
  state, not the version ledger.
