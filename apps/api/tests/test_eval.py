import pytest
from compliance.eval.dataset import load_dataset, select_suite
from compliance.eval.models import (
    EvaluationCase,
    EvaluationObservation,
    EvaluationResult,
    EvaluationScores,
)
from compliance.eval.report import render_report
from compliance.eval.run import faithfulness_exit_code, summarise


def _result(case_id: str, faithfulness: float = 0.9) -> EvaluationResult:
    return EvaluationResult(
        observation=EvaluationObservation(
            case_id=case_id,
            response="A source-grounded response.",
            retrieved_clause_ids=["doc:v:1"],
            retrieved_contexts=["The retrieved regulatory context."],
        ),
        scores=EvaluationScores(
            faithfulness=faithfulness,
            answer_relevance=0.8,
            context_precision=0.8,
            context_recall=0.8,
        ),
    )


def test_dataset_is_frozen_and_balanced() -> None:
    dataset = load_dataset()

    assert len(dataset.cases) == 18
    assert len(select_suite(dataset, "ci")) == 6
    assert sum(case.should_refuse for case in dataset.cases) == 3


def test_faithfulness_gate_fails_below_minimum() -> None:
    summary = summarise("ci", "test", [_result("eval-01", 0.79)])

    assert faithfulness_exit_code(summary, 0.80) == 1
    assert faithfulness_exit_code(summary, 0.79) == 0


def test_report_includes_context_for_low_score() -> None:
    case = EvaluationCase(
        case_id="eval-01",
        question="What is required?",
        reference_answer="The requirement.",
        ground_truth_clause_ids=["doc:v:1"],
        suites=["ci"],
    )
    summary = summarise("ci", "test", [_result(case.case_id, 0.6)])

    report = render_report(summary, [case], 0.7)

    assert "eval-01: What is required?" in report
    assert "The retrieved regulatory context." in report


def test_report_explains_the_answer_relevance_metric_mismatch() -> None:
    case = EvaluationCase(
        case_id="eval-01",
        question="What is required?",
        reference_answer="The requirement.",
        ground_truth_clause_ids=["doc:v:1"],
        suites=["ci"],
    )
    summary = summarise("ci", "test", [_result(case.case_id)])

    report = render_report(summary, [case], 0.7)

    assert "Reading the answer relevance score" in report
    assert "noncommittal" in report
    assert "adr/003-guardrails.md" in report


def test_report_matches_results_to_cases_by_id_not_position() -> None:
    case_a = EvaluationCase(
        case_id="eval-01",
        question="Question A.",
        reference_answer="Answer A.",
        ground_truth_clause_ids=["doc:v:1"],
        suites=["ci"],
    )
    case_b = EvaluationCase(
        case_id="eval-02",
        question="Question B.",
        reference_answer="Answer B.",
        ground_truth_clause_ids=["doc:v:1"],
        suites=["ci"],
    )
    # Results deliberately stored in the opposite order from cases, mirroring how
    # a snapshot's stored order need not match select_suite's returned order.
    summary = summarise("ci", "test", [_result("eval-02", 0.6), _result("eval-01", 0.9)])

    report = render_report(summary, [case_a, case_b], 0.7)

    assert "eval-01: Question A." not in report
    assert "eval-02: Question B." in report


def test_report_raises_when_a_case_has_no_matching_result() -> None:
    case = EvaluationCase(
        case_id="eval-01",
        question="Question A.",
        reference_answer="Answer A.",
        ground_truth_clause_ids=["doc:v:1"],
        suites=["ci"],
    )
    summary = summarise("ci", "test", [_result("eval-99", 0.9)])

    with pytest.raises(ValueError, match="eval-01"):
        render_report(summary, [case], 0.7)
