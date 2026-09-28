import { useEffect, useRef, useState } from "react";
import { api } from "./client";

type RecordRow = {
  key: string; patient: string; specialty: string; source: string; source_status: string;
  appointment_at: string | null; requires_attention: boolean; reason: string;
  case_id: string | null; trigger: string; agent_status: string | null;
};
type OpenCase = { id: string; patient: string; specialty: string; trigger: string; agent_status: string | null };

export function DashboardRecords({ refresh, attentionOnly, onOpen }: {
  refresh: number; attentionOnly: boolean; onOpen: (c: OpenCase) => void;
}) {
  const [data, setData] = useState<{ records: RecordRow[]; warnings: string[] } | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const selected = data?.records.find(r => r.key === selectedKey);
  useEffect(() => {
    if (selected) dialog.current?.showModal();
    else dialog.current?.close();
  }, [selected]);
  const formattedDate = (value: string | null) => value ? new Date(value).toLocaleString("en-SG", { timeZone: "Asia/Singapore", dateStyle: "medium", timeStyle: "short" }) + " SGT" : "Not provided";
  const pretty = (value: string) => value.replaceAll("_", " ");
  function guidance(r: RecordRow) {
    if (r.reason === "Past appointment — verify status") return "This appointment date has passed, but its source still says scheduled. Ask the clinic team to verify whether the patient attended, missed or cancelled the visit, and update the owning source. Forget-lah does not assume a missed visit from the date alone.";
    if (r.case_id) return "A follow-up case is available. Open it to review the conversation, current plan and any staff handoff before taking action.";
    if (r.reason === "Outside follow-up window") return "This record is saved and visible. Scheduled appointments become eligible for follow-up within seven days; recalls become eligible when due. No follow-up has started for this record.";
    return "Review the recorded status with the clinic team. A follow-up is created only when the record meets the follow-up rules.";
  }
  useEffect(() => {
    const abort = new AbortController(); let loading = false;
    async function load() {
      if (loading) return; loading = true;
      try {
        const next = await api<{ records: RecordRow[]; warnings: string[] }>("/api/dashboard/records", { signal: abort.signal });
        if (!abort.signal.aborted) { setData(next); setError(""); }
      } catch (e) { if (!abort.signal.aborted) setError((e as Error).message); }
      finally { loading = false; }
    }
    void load(); const timer = window.setInterval(() => void load(), 30000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [refresh]);
  const rows = (data?.records ?? []).filter(r => (filter === "all" || (filter === "escalated" ? r.agent_status === "escalated" : filter === "paused" ? r.agent_status === "paused" : filter === "active" ? !!r.case_id : filter === "future" ? r.reason === "Outside follow-up window" : r.source === filter))).filter(r => `${r.patient} ${r.specialty} ${r.source} ${r.reason}`.toLowerCase().includes(query.toLowerCase()));
  function cards(items: RecordRow[]) {
    return <div className="staff-case-grid record-grid">{items.map(r => <article className={`staff-case record-card ${r.requires_attention ? "record-attention" : ""}`} key={r.key}>
      <div className="record-meta"><span>{r.source}</span><span className="capitalize">{r.specialty}</span></div>
      <h3>{r.patient}</h3><p className="record-date">{formattedDate(r.appointment_at)}</p>
      <span className={`pill ${r.requires_attention ? "record-pill-attention" : ""}`}>{r.reason}</span>
      <p className="record-caption">{r.case_id ? (r.agent_status === "escalated" ? "Escalated · staff handoff" : r.agent_status === "paused" ? "Paused · review required" : "Follow-up available") : r.reason === "Past appointment — verify status" ? "Clinic status needs confirmation" : "Record saved · no follow-up started"}</p>
      <div className="record-actions"><button className="secondary" onClick={() => setSelectedKey(r.key)}>View record</button>
      {r.case_id && <button className="text-button" onClick={() => onOpen({ id: r.case_id!, patient: r.patient, specialty: r.specialty, trigger: r.trigger, agent_status: r.agent_status })}>Open follow-up →</button>}</div>
    </article>)}</div>;
  }

  const attention = rows.filter(r => attentionOnly ? ["escalated", "paused"].includes(r.agent_status ?? "") : r.requires_attention);
  return <>
    <div className="record-toolbar"><label>Find a patient or record<input type="search" placeholder="Search name, specialty or status" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Show records<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All sources and statuses</option><option value="Clinic System">Clinic System</option><option value="Intelligent Intake">Intelligent Intake</option><option value="escalated">Escalated cases</option><option value="paused">Paused reviews</option><option value="active">With a follow-up</option><option value="future">Outside follow-up window</option></select></label>
    </div>
    {error && <p className="error" role="alert">{error}{data ? " Showing the last loaded records." : ""}</p>}
    {data?.warnings.map(w => <p role="status" key={w}>{w}</p>)}
    {!data && !error && <p role="status">Loading patient records…</p>}
    {data && <>
      <section className="panel staff-panel"><div className="record-heading"><div><p className="eyebrow">PRIORITY WORKLIST</p><h2>{attentionOnly ? "Staff attention" : "Due follow-ups & staff review"}</h2></div><span className="record-count">{attention.length}</span></div>
        <p className="muted">{attentionOnly ? "Escalated cases and paused reviews requiring staff action. Routine follow-ups remain in Overview." : "Appointments within 7 days, missed visits, overdue recalls and staff-review items."}</p>
        {cards(attention)}{!attention.length && <p>No matching records require attention.</p>}
      </section>
      {!attentionOnly && <section className="panel staff-panel"><div className="record-heading"><div><p className="eyebrow">COMPLETE OVERVIEW</p><h2>All records</h2></div><span className="record-count">{rows.length}</span></div>
        <p className="muted">Every available appointment and recall, including the priority records above. Dates shown in Singapore time.</p>
        {cards(rows)}{!rows.length && <p>No matching records.</p>}
      </section>}
    </>}
    <dialog ref={dialog} className="record-dialog" aria-labelledby="record-title" onClose={() => setSelectedKey(null)}>
      {selected && <><div className="record-heading"><div><p className="eyebrow">PATIENT FOLLOW-UP RECORD</p><h2 id="record-title">{selected.patient}</h2></div><button className="secondary" autoFocus onClick={() => dialog.current?.close()} aria-label="Close record">Close ×</button></div>
        <span className="pill">{selected.reason}</span>
        <dl className="record-details"><div><dt>Appointment / recall date</dt><dd>{formattedDate(selected.appointment_at)}</dd></div><div><dt>Recorded status</dt><dd className="capitalize">{pretty(selected.source_status)}</dd></div><div><dt>Specialty</dt><dd className="capitalize">{selected.specialty}</dd></div><div><dt>Record source</dt><dd>{selected.source}</dd></div><div><dt>Follow-up</dt><dd>{selected.case_id ? pretty(selected.agent_status ?? "Preparing") : "Not started"}</dd></div></dl>
        <section className="record-next"><h3>What happens next?</h3><p>{guidance(selected)}</p></section>
        <p className="muted">{selected.source === "Clinic System" ? "The Clinic System owns this appointment. Its status must be verified and updated there." : selected.source === "Intelligent Intake" ? "This approved import is managed by Forget-lah. Contact the authorised clinic team to verify any uncertain appointment status." : "This is a saved follow-up. Current source details are not available in this overview."}</p>
        <footer className="record-dialog-footer"><p className="small">Read-only view · opening this record does not send a message or change an appointment.</p>{selected.case_id && <button className="primary" onClick={() => { dialog.current?.close(); onOpen({ id: selected.case_id!, patient: selected.patient, specialty: selected.specialty, trigger: selected.trigger, agent_status: selected.agent_status }); }}>Open follow-up →</button>}</footer>
      </>}
    </dialog>
  </>;
}
