"""Module 3A embeddings: Titan request/response handling and the backfill command. No AWS calls."""
import io
import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from app.ai.embeddings import TitanEmbedder, build_embedding_text, model_tag
from app.ai.errors import ChatError
from app.embed import embed_products
from app.migrate_embedding_dim import decide

MODEL = "amazon.titan-embed-text-v2:0"


class FakeTitan:
    """Mimics bedrock-runtime invoke_model for Titan V2."""

    def __init__(self, dims=1024, error=None, payload=None):
        self.dims, self.error, self.payload, self.calls = dims, error, payload, []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        payload = self.payload if self.payload is not None else {"embedding": [0.01] * self.dims, "inputTextTokenCount": 5}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


# ------------------------------------------------------------------ embedding text
def test_embedding_text_has_specs_tags_and_description_but_not_price(make_product):
    p = make_product(name="DevBook 14 Pro", price=849, best_for="programming;travel", description="Quiet and light.")
    text = build_embedding_text(p)
    for part in ("Lenovo DevBook 14 Pro", "AMD Ryzen 7 7840U", "Integrated Radeon 780M", "16 GB RAM", "512 GB SSD",
                 "1.3 kg", "Windows 11", "Good for: programming, travel.", "Quiet and light."):  # fmt: skip
        assert part in text
    assert "849" not in text and "$" not in text


def test_embedding_text_without_tags(make_product):
    assert "Good for" not in build_embedding_text(make_product(best_for=""))


# ------------------------------------------------------------------ Titan client
def test_titan_request_format_and_response_parsing():
    fake = FakeTitan()
    vector = TitanEmbedder(fake, MODEL, 1024).embed("quiet laptop")
    assert len(vector) == 1024 and all(isinstance(v, float) for v in vector)
    call = fake.calls[0]
    assert call["modelId"] == MODEL and call["contentType"] == "application/json"
    assert json.loads(call["body"]) == {"inputText": "quiet laptop", "dimensions": 1024, "normalize": True}


def test_titan_rejects_unsupported_dimensions():
    with pytest.raises(ValueError):
        TitanEmbedder(FakeTitan(), MODEL, 1536)


@pytest.mark.parametrize(
    "payload",
    [{"embedding": [0.1] * 512}, {"embedding": None}, {}, {"embedding": [0.1] * 1023 + ["x"]}, {"embedding": [0.1] * 1023 + [float("nan")]}],
    ids=["wrong-size", "null", "missing", "non-number", "nan"],
)
def test_titan_invalid_response_is_a_safe_error(payload):
    with pytest.raises(ChatError) as err:
        TitanEmbedder(FakeTitan(payload=payload), MODEL, 1024).embed("x")
    assert err.value.code == "embedding_invalid"


def test_titan_aws_errors_are_mapped():
    auth = ClientError({"Error": {"Code": "UnrecognizedClientException"}}, "InvokeModel")
    with pytest.raises(ChatError) as err:
        TitanEmbedder(FakeTitan(error=auth), MODEL).embed("x")
    assert err.value.code == "aws_credentials_invalid"
    with pytest.raises(ChatError) as err:
        TitanEmbedder(FakeTitan(error=ReadTimeoutError(endpoint_url="https://x")), MODEL).embed("x")
    assert err.value.code == "ai_timeout"


# ------------------------------------------------------------------ backfill command
@pytest.fixture
def catalog(make_product):
    products = [make_product(), make_product(), make_product()]
    db = MagicMock()
    db.scalars.return_value = products
    return db, products


def test_embed_products_fills_all_three_columns_and_commits_each(catalog):
    db, products = catalog
    fake = FakeTitan()
    stats = embed_products(db, TitanEmbedder(fake, MODEL))
    assert (stats.embedded, stats.unchanged) == (3, 0)
    assert len(fake.calls) == 3 and db.commit.call_count == 3
    for p in products:
        assert len(p.embedding) == 1024
        assert p.embedding_text == build_embedding_text(p)
        assert p.embedding_model == model_tag(MODEL, 1024)


def test_second_run_makes_no_aws_calls(catalog):
    db, _ = catalog
    embed_products(db, TitanEmbedder(FakeTitan(), MODEL))
    again = FakeTitan()
    stats = embed_products(db, TitanEmbedder(again, MODEL))
    assert (stats.embedded, stats.unchanged) == (0, 3)
    assert again.calls == []


def test_changed_product_text_or_model_is_re_embedded(catalog):
    db, products = catalog
    embed_products(db, TitanEmbedder(FakeTitan(), MODEL))
    products[0].description = "Updated description after a CSV import."
    products[1].embedding_model = "amazon.titan-embed-text-v1:1536"
    fake = FakeTitan()
    stats = embed_products(db, TitanEmbedder(fake, MODEL))
    assert (stats.embedded, stats.unchanged) == (2, 1)


def test_force_re_embeds_everything(catalog):
    db, _ = catalog
    embed_products(db, TitanEmbedder(FakeTitan(), MODEL))
    forced = FakeTitan()
    assert embed_products(db, TitanEmbedder(forced, MODEL), force=True).embedded == 3
    assert len(forced.calls) == 3


def test_dry_run_makes_no_calls_and_no_writes(catalog):
    db, products = catalog
    dry = FakeTitan()
    stats = embed_products(db, TitanEmbedder(dry, MODEL), dry_run=True)
    assert stats.would_embed == 3 and dry.calls == [] and db.commit.call_count == 0
    assert all(p.embedding is None and p.embedding_text is None for p in products)


def test_aws_failure_keeps_earlier_progress(catalog):
    db, products = catalog

    class FailsOnSecond(FakeTitan):
        def invoke_model(self, **kwargs):
            if len(self.calls) == 1:
                self.calls.append(kwargs)
                raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")
            return super().invoke_model(**kwargs)

    with pytest.raises(ChatError) as err:
        embed_products(db, TitanEmbedder(FailsOnSecond(), MODEL))
    assert err.value.code == "ai_rate_limited"
    assert products[0].embedding is not None and products[1].embedding is None
    assert db.commit.call_count == 1


# ------------------------------------------------------------------ migration decision rule
@pytest.mark.parametrize(
    "current, stored, expected",
    [("vector(1536)", 0, "migrate"), ("vector(1024)", 0, "already_done"), ("vector(1024)", 41, "already_done"),
     ("vector(1536)", 1, "blocked"), (None, 0, "missing")],
)  # fmt: skip
def test_migration_decision(current, stored, expected):
    assert decide(current, stored, 1024) == expected
