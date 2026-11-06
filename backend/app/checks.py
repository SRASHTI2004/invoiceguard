"""Deterministic fraud checks: plain code, no LLM, no network.

An invoice is a dict with: supplier_name, invoice_number, invoice_date, po_number, total_cents,
payee_email, line_items = [{"description", "qty", "unit_cents"}].
Each check returns a list of Findings. BLOCK = looks like fraud/error, HOLD = needs a human.
"""
import sqlite3
from dataclasses import dataclass

from . import config

BLOCK = "BLOCK"
HOLD = "HOLD"

REQUIRED_FIELDS = ["supplier_name", "invoice_number", "invoice_date", "total_cents", "payee_email"]


@dataclass
class Finding:
    code: str
    severity: str  # BLOCK or HOLD
    message: str


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def check_extraction(inv: dict) -> list[Finding]:
    """Required fields present and line items add up to the total (to the cent)."""
    missing = [f for f in REQUIRED_FIELDS if inv.get(f) in (None, "", 0) and f != "total_cents" or
               (f == "total_cents" and not isinstance(inv.get(f), int))]
    if missing:
        return [Finding("missing_fields", HOLD, f"Extraction is missing required fields: {', '.join(missing)}")]
    items = inv.get("line_items") or []
    if not items:
        return [Finding("no_line_items", HOLD, "Invoice has no line items")]
    try:
        items_total = sum(int(i["qty"]) * int(i["unit_cents"]) for i in items)
    except (KeyError, TypeError, ValueError):
        return [Finding("bad_line_items", HOLD, "Line items could not be read (qty/unit price missing)")]
    if items_total != inv["total_cents"]:
        return [Finding("total_mismatch", HOLD,
                        f"Line items add up to {money(items_total)} but the invoice total is {money(inv['total_cents'])}")]
    return []


def get_supplier(conn: sqlite3.Connection, name: str):
    return conn.execute("SELECT * FROM suppliers WHERE lower(name) = lower(?)", (name.strip(),)).fetchone()


def check_supplier(supplier, name: str) -> list[Finding]:
    if supplier is None:
        return [Finding("unknown_supplier", BLOCK, f"'{name}' is not a known supplier")]
    if not supplier["approved"]:
        return [Finding("unapproved_supplier", BLOCK, f"Supplier '{supplier['name']}' is not on the approved list")]
    return []


def check_duplicate(conn, inv: dict, supplier_id: int, exclude_id: int | None = None) -> list[Finding]:
    """Same supplier + invoice number, or same supplier + amount + date, already recorded."""
    excl = exclude_id if exclude_id is not None else -1
    row = conn.execute(
        "SELECT id FROM invoices WHERE supplier_id = ? AND id != ? AND lower(invoice_number) = lower(?)",
        (supplier_id, excl, inv["invoice_number"])).fetchone()
    if row:
        return [Finding("duplicate_number", BLOCK,
                        f"Duplicate: invoice {inv['invoice_number']} from this supplier was already received (#{row['id']})")]
    row = conn.execute(
        "SELECT id FROM invoices WHERE supplier_id = ? AND id != ? AND total_cents = ? AND invoice_date = ?",
        (supplier_id, excl, inv["total_cents"], inv["invoice_date"])).fetchone()
    if row:
        return [Finding("duplicate_amount_date", BLOCK,
                        f"Duplicate: same supplier, amount {money(inv['total_cents'])} and date as invoice #{row['id']}")]
    return []


def check_po(conn, inv: dict, supplier_id: int) -> list[Finding]:
    po_number = inv.get("po_number")
    if not po_number:
        return [Finding("no_po", HOLD, "Invoice does not reference a purchase order")]
    po = conn.execute("SELECT * FROM purchase_orders WHERE lower(po_number) = lower(?)", (po_number.strip(),)).fetchone()
    if po is None:
        return [Finding("po_not_found", BLOCK, f"Purchase order {po_number} does not exist")]
    if po["supplier_id"] != supplier_id:
        return [Finding("po_wrong_supplier", BLOCK, f"Purchase order {po_number} belongs to a different supplier")]
    if inv["total_cents"] > po["amount_cents"]:
        return [Finding("over_po", BLOCK,
                        f"Invoice total {money(inv['total_cents'])} is more than the PO amount {money(po['amount_cents'])}")]
    if inv["total_cents"] < po["amount_cents"]:
        return [Finding("under_po", HOLD,
                        f"Invoice total {money(inv['total_cents'])} is less than the PO amount {money(po['amount_cents'])}")]
    return []


def check_payee_email(supplier, inv: dict) -> list[Finding]:
    if inv["payee_email"].strip().lower() != supplier["payment_email"].strip().lower():
        return [Finding("payee_email_mismatch", BLOCK,
                        f"Payee email {inv['payee_email']} does not match the saved payment email for {supplier['name']}")]
    return []


def paid_today_cents(conn, today: str | None = None) -> int:
    day = today or "now"
    row = conn.execute(
        "SELECT COALESCE(SUM(total_cents), 0) FROM invoices WHERE status = 'PAID' AND date(paid_at) = date(?)",
        (day,)).fetchone()
    return row[0]


def check_limits(conn, inv: dict, today: str | None = None) -> list[Finding]:
    out = []
    total = inv["total_cents"]
    if total > config.PER_PAYMENT_LIMIT_CENTS:
        out.append(Finding("over_payment_limit", HOLD,
                           f"{money(total)} is over the per-payment limit of {money(config.PER_PAYMENT_LIMIT_CENTS)}"))
    already = paid_today_cents(conn, today)
    if already + total > config.DAILY_LIMIT_CENTS:
        out.append(Finding("over_daily_limit", HOLD,
                           f"Paying this would bring today's total to {money(already + total)}, "
                           f"over the daily limit of {money(config.DAILY_LIMIT_CENTS)}"))
    return out


def run_checks(conn, inv: dict, exclude_id: int | None = None, today: str | None = None) -> list[Finding]:
    """Run every deterministic check. Returns all findings (empty list = all passed)."""
    findings = check_extraction(inv)
    if any(f.code in ("missing_fields", "no_line_items", "bad_line_items") for f in findings):
        return findings  # cannot run the other checks without the basic fields
    supplier = get_supplier(conn, inv["supplier_name"])
    sup_findings = check_supplier(supplier, inv["supplier_name"])
    findings += sup_findings
    if supplier is None:
        return findings
    findings += check_duplicate(conn, inv, supplier["id"], exclude_id)
    findings += check_po(conn, inv, supplier["id"])
    if supplier["approved"]:
        findings += check_payee_email(supplier, inv)
    findings += check_limits(conn, inv, today)
    return findings
