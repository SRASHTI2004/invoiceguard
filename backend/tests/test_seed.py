from app import config, db
from seed.data import DEMO_INVOICES, INVOICES, PURCHASE_ORDERS, SUPPLIERS
from seed.seed import seed_db


def test_seed_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    assert seed_db() is True
    assert seed_db() is False  # second call does nothing
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == len(SUPPLIERS)
        assert conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == len(PURCHASE_ORDERS)


def test_sample_invoices_are_consistent():
    names = {s[0] for s in SUPPLIERS}
    for inv in INVOICES:
        assert inv["supplier"] in names
        assert sum(q * u for _, q, u in inv["items"]) == inv["total"]
    assert 8 <= len(INVOICES) <= 12
    assert any(i["category"] == "prompt_injection" and i.get("hidden") for i in INVOICES)


def test_sample_pdfs_are_pre_cached_so_no_gemini_call_is_needed(tmp_path, monkeypatch):
    from pathlib import Path

    from app import gemini
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    seed_db()
    with db.connect() as conn:
        for inv in INVOICES + DEMO_INVOICES:
            h = gemini.pdf_hash((Path(__file__).parents[1] / "seed" / "invoices" / inv["file"]).read_bytes())
            kinds = {r[0] for r in conn.execute("SELECT kind FROM gemini_cache WHERE file_hash = ?", (h,))}
            assert kinds == {"extract", "review"}, inv["file"]
