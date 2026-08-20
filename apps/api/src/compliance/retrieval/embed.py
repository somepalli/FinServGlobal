"""Create local BGE-M3 dense and lexical clause embeddings."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Protocol, TypedDict, cast

from compliance.config.settings import Settings
from compliance.ingest.chunk import embedding_text
from compliance.schemas import Clause, ClauseEmbedding


class EmbeddingError(RuntimeError):
    pass


class _RawEmbedding(TypedDict):
    dense_vecs: Sequence[Sequence[float]]
    lexical_weights: Sequence[Mapping[str | int, float]]


class _BgeModel(Protocol):
    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        max_length: int,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
    ) -> _RawEmbedding: ...


@lru_cache(maxsize=4)
def _load_model(model_name: str, use_fp16: bool) -> _BgeModel:
    from FlagEmbedding import (  # type: ignore[import-untyped]  # Package has no PEP 561 marker.
        BGEM3FlagModel,
    )

    model = BGEM3FlagModel(model_name, use_fp16=use_fp16)
    return cast(_BgeModel, model)


def _sparse_parts(weights: Mapping[str | int, float]) -> tuple[list[int], list[float]]:
    ordered = sorted((int(index), float(value)) for index, value in weights.items())
    return [item[0] for item in ordered], [item[1] for item in ordered]


def _validate_count(raw: _RawEmbedding, expected: int) -> None:
    dense_count = len(raw["dense_vecs"])
    sparse_count = len(raw["lexical_weights"])
    if dense_count != expected or sparse_count != expected:
        raise EmbeddingError(
            f"model returned {dense_count} dense and {sparse_count} sparse vectors "
            f"for {expected} clauses"
        )


class BgeM3Embedder:
    def __init__(self, settings: Settings, *, model: _BgeModel | None = None) -> None:
        self._settings = settings
        self._model = model

    def _active_model(self) -> _BgeModel:
        if self._model is not None:
            return self._model
        return _load_model(self._settings.embedding_model, self._settings.embedding_use_fp16)

    def embed(self, clauses: list[Clause]) -> list[ClauseEmbedding]:
        if not clauses:
            return []
        raw = self._active_model().encode(
            [embedding_text(clause) for clause in clauses],
            batch_size=self._settings.embedding_batch_size,
            max_length=self._settings.embedding_max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        _validate_count(raw, len(clauses))
        return [
            self._build_embedding(clause, dense, sparse)
            for clause, dense, sparse in zip(
                clauses, raw["dense_vecs"], raw["lexical_weights"], strict=True
            )
        ]

    def _build_embedding(
        self,
        clause: Clause,
        dense: Sequence[float],
        sparse: Mapping[str | int, float],
    ) -> ClauseEmbedding:
        indices, values = _sparse_parts(sparse)
        return ClauseEmbedding(
            clause_id=clause.clause_id,
            dense=[float(value) for value in dense],
            sparse_indices=indices,
            sparse_values=values,
        )
