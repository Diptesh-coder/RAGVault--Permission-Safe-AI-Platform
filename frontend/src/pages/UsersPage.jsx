import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Header from "@/components/Header";

const roleTint = {
  admin: "sr-chip-primary",
  manager: "sr-chip-dark",
  employee: "sr-chip-outline",
  intern: "sr-chip-muted",
};
const sensTint = { low: "sr-chip-muted", medium: "sr-chip-warn", high: "sr-chip-danger" };

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  useEffect(() => { api.get("/users").then((r) => setUsers(r.data)); }, []);

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Header />
      <div className="max-w-[1400px] mx-auto px-6 py-8" data-testid="users-page">
        <div className="mb-6">
          <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">/ identity</div>
          <h1 className="text-4xl font-bold tracking-tighter">Users & Policies</h1>
          <p className="text-sm text-[#737373] mt-1">Identity directory (simulated SSO/LDAP).</p>
        </div>
        <div className="border border-[#E5E5E5] bg-white overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b border-[#E5E5E5] bg-[#F5F5F5]">
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Name</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Username</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Role</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Department</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Clearance</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-[#E5E5E5] hover:bg-[#F5F5F5]">
                  <td className="px-4 py-3 font-medium">{u.full_name}</td>
                  <td className="px-4 py-3 font-mono text-xs">{u.username}</td>
                  <td className="px-4 py-3"><span className={`sr-chip ${roleTint[u.role]}`}>{u.role}</span></td>
                  <td className="px-4 py-3 font-mono text-xs">{u.department}</td>
                  <td className="px-4 py-3"><span className={`sr-chip ${sensTint[u.clearance]}`}>{u.clearance}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
