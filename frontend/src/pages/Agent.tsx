import { useState } from "react";
import { AgentStep, api } from "../api";

const EXAMPLES = [
  "Pay all held invoices due this week",
  "What is waiting for approval and why?",
  "Pay every invoice from Atlas Industrial Parts",
];

export default function AgentPage({ reload }: { reload: () => Promise<void> }) {
  const [text, setText] = useState(EXAMPLES[0]);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    setReply(null);
    setSteps([]);
    try {
      const res = await api.agent(text);
      setReply(res.reply);
      setSteps(res.steps);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
    await reload();
  };

  return (
    <section>
      <p className="muted">
        Ask in plain English. The agent uses tools (list invoices, run checks, request payment), but every payment still goes
        through the firewall: it can never pay a blocked invoice or override a limit.
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
              <div className="muted">{JSON.stringify(s.result).slice(0, 220)}</div>
            </li>
          ))}
        </ol>
      )}
      {reply && <div className="agent-reply">{reply}</div>}
    </section>
  );
}
