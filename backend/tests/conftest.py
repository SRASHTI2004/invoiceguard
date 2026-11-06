import pytest

from app import config, db, paypal
from seed.seed import seed_db


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")  # force cache-only
    seed_db()
    payouts = []

    def fake_send(ref, email, amount_cents, note, client=None):
        payouts.append({"ref": ref, "email": email, "cents": amount_cents})
        return {"batch_id": f"BATCH{len(payouts)}", "status": "PENDING"}

    monkeypatch.setattr(paypal, "send_payout", fake_send)
    monkeypatch.setattr(paypal, "get_payout_status", lambda batch_id, client=None: "SUCCESS")
    conn = db.connect()
    yield conn, payouts
    conn.close()
