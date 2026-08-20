# Task 10 — Evaluation harness

## Build
- `eval/dataset.py` — 18 question/answer pairs with ground-truth clause ids,
  in `eval/data/testset.yaml`. Spread across all five documents. Include at
  least three that should be refused (out of corpus, or answerable only by a
  superseded version).
- `eval/run.py` — RAGAS with a locally served judge model, not OpenAI. Measures
  faithfulness, answer relevance, context precision, context recall. Writes to
  `eval_runs` and emits `docs/evaluation-report.md`.
- `--suite ci` runs a fixed 6-question subset; `--min-faithfulness` fails the
  process below threshold.

## Acceptance
- `uv run python -m compliance.eval.run --suite ci --min-faithfulness 0.80`
  exits non-zero when the threshold is not met.
- The report includes a failure analysis section listing every question that
  scored below 0.7 with the retrieved context, so failures can be read.

## Note
Do not tune the test set until the scores look good. A test set written to pass
is worth nothing. Record the first honest run.
