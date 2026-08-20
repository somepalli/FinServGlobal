import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from compliance.eval.models import EvaluationResult, EvaluationSnapshot


class EvaluationSnapshotError(ValueError):
    pass


def default_snapshot_path() -> Path:
    return Path(__file__).with_name("data") / "first-run.json"


def load_snapshot(path: Path | None = None) -> EvaluationSnapshot:
    snapshot_path = path or default_snapshot_path()
    try:
        return EvaluationSnapshot.model_validate_json(snapshot_path.read_text("utf-8"))
    except (OSError, ValidationError) as exc:
        raise EvaluationSnapshotError(f"invalid evaluation snapshot: {exc}") from exc


def write_snapshot(
    results: list[EvaluationResult], judge_model: str, commit_sha: str, path: Path | None = None
) -> Path:
    snapshot = EvaluationSnapshot(
        generated_at=datetime.now(UTC),
        judge_model=judge_model,
        commit_sha=commit_sha,
        results=results,
    )
    snapshot_path = path or default_snapshot_path()
    content = json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False)
    snapshot_path.write_text(f"{content}\n", encoding="utf-8")
    return snapshot_path
