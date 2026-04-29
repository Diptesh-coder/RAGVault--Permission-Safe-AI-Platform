import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Header from "@/components/Header";
import { Activity, AlertTriangle, ShieldOff, Zap, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const REFRESH_MS = 5000;

export default function OpsPage() {
  const [snap, setSnap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = async () => {
    try {
      const { data } = await api.get("/admin/ops");
      setSnap(data);
      setUpdatedAt(new Date());
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load ops metrics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    if (!autoRefresh) return;
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh]);

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Header />
      <div className="max-w-[1400px] mx-auto px-6 py-8" data-testid="ops-page">
        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
              / observability · live
            </div>
            <h1 className="text-4xl font-bold tracking-tighter">Ops Console</h1>
            <p className="text-sm text-[#737373] mt-1">
              Headline KPIs sourced from the in-process Prometheus registry.
              {updatedAt && (
                <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.15em]">
                  · last refresh {updatedAt.toLocaleTimeString()}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              data-testid="ops-toggle-refresh"
              onClick={() => setAutoRefresh((v) => !v)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.15em] border transition-colors ${
                autoRefresh
                  ? "bg-[#002FA7] text-white border-[#002FA7]"
                  : "bg-white text-[#0A0A0A] border-[#E5E5E5]"
              }`}
            >
              <Activity size={10} /> Auto · 5s
            </button>
            <button
              data-testid="ops-refresh-btn"
              onClick={load}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#E5E5E5] bg-white hover:border-[#0A0A0A]"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>

        {/* KPI tiles */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <KpiTile
            testId="kpi-ttft"
            icon={Zap}
            label="TTFT p95 · real stream"
            value={snap ? `${snap.ttft_p95_real.toFixed(2)}s` : "—"}
            sub={snap ? `${snap.ttft_observations_real.toFixed(0)} samples` : "loading…"}
            tone={tonalize(snap?.ttft_p95_real, [4, 8])}
            footer={snap ? `fallback p95 ${snap.ttft_p95_fallback.toFixed(2)}s` : ""}
          />
          <KpiTile
            testId="kpi-fallback"
            icon={Activity}
            label="Stream fallback rate"
            value={snap ? `${(snap.fallback_rate * 100).toFixed(1)}%` : "—"}
            sub={snap ? `${snap.stream_fallback_total.toFixed(0)} of ${snap.stream_total.toFixed(0)} streams` : "loading…"}
            tone={snap?.fallback_rate > 0 ? "danger" : "primary"}
            footer={snap?.fallback_rate > 0 ? "Real-stream regressed — investigate" : "Real-stream healthy"}
          />
          <KpiTile
            testId="kpi-denied-ratio"
            icon={ShieldOff}
            label="Denied / Granted"
            value={snap ? `${(snap.denied_to_granted_ratio * 100).toFixed(0)}%` : "—"}
            sub={snap ? `granted ${snap.decisions.granted.toFixed(0)} · partial ${snap.decisions.partial.toFixed(0)} · denied ${snap.decisions.denied.toFixed(0)}` : "loading…"}
            tone={tonalize(snap?.denied_to_granted_ratio, [0.4, 0.8])}
            footer="Spike → audit query patterns"
          />
          <KpiTile
            testId="kpi-guardrail"
            icon={AlertTriangle}
            label="Guardrail hits"
            value={snap ? snap.guardrail_total.toFixed(0) : "—"}
            sub={snap ? `${snap.stream_total + 0} total chats` : "loading…"}
            tone={snap?.guardrail_total > 20 ? "warn" : "muted"}
            footer="Sensitive-pattern triggers"
          />
        </div>

        {/* Decision breakdown */}
        <div className="border border-[#E5E5E5] bg-white p-6 mb-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] mb-3">
            Decision distribution
          </div>
          {snap ? (
            <DecisionBar decisions={snap.decisions} />
          ) : (
            <div className="text-xs text-[#737373]">Loading…</div>
          )}
        </div>

        {/* Raw metrics table */}
        <div className="border border-[#E5E5E5] bg-white">
          <div className="px-5 py-3 border-b border-[#E5E5E5] flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Raw metrics snapshot</div>
              <div className="text-sm font-medium">/api/admin/ops</div>
            </div>
            <span className="sr-chip sr-chip-outline">JSON</span>
          </div>
          <pre className="p-5 text-xs font-mono overflow-x-auto whitespace-pre-wrap" data-testid="ops-raw">
            {snap ? JSON.stringify(snap, null, 2) : (loading ? "Loading…" : "(no data)")}
          </pre>
        </div>
      </div>
    </div>
  );
}

function tonalize(v, [warnAt, dangerAt]) {
  if (v === undefined || v === null) return "muted";
  if (v >= dangerAt) return "danger";
  if (v >= warnAt) return "warn";
  return "primary";
}

function KpiTile({ testId, icon: Icon, label, value, sub, tone, footer }) {
  const valueColor =
    tone === "primary" ? "text-[#002FA7]" :
    tone === "danger"  ? "text-[#FF3B30]" :
    tone === "warn"    ? "text-[#8a6d00]" : "text-[#0A0A0A]";
  const accentBar =
    tone === "primary" ? "bg-[#002FA7]" :
    tone === "danger"  ? "bg-[#FF3B30]" :
    tone === "warn"    ? "bg-[#FFCC00]" : "bg-[#737373]";

  return (
    <div className="border border-[#E5E5E5] bg-white relative overflow-hidden" data-testid={testId}>
      <span className={`absolute left-0 top-0 bottom-0 w-1 ${accentBar}`} />
      <div className="p-5">
        <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
          <Icon size={11} /> {label}
        </div>
        <div className={`mt-3 text-4xl font-bold tracking-tighter ${valueColor}`}>{value}</div>
        <div className="mt-1 text-xs text-[#0A0A0A]">{sub}</div>
        {footer && (
          <div className="mt-3 pt-3 border-t border-[#E5E5E5] text-[10px] font-mono uppercase tracking-[0.15em] text-[#737373]">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionBar({ decisions }) {
  const total = (decisions.granted || 0) + (decisions.partial || 0) + (decisions.denied || 0);
  if (total === 0) {
    return <div className="text-xs text-[#737373]">No decisions recorded yet.</div>;
  }
  const pct = (n) => `${((n / total) * 100).toFixed(1)}%`;
  return (
    <div>
      <div className="flex h-2 overflow-hidden border border-[#E5E5E5]">
        <div className="bg-[#002FA7]" style={{ width: pct(decisions.granted) }} title={`granted ${decisions.granted}`} />
        <div className="bg-[#FFCC00]" style={{ width: pct(decisions.partial) }} title={`partial ${decisions.partial}`} />
        <div className="bg-[#FF3B30]" style={{ width: pct(decisions.denied) }} title={`denied ${decisions.denied}`} />
      </div>
      <div className="mt-3 flex items-center gap-4 text-xs">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 bg-[#002FA7]" /> granted · <span className="font-mono">{decisions.granted.toFixed(0)} ({pct(decisions.granted)})</span></span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 bg-[#FFCC00]" /> partial · <span className="font-mono">{decisions.partial.toFixed(0)} ({pct(decisions.partial)})</span></span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 bg-[#FF3B30]" /> denied · <span className="font-mono">{decisions.denied.toFixed(0)} ({pct(decisions.denied)})</span></span>
      </div>
    </div>
  );
}
