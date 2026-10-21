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
- **Changed `EMBEDDING_DIM` after the first run**: the column size is fixed at table creation. Run
  `docker compose down -v` to recreate the database.
