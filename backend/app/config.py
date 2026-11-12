"""Settings loaded from the environment / .env file. Never print or log secret values."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")



def _secret(name: str) -> str:
    """Read a secret and strip leading/trailing whitespace and quotes (pasted spaces or newlines break auth)."""
    return os.getenv(name, "").strip().strip("\"'").strip()


GEMINI_API_KEY = _secret("GEMINI_API_KEY")
# Comma-separated list: tried in order. The free tier allows only ~20 requests/day per model,
# so later models act as fallbacks when one is out of quota or overloaded.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3.8-flash")
PAYPAL_CLIENT_ID = _secret("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = _secret("PAYPAL_CLIENT_SECRET")
# "sandbox" = real PayPal sandbox payouts; "simulate" = no PayPal call (for repeated testing without spending sandbox funds)
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox").lower()
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").strip().rstrip("/")

# The public demo sends real sandbox payouts: the reset/load-samples endpoint may run at most once per cooldown.
DEMO_COOLDOWN_SECONDS = int(os.getenv("DEMO_COOLDOWN_SECONDS", "600"))  # 10 minutes

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


def secret_lengths() -> dict[str, int]:
    """Length of each secret after trimming (never the value), to spot pasted spaces or truncated keys."""
    return {"GEMINI_API_KEY": len(GEMINI_API_KEY), "PAYPAL_CLIENT_ID": len(PAYPAL_CLIENT_ID),
            "PAYPAL_CLIENT_SECRET": len(PAYPAL_CLIENT_SECRET)}
