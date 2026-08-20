from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

Jurisdiction = str  # "IN" | "EU" | "US"; validated against the document registry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMPLIANCE_", env_file=".env")

    corpus_dir: Path = Path("data/corpus")
    corpus_manifest: Path = Path("data/corpus/manifest.yaml")
    corpus_fetch_timeout_seconds: float = Field(default=120.0, gt=0.0)
    corpus_fetch_chunk_bytes: int = Field(default=64 * 1024, gt=0)
    corpus_fetch_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
    )
    corpus_fetch_referer: str = "https://www.rbi.org.in/"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "regulations"
    qdrant_dense_size: int = Field(default=1024, gt=0)
    qdrant_upsert_batch_size: int = Field(default=64, gt=0)

    database_url: PostgresDsn
    database_pool_min_size: int = Field(default=0, ge=0)
    database_pool_max_size: int = Field(default=10, gt=0)

    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = Field(default=16, gt=0)
    embedding_max_length: int = Field(default=8192, gt=0)
    embedding_use_fp16: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_batch_size: int = Field(default=16, gt=0)
    reranker_max_length: int = Field(default=1024, gt=0)
    reranker_use_fp16: bool = False

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
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    @property
    def is_local(self) -> bool:
        return self.qdrant_url.startswith("http://localhost")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from env
