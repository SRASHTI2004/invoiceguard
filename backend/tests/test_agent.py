import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agent, config, pipeline
from app.main import app

SAMPLES = Path(__file__).parents[1] / "seed" / "invoices"


def run(conn, name):
    return pipeline.process_invoice(conn, (SAMPLES / name).read_bytes(), name)


def scripted(responses, seen=None):
    """A fake Gemini that replays the given candidate contents in order."""
    it = iter(responses)

    def handler(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"candidates": [{"content": next(it)}]})

    return httpx.Client(base_url="https://g.test", transport=httpx.MockTransport(handler))


def call(name, **args):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}


def say(text):
    return {"role": "model", "parts": [{"text": text}]}


@pytest.fixture()
def held(env):
    conn, payouts = env
    inv = run(conn, "inv12_cedarpine_partial.pdf")
    assert inv["status"] == "HELD" and "less than the PO" in inv["reason"]
    return conn, payouts, inv


def test_agent_pays_a_soft_hold_through_the_firewall(held, monkeypatch):
    conn, payouts, inv = held
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    client = scripted([call("list_invoices", status="HELD"), call("request_payment", invoice_id=inv["id"]),
                       say("Paid the Cedar & Pine invoice.")])
    out = agent.run_agent(conn, "pay held invoices due this week", today="2026-11-06", client=client)
    assert [s["tool"] for s in out["steps"]] == ["list_invoices", "request_payment"]
    assert out["steps"][1]["result"]["paid"] is True and out["reply"].startswith("Paid")
    assert len(payouts) == 1 and payouts[0]["cents"] == 300000
    assert pipeline.get_invoice(conn, inv["id"])["status"] == "PAID"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='agent_requested_payment'").fetchone()[0] == 1


def test_agent_can_never_pay_a_blocked_invoice(env):
    conn, payouts = env
    blocked = run(conn, "inv08_pinnacle_email_changed.pdf")
    res = pipeline.agent_pay(conn, blocked["id"])
    assert res["paid"] is False and payouts == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='agent_refused'").fetchone()[0] == 1


def test_agent_cannot_override_a_limit(held, monkeypatch):
    conn, payouts, inv = held
    monkeypatch.setattr(config, "PER_PAYMENT_LIMIT_CENTS", 100000)
    res = pipeline.agent_pay(conn, inv["id"])
    assert res["paid"] is False and "per-payment limit" in res["refused"][0] and payouts == []


def test_agent_refuses_when_ai_review_was_missing(env):
    conn, payouts = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    held_inv = run(conn, "inv12_cedarpine_partial.pdf")
    assert pipeline.agent_pay(conn, held_inv["id"])["paid"] is False and payouts == []


def test_agent_cannot_pay_twice(held):
    conn, payouts, inv = held
    assert pipeline.agent_pay(conn, inv["id"])["paid"] is True
    assert pipeline.agent_pay(conn, inv["id"])["paid"] is False
    assert len(payouts) == 1


def test_unknown_tool_and_bad_args_are_handled(held):
    conn, _, _ = held
    assert "error" in agent.dispatch(conn, "delete_everything", {}, [0], 10)
    assert "error" in agent.dispatch(conn, "request_payment", {"invoice_id": "abc"}, [0], 10)
    assert agent.dispatch(conn, "request_payment", {"invoice_id": 999}, [0], 10)["paid"] is False


def test_payment_cap_per_request(held):
    conn, payouts, inv = held
    assert agent.dispatch(conn, "request_payment", {"invoice_id": inv["id"]}, [10], 10)["paid"] is False
    assert payouts == []


def test_step_limit_stops_a_looping_agent(held, monkeypatch):
    conn, _, _ = held
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    out = agent.run_agent(conn, "loop", client=scripted([call("list_invoices")] * 3), max_steps=3)
    assert "too many steps" in out["reply"] and len(out["steps"]) == 3


def test_agent_sends_tool_results_back_and_never_sends_the_key(held, monkeypatch):
    conn, _, _ = held
    monkeypatch.setattr(config, "GEMINI_API_KEY", "secret-key")
    seen = []
    agent.run_agent(conn, "list", client=scripted([call("list_invoices"), say("ok")], seen))
    last = seen[-1]["contents"][-1]["parts"][0]["functionResponse"]
    assert last["name"] == "list_invoices" and "invoices" in last["response"]["result"]
    assert "secret-key" not in json.dumps(seen)


def test_agent_route_reports_gemini_down(env, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with TestClient(app) as c:
        assert c.post("/api/agent", json={"message": "hi"}).status_code == 503
        assert c.post("/api/agent", json={"message": "  "}).status_code == 400
