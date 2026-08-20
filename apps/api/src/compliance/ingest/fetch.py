"""Fetch reproducible legal source files for the regulatory corpus.

If source text changes without detection, prior compliance answers cannot be
reproduced. Each accepted file is therefore tied to the manifest by SHA-256.
"""

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import httpx
import yaml  # type: ignore[import-untyped]  # PyYAML does not publish a PEP 561 marker.
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from compliance.config.settings import Settings, get_settings

_PDF_SIGNATURE = b"%PDF-"


class CorpusFetchError(RuntimeError):
    pass


class ManifestError(CorpusFetchError):
    pass


class MissingHashError(CorpusFetchError):
    pass


class HashMismatchError(CorpusFetchError):
    pass


class DownloadError(CorpusFetchError):
    pass


class _ManifestDocument(BaseModel):
    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source_url: HttpUrl
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class _CorpusManifest(BaseModel):
    documents: list[_ManifestDocument] = Field(min_length=1)


def _load_manifest(path: Path) -> tuple[_CorpusManifest, str]:
    try:
        text = path.read_text(encoding="utf-8")
        raw: object = yaml.safe_load(text)
        return _CorpusManifest.model_validate(raw), text
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest does not exist: {path}") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise ManifestError(f"invalid corpus manifest {path}: {exc}") from exc


def _hash_file(path: Path, chunk_bytes: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_length(response: httpx.Response, doc_id: str) -> int | None:
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DownloadError(f"{doc_id}: invalid Content-Length {value!r}") from exc


def _stream_pdf(
    response: httpx.Response, destination: Path, doc_id: str, chunk_bytes: int
) -> str:
    digest = hashlib.sha256()
    prefix = b""
    downloaded = 0
    with destination.open("xb") as output:
        for chunk in response.iter_raw(chunk_size=chunk_bytes):
            output.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            if len(prefix) < len(_PDF_SIGNATURE):
                prefix = (prefix + chunk)[: len(_PDF_SIGNATURE)]
    declared_length = _declared_length(response, doc_id)
    if declared_length is not None and declared_length != downloaded:
        raise DownloadError(f"{doc_id}: incomplete download")
    if prefix != _PDF_SIGNATURE:
        raise DownloadError(f"{doc_id}: source did not return a PDF")
    return digest.hexdigest()


def _download_document(
    client: httpx.Client,
    document: _ManifestDocument,
    target: Path,
    chunk_bytes: int,
) -> str:
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        with client.stream("GET", str(document.source_url)) as response:
            response.raise_for_status()
            actual_hash = _stream_pdf(response, temporary, document.doc_id, chunk_bytes)
        if document.sha256 is not None and actual_hash != document.sha256:
            raise HashMismatchError(
                f"{document.doc_id}: SHA-256 mismatch; expected "
                f"{document.sha256}, received {actual_hash}"
            )
        temporary.replace(target)
        return actual_hash
    except httpx.HTTPError as exc:
        raise DownloadError(f"{document.doc_id}: download failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _fetch_document(
    client: httpx.Client,
    document: _ManifestDocument,
    settings: Settings,
) -> Path:
    target = settings.corpus_dir / f"{document.doc_id}.pdf"
    if document.sha256 is not None and target.exists():
        actual_hash = _hash_file(target, settings.corpus_fetch_chunk_bytes)
        if actual_hash != document.sha256:
            raise HashMismatchError(
                f"{document.doc_id}: SHA-256 mismatch; expected "
                f"{document.sha256}, found {actual_hash}"
            )
        return target
    document.sha256 = _download_document(
        client, document, target, settings.corpus_fetch_chunk_bytes
    )
    return target


def _record_hashes(path: Path, text: str, documents: list[_ManifestDocument]) -> None:
    updated = text
    for document in documents:
        pattern = re.compile(
            rf"(^[ \t]*- doc_id:[ \t]*{re.escape(document.doc_id)}[ \t]*\r?$"
            rf".*?^[ \t]*sha256:[ \t]*)([^\r\n]*)",
            flags=re.MULTILINE | re.DOTALL,
        )
        updated, count = pattern.subn(rf"\g<1>{document.sha256}", updated, count=1)
        if count != 1:
            raise ManifestError(f"{document.doc_id}: sha256 field is missing from manifest")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _new_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=settings.corpus_fetch_timeout_seconds,
        headers={
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "identity",
            "Referer": settings.corpus_fetch_referer,
            "User-Agent": settings.corpus_fetch_user_agent,
        },
    )


def fetch_corpus(
    settings: Settings | None = None,
    *,
    record_hashes: bool = False,
    client: httpx.Client | None = None,
) -> list[Path]:
    active_settings = settings or get_settings()
    manifest, manifest_text = _load_manifest(active_settings.corpus_manifest)
    missing = [document.doc_id for document in manifest.documents if document.sha256 is None]
    if missing and not record_hashes:
        raise MissingHashError(f"missing SHA-256 for: {', '.join(missing)}")
    active_settings.corpus_dir.mkdir(parents=True, exist_ok=True)
    active_client = client or _new_client(active_settings)
    try:
        paths = [
            _fetch_document(active_client, document, active_settings)
            for document in manifest.documents
        ]
    finally:
        if client is None:
            active_client.close()
    if record_hashes:
        _record_hashes(active_settings.corpus_manifest, manifest_text, manifest.documents)
    return paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and verify the regulatory corpus")
    parser.add_argument("--record-hashes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = fetch_corpus(record_hashes=args.record_hashes)
    except CorpusFetchError as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
