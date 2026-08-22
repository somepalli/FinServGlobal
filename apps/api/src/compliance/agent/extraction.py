"""Parse a free-text transaction description into a structured payload."""

import re
from json import JSONDecodeError
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

from compliance.config.settings import Settings
from compliance.retrieval.answer import is_internal_endpoint
from compliance.schemas import TransactionPayload

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = """\
Extract structured transaction facts from the compliance officer's description.
Respond with a single JSON object and nothing else, matching exactly this shape:

{
  "amount": <number or null>,
  "currency": <ISO 4217 currency code string or null>,
  "counterparty_type": <short string describing the counterparty, or null>,
  "jurisdictions": <array of zero or more of "IN", "EU", "US", "GLOBAL">,
  "instrument": <short string naming the transaction or instrument type, or null>,
  "kyc_status": <true if KYC is stated complete, false if stated missing or failed, \
null if not mentioned>,
  "high_risk_jurisdiction": <true, false, or null>,
  "large_exposure_threshold_exceeded": <true, false, or null>,
  "appropriateness_assessed": <true if an appropriateness or suitability assessment \
is stated done, false if stated not done, null if not mentioned>,
  "priority_sector_reporting_required": <true, false, or null>
}

Use null for anything the description does not state. Do not guess or infer values \
the text does not support. Output JSON only, with no surrounding text or markdown.\
"""


class TransactionExtractionError(RuntimeError):
    pass


class UnsafeLlmEndpointError(TransactionExtractionError):
    pass


class _ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class _ChatResponse(BaseModel):
    choices: list[dict[str, _ChatMessage]]


class _ExtractedFields(BaseModel):
    amount: float | None = None
    currency: str | None = None
    counterparty_type: str | None = None
    jurisdictions: list[Literal["IN", "EU", "US", "GLOBAL"]] | None = None
    instrument: str | None = None
    kyc_status: bool | None = None
    high_risk_jurisdiction: bool | None = None
    large_exposure_threshold_exceeded: bool | None = None
    appropriateness_assessed: bool | None = None
    priority_sector_reporting_required: bool | None = None


def _parse_json_object(content: str) -> str:
    match = _JSON_OBJECT.search(content)
    if match is None:
        raise TransactionExtractionError("extractor response did not contain a JSON object")
    return match.group(0)


class LocalTransactionExtractor:
    def __init__(self, settings: Settings) -> None:
        if not is_internal_endpoint(settings.llm_base_url):
            raise UnsafeLlmEndpointError(
                "transaction descriptions may only be sent to an internal LLM"
            )
        self._settings = settings

    async def extract(self, description: str) -> TransactionPayload:
        request = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": description},
            ],
            "temperature": 0.0,
            "max_tokens": self._settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        endpoint = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(endpoint, json=request)
                response.raise_for_status()
            completion = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, JSONDecodeError, ValidationError) as exc:
            raise TransactionExtractionError(f"local LLM request failed: {exc}") from exc
        if not completion.choices:
            raise TransactionExtractionError("local LLM returned no choices")
        content = completion.choices[0]["message"].content
        try:
            fields = _ExtractedFields.model_validate_json(_parse_json_object(content))
        except (JSONDecodeError, ValidationError) as exc:
            raise TransactionExtractionError(
                f"could not parse structured transaction facts: {exc}"
            ) from exc
        extracted = fields.model_dump()
        extracted["jurisdictions"] = extracted["jurisdictions"] or None
        return TransactionPayload(txn_id=f"desc-{uuid4().hex[:12]}", **extracted)
