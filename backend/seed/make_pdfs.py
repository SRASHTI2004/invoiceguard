"""Generate the sample invoice PDFs (5 different layouts) and labels.json.  Run from backend/:
    python -m seed.make_pdfs
"""
import json
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from seed.data import BUYER, INVOICES, SUPPLIERS

OUT = Path(__file__).parent / "invoices"
W, H = A4
SUP = {s[0]: s for s in SUPPLIERS}


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur]


def pay_email(inv) -> str:
    return inv.get("payee_email") or SUP[inv["supplier"]][2]


def table(c, inv, x, y, widths, font="Helvetica", size=10, zebra=None, line=True):
    """Draw the line-item table + total; returns y after the table."""
    regular = "Times-Roman" if font == "Times" else font
    cols = [x, x + widths[0], x + widths[0] + widths[1], x + sum(widths[:3])]
    c.setFont(font + "-Bold" if font != "Courier" else "Courier-Bold", size)
    for cx, label in zip(cols, ["Description", "Qty", "Unit", "Amount"]):
        c.drawString(cx, y, label)
    y -= 6
    if line:
        c.line(x, y, x + sum(widths), y)
    y -= 16
    for i, (desc, qty, unit) in enumerate(inv["items"]):
        if zebra and i % 2 == 0:
            c.setFillColorRGB(*zebra)
            c.rect(x - 4, y - 4, sum(widths) + 8, 17, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
        c.setFont(regular, size)
        c.drawString(cols[0], y, desc)
        c.drawString(cols[1], y, str(qty))
        c.drawString(cols[2], y, money(unit))
        c.drawString(cols[3], y, money(qty * unit))
        y -= 18
    if line:
        c.line(x, y + 8, x + sum(widths), y + 8)
    y -= 8
    c.setFont(font + "-Bold" if font != "Courier" else "Courier-Bold", size + 2)
    c.drawString(cols[2], y, "TOTAL")
    c.drawString(cols[3], y, money(inv["total"]))
    return y - 30


def banner(c, inv, x, y, width_chars=80, color=(0.8, 0, 0)):
    if not inv.get("banner"):
        return y
    c.setFillColorRGB(*color)
    c.setFont("Helvetica-Bold", 11)
    for ln in wrap(inv["banner"], width_chars):
        c.drawString(x, y, ln)
        y -= 14
    c.setFillColorRGB(0, 0, 0)
    return y - 6


def hidden_text(c, inv):
    """White 1pt text at the bottom of the page: invisible to a human, readable by a text extractor."""
    if inv.get("hidden"):
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica", 1)
        c.drawString(40, 30, inv["hidden"])
        c.setFillColorRGB(0, 0, 0)


def style_classic(c, inv):
    sup = SUP[inv["supplier"]]
    c.setFont("Helvetica-Bold", 20)
    c.drawString(40, H - 60, sup[0])
    c.setFont("Helvetica", 10)
    c.drawString(40, H - 76, sup[3])
    c.setFont("Helvetica-Bold", 26)
    c.setFillColorRGB(*inv["accent"])
    c.drawRightString(W - 40, H - 60, "INVOICE")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    for i, t in enumerate([f"Invoice No: {inv['number']}", f"Date: {inv['date']}", f"Due: {inv['due']}", f"PO Ref: {inv['po']}"]):
        c.drawRightString(W - 40, H - 80 - i * 14, t)
    c.drawString(40, H - 130, "Bill To:")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, H - 145, BUYER["name"])
    c.setFont("Helvetica", 10)
    c.drawString(40, H - 159, BUYER["address"])
    y = banner(c, inv, 40, H - 190)
    y = table(c, inv, 40, min(y, H - 210), [270, 50, 90, 90], zebra=None)
    c.setFont("Helvetica", 10)
    c.drawString(40, y, "Payment terms: net 14 days. Pay by PayPal to:")
    c.drawString(40, y - 14, pay_email(inv))
    hidden_text(c, inv)


