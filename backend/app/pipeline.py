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


def approve(conn, inv_id: int, note: str | None = None) -> dict:
    inv = get_invoice(conn, inv_id)
    if inv is None:
        raise ActionError("Invoice not found")
    if inv["status"] != "HELD":
        raise ActionError("Only invoices on hold can be approved")
    blockers = hard_blockers(conn, inv)  # re-run the checks at the moment of approval
    if blockers:
        audit.log(conn, inv_id, "approval_refused", "BLOCK", "; ".join(blockers))
        raise ActionError("Cannot approve, the checks now fail: " + "; ".join(blockers))
    audit.log(conn, inv_id, "owner_approved", "APPROVED", note or "Approved by the owner")
    return pay_invoice(conn, inv_id, actor="owner")


def _check_input(inv: dict) -> dict:
    return {k: inv[k] for k in ("supplier_name", "invoice_number", "invoice_date", "po_number", "total_cents",
                                "payee_email", "line_items")}


def hard_blockers(conn, inv: dict) -> list[str]:
    """Fresh deterministic re-check: messages of any BLOCK-level finding (duplicate, PO, payee email, supplier)."""
    if not inv["supplier_name"] or inv["total_cents"] is None:
        return []  # unreadable invoice: pay_invoice refuses it
    fresh = checks.run_checks(conn, _check_input(inv), exclude_id=inv["id"])
    return [f.message for f in fresh if f.severity == checks.BLOCK]


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


# ---- AP agent support -------------------------------------------------------------------------------------------
# The agent can only RECOMMEND. Money moves only when the owner confirms, through approve() above.
# The agent may recommend only these SOFT holds; everything else needs the owner's own judgement on Approvals.
AGENT_ALLOWED_FINDINGS = {"under_po", "no_po"}


def proposal_refusals(conn, inv: dict) -> list[str]:
    """Why this invoice must NOT be recommended / confirmed through the agent (empty = fine). Fresh re-check."""
    if inv["status"] != "HELD":
        return [f"Invoice is {inv['status']}; only invoices on hold can be proposed"]
    if not inv["supplier_name"] or inv["total_cents"] is None:
        return ["Invoice could not be read properly; the owner must review it"]
    fresh = checks.run_checks(conn, _check_input(inv), exclude_id=inv["id"])
    out = [f.message for f in fresh if f.code not in AGENT_ALLOWED_FINDINGS]
    if inv["risk_score"] is None or inv["risk_score"] >= decide.AI_HOLD_RISK:
        out.append("AI review risk is missing or not low; the owner must review this one")
    return out


def propose_payment(conn, inv_id: int) -> dict:
    """Read-only for money: re-runs the checks and returns a recommendation. Never pays."""
    inv = get_invoice(conn, inv_id)
    if inv is None:
        return {"invoice_id": inv_id, "recommended": False, "reasons": ["Invoice not found"]}
    refusals = proposal_refusals(conn, inv)
    if refusals:
        audit.log(conn, inv_id, "agent_proposal", "NOT_RECOMMENDED", "; ".join(refusals))
        return {"invoice_id": inv_id, "recommended": False, "reasons": refusals}
    reasons = [f"On hold only because: {inv['reason']}",
               "Fresh checks found no fraud signals or limit problems and the AI review risk is low"]
    audit.log(conn, inv_id, "agent_proposal", "RECOMMENDED", "; ".join(reasons))
    return {"invoice_id": inv_id, "recommended": True, "reasons": reasons}


def confirm_proposal(conn, inv_id: int) -> dict:
    """The owner clicked "Confirm and pay". Re-check everything now, then pay via the normal approve path."""
    inv = get_invoice(conn, inv_id)
    if inv is None:
        return {"invoice_id": inv_id, "paid": False, "message": "Invoice not found"}
    refusals = proposal_refusals(conn, inv)
    if refusals:
        audit.log(conn, inv_id, "agent_confirm_refused", None, "; ".join(refusals))
        return {"invoice_id": inv_id, "paid": False, "message": "Not paid: " + "; ".join(refusals)}
    try:
        paid = approve(conn, inv_id, note="Approved by the owner by confirming an AP agent proposal")
    except ActionError as e:
        return {"invoice_id": inv_id, "paid": False, "message": str(e)}
    return {"invoice_id": inv_id, "paid": True, "message": f"Paid {checks.money(paid['total_cents'])}",
            "payout_status": paid["payout_status"]}
