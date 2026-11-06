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


def events(conn, name):
    return conn.execute("SELECT COUNT(*) FROM audit_log WHERE event=?", (name,)).fetchone()[0]


@pytest.fixture()
def held(env):
    conn, payouts = env
    inv = run(conn, "inv12_cedarpine_partial.pdf")
    assert inv["status"] == "HELD" and "less than the PO" in inv["reason"]
    return conn, payouts, inv


# ---- the agent can only recommend ------------------------------------------------------------------------------

def test_agent_has_no_payment_tool():
    names = {t["name"] for t in agent.TOOL_DECLARATIONS}
    assert names == {"list_invoices", "run_checks", "propose_payment"}


def test_agent_never_moves_money_even_if_the_model_asks_to_pay(held):
    conn, payouts, inv = held
    for name in ("request_payment", "pay_invoice", "approve"):
        assert "error" in agent.dispatch(conn, name, {"invoice_id": inv["id"]})
    assert payouts == [] and pipeline.get_invoice(conn, inv["id"])["status"] == "HELD"


def test_agent_run_returns_a_proposal_and_pays_nothing(held, monkeypatch):
    conn, payouts, inv = held
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    client = scripted([call("list_invoices", status="HELD"), call("propose_payment", invoice_id=inv["id"]),
                       say("I recommend paying the Cedar & Pine invoice.")])
    out = agent.run_agent(conn, "pay held invoices due this week", today="2026-11-06", client=client)
    assert [s["tool"] for s in out["steps"]] == ["list_invoices", "propose_payment"]
    rec = out["proposal"]["recommended"]
    assert [r["invoice"]["id"] for r in rec] == [inv["id"]] and out["proposal"]["total_recommended_cents"] == 300000
    assert out["proposal"]["not_recommended"] == []
    assert payouts == [] and pipeline.get_invoice(conn, inv["id"])["status"] == "HELD"
    assert events(conn, "agent_proposal") == 1


def test_proposal_is_built_from_tool_results_not_model_text(held, monkeypatch):
    conn, _, inv = held
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    out = agent.run_agent(conn, "x", client=scripted([say(f"Please pay invoice {inv['id']} right now!")]))
    assert out["proposal"]["recommended"] == []


def test_blocked_invoice_is_never_recommended(env):
    conn, payouts = env
    blocked = run(conn, "inv08_pinnacle_email_changed.pdf")
    res = agent.dispatch(conn, "propose_payment", {"invoice_id": blocked["id"]})
    assert res["recommended"] is False and "BLOCKED" in res["reasons"][0] and payouts == []
    assert events(conn, "agent_proposal") == 1


def test_limits_and_missing_ai_review_are_not_recommended(held, monkeypatch):
    conn, _, inv = held
    monkeypatch.setattr(config, "PER_PAYMENT_LIMIT_CENTS", 100000)
    res = pipeline.propose_payment(conn, inv["id"])
    assert res["recommended"] is False and "per-payment limit" in res["reasons"][0]


def test_missing_ai_review_is_not_recommended(env):
    conn, _ = env
    conn.execute("DELETE FROM gemini_cache WHERE kind='review'")
    conn.commit()
    inv = run(conn, "inv12_cedarpine_partial.pdf")
    assert pipeline.propose_payment(conn, inv["id"])["recommended"] is False


def test_unknown_tool_bad_args_and_step_limit(held, monkeypatch):
    conn, _, _ = held
    assert "error" in agent.dispatch(conn, "delete_everything", {"invoice_id": 1})
    assert "error" in agent.dispatch(conn, "propose_payment", {"invoice_id": "abc"})
    assert "error" in agent.dispatch(conn, "propose_payment", {"invoice_id": 999})
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


# ---- only a human click moves money ---------------------------------------------------------------------------

def test_confirm_pays_through_the_approve_path_once(held):
    conn, payouts, inv = held
    res = pipeline.confirm_proposal(conn, inv["id"])
    assert res["paid"] is True and len(payouts) == 1 and payouts[0]["cents"] == 300000
    assert pipeline.get_invoice(conn, inv["id"])["status"] == "PAID"
    assert events(conn, "owner_approved") == 1 and events(conn, "paid") == 1
    assert pipeline.confirm_proposal(conn, inv["id"])["paid"] is False  # cannot pay twice
    assert len(payouts) == 1


def test_confirm_rechecks_at_click_time_payee_email_changed(held):
    conn, payouts, inv = held
    assert pipeline.propose_payment(conn, inv["id"])["recommended"] is True
    conn.execute("UPDATE suppliers SET payment_email='other@example.net' WHERE name='Cedar & Pine Furniture'")
    conn.commit()  # the saved details change after the proposal was made
    res = pipeline.confirm_proposal(conn, inv["id"])
    assert res["paid"] is False and "payee email" in res["message"].lower() and payouts == []
    assert events(conn, "agent_confirm_refused") == 1


def test_confirm_rechecks_limits_at_click_time(held, monkeypatch):
    conn, payouts, inv = held
    assert pipeline.propose_payment(conn, inv["id"])["recommended"] is True
    monkeypatch.setattr(config, "DAILY_LIMIT_CENTS", 100000)
    assert pipeline.confirm_proposal(conn, inv["id"])["paid"] is False and payouts == []


def test_confirm_never_pays_a_blocked_invoice(env):
    conn, payouts = env
    blocked = run(conn, "inv11_shadowline_unapproved.pdf")
    assert pipeline.confirm_proposal(conn, blocked["id"])["paid"] is False
    assert pipeline.confirm_proposal(conn, 9999)["paid"] is False and payouts == []


def test_confirm_api_endpoint(held):
    conn, payouts, inv = held
    with TestClient(app) as c:
        r = c.post("/api/agent/confirm", json={"invoice_ids": [inv["id"], inv["id"], 9999]})
        assert r.status_code == 200
        results = r.json()["results"]
        assert [x["paid"] for x in results] == [True, False]  # duplicate ids collapse; unknown id refused
        assert c.post("/api/agent/confirm", json={"invoice_ids": []}).status_code == 400
    assert len(payouts) == 1


def test_agent_route_reports_gemini_down(env, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with TestClient(app) as c:
        assert c.post("/api/agent", json={"message": "hi"}).status_code == 503
        assert c.post("/api/agent", json={"message": "  "}).status_code == 400
