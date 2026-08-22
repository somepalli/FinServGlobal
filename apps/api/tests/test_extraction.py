import pytest
from compliance.agent.extraction import (
    LocalTransactionExtractor,
    TransactionExtractionError,
    UnsafeLlmEndpointError,
    _parse_json_object,
)
from compliance.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"database_url": "postgresql://u:p@localhost/db"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_external_llm_endpoint_is_rejected() -> None:
    settings = _settings(llm_base_url="https://api.example.com/v1")

    with pytest.raises(UnsafeLlmEndpointError, match="internal LLM"):
        LocalTransactionExtractor(settings)


def test_local_llm_endpoint_is_accepted() -> None:
    settings = _settings(llm_base_url="http://localhost:11434/v1")

    LocalTransactionExtractor(settings)


def test_parse_json_object_extracts_from_markdown_fences() -> None:
    content = '```json\n{"amount": 100, "currency": "USD"}\n```'

    assert _parse_json_object(content) == '{"amount": 100, "currency": "USD"}'


def test_parse_json_object_extracts_from_surrounding_prose() -> None:
    content = 'Here is the transaction:\n{"amount": null, "currency": "EUR"}\nLet me know.'

    assert _parse_json_object(content) == '{"amount": null, "currency": "EUR"}'


def test_parse_json_object_raises_without_a_json_object() -> None:
    with pytest.raises(TransactionExtractionError, match="JSON object"):
        _parse_json_object("I could not identify any transaction details.")
