import { useState } from "react";
import Markdown from "../Markdown";
import { AgentStep, api, ConfirmResult, money, Proposal, ProposalItem } from "../api";

const EXAMPLES = [
  "Pay all held invoices due this week",
  "What is waiting for approval and why?",
  "Pay every invoice from Atlas Industrial Parts",
];

function Item({ item }: { item: ProposalItem }) {
  const inv = item.invoice;
  return (
    <li>
      <strong>{inv?.supplier ?? "Invoice"}</strong> · {inv?.invoice_number} · {inv?.amount} · due {inv?.due_date ?? "?"}
      <ul>
        {item.reasons.map((r, i) => (
          <li key={i} className="muted">{r}</li>
        ))}
      </ul>
    </li>
  );
}

export default function AgentPage({ reload }: { reload: () => Promise<void> }) {
  const [text, setText] = useState(EXAMPLES[0]);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [results, setResults] = useState<ConfirmResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    setReply(null);
    setSteps([]);
    setProposal(null);
    setResults(null);
    try {
      const res = await api.agent(text);
      setReply(res.reply);
      setSteps(res.steps);
      setProposal(res.proposal);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const confirm = async () => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.confirmProposal(proposal.recommended.map((i) => i.invoice!.id));
      setResults(res.results);
      setProposal(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
    await reload();
  };

  return (
    <section>
      <p className="muted">
        <strong>The AI agent can recommend, but only code checks plus your click can move money.</strong> It has no payment tool:
        it proposes, then you confirm. On confirm every check is re-run, and a blocked invoice can never be paid.
      </p>
      <textarea className="agent-input" rows={2} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="toolbar">
        <button className="primary" disabled={busy || !text.trim()} onClick={send}>
          {busy ? "Working…" : "Ask the agent"}
        </button>
        {EXAMPLES.map((ex) => (
          <button key={ex} className="mini" disabled={busy} onClick={() => setText(ex)}>
            {ex}
          </button>
        ))}
      </div>
      {error && <div className="banner error">{error}</div>}
      {steps.length > 0 && (
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={i}>
              <code>
                {s.tool}({Object.entries(s.args).map(([k, v]) => `${k}=${v}`).join(", ")})
              </code>
            </li>
          ))}
        </ol>
      )}
      {reply && (
        <div className="agent-reply">
          <Markdown text={reply} />
        </div>
      )}

      {proposal && (proposal.recommended.length > 0 || proposal.not_recommended.length > 0) && (
        <div className="proposal">
          <h3>Proposal (nothing has been paid yet)</h3>
          {proposal.recommended.length > 0 ? (
            <>
              <h4>Recommended to pay</h4>
              <ul>{proposal.recommended.map((it) => <Item key={it.invoice!.id} item={it} />)}</ul>
              <button className="primary" disabled={busy} onClick={confirm}>
                Confirm and pay {proposal.recommended.length} invoice{proposal.recommended.length > 1 ? "s" : ""} ({money(proposal.total_recommended_cents)})
              </button>
            </>
          ) : (
            <p className="muted">The agent does not recommend paying anything.</p>
          )}
          {proposal.not_recommended.length > 0 && (
            <>
              <h4>Not recommended</h4>
              <ul>{proposal.not_recommended.map((it, i) => <Item key={i} item={it} />)}</ul>
            </>
          )}
        </div>
      )}

      {results && (
        <div className="proposal">
          <h3>Result of your confirmation</h3>
          <ul>
            {results.map((r) => (
              <li key={r.invoice_id}>
                Invoice #{r.invoice_id}: {r.paid ? "✅ " : "⛔ "}
                {r.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
