# ShopWise Module 2B (Bedrock integration)

This is the integrated copy of Module 2A plus the four uploaded AI modules.

## Local Docker setup
1. Do not overwrite an existing `.env`. Copy `.env.example` to `.env` if needed.
2. Authenticate on the Mac using AWS CLI; verify with `aws sts get-caller-identity`.
3. AWS CLI profiles based on Identity Center or `aws login` may require a local credential helper/cache. A read-only `.aws` mount **does not always work** in a Linux container, especially for SSO/credential-process profiles. Prefer a working short-lived profile/role credentials mechanism. Never commit secrets or mount your entire home directory.
4. Run `docker compose up --build`, visit http://localhost:3000.
5. The chat endpoint is `POST /chat` on FastAPI; nginx routes browser `/api/chat` to it.
6. Model must support Bedrock Converse tool use in your region/account. Configure `BEDROCK_MODEL_ID` accordingly.

## Tests
`cd backend && python -m pytest -q` (requires dev requirements and dependencies). Tests mock Bedrock.
`cd frontend && npm install && npm run build`.

## Known limitations
- Only synthetic laptop data; no current prices, purchases or stock.
- No conversation persistence; one question per Bedrock request.
- Integration requires a live credentialed invocation after account verification.
- Existing unit tests may need local dependencies; see test output.

## Module 2C-2: AI product comparison
- Endpoint: `POST /compare/analyze` on FastAPI (browser: `/api/compare/analyze` via nginx / Vite).
  Body: `{"product_ids": [1, 2], "use_case": "programming"}`; 2-3 unique positive ids; `use_case` is optional
  (`general` | `programming` | `student` | `gaming` | `travel`). Extra fields (e.g. client-supplied specs) are rejected with 422.
- Specs are read from PostgreSQL (`crud.get_products_by_ids`); any missing id returns 404 `products_not_found`.
- One Bedrock Converse call (`app/ai/compare.py`), reusing `create_bedrock_client()`, `BEDROCK_MODEL_ID` and the
  existing error mapping. Structured output comes from a forced `submit_comparison` tool (`toolChoice`) and is
  validated server-side; recommended ids not in the selection are discarded (returned as `null` with a `warnings` entry).
- Tests: `backend/tests/test_compare_api.py` (fake Bedrock, no AWS calls).
