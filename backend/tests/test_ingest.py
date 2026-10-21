from unittest.mock import MagicMock

from app.ingest import DEFAULT_CSV, ProductRow, ingest, read_rows

HEADER = (
    "sku,name,brand,price,cpu,gpu,ram_gb,storage_gb,storage_type,display_size_in,display_resolution,"
    "weight_kg,battery_hours,os,best_for,description,source_name,source_url,is_mock\n"
)
GOOD = "A-1,Book,Dell,500,cpu,gpu,16,512,SSD,14,1080p,1.2,10,Win,programming,desc,Src,,true\n"


# ---------------------------------------------------------------- the sample CSV
def test_sample_dataset_is_valid_and_labelled_mock():
    rows, errors = read_rows(DEFAULT_CSV)
    assert errors == []
    assert len(rows) >= 30
    assert len({r.sku for r in rows}) == len(rows)
    assert all(r.is_mock for r in rows), "every sample row must be flagged as mock data"
    assert all(r.sku.startswith("MOCK-") for r in rows)


def test_sample_dataset_covers_the_demo_scenario():
    rows, _ = read_rows(DEFAULT_CSV)
    assert len([r for r in rows if r.price <= 1000 and r.ram_gb >= 16]) >= 5
    assert len({r.brand for r in rows}) >= 5


# ------------------------------------------------------------------ CSV parsing
def test_invalid_and_duplicate_rows_are_reported_not_fatal(tmp_path):
    bad_price = GOOD.replace("A-1", "A-2").replace(",500,", ",-5,")
    path = tmp_path / "x.csv"
    path.write_text(HEADER + GOOD + bad_price + GOOD, encoding="utf-8")
    rows, errors = read_rows(path)
    assert [r.sku for r in rows] == ["A-1"]
    assert len(errors) == 2
    assert "price" in errors[0] and "duplicate" in errors[1]


def test_blank_optional_cells_use_defaults(tmp_path):
    row = "A-1,Book,Dell,500,cpu,gpu,16,512,,14,1080p,1.2,,Win,,desc,Src,,\n"
    path = tmp_path / "x.csv"
    path.write_text(HEADER + row, encoding="utf-8")
    rows, errors = read_rows(path)
    assert errors == []
    assert isinstance(rows[0], ProductRow)
    assert rows[0].storage_type == "SSD" and rows[0].battery_hours is None and rows[0].is_mock is True


# ------------------------------------------------- upsert behaviour (no database)
def _session_with(existing):
    db = MagicMock()
    db.scalars.return_value = list(existing)
    return db


def test_first_import_inserts_every_row():
    rows, _ = read_rows(DEFAULT_CSV)
    db = _session_with([])
    stats = ingest(db, DEFAULT_CSV)
    assert (stats.inserted, stats.updated, stats.unchanged) == (len(rows), 0, 0)
    assert db.add.call_count == len(rows)
    db.commit.assert_called_once()


def test_second_import_is_idempotent_and_changes_are_detected():
    first = _session_with([])
    ingest(first, DEFAULT_CSV)
    products = [call.args[0] for call in first.add.call_args_list]

    again = ingest(_session_with(products), DEFAULT_CSV)
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, len(products))

    products[0].content_hash = "stale"  # simulate the CSV row having changed
    changed = ingest(_session_with(products), DEFAULT_CSV)
    assert (changed.inserted, changed.updated, changed.unchanged) == (0, 1, len(products) - 1)
