# InvoiceGuard – Plan

## Context
Hackathon project (deadline Nov 12): an AI agent that pays supplier invoices via PayPal sandbox, with a fraud firewall before any money moves. Repo is empty (README, LICENSE, .gitignore, .env only). Keep code simple, build in small working steps, minimise Claude usage.

## PayPal API choice: Payouts (`POST /v1/payments/payouts`)
- Built for a business paying many recipients by email; one call, sandbox host `https://api-m.sandbox.paypal.com`, OAuth2 client-credentials token from `/v1/oauth2/token`.
- `sender_batch_id` is idempotent for 30 days -> use the invoice ID, so a retry can never double-pay (a second safety net on top of the duplicate check).
- Status via `GET /v1/payments/payouts/{batch_id}`.
- Alternatives rejected: Orders/Invoicing APIs are for *receiving* money. Agent Toolkit: not confirmed to cover Payouts; I use plain REST via `httpx` (fewer dependencies). Will re-check if you want it featured for the hackathon theme.
- Sandbox needs a funded sandbox Business account and sandbox Personal accounts as supplier emails (you'll need to create these at developer.paypal.com; I'll list the steps in README).

## Architecture
React+TS (AG Grid) -> FastAPI -> SQLite.
Pipeline per invoice: `extract (Gemini vision, cached by file hash)` -> `validate extraction` -> `deterministic checks` -> `AI review (Gemini, cached)` -> `decide` -> `pay (Payouts)` or hold/block -> `audit log`.
- Extraction validation (code, in `extract.py`): required fields present (supplier, invoice number, date, total, payee email) and line items sum to the total (to the cent). Any failure -> HOLD with a clear reason.
- Gemini cache: results stored in a `gemini_cache` table keyed by SHA-256 of the PDF bytes (+ call type: extract / review), so the same PDF is never sent to Gemini twice (protects free-tier quota).
- Decision rule (pure function, unit-tested): any hard-rule failure -> BLOCK; extraction validation failure -> HOLD; AI risk >= high threshold -> BLOCK; medium or over per-payment limit/daily limit -> HOLD; else AUTO-PAY.
- Held invoices: owner clicks Approve (pays) or Reject (blocks) on the approval page.
- Prompt-injection defence: invoice text is passed to Gemini as quoted data; the model's output is schema-validated JSON only; LLM output can never trigger payment, only the code decision function can. Payment email always comes from the saved supplier record, never from the invoice.
- Payouts: after payment, store the PayPal `payout_batch_id` and status (PENDING / SUCCESS / FAILED) on the invoice; the dashboard shows the status with a Refresh button that calls `GET /v1/payments/payouts/{batch_id}`.
- "Money saved" = sum of amounts of blocked invoices.
- Secrets: loaded from `.env` with python-dotenv; `.env` verified in `.gitignore`; never logged or printed.

## Folder structure
```
invoiceguard/
  backend/
    app/ main.py  config.py  db.py  models.py
         extract.py  checks.py  ai_review.py  decide.py
         paypal.py   audit.py  routes.py
    tests/ test_checks.py  test_decide.py
    seed/ seed.py  make_pdfs.py  invoices/ (generated PDFs)
    eval/ run_eval.py
    requirements.txt
  frontend/ (Vite + React + TS + ag-grid-react)
    src/ pages/ Invoices, Approvals, Suppliers, Summary ; api.ts
  render.yaml  .env.example  README.md
```

## Build order (each step runs/tests before the next)
1. Scaffold: backend skeleton, SQLite schema (suppliers, purchase_orders, invoices incl. payout_batch_id/payout_status, audit_log, gemini_cache), `.env.example`, confirm `.env` is ignored.
2. Seed data: 18 suppliers (with sandbox payee emails), matching POs, ~10 PDFs via reportlab: 5 normal, 1 duplicate, 1 inflated amount, 1 changed payee email, 1 hidden prompt-injection text (white/tiny text), 1 urgent "new bank details" social-engineering. Ground-truth labels in a JSON file for the eval.
3. Deterministic checks + decision logic + pytest (no network, no LLM).
4. PayPal sandbox payout client; test with one manual payout.
5. Gemini extraction + AI review (JSON schema output, validation, safe fallback = HOLD on any LLM failure).
6. API routes: upload, list, approve/reject, suppliers, summary, audit.
7. Frontend: AG Grid invoices table, approvals page, suppliers page, summary cards.
8. Eval script: runs all sample PDFs, prints fraud caught (x/y) and valid invoices wrongly held (x/y).
9. Render deploy (`render.yaml`: FastAPI serves built frontend; Render free plan has no persistent disk, so SQLite lives on ephemeral storage and the DB is re-created and re-seeded on startup if empty; no disk in render.yaml), README with setup, sandbox account steps, demo script.
10. (Stretch, only after steps 1-9 work) "AP agent": owner types a request such as "pay all approved invoices due this week"; a Gemini agent uses tools (list invoices, run checks, request payment). The payment tool calls the same pipeline/firewall (`decide.py`), so the agent can never bypass it.

## Verification
- `pytest backend/tests` passes (duplicates, PO mismatch, unapproved supplier, email mismatch, limits, decision matrix).
- `python backend/eval/run_eval.py` prints catch rate and false-hold count.
- Manual: upload each sample PDF in the UI; check the sandbox payout appears in the sandbox business account; check the audit log has one row per decision.

## Open decisions (defaults I'll use unless you say otherwise)
- Gemini model: `gemini-2.5-flash` (confirmed by you).
- Currency USD; per-payment limit $5,000; daily limit $10,000 (configurable).
- No login/auth (demo only; noted in README).
