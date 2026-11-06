import httpx
import pytest

from app import config, paypal


@pytest.fixture(autouse=True)
def fake_creds(monkeypatch):
    monkeypatch.setattr(config, "PAYPAL_CLIENT_ID", "id")
    monkeypatch.setattr(config, "PAYPAL_CLIENT_SECRET", "secret")
    paypal._token.update(value=None, expires=0.0)


def mock_client(handler):
    return httpx.Client(base_url="https://paypal.test", transport=httpx.MockTransport(handler))


def test_send_payout_builds_request_and_maps_response():
    seen = {}

    def handler(req: httpx.Request):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        seen["body"] = req.read()
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(201, json={"batch_header": {"payout_batch_id": "B123", "batch_status": "PENDING"}})

    res = paypal.send_payout("ig-7-abcd", "a@b.com", 124050, "Invoice X", client=mock_client(handler))
    assert res == {"batch_id": "B123", "status": "PENDING"}
    assert seen["auth"] == "Bearer tok"
    body = httpx.Response(200, content=seen["body"]).json()
    assert body["sender_batch_header"]["sender_batch_id"] == "ig-7-abcd"
    item = body["items"][0]
    assert item["receiver"] == "a@b.com" and item["amount"] == {"value": "1240.50", "currency": "USD"}


def test_rejected_payout_raises_without_leaking_secret():
    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(400, json={"name": "INSUFFICIENT_FUNDS", "message": "Sender has insufficient funds"})

    with pytest.raises(paypal.PayPalError) as e:
        paypal.send_payout("r", "a@b.com", 100, "n", client=mock_client(handler))
    assert "INSUFFICIENT_FUNDS" in str(e.value) and "secret" not in str(e.value)
    assert e.value.code == "INSUFFICIENT_FUNDS"


def test_auth_failure_raises():
    with pytest.raises(paypal.PayPalError):
        paypal.get_token(mock_client(lambda req: httpx.Response(401)))


def test_status_mapping():
    m = paypal.map_status
    assert m("SUCCESS", [{"transaction_status": "SUCCESS"}]) == "SUCCESS"
    assert m("PROCESSING", []) == "PENDING"
    assert m("PENDING", []) == "PENDING"
    assert m("SUCCESS", [{"transaction_status": "UNCLAIMED"}]) == "PENDING"
    assert m("SUCCESS", [{"transaction_status": "FAILED"}]) == "FAILED"
    assert m("DENIED", []) == "FAILED"


def test_get_payout_status():
    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"batch_header": {"batch_status": "SUCCESS"},
                                         "items": [{"transaction_status": "SUCCESS"}]})

    assert paypal.get_payout_status("B1", client=mock_client(handler)) == "SUCCESS"


def test_simulate_mode_makes_no_paypal_call(monkeypatch):
    monkeypatch.setattr(config, "PAYPAL_MODE", "simulate")

    def handler(req):
        raise AssertionError("no HTTP call expected in simulate mode")

    res = paypal.send_payout("ref1", "a@b.com", 100, "n", client=mock_client(handler))
    assert res["batch_id"] == "SIMULATED-ref1" and res["status"] == "PENDING"
    assert paypal.get_payout_status(res["batch_id"], client=mock_client(handler)) == "SUCCESS"
