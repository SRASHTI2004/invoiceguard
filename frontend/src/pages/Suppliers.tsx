import { ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useState } from "react";
import { api, Supplier } from "../api";

const columns: ColDef<Supplier>[] = [
  { field: "name", headerName: "Supplier", flex: 1, minWidth: 220 },
  { field: "approved", headerName: "Approved", width: 120, valueFormatter: (p) => (p.value ? "Yes" : "No (suspended)") },
  { field: "payment_email", headerName: "Saved payment email (PayPal)", flex: 1, minWidth: 280 },
  { field: "address", headerName: "Address", flex: 1, minWidth: 240 },
];

export default function SuppliersPage() {
  const [rows, setRows] = useState<Supplier[]>([]);
  useEffect(() => {
    api.suppliers().then(setRows).catch(() => setRows([]));
  }, []);
  return (
    <section>
      <p className="muted">Payments always go to the saved email below, never to an email written on an invoice.</p>
      <div className="grid-wrap">
        <AgGridReact<Supplier>
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          domLayout="autoHeight"
        />
      </div>
    </section>
  );
}
