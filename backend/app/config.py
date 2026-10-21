"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://shopwise:shopwise@localhost:5432/shopwise"

    # Semantic search (Module 3A): Amazon Titan Text Embeddings V2 through the same Bedrock
    # client and credentials as the chat agent. V2 supports 256, 512 or 1024 dimensions; the
    # pgvector column size follows embedding_dim. New databases get it directly; databases created
    # with Module 1's vector(1536) are resized once by hand: python -m app.migrate_embedding_dim
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dim: int = 1024

    # Load data/laptops.csv on startup when the products table is empty.
    auto_ingest: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    aws_region: str = "us-east-1"
    bedrock_model_id: str = "amazon.nova-lite-v1:0"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
