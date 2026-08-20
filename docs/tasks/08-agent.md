# Task 08 — LangGraph compliance agent

## Build
`agent/graph.py` — a LangGraph `StateGraph` with a Postgres checkpointer.

Nodes:
1. `extract` — transaction payload → structured facts (amount, currency,
   counterparty type, jurisdictions, instrument, KYC status). Missing fields
   recorded, not invented.
2. `classify` — which frameworks are in scope. Deterministic rules first;
   the LLM only for cases the rules do not cover.
3. `retrieve` — one `search()` call per framework in scope, filtered by
   jurisdiction.
4. `cross_reference` — find obligations triggered under more than one framework
   simultaneously. This is the scenario the assignment calls out; make it a
   distinct node so it is visible in the graph.
5. `assess` — produce `ComplianceAssessment`.
6. `validate` — citation check per task 06. On failure, one retry with a
   narrowed prompt, then fall back to an assessment carrying
   `unresolved_questions` and no synthesised summary.

Tools are typed functions, not string-dispatch. Every node writes an
`audit_events` row.

## Acceptance
- The checkpointer persists state; a run can be replayed from its thread_id.
- A payload missing KYC status produces non-empty `unresolved_questions` and
  `risk_rating` no higher than MEDIUM.
- Graph renders to Mermaid for the architecture document.
