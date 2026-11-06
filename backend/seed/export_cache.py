"""Save Gemini results for the sample PDFs to seed/gemini_cache.json (committed), so the demo, eval and a fresh
Render deploy work with zero Gemini calls for these files.  Run from backend/:  python -m seed.export_cache
Only extraction/review output is stored (no secrets)."""
import json
from pathlib import Path

from app import db, gemini

HERE = Path(__file__).parent


def main():
    conn = db.connect()
    out = []
    for pdf in sorted((HERE / "invoices").glob("*.pdf")):
        h = gemini.pdf_hash(pdf.read_bytes())
        for kind in ("extract", "review"):
            row = conn.execute("SELECT result_json FROM gemini_cache WHERE file_hash=? AND kind=?", (h, kind)).fetchone()
            if row is None:
                raise SystemExit(f"missing {kind} result for {pdf.name}: run the pipeline on it first")
            out.append({"file": pdf.name, "file_hash": h, "kind": kind, "result": json.loads(row["result_json"])})
    (HERE / "gemini_cache.json").write_text(json.dumps(out, indent=1))
    print(f"exported {len(out)} cached results")


if __name__ == "__main__":
    main()
