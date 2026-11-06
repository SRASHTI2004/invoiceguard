"""Seed suppliers and purchase orders. Safe to call on every startup: does nothing if already seeded."""
import json
from pathlib import Path

from app import db
from seed.data import PURCHASE_ORDERS, SUPPLIERS


CACHE_FILE = Path(__file__).parent / "gemini_cache.json"


def load_gemini_cache() -> int:
    """Pre-fill the Gemini cache for the sample PDFs (INSERT OR IGNORE: never overwrites)."""
    if not CACHE_FILE.exists():
        return 0
    entries = json.loads(CACHE_FILE.read_text())
    with db.connect() as conn:
        for e in entries:
            conn.execute("INSERT OR IGNORE INTO gemini_cache (file_hash, kind, result_json) VALUES (?, ?, ?)",
                         (e["file_hash"], e["kind"], json.dumps(e["result"])))
    return len(entries)


def seed_db(use_cached_gemini: bool = True) -> bool:
    """Insert suppliers and POs if the DB is empty. Returns True if it seeded."""
    db.init_db()
    if use_cached_gemini:
        load_gemini_cache()
    if not db.is_empty():
        return False
    with db.connect() as conn:
        for name, approved, email, address in SUPPLIERS:
            conn.execute(
                "INSERT INTO suppliers (name, approved, payment_email, notes) VALUES (?, ?, ?, ?)",
                (name, approved, email, address),
            )
        for po_number, supplier, amount, desc in PURCHASE_ORDERS:
            conn.execute(
                "INSERT INTO purchase_orders (po_number, supplier_id, amount_cents, description) "
                "VALUES (?, (SELECT id FROM suppliers WHERE name = ?), ?, ?)",
                (po_number, supplier, amount, desc),
            )
    return True


if __name__ == "__main__":
    print("seeded" if seed_db() else "already seeded")
