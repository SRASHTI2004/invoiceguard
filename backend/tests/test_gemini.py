import json

import httpx
import pytest

from app import ai_review, config, db, extract, gemini


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "m1")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def gemini_client(payload, calls, status=200):
    def handler(req: httpx.Request):
        calls.append(req)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(status, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return httpx.Client(base_url="https://g.test", transport=httpx.MockTransport(handler))


RAW = {"supplier_name": " Acme ", "invoice_number": "A-1", "invoice_date": "2026-11-01", "due_date": None,
       "po_number": "", "payee_email": "x@y.com", "total": 1240.5,
       "line_items": [{"description": "Paper", "quantity": 10, "unit_price": 124.05},
                      {"description": "Half", "quantity": 1.5, "unit_price": 10}]}


def test_normalize_converts_to_cents_and_cleans():
    n = extract.normalize(RAW)
    assert n["supplier_name"] == "Acme" and n["po_number"] is None
    assert n["total_cents"] == 124050
    assert n["line_items"][0] == {"description": "Paper", "qty": 10, "unit_cents": 12405}
    assert n["line_items"][1]["qty"] is None  # fractional quantity -> unreadable -> will HOLD in checks


def test_normalize_handles_missing_total():
    assert extract.normalize({})["total_cents"] is None


def test_extract_is_cached_by_file_hash(conn):
    calls = []
    client = gemini_client(RAW, calls)
    a = extract.extract_invoice(b"%PDF same", conn, client)
    b = extract.extract_invoice(b"%PDF same", conn, client)
    assert a == b and len(calls) == 1
    extract.extract_invoice(b"%PDF other", conn, client)
    assert len(calls) == 2


def test_api_key_in_header_not_url_or_body(conn):
    calls = []
    extract.extract_invoice(b"%PDF", conn, gemini_client(RAW, calls))
    req = calls[0]
    assert req.headers["x-goog-api-key"] == "fake-key"
    assert "fake-key" not in str(req.url) and b"fake-key" not in req.content


def test_http_error_and_bad_json_raise_without_key(conn):
    with pytest.raises(gemini.GeminiError) as e:
        extract.extract_invoice(b"1", conn, gemini_client("x", [], status=429))
    assert "429" in str(e.value) and "fake-key" not in str(e.value)
    with pytest.raises(gemini.GeminiError):
        extract.extract_invoice(b"2", conn, gemini_client("not json", []))


def test_failed_call_is_not_cached(conn):
    with pytest.raises(gemini.GeminiError):
        extract.extract_invoice(b"3", conn, gemini_client("x", [], status=500))
    assert conn.execute("SELECT COUNT(*) FROM gemini_cache").fetchone()[0] == 0


def test_review_validates_and_applies_floors():
    ok = ai_review.validate({"risk_score": 0.05, "signals": [], "reasons": []})
    assert ok["risk_score"] == 0.05
    inj = ai_review.validate({"risk_score": 0.2, "signals": ["prompt_injection"], "reasons": ["hidden text"]})
    assert inj["risk_score"] == 0.95
    assert ai_review.validate({"risk_score": 0.1, "signals": ["urgency_pressure"], "reasons": []})["risk_score"] == 0.4


@pytest.mark.parametrize("bad", [{}, {"risk_score": 2, "signals": [], "reasons": []},
                                 {"risk_score": "high", "signals": [], "reasons": []},
                                 {"risk_score": 0.1, "signals": "x", "reasons": []}])
def test_review_rejects_malformed(bad):
    with pytest.raises(gemini.GeminiError):
        ai_review.validate(bad)


def test_review_cached(conn):
    calls = []
    client = gemini_client({"risk_score": 0.0, "signals": [], "reasons": []}, calls)
    ai_review.review_invoice(b"pdf", conn, client)
    ai_review.review_invoice(b"pdf", conn, client)
    assert len(calls) == 1


def test_falls_back_to_next_model_when_quota_exhausted(conn, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "m1, m2")
    paths = []

    def handler(req):
        paths.append(req.url.path)
        if "m1" in req.url.path:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(RAW)}]}}]})

    client = httpx.Client(base_url="https://g.test", transport=httpx.MockTransport(handler))
    assert extract.extract_invoice(b"fb", conn, client)["invoice_number"] == "A-1"
    assert paths == ["/v1beta/models/m1:generateContent", "/v1beta/models/m2:generateContent"]


def test_bad_request_does_not_try_other_models(conn, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "m1,m2")
    paths = []

    def handler(req):
        paths.append(req.url.path)
        return httpx.Response(400, json={})

    client = httpx.Client(base_url="https://g.test", transport=httpx.MockTransport(handler))
    with pytest.raises(gemini.GeminiError):
        extract.extract_invoice(b"bad", conn, client)
    assert len(paths) == 1
