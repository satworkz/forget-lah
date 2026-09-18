import { useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";
type State = { configured: boolean; webhook_url: string; case_id: string | null; case_ids: string[]; outgoing: { id: string; status: string; error: string | null }[]; incoming: { sid: string; status: string }[] };
export function WhatsAppChannel({ cases }: { cases: { id: string; patient: string }[] }) {
  const [state, setState] = useState<State | null>(null);
  const [caseId, setCaseId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    const load = () => api<State>("/api/channels/whatsapp", { signal: abort.signal }).then(s => { if (!abort.signal.aborted) { setState(s); setError(""); } }).catch(e => { if (!abort.signal.aborted) { setState(null); setError(e.message); } });
    void load(); const timer = window.setInterval(() => void load(), 5000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [version]);
  async function bind(enabled: boolean) {
    setBusy(true);
    try { await api("/api/channels/whatsapp/binding", { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ case_id: state?.case_id ?? caseId, enabled }) }); setVersion(n => n + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel staff-panel"><h2>WhatsApp test phone</h2><p>Connect one configured team phone to a synthetic patient. New appointments for that patient receive messages automatically. Appointment updates still affect only the clinic simulator.</p>{error && <p role="alert" className="error">{error}</p>}{state && (state.configured ? <><p>Webhook (POST): <code>{state.webhook_url}</code></p>{state.case_id ? <><p>Connected to <strong>{cases.find(c => c.id === state.case_id)?.patient ?? "a previous case"}</strong> · {state.case_ids.length} follow-up case(s)</p><button className="secondary" disabled={busy} onClick={() => void bind(false)}>Disconnect test phone</button></> : <><label>Select the synthetic patient<select value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">Choose a patient</option>{cases.map(c => <option value={c.id} key={c.id}>{c.patient} · {c.id.slice(0, 8)}</option>)}</select></label><button className="primary" disabled={busy || !caseId} onClick={() => void bind(true)}>Connect configured test phone</button></>}<p className="small">The connection follows this patient across appointments. Replies after completion start a new review and preserve previous history. If several appointments could match, we ask which one you mean; you can also use WhatsApp Reply on the relevant message. Messages created before enrollment are not resent. Reset preserves the connected patient and sends fresh reminders for recreated eligible cases. Outside the active WhatsApp reply window, messages wait for a new incoming message.</p><details><summary>Channel delivery and incoming queue</summary><p>Outgoing: {state.outgoing.map(m => `${m.status}${m.error ? ` (${m.error})` : ""}`).join(", ") || "None"}</p><p>Incoming: {state.incoming.map(m => m.status).join(", ") || "None"}</p><p>“needs_staff” means the reply could not enter the automatic review (for example, the review is paused, already with staff, or the message is unsupported). “uncertain” requires checking Twilio logs before another send.</p></details></> : <p>Not enabled on this deployment.</p>)}</section>;
}
