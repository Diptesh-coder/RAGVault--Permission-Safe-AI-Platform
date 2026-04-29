import { NavLink, useNavigate } from "react-router-dom";
import { Shield, MessageSquare, FileText, ScrollText, LogOut, Users, Activity } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const roleTint = {
  admin: "sr-chip-primary",
  manager: "sr-chip-dark",
  employee: "sr-chip-outline",
  intern: "sr-chip-muted",
};

export default function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;

  const navItem = (to, label, Icon, testId) => (
    <NavLink
      to={to}
      data-testid={testId}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-1.5 text-sm border transition-colors duration-200 ${
          isActive
            ? "bg-[#0A0A0A] text-white border-[#0A0A0A]"
            : "bg-white text-[#0A0A0A] border-[#E5E5E5] hover:border-[#0A0A0A]"
        }`
      }
    >
      <Icon size={14} strokeWidth={1.75} />
      {label}
    </NavLink>
  );

  return (
    <header
      className="sticky top-0 z-50 bg-white border-b border-[#E5E5E5]"
      data-testid="app-header"
    >
      <div className="max-w-[1400px] mx-auto px-6 h-14 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 bg-[#002FA7] text-white flex items-center justify-center">
            <Shield size={15} strokeWidth={2} />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-base font-bold tracking-tight">SENTINEL</span>
            <span className="text-[10px] font-mono uppercase tracking-[0.25em] text-[#737373]">
              RAG / v1
            </span>
          </div>
        </div>

        <nav className="flex items-center gap-2">
          {navItem("/chat", "Chat", MessageSquare, "nav-chat")}
          {navItem("/documents", "Documents", FileText, "nav-documents")}
          {user.role === "admin" && navItem("/admin/audit", "Audit", ScrollText, "nav-audit")}
          {user.role === "admin" && navItem("/admin/ops", "Ops", Activity, "nav-ops")}
          {user.role === "admin" && navItem("/admin/users", "Users", Users, "nav-users")}
        </nav>

        <div className="flex items-center gap-3" data-testid="user-panel">
          <div className="text-right leading-tight hidden sm:block">
            <div className="text-sm font-medium" data-testid="user-fullname">{user.full_name}</div>
            <div className="text-[10px] font-mono text-[#737373] uppercase tracking-[0.15em]">
              {user.department} · clearance:{user.clearance}
            </div>
          </div>
          <span className={`sr-chip ${roleTint[user.role]}`} data-testid="user-role-chip">
            {user.role}
          </span>
          <button
            data-testid="logout-btn"
            onClick={() => { logout(); navigate("/login"); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-[#E5E5E5] bg-white hover:border-[#FF3B30] hover:text-[#FF3B30] transition-colors"
          >
            <LogOut size={14} strokeWidth={1.75} /> Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
