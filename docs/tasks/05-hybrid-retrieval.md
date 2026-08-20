# Task 05 — Hybrid retrieval

## Build
`retrieval/search.py`:

```python
async def search(
    query: str,
    *,
    as_of: date | None = None,
    jurisdictions: list[str] | None = None,
    frameworks: list[str] | None = None,
    top_k: int | None = None,
) -> list[RetrievedClause]
```

Qdrant server-side hybrid query using both named vectors with RRF fusion.
`as_of` defaults to today and is always applied as a range filter on
`effective_from` / `effective_to`.

## Acceptance
- A query using a clause number ("3.1.2") retrieves that clause — this is the
  case dense-only retrieval fails, and it is the justification for hybrid.
  Write that test explicitly.
- A query with `as_of` set to a past date does not return clauses that came
  into force later.
- Filters compose: jurisdiction plus framework plus date.
