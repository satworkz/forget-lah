import { useEffect, useState } from "react";
import { api } from "./client";

type Audit = { patient: string; events: { id: string; actor: string; action: string; source: string; timestamp: string; decision: unknown; evidence: unknown }[] };

export function SecurityAudit({ caseId }: { caseId: string }) {
  const [data, setData] = useState<Audit | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    const load = () => api<Audit>(`/api/cases/${caseId}/audit`, { signal: abort.signal }).then(value => { setData(value); setError(""); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    void load(); const timer = window.setInterval(() => void load(), 5000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [caseId, open]);
  return <section className="panel staff-panel"><details onToggle={event => setOpen(event.currentTarget.open)}><summary>Security &amp; Audit</summary>
    {error && <p role="alert">{error}</p>}
    {data && <><p>Authorized case details: <strong>{data.patient}</strong></p><p className="muted">Saved actors, policy decisions and evidence. Up to 200 recent entries per source; older records remain stored. Earlier actions may lack actor or change details.</p>
    <ol className="staff-conversation">{data.events.map((e, i) => <li key={`${e.id}-${i}`}>
      <strong>{e.action.replaceAll("_", " ")}</strong><time>{new Date(e.timestamp).toLocaleString("en-SG")}</time>
      <p>Actor: {e.actor} · Source: {e.source}</p>
      <p>Decision: {typeof e.decision === "string" ? e.decision : JSON.stringify(e.decision)}</p>
      <details><summary>Evidence, result and recorded changes</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(e.evidence, null, 2)}</pre></details>
    </li>)}</ol>{!data.events.length && <p>No audit evidence has been recorded yet.</p>}</>}
  </details></section>;
}
