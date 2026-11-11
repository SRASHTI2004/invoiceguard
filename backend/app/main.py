from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from seed.seed import seed_db

from . import config, db, gemini, paypal, routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seed_db()  # re-seeds only if empty (Render free plan has no persistent disk)
    yield


app = FastAPI(title="InvoiceGuard", lifespan=lifespan)
app.include_router(routes.router)


def _diagnose() -> dict:
    """Live checks of the secrets. Reports only true/false and an error name, never a secret value."""
    out: dict = {}
    paypal._token["value"] = None  # force a real OAuth attempt
    try:
        paypal.get_token()
        out["paypal_oauth"] = {"ok": True}
    except paypal.PayPalError as e:
        out["paypal_oauth"] = {"ok": False, "error": e.code or str(e)}
    except Exception as e:
        out["paypal_oauth"] = {"ok": False, "error": type(e).__name__}
    try:
        gemini.post_generate({"contents": [{"parts": [{"text": "Reply with the word ok."}]}],
                              "generationConfig": {"maxOutputTokens": 5, "thinkingConfig": {"thinkingBudget": 0}}})
        out["gemini"] = {"ok": True}
    except gemini.GeminiError as e:
        out["gemini"] = {"ok": False, "error_type": "GeminiError", "error": str(e)}
    except Exception as e:
        out["gemini"] = {"ok": False, "error_type": type(e).__name__}
    return out


@app.get("/api/health")
def health(diagnose: bool = False):
    """Cheap by default (Render polls this). Add ?diagnose=1 to also test PayPal OAuth and a tiny Gemini call."""
    result = {"status": "ok", "db_empty": db.is_empty(), "secrets_set": config.secrets_status(),
              "secret_lengths_after_trim": config.secret_lengths(), "paypal_mode": config.PAYPAL_MODE}
    if diagnose:
        result["diagnostics"] = _diagnose()
    return result


# Serve the built React app (frontend/dist) from the same server. Must stay last so /api routes win.
_dist = config.ROOT / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
