# Task 12 — Next.js demo UI

Time-box: 4 hours. If it overruns, ship without it.

## Build
Two pages, Server Components calling the API from the server only.
- `/` — question box, answer with inline citation markers, side panel showing
  each cited clause with its path and effective dates. When
  `synthesised=false`, show the clauses and an explicit "not enough support to
  answer" state. That state is the point of the demo, not an error case.
- `/screen` — paste a transaction JSON, render the assessment: risk rating,
  applicable regulations, required actions, citations, unresolved questions.

No client-side API base URL, no auth tokens in the browser. Plain CSS or CSS
modules; do not add a component library for two pages.

## Acceptance
- `pnpm build` and `pnpm lint` clean, `tsc --noEmit` clean.
- Types for API responses generated from the OpenAPI schema, not hand-written.
