import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Fingerprint, Lock } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

const DEMO = [
  { u: "alice", p: "admin123", role: "admin", label: "Admin · Executive" },
  { u: "bob", p: "manager123", role: "manager", label: "Manager · Finance" },
  { u: "carol", p: "emp123", role: "employee", label: "Employee · Engineering" },
  { u: "dave", p: "intern123", role: "intern", label: "Intern · Engineering" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e, u, p) => {
    if (e) e.preventDefault();
    setBusy(true);
    try {
      const user = await login(u ?? username, p ?? password);
      toast.success(`Authenticated as ${user.username}`);
      navigate("/chat");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid md:grid-cols-2 bg-[#FAFAFA]">
      {/* Left form */}
      <div className="flex items-center justify-center px-6 py-12" data-testid="login-page">
        <div className="w-full max-w-md sr-fadein">
          <div className="flex items-center gap-3 mb-10">
            <div className="w-9 h-9 bg-[#002FA7] text-white flex items-center justify-center">
              <Shield size={18} strokeWidth={2} />
            </div>
            <div>
              <div className="text-xl font-bold tracking-tight">SentinelRAG</div>
              <div className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#737373]">
                Policy-Aware Retrieval · SOC2-Grade
              </div>
            </div>
          </div>

          <h1 className="text-4xl font-bold tracking-tighter leading-none mb-2">
            Sign in.
          </h1>
          <p className="text-sm text-[#737373] mb-10">
            Access is governed by <span className="font-mono">RBAC + ABAC</span> and every
            query is auditable.
          </p>

          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
                Username
              </span>
              <input
                data-testid="login-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 block w-full border border-[#E5E5E5] bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#002FA7] focus:border-[#002FA7]"
                placeholder="alice"
                autoComplete="username"
              />
            </label>
            <label className="block">
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
                Password
              </span>
              <input
                data-testid="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 block w-full border border-[#E5E5E5] bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#002FA7] focus:border-[#002FA7]"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </label>
            <button
              data-testid="login-submit"
              type="submit"
              disabled={busy}
              className="w-full bg-[#002FA7] text-white py-2.5 text-sm font-medium uppercase tracking-[0.15em] hover:bg-[#001c73] transition-colors disabled:opacity-60"
            >
              {busy ? "Authenticating…" : "Continue"}
            </button>
          </form>

          <div className="mt-10">
            <div className="flex items-center gap-3 mb-3">
              <Fingerprint size={14} className="text-[#737373]" />
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
                Demo identities
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.u}
                  data-testid={`login-btn-${d.role}`}
                  onClick={() => submit(null, d.u, d.p)}
                  disabled={busy}
                  className="text-left border border-[#E5E5E5] bg-white px-3 py-2 hover:border-[#0A0A0A] transition-colors group"
                >
                  <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] group-hover:text-[#002FA7]">
                    {d.role}
                  </div>
                  <div className="text-sm font-medium">{d.label}</div>
                  <div className="text-[10px] font-mono text-[#737373] mt-0.5">{d.u} / {d.p}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="mt-10 pt-6 border-t border-[#E5E5E5] flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
            <Lock size={12} /> RBAC · ABAC · Audit-logged · Query guardrails
          </div>
        </div>
      </div>

      {/* Right hero */}
      <div
        className="hidden md:block relative bg-[#0A0A0A]"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1610496571096-8367bdbbae2b?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzNzl8MHwxfHNlYXJjaHwyfHxtaW5pbWFsaXN0JTIwYWJzdHJhY3QlMjB3aGl0ZSUyMGFyY2hpdGVjdHVyZXxlbnwwfHx8fDE3Nzc1MDE0NTV8MA&ixlib=rb-4.1.0&q=85')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-[#0A0A0A]/30" />
        <div className="relative h-full flex flex-col justify-between p-10 text-white">
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.25em]">
            <span className="w-1.5 h-1.5 bg-[#FFCC00] inline-block" /> LIVE · POLICY ENGINE
          </div>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.25em] opacity-70 mb-3">
              / 01 — Objective Authority
            </div>
            <div className="text-4xl font-bold leading-tight tracking-tighter max-w-md">
              No unauthorized token ever reaches the model.
            </div>
            <div className="mt-6 text-sm opacity-80 max-w-md">
              Filter-before-retrieve pipeline. Document-level and attribute-level
              access control. Immutable audit trail.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
