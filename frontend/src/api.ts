export interface Invoice {
  id: number;
  filename: string | null;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  po_number: string | null;
  total_cents: number | null;
  payee_email: string | null;
  status: string;
  decision: string | null;
  reason: string | null;
  risk_score: number | null;
  payout_batch_id: string | null;
  payout_status: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface Supplier {
  id: number;
  name: string;
  approved: number;
  payment_email: string;
  address: string | null;
}

export interface Summary {
  total_paid_cents: number;
  total_blocked_cents: number;
  total_held_cents: number;
  money_saved_cents: number;
  counts: Record<string, number>;
  invoice_count: number;
}

export interface AuditRow {
  id: number;
  invoice_id: number | null;
  event: string;
  decision: string | null;
  reason: string | null;
  created_at: string;
}

export const money = (cents: number | null | undefined) =>
  cents == null ? "" : (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

const post = <T,>(url: string) => call<T>(url, { method: "POST" });

export const api = {
  invoices: () => call<Invoice[]>("/api/invoices"),
  suppliers: () => call<Supplier[]>("/api/suppliers"),
  summary: () => call<Summary>("/api/summary"),
  audit: () => call<AuditRow[]>("/api/audit"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<Invoice>("/api/invoices/upload", { method: "POST", body: form });
  },
  approve: (id: number) => post<Invoice>(`/api/invoices/${id}/approve`),
  reject: (id: number) => post<Invoice>(`/api/invoices/${id}/reject`),
  refreshPayout: (id: number) => post<Invoice>(`/api/invoices/${id}/refresh-payout`),
  runSamples: () => post<{ processed: number }>("/api/demo/run-samples"),
};
