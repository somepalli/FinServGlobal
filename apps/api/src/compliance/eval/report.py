from pathlib import Path

from compliance.eval.models import EvaluationCase, EvaluationResult, EvaluationSummary


def default_report_path() -> Path:
    return Path(__file__).resolve().parents[5] / "docs" / "evaluation-report.md"


_ANSWER_RELEVANCE_NOTE = """\
## Reading the answer relevance score

RAGAS `AnswerRelevancy` forces a score of exactly 0.0 whenever the judge classifies a
response as noncommittal - no partial credit for the rest of the answer. I verified this
against the raw generated text, not just the score pattern: `LocalLlmGenerator`'s system
prompt (`retrieval/answer.py`) tells the model to say when sources are insufficient, and the
7B generator applies that instruction to answers it actually completed, not only ones it
could not. A single trailing hedge sentence zeroes the whole score even when everything
above it is a correct, cited answer. Raising RAGAS's `strictness` from 1 to 3 does not help;
the judge reaches the same noncommittal verdict every time, so there is nothing for
repetition to average out.

The three `should_refuse` cases genuinely earn a near-zero score here - that part of the
metric is working as intended. The rest of this metric's low scores are a structural
mismatch, not a retrieval defect: this system is built to hedge visibly rather than overclaim
([ADR-003](adr/003-guardrails.md)), and `AnswerRelevancy` treats any hedge as evasive
regardless of what precedes it. Faithfulness and context recall are the metrics that actually
reflect retrieval and citation quality here, and neither is affected by this."""


def _score_table(summary: EvaluationSummary) -> str:
    return "\n".join(
        (
            "| Metric | Score |",
            "| --- | ---: |",
            f"| Faithfulness | {summary.faithfulness:.3f} |",
            f"| Answer relevance | {summary.answer_relevance:.3f} |",
            f"| Context precision | {summary.context_precision:.3f} |",
            f"| Context recall | {summary.context_recall:.3f} |",
        )
    )


def _failure(case: EvaluationCase, result: EvaluationResult) -> str:
    contexts = "\n\n".join(
        f"> {context.replace(chr(10), ' ')[:1200].rstrip()}"
        for context in result.observation.retrieved_contexts
    )
    scores = result.scores
    return (
        f"### {case.case_id}: {case.question}\n\n"
        f"Scores: faithfulness {scores.faithfulness:.3f}, relevance "
        f"{scores.answer_relevance:.3f}, precision {scores.context_precision:.3f}, "
        f"recall {scores.context_recall:.3f}.\n\n"
        f"Retrieved context:\n\n{contexts or '> No context was retrieved.'}"
    )


def render_report(
    summary: EvaluationSummary, cases: list[EvaluationCase], failure_score: float
) -> str:
    results_by_case_id = {result.observation.case_id: result for result in summary.results}
    failures = []
    for case in cases:
        result = results_by_case_id.get(case.case_id)
        if result is None:
            raise ValueError(f"no evaluation result for case {case.case_id}")
        if result.scores.lowest < failure_score:
            failures.append(_failure(case, result))
    analysis = "\n\n".join(failures) or "No question scored below the failure threshold."
    return (
        "# Evaluation report\n\n"
        "I froze the 18-question test set before the first run. The six-case CI "
        "suite is a fixed subset of that set.\n\n"
        f"Suite: `{summary.suite}`\n\nCommit: `{summary.commit_sha}`\n\n"
        f"{_score_table(summary)}\n\n"
        f"{_ANSWER_RELEVANCE_NOTE}\n\n"
        f"## Failure analysis\n\n{analysis}\n"
    )


def write_report(
    summary: EvaluationSummary,
    cases: list[EvaluationCase],
    failure_score: float,
    path: Path | None = None,
) -> Path:
    report_path = path or default_report_path()
    report_path.write_text(render_report(summary, cases, failure_score), encoding="utf-8")
    return report_path
