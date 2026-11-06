"""Settings loaded from the environment / .env file. Never print or log secret values."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Comma-separated list: tried in order. The free tier allows only ~20 requests/day per model,
# so later models act as fallbacks when one is out of quota or overloaded.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3.8-flash")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")

DB_PATH = os.getenv("DB_PATH", str(ROOT / "backend" / "invoiceguard.db"))

# Limits are in cents to avoid float rounding problems.
CURRENCY = "USD"
PER_PAYMENT_LIMIT_CENTS = int(os.getenv("PER_PAYMENT_LIMIT_CENTS", "500000"))  # $5,000
DAILY_LIMIT_CENTS = int(os.getenv("DAILY_LIMIT_CENTS", "1000000"))  # $10,000


def secrets_status() -> dict[str, bool]:
    """Which secrets are set (booleans only, never the values)."""
    return {
        "GEMINI_API_KEY": bool(GEMINI_API_KEY),
        "PAYPAL_CLIENT_ID": bool(PAYPAL_CLIENT_ID),
        "PAYPAL_CLIENT_SECRET": bool(PAYPAL_CLIENT_SECRET),
    }
