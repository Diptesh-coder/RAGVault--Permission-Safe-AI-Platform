import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Header from "@/components/Header";
import { useAuth } from "@/context/AuthContext";
import { Plus, Trash2, FileText } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";

const ROLES = ["admin", "manager", "employee", "intern"];
const SENS = ["low", "medium", "high"];

const sensTint = { low: "sr-chip-muted", medium: "sr-chip-warn", high: "sr-chip-danger" };

export default function DocumentsPage() {
  const { user } = useAuth();
  const isAdmin = user.role === "admin";
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [department, setDepartment] = useState("All");
  const [sensitivity, setSensitivity] = useState("low");
  const [roleAccess, setRoleAccess] = useState(["admin", "manager", "employee", "intern"]);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(isAdmin && showAll ? "/documents/all" : "/documents");
      setDocs(data);
    } catch (err) {
      toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [showAll]);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post("/documents", {
        title, content, role_access: roleAccess, department, sensitivity,
      });
      toast.success("Document uploaded");
      setOpen(false);
      setTitle(""); setContent(""); setDepartment("All"); setSensitivity("low");
      setRoleAccess(["admin", "manager", "employee", "intern"]);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Upload failed");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this document?")) return;
    await api.delete(`/documents/${id}`);
    toast.success("Document deleted");
    load();
  };

  const toggleRole = (r) =>
    setRoleAccess((arr) => (arr.includes(r) ? arr.filter((x) => x !== r) : [...arr, r]));

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Header />
      <div className="max-w-[1400px] mx-auto px-6 py-8" data-testid="documents-page">
        <div className="flex items-start justify-between mb-6">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">/ library</div>
            <h1 className="text-4xl font-bold tracking-tighter">Documents</h1>
            <p className="text-sm text-[#737373] mt-1">
              {isAdmin
                ? "Full corpus view. Toggle to see only docs accessible to you."
                : "Documents accessible under your policy envelope."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isAdmin && (
              <button
                data-testid="toggle-all-docs"
                onClick={() => setShowAll((v) => !v)}
                className="px-3 py-2 text-xs font-mono uppercase tracking-[0.15em] border border-[#E5E5E5] bg-white hover:border-[#0A0A0A]"
              >
                {showAll ? "My accessible" : "Show all (admin)"}
              </button>
            )}
            {isAdmin && (
              <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                  <button
                    data-testid="upload-doc-btn"
                    className="inline-flex items-center gap-1.5 bg-[#002FA7] text-white px-4 py-2 text-sm uppercase tracking-[0.15em] hover:bg-[#001c73]"
                  >
                    <Plus size={14} /> Upload
                  </button>
                </DialogTrigger>
                <DialogContent className="sm:max-w-xl rounded-none">
                  <DialogHeader>
                    <DialogTitle className="tracking-tight">New policy-bound document</DialogTitle>
                  </DialogHeader>
                  <form onSubmit={submit} className="space-y-4">
                    <div>
                      <label className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Title</label>
                      <input data-testid="doc-title" required value={title} onChange={(e) => setTitle(e.target.value)}
                        className="mt-1 w-full border border-[#E5E5E5] bg-white px-3 py-2 text-sm focus:ring-2 focus:ring-[#002FA7] outline-none" />
                    </div>
                    <div>
                      <label className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Content</label>
                      <textarea data-testid="doc-content" required value={content} onChange={(e) => setContent(e.target.value)} rows={5}
                        className="mt-1 w-full border border-[#E5E5E5] bg-white px-3 py-2 text-sm focus:ring-2 focus:ring-[#002FA7] outline-none" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Department</label>
                        <input data-testid="doc-department" value={department} onChange={(e) => setDepartment(e.target.value)}
                          className="mt-1 w-full border border-[#E5E5E5] bg-white px-3 py-2 text-sm" />
                      </div>
                      <div>
                        <label className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Sensitivity</label>
                        <select data-testid="doc-sensitivity" value={sensitivity} onChange={(e) => setSensitivity(e.target.value)}
                          className="mt-1 w-full border border-[#E5E5E5] bg-white px-3 py-2 text-sm">
                          {SENS.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Role access</label>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {ROLES.map((r) => (
                          <button type="button" key={r}
                            data-testid={`role-toggle-${r}`}
                            onClick={() => toggleRole(r)}
                            className={`sr-chip cursor-pointer ${roleAccess.includes(r) ? "sr-chip-primary" : "sr-chip-outline"}`}>
                            {r}
                          </button>
                        ))}
                      </div>
                    </div>
                    <DialogFooter>
                      <button type="submit" data-testid="upload-doc-submit"
                        className="bg-[#002FA7] text-white px-4 py-2 text-sm uppercase tracking-[0.15em] hover:bg-[#001c73]">
                        Create
                      </button>
                    </DialogFooter>
                  </form>
                </DialogContent>
              </Dialog>
            )}
          </div>
        </div>

        <div className="border border-[#E5E5E5] bg-white overflow-x-auto">
          <table className="w-full text-sm" data-testid="documents-table">
            <thead>
              <tr className="text-left border-b border-[#E5E5E5] bg-[#F5F5F5]">
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Title</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Dept</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Sensitivity</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Role access</th>
                <th className="px-4 py-2 text-[10px] font-mono uppercase tracking-[0.15em]">Uploader</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-[#737373] text-xs font-mono">Loading…</td></tr>
              )}
              {!loading && docs.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-[#737373] text-xs">No documents visible at your clearance level.</td></tr>
              )}
              {docs.map((d) => (
                <tr key={d.id} className="border-b border-[#E5E5E5] hover:bg-[#F5F5F5]">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileText size={14} className="text-[#002FA7]" />
                      <div>
                        <div className="font-medium">{d.title}</div>
                        <div className="text-xs text-[#737373] max-w-lg line-clamp-1">{d.content}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><span className="sr-chip sr-chip-outline">{d.department}</span></td>
                  <td className="px-4 py-3"><span className={`sr-chip ${sensTint[d.sensitivity]}`}>{d.sensitivity}</span></td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {d.role_access.map((r) => <span key={r} className="sr-chip sr-chip-muted">{r}</span>)}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#737373]">{d.uploaded_by}</td>
                  <td className="px-4 py-3 text-right">
                    {isAdmin && (
                      <button onClick={() => remove(d.id)} data-testid={`delete-doc-${d.id}`}
                        className="p-1.5 border border-[#E5E5E5] hover:border-[#FF3B30] hover:text-[#FF3B30]">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
