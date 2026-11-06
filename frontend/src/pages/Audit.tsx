import { ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useState } from "react";
import { api, AuditRow, Invoice } from "../api";

const columns: ColDef<AuditRow>[] = [
  { field: "created_at", headerName: "Time (UTC)", width: 170 },
  { field: "invoice_id", headerName: "Invoice #", width: 110 },
  { field: "event", headerName: "Event", width: 160 },
  { field: "decision", headerName: "Decision", width: 130 },
  { field: "reason", headerName: "Reason (hover for full text)", flex: 1, minWidth: 300, cellClass: "reason-cell", tooltipField: "reason" },
];

// `invoices` changes whenever something happens, so the log reloads with it.
export default function AuditPage({ invoices }: { invoices: Invoice[] }) {
  const [rows, setRows] = useState<AuditRow[]>([]);
  useEffect(() => {
    api.audit().then(setRows).catch(() => setRows([]));
  }, [invoices]);
  return (
    <section>
      <p className="muted">Every decision and action, newest first.</p>
      <div className="grid-wrap">
        <AgGridReact<AuditRow>
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          rowHeight={52}
          tooltipShowDelay={300}
          domLayout="autoHeight"
        />
      </div>
    </section>
  );
}
