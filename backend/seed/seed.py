"""Seed suppliers and purchase orders. Safe to call on every startup: does nothing if already seeded."""
from app import db
from seed.data import PURCHASE_ORDERS, SUPPLIERS


def seed_db() -> bool:
    """Insert suppliers and POs if the DB is empty. Returns True if it seeded."""
    db.init_db()
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
