"""PayPal Payouts (sandbox) client. Never log credentials or the Authorization header."""
import time

import httpx

from . import config


class PayPalError(Exception):
    pass


_token = {"value": None, "expires": 0.0}

# Item-level transaction_status -> our status
_FAILED = {"FAILED", "BLOCKED", "RETURNED", "REFUNDED", "REVERSED", "DENIED"}
_PENDING = {"PENDING", "UNCLAIMED", "ONHOLD"}


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(base_url=config.PAYPAL_BASE_URL, timeout=30)


def get_token(client: httpx.Client | None = None) -> str:
    if _token["value"] and time.time() < _token["expires"] - 30:
        return _token["value"]
    if not (config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET):
        raise PayPalError("PayPal credentials are not set in .env")
    c = _client(client)
    r = c.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
               auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET))
    if r.status_code != 200:
        raise PayPalError(f"PayPal auth failed (HTTP {r.status_code})")
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 300))
    return _token["value"]


def _headers(client):
    return {"Authorization": f"Bearer {get_token(client)}", "Content-Type": "application/json"}


def build_payout_body(batch_ref: str, email: str, amount_cents: int, note: str) -> dict:
    return {
        "sender_batch_header": {
            "sender_batch_id": batch_ref,  # PayPal treats a repeated id as the same request (idempotent)
            "email_subject": "Payment from InvoiceGuard",
            "email_message": note,
        },
        "items": [{
            "recipient_type": "EMAIL",
            "receiver": email,
            "amount": {"value": f"{amount_cents / 100:.2f}", "currency": config.CURRENCY},
            "note": note,
            "sender_item_id": batch_ref,
        }],
    }


def send_payout(batch_ref: str, email: str, amount_cents: int, note: str,
                client: httpx.Client | None = None) -> dict:
    """Send one payout. Returns {"batch_id": str, "status": PENDING/SUCCESS/FAILED}."""
    c = _client(client)
    r = c.post("/v1/payments/payouts", json=build_payout_body(batch_ref, email, amount_cents, note),
               headers=_headers(client))
    if r.status_code not in (200, 201):
        try:
            err = r.json()
            detail = f"{err.get('name', '')}: {err.get('message', '')}"
        except ValueError:
            detail = ""
        raise PayPalError(f"Payout rejected by PayPal (HTTP {r.status_code}) {detail}".strip())
    header = r.json()["batch_header"]
    return {"batch_id": header["payout_batch_id"], "status": map_status(header.get("batch_status"), [])}


def map_status(batch_status: str | None, items: list[dict]) -> str:
    """Map PayPal batch/item statuses to PENDING / SUCCESS / FAILED."""
    batch_status = (batch_status or "").upper()
    if batch_status in ("DENIED", "CANCELED"):
        return "FAILED"
    item_statuses = {(i.get("transaction_status") or "").upper() for i in items}
    if item_statuses & _FAILED:
        return "FAILED"
    if batch_status == "SUCCESS" and not (item_statuses & _PENDING):
        return "SUCCESS"
    return "PENDING"


def get_payout_status(batch_id: str, client: httpx.Client | None = None) -> str:
    c = _client(client)
    r = c.get(f"/v1/payments/payouts/{batch_id}", headers=_headers(client))
    if r.status_code != 200:
        raise PayPalError(f"Could not get payout status (HTTP {r.status_code})")
    data = r.json()
    return map_status(data["batch_header"].get("batch_status"), data.get("items", []))
