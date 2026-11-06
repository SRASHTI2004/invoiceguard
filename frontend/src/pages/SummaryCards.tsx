import { money, Summary } from "../api";

export default function SummaryCards({ summary }: { summary: Summary | null }) {
  const s = summary;
  const cards: [string, string, string, string][] = [
    ["Total paid", money(s?.total_paid_cents ?? 0), `${s?.counts.PAID ?? 0} invoices`, "ok"],
    ["Total blocked", money(s?.total_blocked_cents ?? 0), `${s?.counts.BLOCKED ?? 0} invoices`, "bad"],
    ["Waiting for approval", money(s?.total_held_cents ?? 0), `${s?.counts.HELD ?? 0} invoices`, "warn"],
    ["Money saved", money(s?.money_saved_cents ?? 0), "blocked + rejected", "saved"],
  ];
  return (
    <section className="cards">
      {cards.map(([title, value, sub, tone]) => (
        <div key={title} className={`card ${tone}`}>
          <div className="card-title">{title}</div>
          <div className="card-value">{value}</div>
          <div className="card-sub">{sub}</div>
        </div>
      ))}
    </section>
  );
}
