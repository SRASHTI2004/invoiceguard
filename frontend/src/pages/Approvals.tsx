import { useState } from "react";
import { api, Invoice, money } from "../api";

export default function ApprovalsPage({ held, reload }: { held: Invoice[]; reload: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const act = async (id: number, fn: (id: number) => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await fn(id);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusyId(null);
    await reload();
  };

  if (held.length === 0) return <p className="empty">Nothing is waiting for approval. 🎉</p>;
  return (
    <section>
      {error && <div className="banner error">{error}</div>}
      <div className="approval-list">
        {held.map((inv) => (
          <article key={inv.id} className="approval">
            <div className="approval-head">
              <div>
                <h3>{inv.supplier_name ?? "Unreadable invoice"}</h3>
                <div className="muted">
                  Invoice {inv.invoice_number ?? "?"} · PO {inv.po_number ?? "none"} · due {inv.due_date ?? "?"}
                </div>
              </div>
              <div className="amount">{money(inv.total_cents)}</div>
            </div>
            <p className="why">
              <strong>Why it is on hold:</strong> {inv.reason}
            </p>
            <div className="muted">Payee on invoice: {inv.payee_email ?? "?"} · file {inv.filename}</div>
            <div className="actions">
              <button
                className="primary"
                disabled={busyId === inv.id}
                onClick={() => window.confirm(`Pay ${money(inv.total_cents)} to ${inv.supplier_name}?`) && act(inv.id, api.approve)}
              >
                Approve &amp; pay
              </button>
              <button className="danger" disabled={busyId === inv.id} onClick={() => act(inv.id, api.reject)}>
                Reject
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
