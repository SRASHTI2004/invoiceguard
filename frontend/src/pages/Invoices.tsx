import { ColDef, ICellRendererParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useMemo, useRef, useState } from "react";
import { api, Invoice, money } from "../api";

const badge = (value: string | null) => (value ? <span className={`badge ${value}`}>{value.replace("_", " ")}</span> : null);

export default function InvoicesPage({ invoices, reload }: { invoices: Invoice[]; reload: () => Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<string>) => {
    setBusy(label);
    setMessage(null);
    try {
      setMessage(await fn());
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
    setBusy(null);
    await reload();
  };

  const columns = useMemo<ColDef<Invoice>[]>(
    () => [
      { field: "id", headerName: "#", width: 60 },
      { field: "supplier_name", headerName: "Supplier", flex: 1.4, minWidth: 160, tooltipField: "supplier_name", valueFormatter: (p) => p.value ?? "(unreadable)" },
      { field: "invoice_number", headerName: "Invoice no.", flex: 1, minWidth: 120 },
      { field: "total_cents", headerName: "Amount", width: 110, valueFormatter: (p) => money(p.value), type: "rightAligned" },
      { field: "status", headerName: "Status", width: 110, cellRenderer: (p: ICellRendererParams) => badge(p.value) },
      { field: "decision", headerName: "Decision", width: 115, cellRenderer: (p: ICellRendererParams) => badge(p.value) },
      { field: "reason", headerName: "Reason (hover for full text)", flex: 2.5, minWidth: 220, cellClass: "reason-cell", tooltipField: "reason" },
      {
        headerName: "Payout",
        width: 215,
        sortable: false,
        cellRenderer: (p: ICellRendererParams<Invoice>) =>
          p.data?.payout_batch_id ? (
            <span className="payout">
              {badge(p.data.payout_status)}
              <button
                className="mini"
                title="Refresh from PayPal"
                onClick={() => run("refresh", async () => { await api.refreshPayout(p.data!.id); return "Payout status refreshed from PayPal."; })}
              >
                ↻ Refresh
              </button>
            </span>
          ) : null,
      },
      { field: "risk_score", headerName: "AI risk", width: 90, valueFormatter: (p) => (p.value == null ? "" : p.value.toFixed(2)) },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return (
    <section>
      <div className="toolbar">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f)
              run("upload", async () => {
                const inv = await api.upload(f);
                return `Invoice ${inv.invoice_number ?? f.name}: ${inv.status}. ${inv.reason ?? ""}`;
              });
            e.target.value = "";
          }}
        />
        <button className="primary" disabled={!!busy} onClick={() => fileRef.current?.click()}>
          {busy === "upload" ? "Checking invoice…" : "Upload invoice (PDF)"}
        </button>
        <button
          disabled={!!busy}
          title="Clears all invoices and the audit log, then runs the 12 sample invoices"
          onClick={() => {
            if (!window.confirm("This clears all invoices and the audit log, then loads the 12 sample invoices. Continue?")) return;
            run("samples", async () => {
              const r = await api.runSamples();
              const c = r.summary.counts;
              if (r.throttled) return r.note ?? "Demo data was loaded recently; showing the latest run.";
              return `Loaded ${r.processed} sample invoices: ${c.PAID ?? 0} paid, ${c.BLOCKED ?? 0} blocked, ${c.HELD ?? 0} on hold.`;
            });
          }}
        >
          {busy === "samples" ? "Processing…" : "Reset & load sample invoices"}
        </button>
        {message && <span className="message">{message}</span>}
      </div>
      <div className="grid-wrap">
        <AgGridReact<Invoice>
          rowData={invoices}
          columnDefs={columns}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          getRowId={(p) => String(p.data.id)}
          rowHeight={52}
          domLayout="autoHeight"
          tooltipShowDelay={300}
          overlayNoRowsTemplate="No invoices yet. Upload a PDF or load the sample invoices."
        />
      </div>
    </section>
  );
}
