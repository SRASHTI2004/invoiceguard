"""Evaluation: run every sample invoice through InvoiceGuard and report how many fraud cases were caught
and how many valid invoices were wrongly held/blocked.

Run from backend/:
    python -m eval.run_eval                 # fresh temp DB, cached Gemini results, simulated PayPal (no money, no quota)
    python -m eval.run_eval --live-gemini   # ignore the cache and call Gemini for real (uses free-tier quota)
    python -m eval.run_eval --pay           # send real PayPal SANDBOX payouts for approved invoices
"""
import argparse
import json
import tempfile
from pathlib import Path

from app import config, db, paypal, pipeline
from seed.seed import seed_db

SEED = Path(__file__).resolve().parents[1] / "seed"


def evaluate(conn, labels: list[dict]) -> dict:
    """Process the labelled PDFs in order and compare each decision with the ground truth."""
    rows = []
    for lab in labels:
        inv = pipeline.process_invoice(conn, (SEED / "invoices" / lab["file"]).read_bytes(), lab["file"])
        rows.append({**lab, "decision": inv["decision"], "status": inv["status"], "reason": inv["reason"],
                     "amount_cents": inv["total_cents"] or 0})
    fraud = [r for r in rows if r["is_fraud"]]
    valid = [r for r in rows if not r["is_fraud"]]
    caught = [r for r in fraud if r["decision"] != "AUTO_PAY"]
    wrongly_held = [r for r in valid if r["decision"] != "AUTO_PAY"]
    return {
        "rows": rows,
        "fraud_total": len(fraud), "fraud_caught": len(caught),
        "valid_total": len(valid), "valid_wrongly_held": len(wrongly_held),
        "fraud_cents_stopped": sum(r["amount_cents"] for r in caught),
        "fraud_cents_total": sum(r["amount_cents"] for r in fraud),
        "valid_cents_paid": sum(r["amount_cents"] for r in valid if r["decision"] == "AUTO_PAY"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-gemini", action="store_true", help="ignore the cache and call Gemini")
    ap.add_argument("--pay", action="store_true", help="send real PayPal sandbox payouts")
    args = ap.parse_args()

    labels = json.loads((SEED / "labels.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        config.DB_PATH = str(Path(tmp) / "eval.db")  # never touches your real database
        seed_db(use_cached_gemini=not args.live_gemini)
        if not args.pay:
            paypal.send_payout = lambda ref, email, cents, note, client=None: {"batch_id": "SIMULATED", "status": "PENDING"}
        conn = db.connect()
        result = evaluate(conn, labels)
        conn.close()

    money = lambda c: f"${c / 100:,.2f}"
    print(f"\n{'file':36} {'expected':14} {'decision':9} reason")
    for r in result["rows"]:
        ok = (r["decision"] == "AUTO_PAY") == (not r["is_fraud"])
        print(f"{'OK ' if ok else 'BAD'} {r['file']:32} {r['expected']:14} {r['decision']:9} {(r['reason'] or '')[:90]}")
    print("\n=== InvoiceGuard evaluation ===")
    print(f"Fraud cases caught:             {result['fraud_caught']} / {result['fraud_total']}")
    print(f"Valid invoices wrongly held:    {result['valid_wrongly_held']} / {result['valid_total']}")
    print(f"Fraudulent money stopped:       {money(result['fraud_cents_stopped'])} of {money(result['fraud_cents_total'])}")
    print(f"Valid invoices paid:            {money(result['valid_cents_paid'])}")
    print(f"(PayPal: {'real sandbox payouts' if args.pay else 'simulated'}; Gemini: {'live calls' if args.live_gemini else 'cached results'})")


if __name__ == "__main__":
    main()
