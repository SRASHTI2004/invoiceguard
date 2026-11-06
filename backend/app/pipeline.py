"""The firewall pipeline: extract -> checks -> AI review -> decide -> pay/hold/block -> audit.

Only decide.py's output (or an explicit owner approval of a HELD invoice) can lead to a payment.
"""
import json
import secrets

from . import ai_review, audit, checks, decide, extract, gemini, paypal


class ActionError(Exception):
    """A user-facing problem (wrong invoice state, cannot pay, ...)."""


def get_invoice(conn, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    inv["line_items"] = json.loads(inv["line_items"]) if inv["line_items"] else []
    return inv


def _save_extraction(conn, inv_id: int, inv: dict) -> None:
    supplier = checks.get_supplier(conn, inv["supplier_name"]) if inv.get("supplier_name") else None
    conn.execute(
        "UPDATE invoices SET supplier_id=?, supplier_name=?, invoice_number=?, invoice_date=?, due_date=?, "
        "po_number=?, total_cents=?, payee_email=?, line_items=? WHERE id=?",
        (supplier["id"] if supplier else None, inv["supplier_name"], inv["invoice_number"], inv["invoice_date"],
         inv["due_date"], inv["po_number"], inv["total_cents"], inv["payee_email"],
         json.dumps(inv["line_items"]), inv_id))
    conn.commit()


def process_invoice(conn, pdf_bytes: bytes, filename: str, gemini_client=None) -> dict:
    """Run one uploaded invoice through the whole firewall and return the saved invoice."""
    cur = conn.execute("INSERT INTO invoices (filename, file_hash, status) VALUES (?, ?, 'RECEIVED')",
                       (filename, gemini.pdf_hash(pdf_bytes)))
    conn.commit()
    inv_id = cur.lastrowid
    audit.log(conn, inv_id, "received", details={"filename": filename})

    inv = None
    try:
        inv = extract.extract_invoice(pdf_bytes, conn, gemini_client)
        _save_extraction(conn, inv_id, inv)
        findings = checks.run_checks(conn, inv, exclude_id=inv_id)
    except gemini.GeminiError as e:
        findings = [checks.Finding("extraction_failed", checks.HOLD,
                                   f"Could not read the invoice automatically ({e}); please review it manually")]

    ai, ai_error = None, None
    if inv and not any(f.severity == checks.BLOCK for f in findings):  # already blocked: save the Gemini call
        try:
            ai = ai_review.review_invoice(pdf_bytes, conn, gemini_client)
        except gemini.GeminiError as e:
            ai_error = str(e)

    d = decide.decide(findings, ai)
    status = {"AUTO_PAY": "RECEIVED", "HOLD": "HELD", "BLOCK": "BLOCKED"}[d.decision]
    conn.execute("UPDATE invoices SET decision=?, reason=?, risk_score=?, status=? WHERE id=?",
                 (d.decision, d.reason, d.risk_score, status, inv_id))
    conn.commit()
    audit.log(conn, inv_id, "decision", d.decision, d.reason, {
        "findings": [f.__dict__ for f in findings], "ai_review": ai, "ai_error": ai_error})

    if d.decision == decide.AUTO_PAY:
        try:
            pay_invoice(conn, inv_id, actor="auto")
        except ActionError:
            pass  # the invoice is back on HOLD with the reason (already saved and audited)
    return get_invoice(conn, inv_id)


def pay_invoice(conn, inv_id: int, actor: str) -> dict:
    """Pay an invoice via PayPal. Payee is ALWAYS the supplier's saved email, never the email on the invoice."""
    # Atomic claim so a double click / retry can never pay twice.
    claimed = conn.execute("UPDATE invoices SET status='PAYING' WHERE id=? AND status IN ('HELD','RECEIVED')",
                           (inv_id,)).rowcount
    conn.commit()
    if not claimed:
        raise ActionError("This invoice is not waiting for payment")
    inv = get_invoice(conn, inv_id)
    supplier = conn.execute("SELECT * FROM suppliers WHERE id=?", (inv["supplier_id"],)).fetchone() \
        if inv["supplier_id"] else None
    if supplier is None or not supplier["approved"] or not inv["total_cents"]:
        _back_to_held(conn, inv_id, "Cannot pay: supplier or amount is missing or not approved")
        raise ActionError("Cannot pay this invoice: supplier or amount is missing or not approved")

    ref = inv["payout_ref"] or f"ig-{inv_id}-{secrets.token_hex(4)}"  # idempotency key for PayPal
    conn.execute("UPDATE invoices SET payout_ref=? WHERE id=?", (ref, inv_id))
    conn.commit()
    try:
        res = paypal.send_payout(ref, supplier["payment_email"], inv["total_cents"],
                                 f"Invoice {inv['invoice_number']} from {supplier['name']}")
    except paypal.PayPalError as e:
        _back_to_held(conn, inv_id, f"Payout failed: {e}")
        audit.log(conn, inv_id, "payout_failed", "HOLD", str(e), {"actor": actor})
        raise ActionError(f"Payout failed: {e}")
    conn.execute("UPDATE invoices SET status='PAID', payout_batch_id=?, payout_status=?, paid_at=datetime('now') "
                 "WHERE id=?", (res["batch_id"], res["status"], inv_id))
    conn.commit()
    audit.log(conn, inv_id, "paid", "AUTO_PAY" if actor == "auto" else "APPROVED",
              f"Paid {checks.money(inv['total_cents'])} to {supplier['name']}",
              {"actor": actor, "payout_batch_id": res["batch_id"], "payout_status": res["status"]})
    return get_invoice(conn, inv_id)


def _back_to_held(conn, inv_id: int, reason: str) -> None:
    conn.execute("UPDATE invoices SET status='HELD', decision='HOLD', reason=? WHERE id=?", (reason, inv_id))
    conn.commit()


def approve(conn, inv_id: int) -> dict:
    inv = get_invoice(conn, inv_id)
    if inv is None:
        raise ActionError("Invoice not found")
    if inv["status"] != "HELD":
        raise ActionError("Only invoices on hold can be approved")
    audit.log(conn, inv_id, "owner_approved", "APPROVED", "Approved by the owner")
    return pay_invoice(conn, inv_id, actor="owner")


def reject(conn, inv_id: int) -> dict:
    inv = get_invoice(conn, inv_id)
    if inv is None:
        raise ActionError("Invoice not found")
    changed = conn.execute("UPDATE invoices SET status='REJECTED' WHERE id=? AND status='HELD'", (inv_id,)).rowcount
    conn.commit()
    if not changed:
        raise ActionError("Only invoices on hold can be rejected")
    audit.log(conn, inv_id, "owner_rejected", "REJECTED", "Rejected by the owner")
    return get_invoice(conn, inv_id)


def refresh_payout(conn, inv_id: int) -> dict:
    inv = get_invoice(conn, inv_id)
    if inv is None or not inv["payout_batch_id"]:
        raise ActionError("This invoice has no payout to refresh")
    try:
        status = paypal.get_payout_status(inv["payout_batch_id"])
    except paypal.PayPalError as e:
        raise ActionError(str(e))
    conn.execute("UPDATE invoices SET payout_status=? WHERE id=?", (status, inv_id))
    conn.commit()
    if status != inv["payout_status"]:
        audit.log(conn, inv_id, "payout_status", None, f"Payout status is now {status}",
                  {"payout_batch_id": inv["payout_batch_id"]})
    return get_invoice(conn, inv_id)


def summary(conn) -> dict:
    def total(where):
        return conn.execute(f"SELECT COALESCE(SUM(total_cents),0) FROM invoices WHERE {where}").fetchone()[0]
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM invoices GROUP BY status")}
    return {
        "total_paid_cents": total("status='PAID'"),
        "total_blocked_cents": total("status='BLOCKED'"),
        "total_held_cents": total("status='HELD'"),
        "money_saved_cents": total("status IN ('BLOCKED','REJECTED')"),
        "counts": counts,
        "invoice_count": sum(counts.values()),
    }
