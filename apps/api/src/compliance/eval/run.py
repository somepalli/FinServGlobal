import argparse
import asyncio
from statistics import fmean
from typing import Literal

from compliance.config.settings import Settings
from compliance.eval.dataset import load_dataset, select_suite
from compliance.eval.live import LiveEvaluator
from compliance.eval.models import EvaluationResult, EvaluationSnapshot, EvaluationSummary
from compliance.eval.report import write_report
from compliance.eval.snapshot import load_snapshot, write_snapshot
from compliance.eval.store import persist_summary


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate regulatory retrieval and answers")
    parser.add_argument("--suite", choices=("ci", "full"), default="full")
    parser.add_argument("--min-faithfulness", type=float, default=0.0)
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def _select_results(snapshot: EvaluationSnapshot, case_ids: set[str]) -> list[EvaluationResult]:
    selected = [item for item in snapshot.results if item.observation.case_id in case_ids]
    if len(selected) != len(case_ids):
        raise ValueError("evaluation snapshot does not contain every selected case")
    return selected


def summarise(
    suite: Literal["ci", "full"], commit_sha: str, results: list[EvaluationResult]
) -> EvaluationSummary:
    return EvaluationSummary(
        suite=suite,
        commit_sha=commit_sha,
        faithfulness=fmean(item.scores.faithfulness for item in results),
        answer_relevance=fmean(item.scores.answer_relevance for item in results),
        context_precision=fmean(item.scores.context_precision for item in results),
        context_recall=fmean(item.scores.context_recall for item in results),
        results=results,
    )


async def _live_results(settings: Settings, suite: str) -> list[EvaluationResult]:
    dataset = load_dataset()
    cases = select_suite(dataset, suite)
    return await LiveEvaluator(settings).evaluate(cases)


async def run(suite: Literal["ci", "full"], live: bool) -> EvaluationSummary:
    dataset = load_dataset()
    cases = select_suite(dataset, suite)
    if live:
        settings = Settings()  # type: ignore[call-arg]  # environment supplies database_url
        results = await _live_results(settings, suite)
        if suite == "full":
            write_snapshot(results, settings.eval_judge_model, settings.eval_commit_sha)
        summary = summarise(suite, settings.eval_commit_sha, results)
        await persist_summary(summary, settings)
        failure_score = settings.eval_failure_score
    else:
        snapshot = load_snapshot()
        results = _select_results(snapshot, {case.case_id for case in cases})
        summary = summarise(suite, snapshot.commit_sha, results)
        failure_score = 0.7
    write_report(summary, cases, failure_score)
    return summary


def _print_summary(summary: EvaluationSummary) -> None:
    print(
        f"suite={summary.suite} faithfulness={summary.faithfulness:.3f} "
        f"answer_relevance={summary.answer_relevance:.3f} "
        f"context_precision={summary.context_precision:.3f} "
        f"context_recall={summary.context_recall:.3f}"
    )


def faithfulness_exit_code(summary: EvaluationSummary, minimum: float) -> int:
    return int(summary.faithfulness < minimum)


def main() -> int:
    arguments = _arguments()
    summary = asyncio.run(run(arguments.suite, arguments.live))
    _print_summary(summary)
    return faithfulness_exit_code(summary, arguments.min_faithfulness)


if __name__ == "__main__":
    raise SystemExit(main())
