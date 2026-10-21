# ShopWise AI: Intelligent Laptop Research Agent

An AI shopping assistant that will let you describe the laptop you want in plain language and get grounded,
comparable recommendations. The project is built one module at a time.

| # | Module | Status |
| --- | --- | --- |
| 1 | Project setup + product database | Done |
| 2A | Product search & filtering (keyword, price, RAM, CPU) | **Current** |
| 2B, 2C | Remaining Module 2 work (AI semantic search) | Not started |
| 3 | RAG recommendation agent | Not started |
| 4 | Frontend + product comparison | Not started |
| 5 | Testing + evaluation | Not started |
| 6 | Deployment + documentation | Not started |

> **All product data is mock data.** Brands are real; models, specs, and prices are invented. Every row is flagged
> `is_mock=true` and the UI labels it as mock. See [`backend/data/README.md`](backend/data/README.md).

## What Module 1 includes

- **FastAPI backend**: `GET /health`, `GET /products` (paginated), auto-generated docs at `/docs`
- **PostgreSQL 16 + pgvector** via Docker (the `vector` extension is enabled on startup)
- **`products` table**: full laptop specs, source reference, mock flag, plus a nullable `embedding vector(1536)`
  column that stays empty until Module 2
- **CSV import** (`python -m app.ingest`): validated, idempotent, reports bad rows without aborting
- **41 mock laptops** in `backend/data/laptops.csv`
- **React + TypeScript + Tailwind scaffold**: a live health badge and a paginated product table
- **Pytest**: unit tests (no database needed) plus an opt-in integration test against real Postgres

Not included yet: embeddings, search, filters, RAG, comparison.

## Project layout

```
backend/
  app/
    main.py            FastAPI app, startup (init DB, auto-import)
    config.py          Settings from env / .env
    database.py        Engine, session, init_db() (enables pgvector, creates tables)
    models.py          Product model
    schemas.py         Response models
    crud.py            Database queries (list/count, with optional filters)
    product_filters.py Search & filter SQL conditions (Module 2A)
    ingest.py          CSV import (python -m app.ingest)
    routers/           health.py, products.py
  data/laptops.csv     Mock catalog
  tests/
frontend/              Vite + React + TypeScript + Tailwind
  src/filters.ts       Filter form validation + query building (no React)
  src/components/      HealthBadge, ProductTable, SearchFilters
docker-compose.yml     db + backend + frontend
```

## Run it

### Option A: everything in Docker (simplest)

```bash
docker compose up --build
```

- App: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>

On first start the backend creates the schema and imports the 41 mock laptops automatically.

### Option B: local development (hot reload)

You need Docker (for Postgres), Python 3.12, and Node 20.

```bash
# 1. Database only
docker compose up -d db

# 2. Backend  (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example ../.env                               # optional: defaults already match
uvicorn app.main:app --reload --port 8000

# 3. Frontend  (terminal 2)
cd frontend
npm install
npm run dev                                              # http://localhost:5173
```

The backend imports the CSV on startup when the table is empty. To import manually (or reload after editing the CSV):

```bash
cd backend
python -m app.ingest            # upsert by SKU
python -m app.ingest --reset    # wipe the table first
```

## Verify Module 1

Run these in order. Each has an expected result.

**1. Health check** (database reachable, pgvector installed, catalog loaded)

```bash
curl -s localhost:8000/health
# {"status":"ok","database":true,"pgvector":true,"products_total":41}
```

**2. Product listing and pagination**

```bash
curl -s "localhost:8000/products?limit=2" | python -m json.tool
# "total": 41, 2 items, each with "is_mock": true and "source_name": "ShopWise Mock Catalog"

curl -s -o /dev/null -w "%{http_code}\n" "localhost:8000/products?limit=0"     # 422 (validation)
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8000/products?limit=101"   # 422
```

**3. Import is idempotent**

