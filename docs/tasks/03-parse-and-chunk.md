# Task 03 — Docling parse and clause-aware chunker

## Build
- `ingest/parse.py` — Docling → a document tree preserving heading hierarchy
  and tables. Tables serialised as markdown inside the clause text they belong to.
- `ingest/chunk.py` — walk the tree and emit `Clause` objects.

## Chunking rules
- The unit is the smallest numbered provision (3.1.2, Article 25(2), ¶52).
- `clause_path` is the full breadcrumb, joined with " > ".
- If a clause exceeds 800 tokens, split on sentence boundaries and suffix the
  path with `#part2`, `#part3`. Never split mid-sentence.
- If a clause is under 80 tokens, merge with the following sibling and record
  both numbers in `clause_path`.
- Prepend the breadcrumb to the text that gets embedded. Keep the raw text
  separate for citation quoting — a citation must quote the source, not our
  augmented copy.

## Acceptance
- Given the RBI KYC document, chunking produces clauses whose `clause_path`
  values match the numbering in the PDF. Include a test asserting three known
  clause numbers appear.
- Zero clauses with empty `clause_path`. This is a hard failure.
