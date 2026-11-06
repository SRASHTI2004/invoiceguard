from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from seed.seed import seed_db

from . import config, db, routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seed_db()  # re-seeds only if empty (Render free plan has no persistent disk)
    yield


app = FastAPI(title="InvoiceGuard", lifespan=lifespan)
app.include_router(routes.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "db_empty": db.is_empty(), "secrets_set": config.secrets_status()}


# Serve the built React app (frontend/dist) from the same server. Must stay last so /api routes win.
_dist = config.ROOT / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
