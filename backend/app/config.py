"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://shopwise:shopwise@localhost:5432/shopwise"

    # Size of the pgvector column. The column exists from Module 1 (so the schema is
    # stable) but stays empty until Module 2 adds embeddings.
    embedding_dim: int = 1536

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
