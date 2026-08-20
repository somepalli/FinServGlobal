# Task 04 — Qdrant collection and indexer

## Build
- `retrieval/store.py` — create the `regulations` collection per the spec:
  named `dense` and `sparse` vectors, payload indexes on `jurisdiction`,
  `framework`, `doc_id`, `effective_from`, `effective_to`.
- `retrieval/embed.py` — BGE-M3 wrapper returning dense and lexical weights in
  one pass. Batch. Cache the model between calls.
- `ingest/run.py` — orchestrates fetch → parse → chunk → write Postgres rows →
  embed → upsert Qdrant.

## Ordering
Postgres first, Qdrant second, per spec rule 5. If the Qdrant upsert fails, the
Postgres rows stay and the run is resumable — `ingest/run.py --resume` indexes
only clauses absent from Qdrant.

## Acceptance
- Re-running ingestion is idempotent: same clause count, no duplicates.
- A new version of an existing document does not overwrite the old one. Both
  are queryable, `effective_to` is set on the superseded version.
