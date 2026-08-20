import pytest
from compliance.config.settings import Settings


def test_rerank_window_is_narrower_than_retrieval() -> None:
    s = Settings(database_url="postgresql://u:p@localhost/db")
    assert s.rerank_top_k < s.retrieval_top_k


def test_citation_support_threshold_is_a_probability() -> None:
    with pytest.raises(ValueError):
        Settings(database_url="postgresql://u:p@localhost/db", min_citation_support=1.4)
