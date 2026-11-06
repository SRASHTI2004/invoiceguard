"""SQLite setup. Money is stored as integer cents."""
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    approved      INTEGER NOT NULL DEFAULT 1,
    payment_email TEXT NOT NULL,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number    TEXT NOT NULL UNIQUE,
    supplier_id  INTEGER NOT NULL REFERENCES suppliers(id),
    amount_cents INTEGER NOT NULL,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    filename          TEXT,
    file_hash         TEXT,
    supplier_id       INTEGER REFERENCES suppliers(id),
    supplier_name     TEXT,
    invoice_number    TEXT,
    invoice_date      TEXT,
    due_date          TEXT,
    po_number        TEXT,
    total_cents       INTEGER,
    payee_email       TEXT,
    line_items        TEXT,              -- JSON
    status            TEXT NOT NULL DEFAULT 'RECEIVED',  -- RECEIVED/PAID/HELD/BLOCKED/REJECTED
    decision          TEXT,              -- AUTO_PAY / HOLD / BLOCK
    reason            TEXT,
    risk_score        REAL,
    payout_batch_id   TEXT,
    payout_status     TEXT,              -- PENDING / SUCCESS / FAILED
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER REFERENCES invoices(id),
    event       TEXT NOT NULL,
    decision    TEXT,
    reason      TEXT,
    details     TEXT,                    -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gemini_cache (
    file_hash   TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- 'extract' or 'review'
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (file_hash, kind)
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if missing. Safe to run on every startup."""
    with connect() as conn:
        conn.executescript(SCHEMA)


def is_empty() -> bool:
    """True when there are no suppliers (used on startup to decide whether to re-seed)."""
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0