```bash
cd backend && python -m app.ingest
# INFO Import finished: inserted=0 updated=0 unchanged=41 skipped=0
```

**4. pgvector is really there** (and the embedding column exists, empty)

```bash
docker compose exec db psql -U shopwise -d shopwise \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';" \
  -c "SELECT count(*) AS products, count(embedding) AS embedded FROM products;"
# vector | 0.x.x
# products=41, embedded=0
```

**5. Frontend**: open <http://localhost:3000> (Docker) or <http://localhost:5173> (dev). You should see the green
badge "API ok · 41 products · pgvector on", a table of 10 laptops each marked "Mock", and working Previous/Next.
Stop the backend and refresh: the badge turns red ("API offline") and the table shows an error with **Try again**.

**6. Tests**

```bash
cd backend
pytest                                   # unit tests (incl. search/filter); integration tests are skipped

# Optional: also test against real Postgres + pgvector (uses a throwaway database)
docker compose up -d db
docker compose exec db createdb -U shopwise shopwise_test
TEST_DATABASE_URL=postgresql+psycopg://shopwise:shopwise@localhost:5432/shopwise_test pytest
```

```bash
cd frontend
npm run build                            # type-checks and builds
```

## Verify Module 2A (search & filtering)

Expected totals below are computed from `backend/data/laptops.csv` (41 mock laptops).

```bash
curl -s "localhost:8000/products?q=lenovo&limit=1"                                   | python -m json.tool | grep '"total"'   # 6
curl -s "localhost:8000/products?q=ryzen&max_price=1000&min_ram_gb=16&limit=1"       | python -m json.tool | grep '"total"'   # 6
curl -s "localhost:8000/products?min_ram_gb=32&limit=1"                              | python -m json.tool | grep '"total"'   # 12
curl -s "localhost:8000/products?cpu=i7&min_ram_gb=32&limit=1"                       | python -m json.tool | grep '"total"'   # 3
curl -s "localhost:8000/products?q=zzzz"                                             # {"items":[],"total":0,"limit":20,"offset":0}
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8000/products?min_price=900&max_price=100"   # 422
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8000/products?min_ram_gb=0"                  # 422
curl -s "localhost:8000/products?q=lenovo&limit=4&offset=4" | python -m json.tool | grep -c '"sku"'                 # 2 (6 matches, page 2)
```

