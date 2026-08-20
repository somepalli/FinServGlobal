"""Rerank retrieved clauses and score local text pairs."""

from collections.abc import Sequence
from functools import lru_cache
from math import isfinite
from typing import Protocol, cast

from compliance.config.settings import Settings
from compliance.schemas import RetrievedClause, TextPair


class RerankError(RuntimeError):
    pass


class _RerankerModel(Protocol):
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        batch_size: int,
        max_length: int,
        normalize: bool,
    ) -> float | Sequence[float]: ...


@lru_cache(maxsize=4)
def _load_model(model_name: str, use_fp16: bool) -> _RerankerModel:
    from FlagEmbedding import (  # type: ignore[import-untyped]  # Package has no PEP 561 marker.
        FlagReranker,
    )

    model = FlagReranker(model_name, use_fp16=use_fp16)
    return cast(_RerankerModel, model)


def _score_list(raw: float | Sequence[float], expected: int) -> list[float]:
    scores = [float(raw)] if isinstance(raw, (int, float)) else [float(item) for item in raw]
    if len(scores) != expected:
        raise RerankError(f"model returned {len(scores)} scores for {expected} pairs")
    if any(not isfinite(score) or not 0.0 <= score <= 1.0 for score in scores):
        raise RerankError("normalized reranker score is outside 0..1")
    return scores


class BgeReranker:
    def __init__(self, settings: Settings, *, model: _RerankerModel | None = None) -> None:
        self._settings = settings
        self._model = model

    def _active_model(self) -> _RerankerModel:
        if self._model is not None:
            return self._model
        return _load_model(self._settings.reranker_model, self._settings.reranker_use_fp16)

    def score_pairs(self, pairs: list[TextPair]) -> list[float]:
        if not pairs:
            return []
        raw = self._active_model().compute_score(
            [[pair.query, pair.passage] for pair in pairs],
            batch_size=self._settings.reranker_batch_size,
            max_length=self._settings.reranker_max_length,
            normalize=True,
        )
        return _score_list(raw, len(pairs))

    def rerank(self, query: str, clauses: list[RetrievedClause]) -> list[RetrievedClause]:
        candidates = clauses[: self._settings.retrieval_top_k]
        scores = self.score_pairs(
            [TextPair(query=query, passage=item.clause.text) for item in candidates]
        )
        rescored = [
            item.model_copy(update={"rerank_score": score})
            for item, score in zip(candidates, scores, strict=True)
        ]
        rescored.sort(
            key=lambda item: item.rerank_score if item.rerank_score is not None else 0.0,
            reverse=True,
        )
        return rescored[: self._settings.rerank_top_k]
