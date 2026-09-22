import { useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";
type Slot = { id: string; version: number; starts_at: string; doctor: string };
type Change = { id: string; status: string; notification_status: string; receipt: { scheduled_at: string; old_scheduled_at: string; changed_at: string } | null; reason: string; actor_id: string; actor_name: string; created_at: string };
type Requirement = { instruction_id: string; quote: string; effect: string; date_from?: string; date_to?: string; condition_quote?: string };
type State = { review_status: string; can_review: boolean; review_requirements: Requirement[]; patient_checks: Requirement[]; case_version: number; episode_version: number; source_version: string; scheduled_at: string; slots: Slot[]; blocked: string | null; changes: Change[]; more_available_slots: boolean };
const when = (s: string) => new Date(s).toLocaleString("en-SG", { timeZone: "Asia/Singapore", dateStyle: "medium", timeStyle: "short" }) + " SGT";
export function ChangeAppointment({ caseId, version, reload }: { caseId: string; version: number; reload: () => void }) {
  const [open, setOpen] = useState(false), [state, setState] = useState<State | null>(null);
  const [slot, setSlot] = useState(""), [reason, setReason] = useState(""), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    api<State>(`/api/cases/${caseId}/appointment-change`, { signal: abort.signal }).then(s => { setState(s); setSlot(""); setError(""); }).catch(e => { if (!abort.signal.aborted) setError(e.message); });
    return () => abort.abort();
  }, [caseId, version, open, refresh]);
  useEffect(() => {
    if (!open || state?.review_status !== "running") return;
    const timer = window.setInterval(() => setRefresh(n => n + 1), 2000);
    return () => window.clearInterval(timer);
  }, [open, state?.review_status]);
  async function review(cancel = false) {
    if (!state || busy) return;
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/appointment-change/review${cancel ? "/cancel" : ""}`, { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ expected_case_version: state.case_version }) });
      setRefresh(n => n + 1); reload();
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function change() {
    if (!state || busy) return;
    const selected = state.slots.find(s => s.id === slot); if (!selected) return;
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/appointment-change`, { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ expected_case_version: state.case_version, expected_version: state.episode_version, expected_source_version: state.source_version, slot_id: selected.id, slot_version: selected.version, reason }) });
      setReason(""); setRefresh(n => n + 1); reload();
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function retry(id: string) {
    setBusy(true);
    try { await api(`/api/cases/${caseId}/appointment-change/${id}/retry`, { method: "POST", headers: mutationHeaders() }); setRefresh(n => n + 1); reload(); }
    catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel staff-panel"><button className="secondary" onClick={() => setOpen(!open)}>Change appointment</button>{open && <>
    <h2>Change this follow-up appointment</h2><p>Choose an available time supplied by this patient’s appointment source. The patient will be asked to confirm.</p>
    {error && <p role="alert" className="error">{error}</p>}{!state && !error && <p>Loading availability…</p>}
    {state && <>{state.scheduled_at && <p>Current appointment: <strong>{when(state.scheduled_at)}</strong></p>}{state.blocked ? <><p role="status">{state.blocked}</p>
      {(state.can_review || state.review_status === "failed") && <><p>This checks the doctor’s instructions for eligible times. It does not move the appointment or send a patient message.</p><button className="primary" disabled={busy} onClick={() => void review()}>{state.review_status === "failed" ? "Retry instruction review" : "Review doctor instructions"}</button></>}
      {["running", "failed"].includes(state.review_status) && <button className="secondary" disabled={busy} onClick={() => void review(true)}>Cancel instruction review</button>}
    </> : <form onSubmit={e => { e.preventDefault(); void change(); }}>
      <label>Available appointment<select required value={slot} onChange={e => setSlot(e.target.value)}><option value="">Select a time</option>{state.slots.map(s => <option key={s.id} value={s.id}>{when(s.starts_at)} · {s.doctor}</option>)}</select></label>
      {!state.slots.length && <p>No eligible alternatives are currently available.</p>}{state.more_available_slots && <p>Showing the first available source options.</p>}
      <label>Reason (optional, staff audit only)<textarea maxLength={600} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <p>The patient message uses the verified appointment time. This note is not sent as clinical guidance.</p>
      <button className="primary" disabled={busy || !slot}>Confirm change and notify patient</button>
    </form>}
    {!!state.review_requirements?.length && <details open={!!state.blocked || !state.slots.length}><summary>Doctor instructions checked</summary><ul>{state.review_requirements.map((r, i) => <li key={`${r.instruction_id}-${i}`}><p>{r.quote}</p>{r.effect === "DATE_WINDOW" && <p>Eligible dates: {r.date_from ? `from ${r.date_from}` : ""} {r.date_to ? `on or before ${r.date_to}` : ""} (Singapore time).</p>}{r.effect === "CLINIC_REVIEW" && <p>Clinic review required.</p>}{state.patient_checks?.some(c => c.instruction_id === r.instruction_id && c.condition_quote === r.condition_quote) && <p>Patient check still needed: {r.condition_quote}</p>}</li>)}</ul></details>}
    <button className="text-button" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh availability and delivery status</button>
    {state.changes.map(c => <article key={c.id}><h3>{c.status === "committed" ? "Appointment updated" : c.status === "rejected" ? "Change rejected by source" : c.status === "superseded" ? "Appointment changed again; old notification withheld" : "Source result pending"}</h3>{c.receipt && <p>{when(c.receipt.old_scheduled_at)} → {when(c.receipt.scheduled_at)}</p>}<p>Patient notification: {c.notification_status === "simulated" ? "Saved in demo conversation; no phone delivery receipt" : c.notification_status}</p><p>Recorded by {c.actor_name} · {when(c.created_at)}</p>{c.reason && <p>Staff reason: {c.reason}</p>}{(c.status === "pending" || ["pending", "failed", "undelivered"].includes(c.notification_status)) && <button disabled={busy} onClick={() => void retry(c.id)}>Retry pending change / notification</button>}</article>)}</>}
  </>}</section>;
}
