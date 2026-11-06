import pytest

from app import checks, config, db
from seed.data import SANDBOX_EMAIL
from seed.seed import seed_db


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    seed_db()
    c = db.connect()
    yield c
    c.close()


def good_invoice(**over):
    inv = dict(supplier_name="Northwind Office Supplies", invoice_number="INV-1", invoice_date="2026-10-28",
               po_number="PO-1001", total_cents=124000, payee_email=SANDBOX_EMAIL,
               line_items=[{"description": "x", "qty": 10, "unit_cents": 12400}])
    inv.update(over)
    return inv


def codes(findings):
    return {f.code for f in findings}


def save(conn, inv, status="RECEIVED", paid_at=None):
    sid = checks.get_supplier(conn, inv["supplier_name"])["id"]
    cur = conn.execute(
        "INSERT INTO invoices (supplier_id, supplier_name, invoice_number, invoice_date, total_cents, status, paid_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, inv["supplier_name"], inv["invoice_number"], inv["invoice_date"], inv["total_cents"], status, paid_at))
    conn.commit()
    return cur.lastrowid


def test_clean_invoice_passes(conn):
    assert checks.run_checks(conn, good_invoice()) == []


def test_missing_fields_holds(conn):
    f = checks.run_checks(conn, good_invoice(invoice_number=""))
    assert codes(f) == {"missing_fields"} and f[0].severity == checks.HOLD


def test_line_items_must_add_up(conn):
    inv = good_invoice(line_items=[{"description": "x", "qty": 1, "unit_cents": 100}])
    f = checks.run_checks(conn, inv)
    assert "total_mismatch" in codes(f) and f[0].severity == checks.HOLD


def test_unknown_and_unapproved_supplier_block(conn):
    assert "unknown_supplier" in codes(checks.run_checks(conn, good_invoice(supplier_name="Nobody Ltd")))
    f = checks.run_checks(conn, good_invoice(supplier_name="Shadowline Trading", po_number="PO-1001"))
    assert "unapproved_supplier" in codes(f)


def test_duplicate_invoice_number(conn):
    save(conn, good_invoice(invoice_date="2026-01-01", total_cents=5))
    f = checks.run_checks(conn, good_invoice())
    assert "duplicate_number" in codes(f)


def test_duplicate_amount_and_date(conn):
    save(conn, good_invoice(invoice_number="OTHER"))
    assert "duplicate_amount_date" in codes(checks.run_checks(conn, good_invoice()))


def test_invoice_does_not_duplicate_itself(conn):
    inv = good_invoice()
    iid = save(conn, inv)
    assert checks.run_checks(conn, inv, exclude_id=iid) == []


def test_po_checks(conn):
    inflated = good_invoice(total_cents=200000, line_items=[{"description": "x", "qty": 1, "unit_cents": 200000}])
    assert "over_po" in codes(checks.run_checks(conn, inflated))
    under = good_invoice(total_cents=100000, line_items=[{"description": "x", "qty": 1, "unit_cents": 100000}])
    f = checks.run_checks(conn, under)
    assert codes(f) == {"under_po"} and f[0].severity == checks.HOLD
    assert "po_not_found" in codes(checks.run_checks(conn, good_invoice(po_number="PO-9999")))
    assert "po_wrong_supplier" in codes(checks.run_checks(conn, good_invoice(po_number="PO-1002")))
    assert codes(checks.run_checks(conn, good_invoice(po_number=None))) == {"no_po"}


def test_payee_email_mismatch_blocks_case_insensitively(conn):
    assert "payee_email_mismatch" in codes(checks.run_checks(conn, good_invoice(payee_email="evil@example.net")))
    assert checks.run_checks(conn, good_invoice(payee_email=SANDBOX_EMAIL.upper())) == []


def test_per_payment_limit(conn, monkeypatch):
    monkeypatch.setattr(config, "PER_PAYMENT_LIMIT_CENTS", 100000)
    f = checks.run_checks(conn, good_invoice())
    assert codes(f) == {"over_payment_limit"} and f[0].severity == checks.HOLD


def test_daily_limit_counts_only_todays_paid(conn, monkeypatch):
    monkeypatch.setattr(config, "DAILY_LIMIT_CENTS", 200000)
    save(conn, good_invoice(invoice_number="A", invoice_date="2026-01-01"), "PAID", "2026-11-06 09:00:00")
    save(conn, good_invoice(invoice_number="B", invoice_date="2026-01-02"), "PAID", "2026-11-05 09:00:00")  # other day
    save(conn, good_invoice(invoice_number="C", invoice_date="2026-01-03"), "HELD")  # not paid
    assert checks.paid_today_cents(conn, "2026-11-06") == 124000
    assert "over_daily_limit" in codes(checks.run_checks(conn, good_invoice(), today="2026-11-06"))
    assert "over_daily_limit" not in codes(checks.run_checks(conn, good_invoice(), today="2026-11-07"))
