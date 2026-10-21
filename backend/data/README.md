# Mock laptop dataset

`laptops.csv` is **synthetic development data**, not real product listings.

- Brand names are real; model names, specifications, and prices are invented.
- Every row has `is_mock=true`, and the UI shows a "Mock data" badge on every card.
- `source_url` points to `example.com` placeholders. Replace the CSV (same columns) with
  real data and set `is_mock=false` to remove the badge.

| Column | Notes |
| --- | --- |
| `sku` | Unique key; ingest upserts by SKU |
| `price` | USD, whole dollars |
| `storage_gb` | Binary sizes are used for "1 TB" (1024) and "2 TB" (2048) |
| `best_for` | Semicolon-separated use-case tags, included in the embedded text |
| `source_name`, `source_url` | Shown as the product's source reference |

Run `python -m app.ingest --reset` after editing the file.
