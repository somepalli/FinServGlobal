# Task 13 — Compliance posture reporting

## Build

Add a Compliance Head view for a selected reporting period. Postgres computes
activity totals, risk distribution, unresolved-screening totals, daily activity,
and prior-period comparisons from append-only audit events.

The local LLM may write a short commentary from qualitative movements already
derived from those figures. It must never calculate or emit a number. The UI
labels generated commentary and keeps it visually separate from reported facts.
If the model returns numeric text, omit the commentary.

## Acceptance

- No count, distribution, or comparison is produced by the LLM.
- A test proves that the commentary prompt contains no number and does not ask
  for a count.
- Numeric model commentary is withheld.
- The UI identifies SQL-derived figures and generated commentary.
- API tests, Python type checks, web lint, web type checks, and the production
  build pass.
