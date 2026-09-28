import { DashboardRecords } from "./DashboardRecords";
import { useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";
import { PatientPreferences } from "./PatientPreferences";
import { BridgeFollowupOptions, type ManagedFollowup } from "./BridgeFollowupOptions";
import { ChangeAppointment } from "./ChangeAppointment";
import { SecurityAudit } from "./SecurityAudit";
import { DoctorNotes } from "./DoctorNotes";
import { BridgeIntake } from "./BridgeIntake";
import { PatientMessage, type StaffTranslation } from "./PatientMessage";
import type { Preferences } from "./PatientPreferences";

type Case = { id: string; patient: string; specialty: string; trigger: string; agent_status: string | null };
type Detail = {
  staff_translation_available: boolean;
  bridge: ManagedFollowup | null;
  case_version: number;
  preferences: Preferences;
  run: { id: string; status: string; active_role: string } | null;
  plan?: { attendance: string; instructions: string; preparation: string; learned: string[]; next_action: string };
  patient_simulator: { messages: { id: string; body: string; original_body?: string; created_at: string; delivery_status?: string | null }[] };
  events: { id: string; kind: string; content: string; staff_translation?: StaffTranslation; created_at: string; channel?: string }[];
  handoff: { reason_code: string; risk: string; accepted: boolean; owner: string | null; staff_task_status: string;
    callback?: { question: string; status: string; resolution?: string } | null;
    clinical_review?: { reply_event_id?: string; patient_message: string; status: string; resolution?: string } | null } | null;
};
const label = (value: string) => value.replaceAll("_", " ").toLowerCase();
const reason = (value: string) => ({ UPCOMING: "Upcoming visit", MISSED: "Missed appointment", RECALL_OVERDUE: "Overdue recall" }[value] ?? label(value));
const status = (value: string | null) => ({ waiting: "Waiting for response", escalated: "Staff attention", paused: "Review paused", completed: "Completed", running: "Review in progress", queued: "Review queued" }[value ?? ""] ?? "Preparing follow-up");
const date = (value: string) => new Date(value).toLocaleString("en-SG", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore" }) + " SGT";

export function StaffWorkspace({ onLogout }: { onLogout: () => void }) {
  const [section, setSection] = useState("journey");
  const [tab, setTab] = useState("overview");
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState<Case | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolution, setResolution] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController(); let loading = false;
    async function load() {
      if (loading) return; loading = true;
      try {
        const rows = await api<Case[]>("/api/cases", { signal: abort.signal });
        const next = selected ? await api<Detail>(`/api/cases/${selected.id}/agent`, { signal: abort.signal }) : null;
        if (!abort.signal.aborted) { setCases(rows); setDetail(next); setError(""); }
      } catch (e) { if (!abort.signal.aborted) { setError((e as Error).message); setDetail(null); setCases([]); } }
      finally { loading = false; }
    }
    setDetail(null); void load(); const timer = window.setInterval(() => void load(), 5000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [selected?.id, refresh]);
  async function act(kind: string) {
    if (!selected || !detail?.run || busy) return;
    setBusy(true);
    try {
      await api(`/api/cases/${selected.id}/agent/events`, { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ expected_case_version: detail.case_version, run_id: detail.run.id, kind, content: resolution }) });
      setResolution(""); setRefresh(n => n + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const attention = cases.filter(c => ["escalated", "paused"].includes(c.agent_status ?? ""));
  const conversation = detail ? [
    ...detail.patient_simulator.messages.map(m => ({ ...m, text: m.body, english: m.original_body, staff_translation: undefined as StaffTranslation | undefined, sender: m.delivery_status ? `Clinic · WhatsApp test · ${m.delivery_status}` : "Clinic · simulated", incoming: false })),
    ...detail.events.filter(e => e.kind === "demo_reply").map(e => ({ ...e, text: e.content, english: undefined as string | undefined, sender: e.channel === "whatsapp_test" ? "Patient · WhatsApp test phone" : "Patient · simulated", incoming: true })),
  ].sort((a, b) => a.created_at.localeCompare(b.created_at)) : [];
  return <div className="workspace staff-workspace">
    <aside className="sidebar">
      <div className="wordmark">forget-lah<span>●</span></div><p className="sidebar-label">STAFF WORKSPACE</p>
      <nav aria-label="Staff navigation">{[["overview", "Overview"], ["attention", "Needs attention"], ["bridge", "Intelligent intake"], ["statistics", "Statistics"]].map(([key, title]) => <button key={key} className={tab === key ? "staff-nav active" : "staff-nav"} onClick={() => { setTab(key); setSelected(null); }}>{title}</button>)}</nav>
      <div className="sidebar-bottom"><span className="tag">SYNTHETIC DEMO</span><p>Patient follow-up, with a clear next step.</p><a className="sim-nav" href="#/developer">Developer testing ↗</a><button className="text-button" onClick={onLogout}>Sign out</button></div>
    </aside>
    <main className="content">
      <header><div><p className="eyebrow">CARE THAT CONTINUES</p><h1>{selected ? selected.patient : tab === "statistics" ? "Follow-up at a glance" : tab === "attention" ? "Your attention matters" : tab === "bridge" ? "Bring any follow-up export" : "A clear next step for everyone"}</h1><p className="muted">{selected ? `${selected.specialty} · ${reason(selected.trigger)}` : tab === "bridge" ? "Forget-lah understands legacy clinic exports without forcing a fixed template." : "Keep conversations moving and give each open concern an owner."}</p></div><button className="secondary" onClick={() => setRefresh(n => n + 1)}>Refresh</button></header>
      <p className="small">Team demonstration · synthetic patient records and clinic appointments.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!selected && tab === "bridge" && <BridgeIntake onImported={() => setRefresh(n => n + 1)} />}
      {!selected && tab !== "bridge" && <>
        <section className="metrics staff-metrics" aria-label="Current case totals">{[["Open follow-ups", cases.filter(c => c.agent_status !== "completed").length], ["Staff review", attention.length], ["Waiting for response", cases.filter(c => c.agent_status === "waiting").length], ["Completed", cases.filter(c => c.agent_status === "completed").length]].map(([title, count]) => <article className="metric" key={title}><span>{title}</span><strong>{count}</strong><small>Current cases</small></article>)}</section>
        {tab === "statistics" ? <section className="panel staff-panel"><h2>Case mix</h2><p className="muted">Live counts of current cases. These are not historical response rates or clinical outcomes.</p>{["UPCOMING", "RECALL_OVERDUE", "MISSED"].map(trigger => <div className="staff-stat" key={trigger}><span>{reason(trigger)}</span><meter min={0} max={Math.max(cases.length, 1)} value={cases.filter(c => c.trigger === trigger).length} /><strong>{cases.filter(c => c.trigger === trigger).length}</strong></div>)}</section> : <DashboardRecords refresh={refresh} attentionOnly={tab === "attention"} onOpen={c => { setSelected(c); setResolution(""); setSection("journey"); }} />}
      </>}
      {selected && <div className="followup-workspace"><button className="text-button" onClick={() => setSelected(null)}>← Back to follow-ups</button>{!detail && !error && <p role="status">Loading follow-up…</p>}{detail && <>
        <section className="panel staff-panel"><span className="pill">{status(detail.run?.status ?? null)}</span><h2>Follow-up summary</h2>{detail.run && ["queued", "running"].includes(detail.run.status) && <p role="status">{detail.run.active_role === "engagement" ? "Reviewing appointment details…" : detail.run.active_role === "preparation" ? "Reviewing clinic instructions…" : "Reviewing the reply and next steps…"}</p>}{detail.plan ? <><p><strong>Next step:</strong> {detail.plan.next_action}</p><div className="staff-readiness"><p><strong>Attendance</strong>{detail.plan.attendance}</p><p><strong>Preparation</strong>{detail.plan.preparation}</p><p><strong>Clinic instructions</strong>{detail.plan.instructions}</p></div>{detail.plan.learned.length > 0 && <p><strong>Patient told us:</strong> {detail.plan.learned.join("; ")}</p>}</> : <p>The follow-up is being prepared.</p>}{detail.run?.status === "paused" && <p>The automatic review needs technical attention. Open Developer testing to inspect and retry it.</p>}</section>
        {detail.handoff && <section className={`handoff ${detail.handoff.risk === "RED" ? "handoff-red" : ""}`}><p className="eyebrow">{detail.handoff.risk === "RED" ? "CLINICAL REVIEW" : "STAFF FOLLOW-UP"}</p><h2>{label(detail.handoff.reason_code)}</h2><p>{detail.handoff.staff_task_status === "resolved" ? "Resolved" : detail.handoff.accepted ? `Owned by ${detail.handoff.owner}` : "A staff member needs to take ownership."}</p>{detail.handoff.callback && <p><strong>Patient question:</strong> {detail.handoff.callback.question}</p>}{detail.handoff.clinical_review && <PatientMessage original={detail.handoff.clinical_review.patient_message} translation={detail.events.find(e => e.id === detail.handoff?.clinical_review?.reply_event_id)?.staff_translation} caseId={selected.id} eventId={detail.handoff.clinical_review.reply_event_id} enabled={detail.staff_translation_available} />}{!detail.handoff.accepted && <button className="primary" disabled={busy} onClick={() => void act("accept_handoff")}>Accept follow-up as me</button>}{detail.handoff.accepted && detail.handoff.staff_task_status !== "resolved" && (detail.handoff.callback || detail.handoff.clinical_review) && <form onSubmit={e => { e.preventDefault(); void act(detail.handoff?.clinical_review ? "resolve_clinical" : "resolve_callback"); }}><label htmlFor="staff-resolution">Record the contact outcome</label><textarea id="staff-resolution" value={resolution} onChange={e => setResolution(e.target.value)} required maxLength={600} /><button className="primary" disabled={busy || !resolution.trim()}>Save outcome and resolve</button><p className="small">Only the owner can resolve this task. Recording an outcome does not place a call or send a message.</p></form>}{(detail.handoff.callback?.resolution || detail.handoff.clinical_review?.resolution) && <p><strong>Outcome:</strong> {detail.handoff.callback?.resolution ?? detail.handoff.clinical_review?.resolution}</p>}</section>}
        <nav className="followup-sections" aria-label="Follow-up sections">{[["journey", "Case journey"], ["instructions", "Clinic instructions & preferences"], ["appointment", "Appointment & options"], ["audit", "Security & audit"]].map(([key, title]) => <button key={key} aria-pressed={section === key} onClick={() => setSection(key)}>{title}</button>)}</nav>
        <div className="followup-detail">
        {section === "journey" && <>
        <section className="panel staff-panel"><h2>Case journey</h2><p className="muted">The current review’s conversation and staff actions, in order. Earlier reviews remain in Developer testing.</p><ol className="staff-conversation">{[...conversation, ...detail.events.filter(e => ["accept_handoff", "resolve_callback", "resolve_clinical"].includes(e.kind)).map(e => ({...e, text: e.content || "A staff member accepted ownership of this follow-up.", sender: "Staff action", incoming: false, english: undefined as string | undefined}))].sort((a,b) => a.created_at.localeCompare(b.created_at)).map(m => <li key={m.id} className={m.incoming ? "incoming" : ""}><strong>{m.sender}</strong><time>{date(m.created_at)}</time><>{m.incoming ? <PatientMessage original={m.text} translation={m.staff_translation} caseId={selected.id} eventId={m.id} enabled={detail.staff_translation_available} /> : <><p>{m.text}</p>{m.english && m.english !== m.text && <div className="staff-translation" lang="en"><strong>English source message</strong><p>{m.english}</p></div>}</>}</></li>)}</ol>{!conversation.length && <p>No conversation has been recorded yet.</p>}</section>
        </>}
        {section === "instructions" && <>
<DoctorNotes key={`notes-${selected.id}`} caseId={selected.id} version={detail.case_version} />
        <PatientPreferences caseId={selected.id} version={detail.case_version} preferences={detail.preferences} onSaved={async () => setRefresh(n => n + 1)} disabled={busy || ["queued", "running"].includes(detail.run?.status ?? "")} />
        </>}
        {section === "appointment" && <>
        <ChangeAppointment key={selected.id} caseId={selected.id} version={detail.case_version} reload={() => setRefresh(n => n + 1)} />
        {detail.bridge && <BridgeFollowupOptions key={selected.id} caseId={selected.id} state={detail.bridge} reload={async () => setRefresh(n => n + 1)} />}
        </>}
        {section === "audit" && <>
        <SecurityAudit key={`audit-${selected.id}`} caseId={selected.id} />
        </>}
        </div>
      </>}</div>}
    </main>
  </div>;
}
