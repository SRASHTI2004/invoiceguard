"""Audit log: one row per decision / action. Never put secrets in `details`."""
import json


def log(conn, invoice_id: int | None, event: str, decision: str | None = None,
        reason: str | None = None, details: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (invoice_id, event, decision, reason, details) VALUES (?, ?, ?, ?, ?)",
        (invoice_id, event, decision, reason, json.dumps(details) if details else None))
    conn.commit()
