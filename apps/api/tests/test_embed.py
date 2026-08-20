from datetime import date

from compliance.config.settings import Settings
from compliance.retrieval.embed import BgeM3Embedder, _RawEmbedding
from compliance.schemas import Clause


class _FakeBgeModel:
    def __init__(self) -> None:
        self.sentences: list[str] = []

    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        max_length: int,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
    ) -> _RawEmbedding:
        self.sentences = sentences
        assert batch_size == 2
        assert max_length == 128
        assert return_dense and return_sparse and not return_colbert_vecs
        return {
            "dense_vecs": [[0.1, 0.2, 0.3]],
            "lexical_weights": [{"7": 0.25, "2": 0.75}],
        }


def _clause() -> Clause:
    return Clause(
        clause_id="rbi-kyc-md:v1:1",
        doc_id="rbi-kyc-md",
        version="v1",
        jurisdiction="IN",
        framework="RBI",
        clause_path="Chapter I > 1",
        text="A regulated entity must identify its customer.",
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )


def test_bge_wrapper_returns_dense_and_sorted_lexical_weights() -> None:
    settings = Settings(
        database_url="postgresql://u:p@localhost/db",
        embedding_batch_size=2,
        embedding_max_length=128,
    )
    model = _FakeBgeModel()
    embedder = BgeM3Embedder(settings, model=model)

    result = embedder.embed([_clause()])

    assert model.sentences == ["Chapter I > 1\n\nA regulated entity must identify its customer."]
    assert result[0].dense == [0.1, 0.2, 0.3]
    assert result[0].sparse_indices == [2, 7]
    assert result[0].sparse_values == [0.75, 0.25]


def test_empty_batch_does_not_load_the_model() -> None:
    settings = Settings(database_url="postgresql://u:p@localhost/db")

    assert BgeM3Embedder(settings).embed([]) == []
