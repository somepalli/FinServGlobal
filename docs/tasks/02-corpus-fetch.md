# Task 02 — Corpus fetch with hash verification

## Build
`apps/api/src/compliance/ingest/fetch.py` with a `fetch_corpus()` that reads
`data/corpus/manifest.yaml`, downloads each `source_url` to
`settings.corpus_dir`, and verifies SHA-256 against the manifest.

First run has no hashes recorded. Support `--record-hashes` to write them back
into the manifest. Every later run verifies and fails loudly on mismatch.

Add `source_url` and `sha256` fields to the manifest entries.

## Acceptance
- `uv run python -m compliance.ingest.fetch --record-hashes` populates hashes.
- A tampered file causes a non-zero exit naming the document.
- Downloads are resumable-safe: a partial file is never accepted as valid.
- Tests use a local fixture server or monkeypatched httpx, not the network.

## Why the hashes matter
The corpus is legal source text. If it changes underneath us, every answer we
previously produced becomes unreproducible. Say that in the module docstring.
