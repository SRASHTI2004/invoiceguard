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
        assert client.post("/api/demo/run-samples").json()["processed"] == 11  # 12 sample PDFs, the first was already uploaded
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
