from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from . import agent, db, gemini, pipeline

router = APIRouter(prefix="/api")
MAX_PDF_BYTES = 10 * 1024 * 1024
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "seed" / "invoices"


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def _act(fn, *args):
    try:
        return fn(*args)
    except pipeline.ActionError as e:
        raise HTTPException(400, str(e))


@router.get("/invoices")
def list_invoices(conn=Depends(get_conn)):
    return _rows(conn, "SELECT id, filename, supplier_name, invoice_number, invoice_date, due_date, po_number, "
                       "total_cents, payee_email, status, decision, reason, risk_score, payout_batch_id, "
                       "payout_status, paid_at, created_at FROM invoices ORDER BY id DESC")


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, conn=Depends(get_conn)):
    inv = pipeline.get_invoice(conn, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.post("/invoices/upload")
async def upload_invoice(file: UploadFile = File(...), conn=Depends(get_conn)):
    data = await file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "File is too large (10 MB max)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF file")
    return pipeline.process_invoice(conn, data, Path(file.filename or "invoice.pdf").name)


@router.post("/invoices/{invoice_id}/approve")
def approve(invoice_id: int, conn=Depends(get_conn)):
    return _act(pipeline.approve, conn, invoice_id)


@router.post("/invoices/{invoice_id}/reject")
def reject(invoice_id: int, conn=Depends(get_conn)):
    return _act(pipeline.reject, conn, invoice_id)


@router.post("/invoices/{invoice_id}/refresh-payout")
def refresh_payout(invoice_id: int, conn=Depends(get_conn)):
    return _act(pipeline.refresh_payout, conn, invoice_id)


@router.get("/suppliers")
def suppliers(conn=Depends(get_conn)):
    return _rows(conn, "SELECT id, name, approved, payment_email, notes AS address FROM suppliers ORDER BY name")


@router.get("/summary")
def summary(conn=Depends(get_conn)):
    return pipeline.summary(conn)


@router.get("/audit")
def audit_log(invoice_id: int | None = None, conn=Depends(get_conn)):
    if invoice_id is not None:
        return _rows(conn, "SELECT * FROM audit_log WHERE invoice_id = ? ORDER BY id DESC", (invoice_id,))
    return _rows(conn, "SELECT * FROM audit_log ORDER BY id DESC LIMIT 500")


@router.post("/demo/run-samples")
def run_samples(conn=Depends(get_conn)):
    """Demo helper: push the sample PDFs through the firewall (skips ones already uploaded)."""
    done = {r["file_hash"] for r in conn.execute("SELECT file_hash FROM invoices")}
    processed = []
    for pdf in sorted(SAMPLES_DIR.glob("*.pdf")):
        data = pdf.read_bytes()
        if gemini.pdf_hash(data) in done:
            continue
        processed.append(pipeline.process_invoice(conn, data, pdf.name)["id"])
    return {"processed": len(processed), "invoice_ids": processed}


class AgentRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    invoice_ids: list[int]


@router.post("/agent/confirm")
def confirm_agent_proposal(req: ConfirmRequest, conn=Depends(get_conn)):
    """The owner clicked "Confirm and pay". Each invoice is fully re-checked now, then paid via the approve path."""
    if not req.invoice_ids or len(req.invoice_ids) > 20:
        raise HTTPException(400, "Confirm between 1 and 20 invoices")
    return {"results": [pipeline.confirm_proposal(conn, i) for i in dict.fromkeys(req.invoice_ids)]}


@router.post("/agent")
def run_agent(req: AgentRequest, conn=Depends(get_conn)):
    """AP agent: e.g. "pay all held invoices due this week". It returns a proposal; it never pays."""
    if not req.message.strip():
        raise HTTPException(400, "Please type a request")
    try:
        return agent.run_agent(conn, req.message)
    except gemini.GeminiError as e:
        raise HTTPException(503, f"The AI agent is unavailable right now ({e}). Use the Approvals page instead.")
