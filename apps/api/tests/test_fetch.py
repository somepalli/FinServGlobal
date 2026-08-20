import hashlib
from pathlib import Path

import httpx
import pytest
from compliance.config.settings import Settings, get_settings
from compliance.ingest.fetch import (
    DownloadError,
    HashMismatchError,
    MissingHashError,
    fetch_corpus,
    main,
)

_PDF = b"%PDF-1.7\nfixture document"


def _write_manifest(path: Path, sha256: str | None) -> None:
    value = "null" if sha256 is None else sha256
    path.write_text(
        "documents:\n"
        "  - doc_id: test-regulation\n"
        "    source_url: https://regulator.test/source.pdf\n"
        f"    sha256: {value}\n",
        encoding="utf-8",
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://user:password@localhost/database",
        corpus_dir=tmp_path / "corpus",
        corpus_manifest=tmp_path / "manifest.yaml",
        corpus_fetch_chunk_bytes=8,
    )


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def _response(content: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, headers=headers, stream=httpx.ByteStream(content))


def test_record_hashes_downloads_pdf_and_updates_manifest(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, None)
    transport = httpx.MockTransport(lambda request: _response(_PDF))

    with _client(transport) as client:
        paths = fetch_corpus(settings, record_hashes=True, client=client)

    expected_hash = hashlib.sha256(_PDF).hexdigest()
    assert paths == [settings.corpus_dir / "test-regulation.pdf"]
    assert paths[0].read_bytes() == _PDF
    assert f"sha256: {expected_hash}" in settings.corpus_manifest.read_text(encoding="utf-8")
    assert list(settings.corpus_dir.glob("*.part")) == []


def test_record_hashes_preserves_following_documents(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.corpus_manifest.write_text(
        "documents:\n"
        "  - doc_id: first-regulation\n"
        "    source_url: https://regulator.test/first.pdf\n"
        "    sha256: null\n"
        "  - doc_id: second-regulation\n"
        "    source_url: https://regulator.test/second.pdf\n"
        "    sha256: null\n",
        encoding="utf-8",
    )
    transport = httpx.MockTransport(lambda request: _response(_PDF))

    with _client(transport) as client:
        fetch_corpus(settings, record_hashes=True, client=client)

    manifest = settings.corpus_manifest.read_text(encoding="utf-8")
    assert "doc_id: first-regulation" in manifest
    assert "doc_id: second-regulation" in manifest
    assert manifest.count(hashlib.sha256(_PDF).hexdigest()) == 2


def test_existing_file_is_verified_without_network(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    expected_hash = hashlib.sha256(_PDF).hexdigest()
    _write_manifest(settings.corpus_manifest, expected_hash)
    settings.corpus_dir.mkdir()
    target = settings.corpus_dir / "test-regulation.pdf"
    target.write_bytes(_PDF)

    def fail_on_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    with _client(httpx.MockTransport(fail_on_request)) as client:
        assert fetch_corpus(settings, client=client) == [target]


def test_tampered_file_fails_with_document_name(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, hashlib.sha256(_PDF).hexdigest())
    settings.corpus_dir.mkdir()
    (settings.corpus_dir / "test-regulation.pdf").write_bytes(b"tampered")

    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    with _client(transport) as client, pytest.raises(
        HashMismatchError, match="test-regulation"
    ):
        fetch_corpus(settings, client=client)


def test_cli_returns_nonzero_and_names_tampered_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, hashlib.sha256(_PDF).hexdigest())
    settings.corpus_dir.mkdir()
    (settings.corpus_dir / "test-regulation.pdf").write_bytes(b"tampered")
    monkeypatch.setenv("COMPLIANCE_DATABASE_URL", str(settings.database_url))
    monkeypatch.setenv("COMPLIANCE_CORPUS_DIR", str(settings.corpus_dir))
    monkeypatch.setenv("COMPLIANCE_CORPUS_MANIFEST", str(settings.corpus_manifest))
    get_settings.cache_clear()

    try:
        assert main([]) == 1
        assert "test-regulation" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()


def test_partial_download_never_becomes_target(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, None)
    response_headers = {"Content-Length": str(len(_PDF) + 10)}
    transport = httpx.MockTransport(
        lambda request: _response(_PDF, response_headers)
    )

    with _client(transport) as client, pytest.raises(DownloadError, match="test-regulation"):
        fetch_corpus(settings, record_hashes=True, client=client)

    assert not (settings.corpus_dir / "test-regulation.pdf").exists()
    assert list(settings.corpus_dir.glob("*.part")) == []


def test_html_challenge_is_not_accepted_as_a_pdf(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, None)
    transport = httpx.MockTransport(lambda request: _response(b"<html>challenge</html>"))

    with _client(transport) as client, pytest.raises(
        DownloadError, match="did not return a PDF"
    ):
        fetch_corpus(settings, record_hashes=True, client=client)

    assert not (settings.corpus_dir / "test-regulation.pdf").exists()


def test_missing_hash_requires_record_mode(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings.corpus_manifest, None)

    with pytest.raises(MissingHashError, match="test-regulation"):
        fetch_corpus(settings)
