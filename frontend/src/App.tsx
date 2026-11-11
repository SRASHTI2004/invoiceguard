import { useCallback, useEffect, useState } from "react";
import { api, Invoice, Summary } from "./api";
import AgentPage from "./pages/Agent";
import ApprovalsPage from "./pages/Approvals";
import AuditPage from "./pages/Audit";
import InvoicesPage from "./pages/Invoices";
import SuppliersPage from "./pages/Suppliers";
import SummaryCards from "./pages/SummaryCards";

type Tab = "invoices" | "approvals" | "agent" | "suppliers" | "audit";

const FLOW: [string, string, string][] = [
  ["📄", "Read invoice", "AI reads the PDF"],
  ["🔍", "Code checks", "duplicate, PO, payee, limits"],
  ["🤖", "AI review", "spots scams and injection"],
  ["⚖️", "Decision", "pay, hold or block"],
  ["💸", "PayPal payout", "sandbox, to the saved email"],
];

export default function App() {
  const [tab, setTab] = useState<Tab>("invoices");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [inv, sum] = await Promise.all([api.invoices(), api.summary()]);
      setInvoices(inv);
      setSummary(sum);
      setError(null);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const runDemo = async () => {
    setDemoBusy(true);
    setDemoError(null);
    try {
      await api.runSamples();
    } catch (e) {
      setDemoError((e as Error).message);
    }
    setDemoBusy(false);
    await reload();
  };

  const held = invoices.filter((i) => i.status === "HELD");
  const unfunded = held.filter((i) => i.reason?.includes("insufficient funds"));
  const tabs: [Tab, string][] = [
    ["invoices", "Invoices"],
    ["approvals", `Approvals${held.length ? ` (${held.length})` : ""}`],
    ["agent", "AP agent"],
    ["suppliers", "Suppliers"],
    ["audit", "Audit log"],
  ];

  return (
    <div className="app">
      <header>
        <h1>🛡️ InvoiceGuard</h1>
        <p className="tagline">AI payments agent with a fraud firewall. Nothing is paid until every check passes.</p>
      </header>
      <ol className="flow" aria-label="How InvoiceGuard works">
        {FLOW.map(([icon, title, sub]) => (
          <li key={title}>
            <span className="flow-icon" aria-hidden="true">{icon}</span>
            <strong>{title}</strong>
            <span className="flow-sub">{sub}</span>
          </li>
        ))}
      </ol>
      {loaded && invoices.length === 0 && (
        <div className="hero">
          <h2>See it work in about 30 seconds</h2>
          <p>
            Load 12 sample supplier invoices: 5 are valid and get paid through the PayPal sandbox, 6 are fraud attempts
            (duplicate, inflated amount, changed bank email, hidden prompt injection…) and get blocked, 1 waits for your approval.
          </p>
          <button className="primary big" disabled={demoBusy} onClick={runDemo}>
            {demoBusy ? "Checking 12 invoices…" : "▶ Run the demo"}
          </button>
          {demoError && <div className="banner error">Demo failed: {demoError}</div>}
        </div>
      )}
      {!loaded && !error && <p className="muted">Loading… the free server can take up to a minute to wake up.</p>}
      <SummaryCards summary={summary} />
      <nav>
        {tabs.map(([key, label]) => (
          <button key={key} className={tab === key ? "tab active" : "tab"} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      {error && <div className="banner error">Could not reach the server: {error}</div>}
      {unfunded.length > 0 && (
        <div className="banner funds" role="alert">
          <strong>💸 {unfunded.length} invoice{unfunded.length > 1 ? "s" : ""} could not be paid: the PayPal account has insufficient funds.</strong>
          <div>
            Nothing is lost and each invoice already passed every check. Add money to the sandbox Business account, then open{" "}
            <button className="link" onClick={() => setTab("approvals")}>Approvals</button> and click Approve to pay{" "}
            {unfunded.length > 1 ? "them" : "it"}.
          </div>
        </div>
      )}
      {tab === "invoices" && <InvoicesPage invoices={invoices} reload={reload} />}
      {tab === "approvals" && <ApprovalsPage held={held} reload={reload} />}
      {tab === "agent" && <AgentPage reload={reload} />}
      {tab === "suppliers" && <SuppliersPage />}
      {tab === "audit" && <AuditPage invoices={invoices} />}
    </div>
  );
}