def style_modern(c, inv):
    sup = SUP[inv["supplier"]]
    c.setFillColorRGB(*inv["accent"])
    c.rect(0, H - 110, W, 110, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(40, H - 60, sup[0])
    c.setFont("Helvetica", 10)
    c.drawString(40, H - 80, sup[3])
    c.setFillColorRGB(0.94, 0.94, 0.94)
    c.rect(40, H - 190, W - 80, 55, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10)
    for i, (k, v) in enumerate([("INVOICE #", inv["number"]), ("ISSUED", inv["date"]), ("DUE", inv["due"]), ("PURCHASE ORDER", inv["po"])]):
        c.drawString(55 + i * 125, H - 155, k)
        c.setFont("Helvetica", 11)
        c.drawString(55 + i * 125, H - 172, v)
        c.setFont("Helvetica-Bold", 10)
    c.drawString(40, H - 215, f"Billed to {BUYER['name']}, {BUYER['address']}")
    y = banner(c, inv, 40, H - 245)
    y = table(c, inv, 40, min(y, H - 260), [260, 50, 90, 100], zebra=(0.95, 0.97, 1), line=False)
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Please remit payment via PayPal: {pay_email(inv)}")
    hidden_text(c, inv)


def style_minimal(c, inv):
    sup = SUP[inv["supplier"]]
    y = H - 60
    c.setFont("Courier-Bold", 13)
    c.drawString(40, y, sup[0].upper())
    c.setFont("Courier", 10)
    for t in [sup[3], "-" * 60, f"INVOICE {inv['number']}   DATE {inv['date']}   DUE {inv['due']}",
              f"ORDER REF {inv['po']}", f"CUSTOMER: {BUYER['name']}", "-" * 60]:
        y -= 15
        c.drawString(40, y, t)
    y = banner(c, inv, 40, y - 20, 70, (0, 0, 0))
    y = table(c, inv, 40, y - 10, [270, 50, 90, 90], font="Courier", size=9, line=False)
    c.setFont("Courier", 10)
    c.drawString(40, y, f"PAYPAL: {pay_email(inv)}")
    hidden_text(c, inv)


def style_sidebar(c, inv):
    sup = SUP[inv["supplier"]]
    c.setFillColorRGB(*inv["accent"])
    c.rect(0, 0, 170, H, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    for i, ln in enumerate(wrap(sup[0], 16)):
        c.drawString(20, H - 60 - i * 18, ln)
    c.setFont("Helvetica", 9)
    for i, ln in enumerate(wrap(sup[3], 26)):
        c.drawString(20, H - 130 - i * 12, ln)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20, 140, "PAYMENT DETAILS")
    c.setFont("Helvetica", 8)
    c.drawString(20, 126, "PayPal:")
    for i, ln in enumerate(wrap(pay_email(inv), 28)):
        c.drawString(20, 114 - i * 11, ln)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(200, H - 60, "Tax Invoice")
    c.setFont("Helvetica", 10)
    for i, t in enumerate([f"Number: {inv['number']}", f"Date: {inv['date']}   Due: {inv['due']}",
                           f"Your PO: {inv['po']}", f"To: {BUYER['name']}"]):
        c.drawString(200, H - 90 - i * 14, t)
    y = banner(c, inv, 200, H - 170, 55)
    y = table(c, inv, 200, min(y, H - 185), [170, 35, 70, 75], size=9)
    hidden_text(c, inv)


def style_statement(c, inv):
    sup = SUP[inv["supplier"]]
    c.setFont("Times-Bold", 22)
    c.drawCentredString(W / 2, H - 55, sup[0])
    c.setFont("Times-Italic", 11)
    c.drawCentredString(W / 2, H - 72, sup[3])
    c.rect(40, H - 150, W - 80, 55)
    c.setFont("Times-Bold", 12)
    c.drawString(50, H - 112, f"STATEMENT / INVOICE  {inv['number']}")
    c.setFont("Times-Roman", 11)
    c.drawString(50, H - 128, f"Issued {inv['date']}  |  Payment due {inv['due']}  |  Order {inv['po']}")
    c.drawString(50, H - 143, f"Customer: {BUYER['name']}")
    y = banner(c, inv, 40, H - 180, 78, inv["accent"])
    y = table(c, inv, 40, min(y, H - 195), [270, 50, 90, 90], font="Times", size=11)
    c.setFont("Times-Roman", 11)
    c.drawString(40, y, f"Remittance (PayPal): {pay_email(inv)}")
    hidden_text(c, inv)


STYLES = dict(classic=style_classic, modern=style_modern, minimal=style_minimal,
              sidebar=style_sidebar, statement=style_statement)


def main(only=None):
    OUT.mkdir(exist_ok=True)
    labels = []
    for inv in INVOICES:
        labels.append({k: inv[k] for k in ("file", "supplier", "number", "is_fraud", "expected", "category")})
        if only and inv["file"] not in only:
            continue
        assert sum(q * u for _, q, u in inv["items"]) == inv["total"], inv["file"]
        c = canvas.Canvas(str(OUT / inv["file"]), pagesize=A4, invariant=1)  # invariant: same bytes every run
        c.setTitle(f"Invoice {inv['number']}")
        STYLES[inv["style"]](c, inv)
        c.save()
    (Path(__file__).parent / "labels.json").write_text(json.dumps(labels, indent=2))
    print(f"wrote {len(INVOICES)} PDFs to {OUT}")


if __name__ == "__main__":
    main(only=sys.argv[1:] or None)  # optional: file names to regenerate
