from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML has no bundled type marker.
from pydantic import ValidationError

from compliance.eval.models import EvaluationCase, EvaluationDataset

_EXPECTED_DOCUMENTS = {"rbi-kyc-md", "rbi-lef", "rbi-psl", "mifid2-dir", "basel3-d424"}


class EvaluationDatasetError(ValueError):
    pass


def default_dataset_path() -> Path:
    return Path(__file__).with_name("data") / "testset.yaml"


def _validate_composition(dataset: EvaluationDataset) -> None:
    if len(dataset.cases) != 18:
        raise EvaluationDatasetError("evaluation dataset must contain 18 cases")
    refusals = [case for case in dataset.cases if case.should_refuse]
    if len(refusals) < 3:
        raise EvaluationDatasetError("evaluation dataset must contain at least three refusals")
    ci_cases = [case for case in dataset.cases if "ci" in case.suites]
    if len(ci_cases) != 6:
        raise EvaluationDatasetError("ci suite must contain six cases")
    doc_ids = {
        clause_id.split(":", maxsplit=1)[0]
        for case in dataset.cases
        for clause_id in case.ground_truth_clause_ids
    }
    if doc_ids != _EXPECTED_DOCUMENTS:
        raise EvaluationDatasetError("evaluation dataset must cover all five corpus documents")


def load_dataset(path: Path | None = None) -> EvaluationDataset:
    dataset_path = path or default_dataset_path()
    try:
        dataset = EvaluationDataset.model_validate(yaml.safe_load(dataset_path.read_text("utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise EvaluationDatasetError(f"invalid evaluation dataset: {exc}") from exc
    _validate_composition(dataset)
    return dataset


def select_suite(dataset: EvaluationDataset, suite: str) -> list[EvaluationCase]:
    return [case for case in dataset.cases if suite in case.suites]
