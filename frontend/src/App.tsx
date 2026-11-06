import { useCallback, useEffect, useState } from "react";
import { api, Invoice, Summary } from "./api";
import ApprovalsPage from "./pages/Approvals";
import AuditPage from "./pages/Audit";
import InvoicesPage from "./pages/Invoices";
import SuppliersPage from "./pages/Suppliers";
import SummaryCards from "./pages/SummaryCards";

type Tab = "invoices" | "approvals" | "suppliers" | "audit";

export default function App() {
  const [tab, setTab] = useState<Tab>("invoices");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [inv, sum] = await Promise.all([api.invoices(), api.summary()]);
      setInvoices(inv);
      setSummary(sum);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const held = invoices.filter((i) => i.status === "HELD");
  const tabs: [Tab, string][] = [
    ["invoices", "Invoices"],
    ["approvals", `Approvals${held.length ? ` (${held.length})` : ""}`],
    ["suppliers", "Suppliers"],
    ["audit", "Audit log"],
  ];

  return (
    <div className="app">
      <header>
        <h1>🛡️ InvoiceGuard</h1>
        <p className="tagline">AI payments agent with a fraud firewall. Nothing is paid until every check passes.</p>
      </header>
      <SummaryCards summary={summary} />
      <nav>
        {tabs.map(([key, label]) => (
          <button key={key} className={tab === key ? "tab active" : "tab"} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      {error && <div className="banner error">Could not reach the server: {error}</div>}
      {tab === "invoices" && <InvoicesPage invoices={invoices} reload={reload} />}
      {tab === "approvals" && <ApprovalsPage held={held} reload={reload} />}
      {tab === "suppliers" && <SuppliersPage />}
      {tab === "audit" && <AuditPage invoices={invoices} />}
    </div>
  );
}
