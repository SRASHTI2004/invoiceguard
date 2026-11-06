"""Minimal Gemini REST client (PDF in, JSON out) plus a result cache keyed by file hash.

The API key is sent in a header and is never logged or put in error messages.
"""
import base64
import hashlib
import json
import time

import httpx

from . import config

BASE_URL = "https://generativelanguage.googleapis.com"
RETRY_WAIT = 4  # seconds


class GeminiError(Exception):
    pass


def pdf_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def post_generate(body: dict, client: httpx.Client | None = None) -> httpx.Response:
    """POST to generateContent, trying each model in GEMINI_MODEL in turn. Raises GeminiError if all fail."""
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is not set in .env")
    c = client or httpx.Client(base_url=BASE_URL, timeout=90)
    headers = {"x-goog-api-key": config.GEMINI_API_KEY}
    r = None
    for model in [m.strip() for m in config.GEMINI_MODEL.split(",") if m.strip()]:
        url = f"/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            r = c.post(url, json=body, headers=headers)
            if r.status_code == 503 and attempt == 0:  # overloaded: one short wait, then retry
                time.sleep(RETRY_WAIT)
                continue
            break
        if r.status_code == 200 or r.status_code not in (404, 429, 503):
            break  # success, or an error another model will not fix
        # 404 (model retired), 429 (quota) or 503 (overloaded): try the next model in the list
    if r is None or r.status_code != 200:
        raise GeminiError(f"Gemini request failed (HTTP {r.status_code if r is not None else 'n/a'})")
    return r


def generate_json(prompt: str, pdf_bytes: bytes, schema: dict, thinking: bool = False,
                  client: httpx.Client | None = None) -> dict:
    """Send the prompt + PDF to Gemini and return the parsed JSON object."""
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is not set in .env")
    gen_cfg = {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0}
    if not thinking:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode()}},
        ]}],
        "generationConfig": gen_cfg,
    }
    r = post_generate(body, client)
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
    except (KeyError, IndexError, ValueError, TypeError):
        raise GeminiError("Gemini returned an unreadable response")
    if not isinstance(data, dict):
        raise GeminiError("Gemini returned JSON that is not an object")
    return data


def cached_call(conn, file_hash: str, kind: str, fn):
    """Return the cached result for (file_hash, kind), else call fn() once and cache it."""
    row = conn.execute("SELECT result_json FROM gemini_cache WHERE file_hash = ? AND kind = ?",
                       (file_hash, kind)).fetchone()
    if row:
        return json.loads(row["result_json"])
    result = fn()
    conn.execute("INSERT OR REPLACE INTO gemini_cache (file_hash, kind, result_json) VALUES (?, ?, ?)",
                 (file_hash, kind, json.dumps(result)))
    conn.commit()
    return result
