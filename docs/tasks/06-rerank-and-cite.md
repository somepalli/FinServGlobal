# Task 06 — Reranking and citation assembly

## Build
- `retrieval/rerank.py` — bge-reranker-v2-m3 cross-encoder over the top
  `settings.retrieval_top_k`, returning `settings.rerank_top_k`.
- `retrieval/answer.py` — build an `Answer`:
  1. generate with the LLM, given only the reranked clauses
  2. split the generated text into sentences
  3. for each sentence, score entailment against each cited clause
  4. attach `Citation` objects with the verbatim supporting span
  5. if mean support < `settings.min_citation_support`, return
     `Answer(synthesised=False)` with the clauses and no generated text

## Acceptance
- An answer never contains a citation whose `quote` is absent from the source
  clause text. Assert this.
- A deliberately unanswerable question ("what is the capital adequacy ratio for
  Martian banks") returns `synthesised=False` rather than a fabricated answer.
- Reranking changes the order for at least one fixture query — if it never
  does, the reranker is not wired in.
