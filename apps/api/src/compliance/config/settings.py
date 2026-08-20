from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

Jurisdiction = str  # "IN" | "EU" | "US"; validated against the document registry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMPLIANCE_", env_file=".env")

    corpus_dir: Path = Path("data/corpus")

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "regulations"

    database_url: PostgresDsn

    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Retrieve wide, rerank narrow. The reranker is the expensive step, so the
    # first number is what we can afford to pay the vector store for and the
    # second is what we can afford to pay the cross-encoder for.
    retrieval_top_k: int = 50
    rerank_top_k: int = 8

    # Below this, we return retrieved clauses without synthesis rather than
    # generating an answer we cannot attribute.
    min_citation_support: float = Field(default=0.6, ge=0.0, le=1.0)

    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b-instruct"

    @property
    def is_local(self) -> bool:
        return self.qdrant_url.startswith("http://localhost")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env
