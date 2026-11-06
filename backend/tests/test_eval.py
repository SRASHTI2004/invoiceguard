import json

import pytest

from app import config, db, paypal
from eval import run_eval
from seed.seed import seed_db


def test_eval_metrics_on_sample_invoices(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(paypal, "send_payout", lambda *a, **k: {"batch_id": "X", "status": "PENDING"})
    seed_db()
    labels = json.loads((run_eval.SEED / "labels.json").read_text())
    conn = db.connect()
    r = run_eval.evaluate(conn, labels)
    assert (r["fraud_caught"], r["fraud_total"]) == (6, 6)
    assert (r["valid_wrongly_held"], r["valid_total"]) == (0, 5)
    assert r["valid_cents_paid"] == 670050
