from app import config, db
from seed.data import INVOICES, PURCHASE_ORDERS, SUPPLIERS
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
