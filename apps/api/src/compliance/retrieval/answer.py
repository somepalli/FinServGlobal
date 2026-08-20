"""Generate locally and retain only source-supported answer sentences."""

import asyncio
import re
from collections.abc import Sequence
from datetime import date
from ipaddress import ip_address
from json import JSONDecodeError
from statistics import fmean
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from compliance.config.settings import Settings
from compliance.retrieval.rerank import BgeReranker
from compliance.schemas import Answer, Citation, RetrievedClause, TextPair

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'“])")


class AnswerGenerationError(RuntimeError):
    pass


class UnsafeLlmEndpointError(AnswerGenerationError):
    pass


class _Generator(Protocol):
    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str: ...


class _SupportScorer(Protocol):
    def score_pairs(self, pairs: list[TextPair]) -> list[float]: ...


class _ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class _ChatRequest(BaseModel):
    model: str
    messages: list[_ChatMessage]
    temperature: float


class _ChatChoice(BaseModel):
    message: _ChatMessage


class _ChatResponse(BaseModel):
    choices: list[_ChatChoice]


def _is_internal_endpoint(url: str) -> bool:
    hostname = urlparse(url).hostname
    if hostname is None:
        return False
    if hostname == "localhost" or "." not in hostname:
        return True
    if hostname.endswith((".svc", ".svc.cluster.local", ".cluster.local")):
        return True
    try:
        address = ip_address(hostname)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def _source_prompt(question: str, clauses: list[RetrievedClause]) -> str:
    sources = "\n\n".join(
        f"SOURCE {item.clause.clause_id}\nPATH {item.clause.clause_path}\nTEXT {item.clause.text}"
        for item in clauses
    )
    return (
        "Answer the question using only the supplied regulatory sources. "
        "State that the sources are insufficient when they do not answer it.\n\n"
        f"QUESTION\n{question}\n\nSOURCES\n{sources}"
    )


class LocalLlmGenerator:
    def __init__(self, settings: Settings) -> None:
        if not _is_internal_endpoint(settings.llm_base_url):
            raise UnsafeLlmEndpointError("regulatory text may only be sent to an internal LLM")
        self._settings = settings

    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str:
        request = _ChatRequest(
            model=self._settings.llm_model,
            messages=[
                _ChatMessage(
                    role="system",
                    content="Cite only facts stated in the supplied regulatory sources.",
                ),
                _ChatMessage(role="user", content=_source_prompt(question, clauses)),
            ],
            temperature=self._settings.llm_temperature,
        )
        endpoint = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(endpoint, json=request.model_dump())
                response.raise_for_status()
            completion = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, JSONDecodeError, ValidationError) as exc:
            raise AnswerGenerationError(f"local LLM request failed: {exc}") from exc
        if not completion.choices:
            raise AnswerGenerationError("local LLM returned no choices")
        return completion.choices[0].message.content.strip()


def _sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        sentences.extend(part.strip() for part in _SENTENCE_BOUNDARY.split(block.strip()))
    return [sentence for sentence in sentences if sentence]


def _source_spans(item: RetrievedClause) -> list[str]:
    spans = _sentences(item.clause.text)
    return spans or [item.clause.text]


async def _citation_for_sentence(
    sentence: str,
    clauses: list[RetrievedClause],
    scorer: _SupportScorer,
) -> Citation:
    candidates = [(item, span) for item in clauses for span in _source_spans(item) if span]
    if not candidates:
        raise AnswerGenerationError("reranked clauses contain no source text")
    pairs = [TextPair(query=sentence, passage=span) for _item, span in candidates]
    scores = await asyncio.to_thread(scorer.score_pairs, pairs)
    if len(scores) != len(candidates):
        raise AnswerGenerationError("support scorer returned the wrong number of scores")
    best_index = max(range(len(scores)), key=scores.__getitem__)
    item, quote = candidates[best_index]
    return Citation(
        clause_id=item.clause.clause_id,
        clause_path=item.clause.clause_path,
        quote=quote,
        support=scores[best_index],
    )


def _fallback(clauses: Sequence[RetrievedClause], as_of: date) -> Answer:
    text = "\n\n".join(f"{item.clause.clause_path}\n{item.clause.text}" for item in clauses)
    citations = [
        Citation(
            clause_id=item.clause.clause_id,
            clause_path=item.clause.clause_path,
            quote=item.clause.text,
            support=1.0,
        )
        for item in clauses
    ]
    return Answer(text=text, citations=citations, synthesised=False, as_of=as_of)


async def build_answer(
    question: str,
    clauses: list[RetrievedClause],
    settings: Settings,
    *,
    as_of: date | None = None,
    generator: _Generator | None = None,
    scorer: _SupportScorer | None = None,
) -> Answer:
    active_date = as_of or date.today()
    if not question.strip():
        raise AnswerGenerationError("question cannot be empty")
    if not clauses:
        return _fallback([], active_date)
    active_generator = generator or LocalLlmGenerator(settings)
    active_scorer = scorer or BgeReranker(settings)
    generated = await active_generator.generate(question, clauses)
    sentences = _sentences(generated)
    if not sentences:
        return _fallback(clauses, active_date)
    citations = [
        await _citation_for_sentence(sentence, clauses, active_scorer) for sentence in sentences
    ]
    if fmean(citation.support for citation in citations) < settings.min_citation_support:
        return _fallback(clauses, active_date)
    return Answer(
        text=generated,
        citations=citations,
        synthesised=True,
        as_of=active_date,
    )
