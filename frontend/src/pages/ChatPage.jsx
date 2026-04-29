import { useEffect, useRef, useState } from "react";
import { api, API } from "@/lib/api";
import Header from "@/components/Header";
import { useAuth } from "@/context/AuthContext";
import { Send, AlertTriangle, ShieldCheck, ShieldAlert, FileText, Lock, Zap } from "lucide-react";
import { toast } from "sonner";

const SAMPLE_QS = [
  "What is the CEO compensation package?",
  "Summarize the Q4 2025 finance report",
  "What is the company leave policy?",
  "What engineering initiatives are planned for H1 2026?",
];

const sensTint = { low: "sr-chip-muted", medium: "sr-chip-warn", high: "sr-chip-danger" };

export default function ChatPage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [useStreaming, setUseStreaming] = useState(true);
  const feedRef = useRef(null);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const parseSSE = (buf) => {
    const events = [];
    const parts = buf.split("\n\n");
    const remainder = parts.pop();
    for (const part of parts) {
      const lines = part.split("\n");
      let event = "message", data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) events.push({ event, data });
    }
    return [events, remainder];
  };

  const sendStream = async (q) => {
    const token = localStorage.getItem("sr_token");
    const resp = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ query: q, session_id: sessionId }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    // Seed an empty assistant message
    setMessages((m) => [...m, { role: "assistant", answer: "", citations: [], access_decision: "granted", _streaming: true }]);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const [events, remainder] = parseSSE(buf);
      buf = remainder;
      for (const ev of events) {
        let payload;
        try { payload = JSON.parse(ev.data); } catch { continue; }
        if (ev.event === "meta") {
          setSessionId(payload.session_id);
          setMessages((m) => {
            const arr = [...m];
            const last = arr[arr.length - 1];
            last.citations = payload.citations || [];
            last.access_decision = payload.access_decision;
            last.guardrail_triggered = payload.guardrail_triggered;
            last.guardrail_reason = payload.guardrail_reason;
            last.filtered_out_count = payload.filtered_out_count;
            return arr;
          });
        } else if (ev.event === "token") {
          setMessages((m) => {
            const arr = [...m];
            const last = arr[arr.length - 1];
            last.answer = (last.answer || "") + (payload.t || "");
            return arr;
          });
        } else if (ev.event === "done") {
          setMessages((m) => {
            const arr = [...m];
            const last = arr[arr.length - 1];
            last._streaming = false;
            if (payload.answer) last.answer = payload.answer;
            return arr;
          });
        } else if (ev.event === "error") {
          throw new Error(payload.detail || "stream error");
        }
      }
    }
  };

  const sendRegular = async (q) => {
    const { data } = await api.post("/chat", { query: q, session_id: sessionId });
    setSessionId(data.session_id);
    setMessages((m) => [...m, { role: "assistant", ...data }]);
  };

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q }]);
    setBusy(true);
    try {
      if (useStreaming) await sendStream(q);
      else await sendRegular(q);
    } catch (err) {
      toast.error(err.message || "Chat request failed");
      setMessages((m) => [...m, { role: "assistant", answer: "⚠︎ Request failed.", citations: [], access_decision: "denied" }]);
    } finally {
      setBusy(false);
    }
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Header />
      <div className="max-w-[1400px] mx-auto px-6 py-6 grid lg:grid-cols-[1fr_380px] gap-6 h-[calc(100vh-3.5rem)]">
        <section className="flex flex-col border border-[#E5E5E5] bg-white">
          <div className="px-5 py-3 border-b border-[#E5E5E5] flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Session</div>
              <div className="text-sm font-medium">Policy-Aware Assistant</div>
            </div>
            <div className="flex items-center gap-3">
              <button
                data-testid="toggle-streaming"
                onClick={() => setUseStreaming((v) => !v)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.15em] border transition-colors ${
                  useStreaming ? "bg-[#002FA7] text-white border-[#002FA7]" : "bg-white text-[#0A0A0A] border-[#E5E5E5]"
                }`}
              >
                <Zap size={10} /> {useStreaming ? "Streaming" : "Batch"}
              </button>
              <div className="hidden md:flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">
                <ShieldCheck size={12} className="text-[#002FA7]" />
                Filter · Retrieve · Re-rank · Validate
              </div>
            </div>
          </div>

          <div ref={feedRef} className="flex-1 overflow-y-auto px-5 py-6 space-y-4" data-testid="chat-feed">
            {messages.length === 0 && (
              <div className="sr-fadein">
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] mb-3">
                  / suggested queries for role = {user.role}
                </div>
                <div className="grid sm:grid-cols-2 gap-2">
                  {SAMPLE_QS.map((q) => (
                    <button key={q} data-testid="sample-query" onClick={() => send(q)}
                      className="text-left border border-[#E5E5E5] bg-white px-4 py-3 text-sm hover:border-[#0A0A0A] transition-colors">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="flex justify-end sr-fadein">
                  <div className="max-w-[75%] bg-[#002FA7] text-white px-4 py-2.5 text-sm" data-testid="msg-user">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="sr-fadein" data-testid="msg-assistant">
                  {m.guardrail_triggered && (
                    <div className="mb-2 flex items-start gap-2 border border-[#FFCC00] bg-[#FFF8D6] px-3 py-2" data-testid="guardrail-banner">
                      <AlertTriangle size={14} className="mt-0.5 text-[#8a6d00]" />
                      <div>
                        <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#8a6d00]">Guardrail triggered</div>
                        <div className="text-xs text-[#5e4a00]">{m.guardrail_reason}</div>
                      </div>
                    </div>
                  )}
                  {m.access_decision === "denied" && (
                    <div className="mb-2 flex items-start gap-2 border border-[#FF3B30] bg-[#FFEBEA] px-3 py-2" data-testid="access-denied-banner">
                      <ShieldAlert size={14} className="mt-0.5 text-[#FF3B30]" />
                      <div>
                        <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#FF3B30]">Error 403 · Security Policy Violation</div>
                        <div className="text-xs text-[#0A0A0A]">
                          Insufficient clearance. {m.filtered_out_count} document(s) were excluded before retrieval.
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="max-w-[85%] bg-[#F5F5F5] text-[#0A0A0A] px-4 py-3 text-sm whitespace-pre-wrap border border-[#E5E5E5]">
                    {m.answer}
                    {m._streaming && <span className="inline-block w-1.5 h-3.5 align-middle bg-[#002FA7] ml-0.5 animate-pulse" />}
                  </div>
                  {m.citations?.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="citations-inline">
                      {m.citations.map((c) => (
                        <button key={c.doc_id} onClick={() => setSelectedCitation(c.doc_id)}
                          className="sr-chip sr-chip-outline hover:bg-[#002FA7] hover:text-white hover:border-[#002FA7]"
                          data-testid={`citation-${c.doc_id}`}>
                          <FileText size={10} className="mr-1" /> {c.title}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            )}

            {busy && !messages[messages.length - 1]?._streaming && (
              <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] sr-fadein">
                <span className="w-1.5 h-1.5 bg-[#002FA7] animate-pulse" />
                Running policy-aware retrieval…
              </div>
            )}
          </div>

          <div className="border-t border-[#E5E5E5] p-4 bg-white">
            <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex items-center gap-2">
              <input data-testid="chat-input-field" value={input} onChange={(e) => setInput(e.target.value)}
                placeholder="Ask something within your clearance…"
                className="flex-1 border border-[#E5E5E5] bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#002FA7] focus:border-[#002FA7]" />
              <button type="submit" disabled={busy || !input.trim()} data-testid="chat-send-btn"
                className="bg-[#002FA7] text-white px-4 py-2.5 text-sm font-medium uppercase tracking-[0.15em] hover:bg-[#001c73] transition-colors disabled:opacity-60 inline-flex items-center gap-1.5">
                <Send size={14} /> Send
              </button>
            </form>
          </div>
        </section>

        <aside className="border border-[#E5E5E5] bg-white flex flex-col" data-testid="explainability-panel">
          <div className="px-5 py-3 border-b border-[#E5E5E5]">
            <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373]">Explainability</div>
            <div className="text-sm font-medium">Policy Decision Trace</div>
          </div>
          <div className="p-5 space-y-5 overflow-y-auto flex-1">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] mb-2">Your attributes</div>
              <div className="flex flex-wrap gap-1.5">
                <span className="sr-chip sr-chip-primary">role:{user.role}</span>
                <span className="sr-chip sr-chip-dark">dept:{user.department}</span>
                <span className="sr-chip sr-chip-outline">clr:{user.clearance}</span>
              </div>
            </div>

            {lastAssistant ? (
              <>
                <div>
                  <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] mb-2">Decision</div>
                  <div className="flex items-center gap-2">
                    {lastAssistant.access_decision === "granted" && (
                      <span className="sr-chip sr-chip-primary"><ShieldCheck size={10} className="mr-1" /> granted</span>
                    )}
                    {lastAssistant.access_decision === "partial" && <span className="sr-chip sr-chip-warn">partial</span>}
                    {lastAssistant.access_decision === "denied" && (
                      <span className="sr-chip sr-chip-danger"><Lock size={10} className="mr-1" /> denied</span>
                    )}
                    <span className="text-[10px] font-mono text-[#737373] uppercase tracking-[0.15em]">
                      {lastAssistant.filtered_out_count ?? 0} excluded
                    </span>
                  </div>
                </div>
                <div>
                  <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-[#737373] mb-2">Documents used</div>
                  {lastAssistant.citations?.length ? (
                    <ul className="space-y-2">
                      {lastAssistant.citations.map((c) => (
                        <li key={c.doc_id}
                          className={`border px-3 py-2 transition-colors ${
                            selectedCitation === c.doc_id ? "border-[#002FA7] bg-[#EEF2FF]" : "border-[#E5E5E5] bg-white"
                          }`}
                          data-testid={`panel-citation-${c.doc_id}`}>
                          <div className="text-sm font-medium">{c.title}</div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            <span className="sr-chip sr-chip-outline">dept:{c.department}</span>
                            <span className={`sr-chip ${sensTint[c.sensitivity]}`}>sens:{c.sensitivity}</span>
                            <span className="sr-chip sr-chip-muted">score:{Number(c.score).toFixed(3)}</span>
                          </div>
                          <div className="mt-1 text-[10px] font-mono text-[#737373] break-all">
                            id:{c.doc_id?.slice(0, 8)}…
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="text-xs text-[#737373]">No documents were cited.</div>
                  )}
                </div>
              </>
            ) : (
              <div className="text-xs text-[#737373]">Send a query to see the filter → retrieve → validate trace.</div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
