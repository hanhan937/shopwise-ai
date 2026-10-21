"""API response schemas."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    brand: str
    price: float
    cpu: str
    gpu: str
    ram_gb: int
    storage_gb: int
    storage_type: str
    display_size_in: float
    display_resolution: str
    weight_kg: float
    battery_hours: float | None = None
    os: str
    best_for: list[str] = Field(default_factory=list)
    description: str
    source_name: str
    source_url: str | None = None
    is_mock: bool = True

    @field_validator("price", mode="before")
    @classmethod
    def _price_to_float(cls, v):  # Numeric columns come back as Decimal
        return float(v)

    @field_validator("best_for", mode="before")
    @classmethod
    def _split_tags(cls, v):  # stored as "programming;travel"
        if isinstance(v, str):
            return [t.strip() for t in v.split(";") if t.strip()]
        return v


class ProductList(BaseModel):
    items: list[ProductOut]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    database: bool  # can we run a query?
    pgvector: bool  # is the `vector` extension installed?
    products_total: int
