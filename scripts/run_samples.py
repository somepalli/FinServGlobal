"""Run the four checked-in sample transactions against local services."""

import asyncio
import sys
from pathlib import Path
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]  # The package has no PEP 561 marker.
from compliance.agent.graph import PostgresScreeningService
from compliance.api.service import AuditRepository
from compliance.config.settings import Settings, get_settings
from compliance.db import create_pool
from compliance.ingest.run import load_ingestion_manifest
from compliance.retrieval.embed import BgeM3Embedder
from compliance.retrieval.search import HybridSearcher
from compliance.schemas import (
    ComplianceAssessment,
    CorpusManifest,
    SampleAssessment,
    TransactionPayload,
)
from psycopg import Error as PsycopgError
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse


class SampleRunError(RuntimeError):
    pass


class ScreeningTool(Protocol):
    async def assess(
        self, payload: TransactionPayload, *, thread_id: str
    ) -> ComplianceAssessment: ...


def _input_paths(settings: Settings) -> list[Path]:
    paths = sorted((settings.samples_dir / "input").glob("*.json"))
    if not paths:
        raise SampleRunError(f"no sample payloads found in {settings.samples_dir / 'input'}")
    return paths


def _expected_document(manifest: CorpusManifest, name: str) -> str:
    matches = [document.doc_id for document in manifest.documents if name in document.covers]
    if len(matches) != 1:
        raise SampleRunError(f"sample {name} must map to exactly one manifest document")
    return matches[0]


def _verify_citation(sample: SampleAssessment) -> None:
    prefix = f"{sample.expected_doc_id}:"
    if not any(item.clause_id.startswith(prefix) for item in sample.assessment.citations):
        raise SampleRunError(
            f"sample {sample.name} has no citation from {sample.expected_doc_id}"
        )


async def _run_cases(
    settings: Settings, screening: ScreeningTool
) -> list[SampleAssessment]:
    manifest = load_ingestion_manifest(settings.corpus_manifest)
    results: list[SampleAssessment] = []
    for path in _input_paths(settings):
        payload = TransactionPayload.model_validate_json(path.read_text(encoding="utf-8"))
        assessment = await screening.assess(payload, thread_id=payload.txn_id)
        sample = SampleAssessment(
            name=path.stem,
            expected_doc_id=_expected_document(manifest, path.stem),
            assessment=assessment,
        )
        _verify_citation(sample)
        results.append(sample)
    return results


def _markdown(samples: list[SampleAssessment]) -> str:
    lines = [
        "# Sample compliance assessments",
        "",
        "I generated these assessments from the local corpus and retained every cited clause ID.",
        "",
        "| Sample | Risk | Required actions | Cited clauses | Unresolved questions |",
        "|---|---|---|---|---|",
    ]
    for sample in samples:
        assessment = sample.assessment
        citations = "<br>".join(item.clause_id for item in assessment.citations) or "None"
        actions = "<br>".join(assessment.required_actions) or "None"
        unresolved = "<br>".join(assessment.unresolved_questions) or "None"
        lines.append(
            f"| {sample.name} | {assessment.risk_rating.value} | {actions} | "
            f"{citations} | {unresolved} |"
        )
    return "\n".join(lines) + "\n"


def _write_outputs(settings: Settings, samples: list[SampleAssessment]) -> None:
    output_dir = settings.samples_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        target = output_dir / f"{sample.name}.json"
        target.write_text(sample.assessment.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(_markdown(samples), encoding="utf-8")


async def _run_production(settings: Settings) -> list[SampleAssessment]:
    pool = await create_pool(settings)
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        audit = AuditRepository(pool)
        searcher = HybridSearcher(qdrant, BgeM3Embedder(settings), settings)
        screening = PostgresScreeningService(searcher, audit, settings)
        return await _run_cases(settings, screening)
    finally:
        qdrant.close()
        await pool.close()


async def run_samples(
    settings: Settings, *, screening: ScreeningTool | None = None
) -> list[SampleAssessment]:
    samples = (
        await _run_cases(settings, screening)
        if screening is not None
        else await _run_production(settings)
    )
    _write_outputs(settings, samples)
    return samples


def main() -> int:
    try:
        samples = asyncio.run(run_samples(get_settings()))
    except (
        SampleRunError,
        OSError,
        ValidationError,
        asyncpg.PostgresError,
        PsycopgError,
        ResponseHandlingException,
        UnexpectedResponse,
    ) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {len(samples)} sample assessments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
