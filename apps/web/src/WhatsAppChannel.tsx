import { useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";
type Binding = { id: string; recipient: string; case_id: string; case_ids: string[]; enabled: boolean; window_open: boolean };
type State = { configured: boolean; webhook_url: string; bindings: Binding[]; outgoing: { id: string; status: string; error: string | null }[]; incoming: { sid: string; status: string }[] };
export function WhatsAppChannel({ cases }: { cases: { id: string; patient: string }[] }) {
  const [state, setState] = useState<State | null>(null);
  const [caseId, setCaseId] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    const load = () => api<State>("/api/channels/whatsapp", { signal: abort.signal }).then(s => { if (!abort.signal.aborted) setState(s); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    void load(); const timer = window.setInterval(() => void load(), 5000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [version]);
  async function bind(enabled: boolean, binding?: Binding) {
    setBusy(true); setError(""); setNotice("");
    try {
      await api("/api/channels/whatsapp/binding", { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ case_id: binding?.case_id ?? caseId, enabled, ...(binding ? { binding_id: binding.id } : { recipient: phone.trim() }) }) });
      setVersion(n => n + 1); setNotice(enabled ? "Phone connected. Send a WhatsApp message to the sandbox to open the reply window." : "Phone disconnected. Other teammates remain connected.");
      if (!binding) { setPhone(""); setCaseId(""); }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel staff-panel">
    <h2>WhatsApp team test phones</h2>
    <p>Each teammate can connect their phone to a different demo patient. New appointments for that patient use the same connection. All appointment changes remain in the clinic simulator.</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {state && (state.configured ? <>
      <ol><li>Ask each teammate to join your Twilio WhatsApp Sandbox using its join code.</li><li>Register their number and a separate patient below.</li><li>After connecting, they must send a message to the sandbox number before the app can reply.</li></ol>
      <form onSubmit={e => { e.preventDefault(); void bind(true); }}>
        <label>Teammate’s WhatsApp number<input type="tel" required maxLength={25} placeholder="+6591234567" value={phone} onChange={e => setPhone(e.target.value)} /></label>
        <p className="small">Include the country code, with no spaces. One active phone per demo patient.</p>
        <label>Demo patient<select required value={caseId} onChange={e => setCaseId(e.target.value)}><option value="">Choose a patient</option>{cases.map(c => <option value={c.id} key={c.id}>{c.patient} · {c.id.slice(0, 8)}</option>)}</select></label>
        <button className="primary" disabled={busy || !caseId || !phone.trim()}>Connect test phone</button>
      </form>
      <h3>Registered phones</h3>
      {state.bindings.length === 0 && <p>No phones registered yet.</p>}
      {state.bindings.map(b => <article className="panel" key={b.id}>
        <p><strong>{b.recipient.replace("whatsapp:", "")}</strong> · {cases.find(c => c.id === b.case_id)?.patient ?? "Previous demo patient"}</p>
        <p>{b.enabled ? `Connected · ${b.case_ids.length} follow-up case(s) · ${b.window_open ? "Reply window open" : "Waiting for an incoming WhatsApp message"}` : "Disconnected"}</p>
        <button type="button" className="secondary" disabled={busy || (!b.enabled && !cases.some(c => c.id === b.case_id))} onClick={() => void bind(!b.enabled, b)}>{b.enabled ? "Disconnect" : "Reconnect"}</button>
      </article>)}
      <p className="small">Messages created before connection are not replayed. Reset preserves active patient connections, but clears everyone’s demo conversations and preferences. Coordinate resets with the team. Sandbox participants may need to rejoin after three days.</p>
      <details><summary>Channel settings and delivery</summary><p>Webhook (POST): <code>{state.webhook_url}</code></p><p>Outgoing: {state.outgoing.map(m => `${m.status}${m.error ? ` (${m.error})` : ""}`).join(", ") || "None"}</p><p>Incoming: {state.incoming.map(m => m.status).join(", ") || "None"}</p><p>Uncertain deliveries require checking Twilio logs before another send.</p></details>
    </> : <p>Not enabled on this deployment.</p>)}
  </section>;
}
