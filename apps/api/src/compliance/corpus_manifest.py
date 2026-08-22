"""Load the corpus manifest that declares which regulatory documents to track."""

from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML does not publish a PEP 561 marker.
from pydantic import ValidationError

from compliance.schemas import CorpusManifest


class ManifestError(RuntimeError):
    pass


def load_ingestion_manifest(path: Path) -> CorpusManifest:
    try:
        return CorpusManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest does not exist: {path}") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise ManifestError(f"invalid ingestion manifest {path}: {exc}") from exc
