"""End-to-end firewall tests on the real sample PDFs. Gemini results come from the pre-seeded cache
(the API key is blanked, so any real Gemini call would fail), and PayPal is faked."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import paypal, pipeline
from app.main import app
from seed.data import INVOICES, SANDBOX_EMAIL

SAMPLES = Path(__file__).parents[1] / "seed" / "invoices"


def run(conn, filename):
    return pipeline.process_invoice(conn, (SAMPLES / filename).read_bytes(), filename)


def test_all_samples_get_the_expected_decision(env):
    conn, payouts = env
    results = {inv["file"]: run(conn, inv["file"]) for inv in INVOICES}  # in order: duplicate comes after original
    for inv in INVOICES:
        r = results[inv["file"]]
        if inv["expected"] == "AUTO_PAY":
            assert r["decision"] == "AUTO_PAY" and r["status"] == "PAID", (inv["file"], r["reason"])
            assert r["payout_batch_id"] and r["payout_status"] == "PENDING"
        elif inv["expected"] == "BLOCK":
            assert r["decision"] == "BLOCK" and r["status"] == "BLOCKED", (inv["file"], r["reason"])
        else:
            assert r["decision"] in ("HOLD", "BLOCK"), inv["file"]
        assert r["reason"]
    assert len(payouts) == 5
    assert {p["email"] for p in payouts} == {SANDBOX_EMAIL}  # paid to the saved supplier email only


def test_fraud_cases_have_the_right_reason(env):
    conn, _ = env
    run(conn, "inv01_northwind.pdf")
    assert "Duplicate" in run(conn, "inv06_northwind_duplicate.pdf")["reason"]
    assert "more than the PO" in run(conn, "inv07_atlas_inflated.pdf")["reason"]
    assert "does not match the saved payment email" in run(conn, "inv08_pinnacle_email_changed.pdf")["reason"]
    assert "AI review" in run(conn, "inv09_blueriver_injection.pdf")["reason"]
    assert "not on the approved list" in run(conn, "inv11_shadowline_unapproved.pdf")["reason"]


def test_every_decision_is_in_the_audit_log(env):
    conn, _ = env
    for inv in INVOICES[:6]:
        run(conn, inv["file"])
    n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='decision'").fetchone()[0]
    assert n == 6


def test_unreadable_invoice_is_held_not_paid(env, monkeypatch):
    conn, payouts = env
    r = pipeline.process_invoice(conn, b"%PDF-1.4 not in cache", "weird.pdf")  # cache miss + no key -> Gemini error
    assert r["status"] == "HELD" and "manually" in r["reason"] and payouts == []


def test_ai_failure_holds_instead_of_paying(env):
    conn, payouts = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    r = run(conn, "inv02_brightline.pdf")  # extraction cached, review missing and Gemini unavailable
    assert r["status"] == "HELD" and "AI review unavailable" in r["reason"] and payouts == []


def test_owner_can_approve_a_held_invoice_once_only(env):
    conn, payouts = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    held = run(conn, "inv02_brightline.pdf")
    paid = pipeline.approve(conn, held["id"])
    assert paid["status"] == "PAID" and len(payouts) == 1 and payouts[0]["cents"] == 86050
    with pytest.raises(pipeline.ActionError):
        pipeline.approve(conn, held["id"])
    assert len(payouts) == 1  # never paid twice


def test_blocked_invoice_cannot_be_approved(env):
    conn, payouts = env
    blocked = run(conn, "inv11_shadowline_unapproved.pdf")
    with pytest.raises(pipeline.ActionError):
        pipeline.approve(conn, blocked["id"])
    assert payouts == []


def test_reject_and_summary(env):
    conn, _ = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    held = run(conn, "inv02_brightline.pdf")
    run(conn, "inv11_shadowline_unapproved.pdf")
    assert pipeline.summary(conn)["total_held_cents"] == 86050
    assert pipeline.reject(conn, held["id"])["status"] == "REJECTED"
    s = pipeline.summary(conn)
    assert s["money_saved_cents"] == 86050 + 190000 and s["total_paid_cents"] == 0


def test_payout_failure_returns_invoice_to_held(env, monkeypatch):
    conn, _ = env

    def boom(*a, **k):
        raise paypal.PayPalError("Sender has insufficient funds")

    monkeypatch.setattr(paypal, "send_payout", boom)
    r = run(conn, "inv01_northwind.pdf")
    assert r["status"] == "HELD" and "insufficient funds" in r["reason"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='payout_failed'").fetchone()[0] == 1


def test_refresh_payout_status(env):
    conn, _ = env
    r = run(conn, "inv01_northwind.pdf")
    assert r["payout_status"] == "PENDING"
    assert pipeline.refresh_payout(conn, r["id"])["payout_status"] == "SUCCESS"
    with pytest.raises(pipeline.ActionError):
        pipeline.refresh_payout(conn, run(conn, "inv11_shadowline_unapproved.pdf")["id"])


def test_api_upload_list_summary(env):
    with TestClient(app) as client:
        r = client.post("/api/invoices/upload", files={"file": ("a.pdf", (SAMPLES / "inv01_northwind.pdf").read_bytes(), "application/pdf")})
        assert r.status_code == 200 and r.json()["status"] == "PAID"
        assert client.post("/api/invoices/upload", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400
        assert len(client.get("/api/invoices").json()) == 1
        assert client.get("/api/summary").json()["total_paid_cents"] == 124000
        assert len(client.get("/api/suppliers").json()) == 19
        assert client.post("/api/invoices/999/approve").status_code == 400
        assert client.post("/api/demo/run-samples").json()["processed"] == 12  # resets first, then loads all 12
        assert len(client.get("/api/invoices").json()) == 12
        assert client.get("/api/audit").status_code == 200


def test_approve_rechecks_at_click_time(env):
    conn, payouts = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    held = run(conn, "inv02_brightline.pdf")
    conn.execute("UPDATE suppliers SET payment_email='changed@example.net' WHERE name='Brightline Packaging Co.'")
    conn.commit()
    with pytest.raises(pipeline.ActionError, match="checks now fail"):
        pipeline.approve(conn, held["id"])
    assert payouts == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='approval_refused'").fetchone()[0] == 1


def snapshot(conn):
    rows = conn.execute("SELECT id, filename, status, decision, total_cents FROM invoices ORDER BY id").fetchall()
    return [tuple(r) for r in rows], pipeline.summary(conn)


def test_load_samples_gives_the_same_result_every_time(env):
    conn, payouts = env
    with TestClient(app) as client:
        first = client.post("/api/demo/run-samples").json()
        a = snapshot(conn)
        second = client.post("/api/demo/run-samples").json()
        b = snapshot(conn)
    assert a == b and first["invoice_ids"] == second["invoice_ids"] == list(range(1, 13))  # ids restart at 1
    s = second["summary"]
    assert s["counts"] == {"PAID": 5, "BLOCKED": 6, "HELD": 1}
    assert s["total_paid_cents"] == 670050 and s["total_held_cents"] == 300000
    assert len(payouts) == 10  # 5 paid per run; nothing was skipped because of earlier runs


def test_leftover_data_cannot_change_the_sample_result(env):
    conn, payouts = env
    # Leftovers from earlier runs: a big payment made today (eats the daily limit) and a duplicate invoice number.
    conn.execute("INSERT INTO invoices (supplier_id, supplier_name, invoice_number, invoice_date, total_cents, "
                 "status, paid_at) VALUES (1, 'Northwind Office Supplies', 'INV-2026-1041', '2026-10-28', 950000, "
                 "'PAID', datetime('now'))")
    conn.commit()
    with TestClient(app) as client:
        client.post("/api/demo/run-samples")
    s = pipeline.summary(conn)
    assert s["counts"] == {"PAID": 5, "BLOCKED": 6, "HELD": 1} and s["total_paid_cents"] == 670050
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 12


def test_reset_keeps_suppliers_pos_and_gemini_cache(env):
    conn, _ = env
    run(conn, "inv01_northwind.pdf")
    n_cache = conn.execute("SELECT COUNT(*) FROM gemini_cache").fetchone()[0]
    pipeline.reset_demo_data(conn)
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 19
    assert conn.execute("SELECT COUNT(*) FROM gemini_cache").fetchone()[0] == n_cache


def test_insufficient_funds_holds_the_invoice_with_a_clear_reason(env, monkeypatch):
    conn, _ = env

    def broke(*a, **k):
        raise paypal.PayPalError("Payout rejected by PayPal (HTTP 422) INSUFFICIENT_FUNDS: no funds", "INSUFFICIENT_FUNDS")

    monkeypatch.setattr(paypal, "send_payout", broke)
    r = run(conn, "inv01_northwind.pdf")
    assert r["status"] == "HELD" and r["reason"] == pipeline.INSUFFICIENT_FUNDS_MESSAGE
    assert "insufficient funds" in r["reason"] and "Add money" in r["reason"]
    audit = conn.execute("SELECT reason, details FROM audit_log WHERE event='payout_failed'").fetchone()
    assert audit["reason"] == pipeline.INSUFFICIENT_FUNDS_MESSAGE and "INSUFFICIENT_FUNDS" in audit["details"]
    # after the owner adds funds, Approve works (same invoice, no loss)
    monkeypatch.setattr(paypal, "send_payout", lambda *a, **k: {"batch_id": "B1", "status": "PENDING"})
    assert pipeline.approve(conn, r["id"])["status"] == "PAID"


def test_other_payout_errors_keep_the_technical_message(env, monkeypatch):
    conn, _ = env

    def fail(*a, **k):
        raise paypal.PayPalError("Payout rejected by PayPal (HTTP 400) VALIDATION_ERROR: bad", "VALIDATION_ERROR")

    monkeypatch.setattr(paypal, "send_payout", fail)
    assert run(conn, "inv01_northwind.pdf")["reason"].startswith("Payout failed: Payout rejected")