In the browser, above the table you now have a search box, min/max price, a min RAM dropdown, and **Search** /
**Reset** buttons. Try: `ryzen` + max price `1000` + RAM `16 GB or more` (6 laptops); `zzzz` (a friendly "No laptops
match your filters" message with a **Reset filters** button); min `900` with max `100` (inline error, no request sent).
Filters stay active while you use Previous/Next, and a new search always starts on page 1.

## Verify Module 3A (semantic search)

Semantic search ranks products by **meaning** instead of exact keywords: "quiet laptop for coding on trains"
finds laptops whose description and tags fit, even if no product contains those words.

- **Embeddings**: Amazon Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`, 1024 dimensions, normalized)
  through the Bedrock **InvokeModel** API, with the same Bedrock client and credentials as the chat agent
  (`AWS_BEARER_TOKEN_BEDROCK`). The Nova Lite chat agent is unchanged. Settings: `EMBEDDING_MODEL_ID`, `EMBEDDING_DIM`.
- **What is embedded**: brand, model, CPU, GPU, RAM, storage, display, weight, OS, use-case tags and the
  description (stored in `embedding_text`). **Price is not embedded**: price and RAM are exact SQL filters
  applied before ranking (hybrid search), so a result never breaks them.
- **No vector index yet**: with 41 rows an exact scan is faster than an index. Add
  `CREATE INDEX ON products USING hnsw (embedding vector_cosine_ops)` when the catalog grows to tens of thousands.
- **Never automatic**: the backend does not alter the database on startup and does not call Titan on startup.
  The migration and embedding generation below are run by hand.

### Required AWS permission (do this first)

If your IAM policy only allows `amazon.nova-lite-v1:0`, Titan calls fail with `bedrock_access_denied`. The
identity behind `AWS_BEARER_TOKEN_BEDROCK` (the IAM user the Bedrock API key belongs to) also needs
`bedrock:InvokeModel` on the Titan model. Add a statement like this to that identity's policy yourself in the
AWS console (this project never changes AWS settings), and check in **Bedrock → Model catalog** that
Titan Text Embeddings V2 is available in your region:

```json
{
  "Sid": "ShopWiseTitanEmbeddings",
  "Effect": "Allow",
  "Action": "bedrock:InvokeModel",
  "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
}
```

Use your `AWS_REGION` in the ARN if it isn't `us-east-1`.

### Docker acceptance steps

```bash
# 1. Rebuild with the new code (the database and its data are kept)
docker compose up --build -d

# 2. One-time migration: vector(1536) -> vector(1024). Check first, then apply.
#    Safe to repeat; stops without changes if any embedding is stored.
docker compose exec backend python -m app.migrate_embedding_dim --check
docker compose exec backend python -m app.migrate_embedding_dim

# 3. Preview the texts that will be embedded (no AWS calls, no writes)
docker compose exec backend python -m app.embed --dry-run

# 4. Generate embeddings: the only step that calls Titan (41 short texts, well under $0.001)
docker compose exec backend python -m app.embed
docker compose exec backend python -m app.embed   # again: should report embedded=0 unchanged=41
```

Expected output: step 2 `Resized products.embedding from vector(1536) to vector(1024)` (a second run says
`already vector(1024). Nothing to do.`); step 4 `embedded=41 unchanged=0`. A database created from scratch with
this version already has `vector(1024)`, so step 2 just reports that nothing is needed.

**5. Search** in <http://localhost:8000/docs> → `GET /products/semantic-search` → *Try it out*, or:

```bash
curl "http://localhost:8000/products/semantic-search?q=lightweight%20laptop%20for%20programming%20and%20travel&max_price=1200&min_ram_gb=16&limit=3"
```

| Response | Meaning |
| --- | --- |
| `200` with `items` | Ranked results. Each is a normal product plus `similarity` (1 = same meaning; compare within one query only). |
| `200` with `items: []` and `message` | Search works, but no embedded laptop passes the price/RAM filters. |
| `503 embeddings_not_initialized` | Steps 2 and 4 haven't been run yet. AWS is not called. |
| `422` | Invalid request: blank or overlong `q`, min > max price, non-finite numbers, unknown or repeated parameters (a typo such as `maxprice` is rejected instead of silently dropping the filter). |
| `503 bedrock_access_denied` | The IAM permission above is missing. |

`catalog_products` larger than `embedded_products` means some products have no embedding yet: re-run step 4.
The keyword search at `GET /products`, the chat, the comparison and the frontend are unchanged.

## Verify Module 3B (RAG chat: two search tools)

The chat agent (Nova Lite, Bedrock Converse tool use) now has two tools and picks one or both per question:

| Tool | For | How it searches |
| --- | --- | --- |
| `search_products` (2B) | exact brands/models, CPU/GPU families, purely numeric needs | SQL keyword match + exact price/RAM filters |
| `semantic_search_products` (3B) | fuzzy needs: use cases, portability, "good for students" | Titan V2 query embedding + pgvector cosine ranking, **with the same exact SQL price/RAM filters** |

Both tools return database rows only. `/chat` keeps its response shape (`reply`, `products`, `tools_used`);
`products` holds the rows the tools returned, de-duplicated by id (semantic rows also carry `similarity`), never
ids the model typed. If semantic search can't run (embeddings missing, Titan error/permission), the model gets an
**error** tool result (not "no matches") and is told to fall back to `search_products`; there are no retries.
Product descriptions are used for retrieval only and are never sent to the model.

Requires Module 3A to be set up (migration + `python -m app.embed`). Then rebuild and watch the backend log:

```bash
docker compose up --build -d
docker compose logs -f backend | grep -E "search_products|semantic_search_products|unavailable"
```

Each tool call logs one line with counts and filters only (no query text, no credentials), for example:

```
INFO app.ai.agent: semantic_search_products ran: returned=5 max_price=1200.0 min_ram_gb=16 limit=5 query_chars=38
INFO app.ai.agent: search_products ran: total_matches=6 returned=5
WARNING app.ai.agent: semantic_search_products unavailable: embeddings_not_initialized
```

Manual prompts for the chat at <http://localhost:3000> (the tool choice is the model's; check `tools_used` in the
browser's network tab or the log lines above):

1. Exact structured search: `Show me Lenovo laptops under $1000 with at least 16GB RAM` (expect `search_products`)
2. Fuzzy semantic search: `I need something light and quiet for writing code on long train rides` (expect `semantic_search_products`)
3. Combined: `A laptop that's good for a university student who travels a lot, under $900, with 16GB RAM`
   (expect `semantic_search_products` with `max_price=900.0 min_ram_gb=16` in the log; every product must be ≤ $900 and ≥ 16 GB)

## Module 4A: AI quality evaluation

A fixed, version-controlled scenario set plus deterministic checks that score the real `/chat` and
`/compare/analyze` responses. Code: `backend/app/eval/`. Dataset: `backend/app/eval/scenarios.json`
(24 scenarios; catalog facts in it are verified against `data/laptops.csv` by `tests/test_eval_dataset.py`).

**Two modes**

| Mode | Command | Calls AWS? | Measures |
| --- | --- | --- | --- |
| Offline | `pytest tests/test_eval_dataset.py tests/test_eval_checks.py tests/test_eval_runner.py` | never | that the evaluator scores correctly (good, bad and malformed responses), with scripted fakes |
| Live | `python -m app.eval.run --live` | yes, through the running backend | real Nova Lite / Titan V2 behaviour on the scenarios |

Offline pass rates say nothing about real model quality. Live mode is only ever started by hand.

```bash
cd backend
.venv/bin/python -m app.eval.run --list                 # preview: no network, no AWS
.venv/bin/python -m app.eval.run --live --max-cases 3   # smoke test (needs `docker compose up` running)
.venv/bin/python -m app.eval.run --live                 # all scenarios (roughly a few cents of Bedrock usage)
.venv/bin/python -m app.eval.run --live --category no_match   # or --only exact-01 --only mixed-01
```

The runner talks to `http://localhost:8000` (`--base-url` to change), loads the catalog from `GET /products`
(PostgreSQL is the source of truth), sends one request at a time with a 90 s timeout (`--timeout`), never retries,
pauses 1 s between cases (`--delay`) and keeps going when a case fails. It needs no AWS credentials itself;
the backend makes the provider calls. Reports: `backend/eval_reports/eval-live-<UTC time>.json` and `.md`
(git-ignored because they contain model replies; `--out` to change).

**Check statuses**: every check is PASS, FAIL or UNKNOWN (not measurable). UNKNOWN is never counted as PASS.
Case verdicts: PASS (all checks pass), INCOMPLETE (no failure, something unknown), FAIL, ERROR (request failed).

| Family | What it checks |
| --- | --- |
| contract | the response arrived with the documented shape; plain text (no markdown) |
| grounding | structured product ids exist and fields match the catalog; prices/RAM/storage quoted next to a single product name match it; named products came from tool results |
| constraints | explicit max price / min RAM / brand / OS / GPU limits, using database values; structured `products` and reply text reported separately; no-match explained |
| tool_selection | the tools that actually ran (`tools_used`): required / preferred / forbidden; a reply claiming a search is not evidence |
| honesty | synthetic-data disclaimer; affirmative stock, benchmark, live-price or battery claims; URLs / retailers; `<thinking>` tags |
| safety | system-prompt or secret leaks, injected prices, invented products, out-of-domain refusals |
| comparison | `/compare/analyze` schema and types, selected ids, recommendations selected-or-null, controlled errors |

Heuristic checks (marked `heuristic` in the JSON) are regular expressions: they flag likely problems and can
produce false positives or miss problems. They cannot prove that no hallucination occurred.

Known evaluator limitations (found in the first live runs, not fixed yet):
- `honesty.synthetic_disclaimer` also triggers when the reply only repeats a product name the user typed
  (e.g. "no stock data for the IdeaSlim 14 OLED"), which can be a false positive.
- Negated sentences are skipped by `safety.rejects_injected_prices`, so "listed as $1, which is not realistic"
  passes that check (a false negative; `grounding.reply_specs_match` still flags the $1).
- Model output varies between runs: in two runs against the same server, 6 of 24 cases changed verdict.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | `{status, database, pgvector, products_total}`; HTTP 503 when degraded |
| GET | `/products` | `{items, total, limit, offset}`; paginated, optionally filtered (below) |

`GET /products` query parameters. All are optional and combine with AND; `total` always counts the **filtered** set.

| Parameter | Type / range | Meaning |
| --- | --- | --- |
| `limit` | int 1-100, default 20 | Page size |
| `offset` | int >= 0, default 0 | Rows to skip |
| `q` | text, max 100 chars, max 8 words | Keyword search over brand, model name, CPU, GPU, OS, display resolution and use-case tags. **Every word must match** (in any of those fields), case-insensitively |
| `min_price`, `max_price` | number 0-1,000,000 | Inclusive USD bounds. `min_price` must not exceed `max_price` |
| `min_ram_gb` | int 1-1024 | At least this much RAM |
| `cpu` | text, max 50 chars, max 8 words | Like `q`, but matches the CPU field only (for example `i7`, `ryzen`) |

```bash
curl -s "localhost:8000/products?q=ryzen&max_price=1000&min_ram_gb=16&limit=5&offset=0"
```

Matching is substring-based and the dataset is small, so it is deliberately simple: `cpu=ryzen 7` also matches a
"Ryzen 5 7520U" (the digit 7 appears in the model number). Whole-token matching and relevance ranking are not part of 2A.

Invalid input returns HTTP 422 in FastAPI's standard shape, with the offending field named:

```json
{"detail": [{"type": "value_error", "loc": ["query", "min_price"], "msg": "min_price must not be greater than max_price.", "input": 900.0}]}
```

Other errors use `{"detail": {"code", "message"}}` (for example `database_unavailable`, HTTP 503).

## Troubleshooting

- **`/health` shows `products_total: 0`**: the import didn't run. Check backend logs, or run `python -m app.ingest`.
- **`connection refused`**: Postgres isn't up. Run `docker compose up -d db` and wait a few seconds.
- **Port 5432 already in use**: stop your local Postgres, or change the host port in `docker-compose.yml`.
- **Frontend shows "API offline" in dev**: the backend must be on port 8000 (or set `VITE_API_PROXY`).
- **`python -m app.embed` says the column is `vector(1536)`**: run `python -m app.migrate_embedding_dim` first.
- **The migration says `STOPPED ... embedding(s) are stored`**: nothing was changed. Only if you really want to
  start over, clear them (`UPDATE products SET embedding = NULL, embedding_text = NULL, embedding_model = NULL;`)
  and run the migration again.
- **Semantic search returns `503 embeddings_not_initialized`**: run the migration, then `python -m app.embed`.
- **Local backend (option B) says `role "shopwise" does not exist`**: another PostgreSQL (e.g. Homebrew) is using
  port 5432 on localhost. Stop it (`brew services stop postgresql`) or use Docker (option A).
