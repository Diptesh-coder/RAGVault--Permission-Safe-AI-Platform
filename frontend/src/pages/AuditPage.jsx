import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Header from "@/components/Header";
import { ShieldCheck, ShieldAlert, AlertTriangle } from "lucide-react";

const roleTint = {
  admin: "sr-chip-primary",
  manager: "sr-chip-dark",
  employee: "sr-chip-outline",
  intern: "sr-chip-muted",
};

export default function AuditPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/audit-logs").then((r) => setRows(r.data)).finally(() => setLoading(false));
  }, []);

  const grantedCount = rows.filter((r) => r.access === "granted").length;
  const deniedCount = rows.filter((r) => r.access === "denied").length;
  const guardrailCount = rows.filter((r) => r.guardrail_triggered).length;

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Header />
      <div className="max-w-[1400px] mx-auto px-6 py-8" data-testid="audit-page">
        <div className="mb-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">/ compliance</div>
          <h1 className="text-4xl font-bold tracking-tighter">Audit Trail</h1>
          <p className="text-sm text-[#737373] mt-1">Immutable log of every policy-aware query.</p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Stat label="Total" value={rows.length} />
          <Stat label="Granted" value={grantedCount} tone="primary" />
          <Stat label="Denied" value={deniedCount} tone="danger" />
          <Stat label="Guardrail hits" value={guardrailCount} tone="warn" />
        </div>

        <div className="border border-[#E5E5E5] bg-white overflow-x-auto">
          <table className="w-full text-sm" data-testid="audit-table">
            <thead>
              <tr className="text-left border-b border-[#E5E5E5] bg-[#F5F5F5]">
                <Th>Timestamp</Th><Th>User</Th><Th>Role</Th><Th>Query</Th><Th>Access</Th><Th>Cited</Th><Th>Excluded</Th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={7} className="px-4 py-6 text-center text-xs text-[#737373] font-mono">Loading…</td></tr>}
              {!loading && rows.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-xs text-[#737373]">No audit records yet.</td></tr>}
              {rows.map((r) => (
                <tr key={r.id} data-testid="audit-row"
                    className={`border-b border-[#E5E5E5] hover:bg-[#F5F5F5] ${r.access === "denied" ? "bg-[#FFF5F4]" : ""}`}>
                  <td className="px-4 py-3 font-mono text-xs text-[#737373]">{new Date(r.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-3 font-medium">{r.username}</td>
                  <td className="px-4 py-3"><span className={`sr-chip ${roleTint[r.role]}`}>{r.role}</span></td>
                  <td className="px-4 py-3 max-w-md">
                    <span className="line-clamp-1">{r.query}</span>
                    {r.guardrail_triggered && (
                      <span className="sr-chip sr-chip-warn ml-1 inline-flex items-center gap-1"><AlertTriangle size={10} /> guardrail</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {r.access === "granted" && <span className="sr-chip sr-chip-primary inline-flex items-center gap-1"><ShieldCheck size={10} /> granted</span>}
                    {r.access === "partial" && <span className="sr-chip sr-chip-warn">partial</span>}
                    {r.access === "denied" && <span className="sr-chip sr-chip-danger inline-flex items-center gap-1"><ShieldAlert size={10} /> denied</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{r.cited_doc_ids.length}</td>
                  <td className="px-4 py-3 font-mono text-xs">{r.filtered_out_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Th({ children }) {
  return <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">{children}</th>;
}

function Stat({ label, value, tone }) {
  const toneCls =
    tone === "primary" ? "text-[#002FA7]" :
    tone === "danger"  ? "text-[#FF3B30]" :
    tone === "warn"    ? "text-[#8a6d00]" : "text-[#0A0A0A]";
  return (
    <div className="border border-[#E5E5E5] bg-white p-4">
      <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">{label}</div>
      <div className={`text-3xl font-bold tracking-tighter ${toneCls}`}>{value}</div>
    </div>
  );
}
