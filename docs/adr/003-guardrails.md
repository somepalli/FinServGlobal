# ADR-003: Guardrail implementation approach

Date: 2026-08-21
Status: Accepted

## Context

An unsupported compliance answer is worse than no answer. A citation marker can
create false confidence even when the quoted clause does not support the claim,
so prompt instructions alone do not satisfy hallucination detection or
regulatory accuracy checks.

## Decision

Use the two-layer guardrail implemented in
`apps/api/src/compliance/retrieval/answer.py`:

1. Split generated text into sentences and score each sentence against every
   candidate source span with the BGE reranker. Select the highest-scoring span
   and build the citation from that verbatim span and its clause provenance.
2. Compute mean citation support. If it is below
   `Settings.min_citation_support`, return the retrieved clauses with
   `synthesised=False` and discard the generated text.

`apps/api/tests/test_answer.py` proves that every published citation quote is
present in the source clause. Its unanswerable-question test supplies a fabricated
Martian-bank claim with low support and asserts that the generated claim is
absent from the fallback response.

## Alternatives considered

- **A second LLM as judge.** Deferred because it adds another model call and
  another probabilistic decision without improving the refusal behavior. The
  entailment threshold makes refusal part of the response construction path.
- **Prompt-only grounding.** Rejected as insufficient. The generator is told to
  use supplied sources, but post-generation attribution still runs because the
  instruction is not evidence that the model complied.
- **PII redaction.** This is related but distinct. Presidio or an equivalent
  redaction stage is not implemented in this repository and remains a known gap.

## Consequences

- `min_citation_support` defaults to `0.6` in
  `apps/api/src/compliance/config/settings.py`. Too high rejects answerable
  questions; too low accepts weak support.
- The current threshold came from engineering judgment, not a recorded threshold
  sweep. `docs/evaluation-report.md` reports faithfulness and retrieval metrics,
  but it does not establish that `0.6` is optimal.
- Sentence-to-span scoring adds reranker work after generation. In exchange, the
  API has a clear, testable refusal state instead of publishing unattributed text.
- Output-schema validation exists through Pydantic models, but PII redaction and
  a separate policy classifier must not be represented as completed guardrails.
