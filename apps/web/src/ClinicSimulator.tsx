import { useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";

type Specialty = "dental" | "myopia" | "antenatal";
type Episode = {
  source_episode_ref: string; patient_id: string; display_alias: string;
  specialty: Specialty; record_type: "appointment" | "recall";
  source_status: string; scheduled_at: string | null; due_at: string | null;
  has_future_booking: boolean; doctor_note: string; note_approved: boolean;
  prerequisite: string; version: number;
  attendance_confirmation?: { confirmed_at: string; status: string; synthetic: boolean } | null;
};
type Slot = { id: string; specialty: Specialty; starts_at: string; ends_at: string; doctor: string; available: boolean; version: number };
type Snapshot = { episodes: Episode[]; slots: Slot[] };
type CaseLink = { id: string; source_episode_ref: string; agent_status: string | null };
type EpisodeForm = Omit<Episode, "patient_id"> & { request_id: string };
type SlotForm = Slot & { request_id: string };
const specialties: Specialty[] = ["dental", "myopia", "antenatal"];
const labels = { dental: "Dental", myopia: "Myopia", antenatal: "Antenatal" };
const sgInput = (value: string | null) => value ? new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16) : "";
const utc = (value: string | null) => value ? new Date(`${value}:00+08:00`).toISOString() : null;
const dateAfter = (days: number) => new Date(Date.now() + 8 * 3600000 + days * 86400000).toISOString().slice(0, 10) + "T10:00";
const displayDate = (value: string | null) => value ? new Date(value).toLocaleString("en-SG", { timeZone: "Asia/Singapore", dateStyle: "medium", timeStyle: "short" }) : "—";
const blankEpisode = (): EpisodeForm => ({ request_id: crypto.randomUUID(), source_episode_ref: "", display_alias: "Test patient", specialty: "dental", record_type: "appointment", source_status: "scheduled", scheduled_at: dateAfter(2), due_at: "", has_future_booking: false, doctor_note: "", note_approved: false, prerequisite: "NOT_APPLICABLE", version: 0 });
const blankSlot = (): SlotForm => ({ request_id: crypto.randomUUID(), id: "", specialty: "dental", starts_at: dateAfter(3), ends_at: dateAfter(3).replace("10:00", "10:30"), doctor: "Demo doctor", available: true, version: 0 });

export function ClinicSimulator({ onBack }: { onBack: () => void }) {
  const [snapshot, setSnapshot] = useState<Snapshot>({ episodes: [], slots: [] });
  const [cases, setCases] = useState<CaseLink[]>([]);
  const [episode, setEpisode] = useState<EpisodeForm>(blankEpisode);
  const [slot, setSlot] = useState<SlotForm>(blankSlot);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [slotFilter, setSlotFilter] = useState("all");
  function selectEpisode(row: Episode) {
    setEpisode({ ...row, request_id: crypto.randomUUID(), scheduled_at: sgInput(row.scheduled_at), due_at: sgInput(row.due_at) });
    setMessage("");
  }
  async function load(selectRef?: string) {
    const [data, links] = await Promise.all([api<Snapshot>("/api/simulator"), api<CaseLink[]>("/api/cases")]);
    setSnapshot(data); setCases(links); setReady(true);
    if (selectRef) { const row = data.episodes.find((e) => e.source_episode_ref === selectRef); if (row) selectEpisode(row); }
  }
  useEffect(() => { void load().catch((e) => setError(e.message)); }, []);
  async function reload() {
    setBusy(true); setError(""); setMessage("");
    try { await load(episode.source_episode_ref); setSlot(blankSlot()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function preset(kind: "upcoming" | "missed" | "overdue") {
    setEpisode((e) => ({ ...e, record_type: kind === "overdue" ? "recall" : "appointment", source_status: kind === "overdue" ? "due" : kind === "missed" ? "no_show" : "scheduled", scheduled_at: kind === "overdue" ? "" : dateAfter(kind === "missed" ? -1 : 2), due_at: kind === "overdue" ? dateAfter(-14) : "", has_future_booking: false }));
  }
  async function saveEpisode(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const fields = { specialty: episode.specialty, record_type: episode.record_type, source_status: episode.source_status, scheduled_at: utc(episode.scheduled_at), due_at: utc(episode.due_at), has_future_booking: episode.has_future_booking, doctor_note: episode.doctor_note, note_approved: episode.note_approved, prerequisite: episode.prerequisite };
    try {
      const result = await api<{ source_episode_ref: string }>(episode.source_episode_ref ? `/api/simulator/episodes/${encodeURIComponent(episode.source_episode_ref)}` : "/api/simulator/episodes", { method: episode.source_episode_ref ? "PUT" : "POST", headers: mutationHeaders(), body: JSON.stringify(episode.source_episode_ref ? { ...fields, expected_version: episode.version } : { ...fields, request_id: episode.request_id, display_alias: episode.display_alias }) });
      await load(result.source_episode_ref);
      setMessage("Saved in the clinic simulator. New eligible episodes appear in forget-lah after the worker's next scan (usually within 10 seconds). Existing case history is preserved.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveSlot(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const fields = { specialty: slot.specialty, starts_at: utc(slot.starts_at), ends_at: utc(slot.ends_at), doctor: slot.doctor, available: slot.available };
    try {
      await api(slot.id ? `/api/simulator/slots/${slot.id}` : "/api/simulator/slots", { method: slot.id ? "PUT" : "POST", headers: mutationHeaders(), body: JSON.stringify(slot.id ? { ...fields, expected_version: slot.version } : { ...fields, request_id: slot.request_id }) });
      await load(); setSlot(blankSlot());
      setMessage("Slot saved. Future available slots appear on the next clinic-context read for that specialty. No booking was made.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const caseLink = cases.find((c) => c.source_episode_ref === episode.source_episode_ref);
  return <main className="sim-page">
    <header className="sim-header"><div><button className="text-button" onClick={onBack}>← Back to forget-lah</button><p className="eyebrow">EXTERNAL TEST SYSTEM · SYNTHETIC DATA ONLY</p><h1>Clinic simulator</h1><p>Appointment schedules, available slots and patient notes in one place.</p></div><button className="secondary" onClick={reload} disabled={busy}>Reload saved data</button></header>
    <div className="journey-note"><strong>Build a scenario, then watch forget-lah respond.</strong><p>1. Add slots and notes. 2. Save a new test episode. 3. Return to forget-lah and refresh cases.</p><p>All dates use Singapore time (UTC+8). Eligible episodes start reviews automatically and may use the configured Claude API. This simulator does not send messages or book appointments.</p></div>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="sim-success" role="status">{message}</p>}
    {episode.attendance_confirmation && <p className="sim-success">Patient confirmed attendance · simulated · {displayDate(episode.attendance_confirmation.confirmed_at)}. The appointment remains scheduled; actual attendance has not been recorded.</p>}
    {!ready && !error && <p role="status">Loading simulator…</p>}
    <fieldset disabled={busy || !ready} className="sim-fieldset"><div className="sim-grid">
      <section className="panel sim-section"><div className="sim-heading"><div><p className="eyebrow">PATIENT RECORD + SCHEDULE</p><h2>{episode.source_episode_ref ? "Edit test episode" : "New test episode"}</h2></div><button className="secondary" onClick={() => { setEpisode(blankEpisode()); setMessage(""); }}>New episode</button></div>
        <label className="sim-label">Open a saved episode<select value={episode.source_episode_ref} onChange={(e) => { const row = snapshot.episodes.find((r) => r.source_episode_ref === e.target.value); if (row) selectEpisode(row); else setEpisode(blankEpisode()); }}><option value="">New test episode</option>{snapshot.episodes.map((e) => <option key={e.source_episode_ref} value={e.source_episode_ref}>{e.display_alias} · {labels[e.specialty]} · {e.source_episode_ref.slice(-8)}</option>)}</select></label>
        {episode.source_episode_ref && <div className="sim-record"><small>{episode.source_episode_ref} · revision {episode.version}</small><p>{caseLink ? `Existing review: ${caseLink.agent_status ?? "preparing"}.` : "No case loaded for this episode. Reload after the worker scans."} Editing does not restart an existing review.</p>{caseLink && <a href={`#/cases/${caseLink.id}/journey`}>Open saved case journey →</a>}<button className="text-button" onClick={() => { setEpisode((e) => ({ ...e, source_episode_ref: "", version: 0, request_id: crypto.randomUUID() })); setMessage("Copied into a fresh synthetic patient episode. Adjust dates and save to begin a new journey."); }}>Copy into a new test episode</button></div>}
        <form onSubmit={saveEpisode}>
          <label className="sim-label">Patient alias<input value={episode.display_alias} maxLength={90} required disabled={!!episode.source_episode_ref} onChange={(e) => setEpisode({ ...episode, display_alias: e.target.value })} /></label>
          <div className="sim-two"><label className="sim-label">Specialty<select value={episode.specialty} onChange={(e) => setEpisode({ ...episode, specialty: e.target.value as Specialty })}>{specialties.map((s) => <option key={s} value={s}>{labels[s]}</option>)}</select></label><label className="sim-label">Record type<select value={episode.record_type} onChange={(e) => preset(e.target.value === "recall" ? "overdue" : "upcoming")}><option value="appointment">Appointment</option><option value="recall">Routine recall</option></select></label></div>
          <div className="sim-presets" aria-label="Schedule examples"><span>Quick examples:</span><button type="button" className="secondary" onClick={() => preset("upcoming")}>Upcoming</button><button type="button" className="secondary" onClick={() => preset("missed")}>Missed</button><button type="button" className="secondary" onClick={() => preset("overdue")}>Overdue recall</button></div>
          <div className="sim-two"><label className="sim-label">Status<select value={episode.source_status} onChange={(e) => setEpisode({ ...episode, source_status: e.target.value })}>{(episode.record_type === "recall" ? ["due", "cancelled", "completed"] : ["scheduled", "no_show", "cancelled", "completed"]).map((s) => <option key={s} value={s}>{s === "no_show" ? "Missed (no-show)" : s[0].toUpperCase() + s.slice(1)}</option>)}</select></label><label className="sim-label">{episode.record_type === "recall" ? "Recall due" : "Appointment time"} (SGT)<input type="datetime-local" required value={(episode.record_type === "recall" ? episode.due_at : episode.scheduled_at) ?? ""} onChange={(e) => setEpisode({ ...episode, [episode.record_type === "recall" ? "due_at" : "scheduled_at"]: e.target.value })} /></label></div>
          {episode.record_type === "recall" && <label className="sim-check"><input type="checkbox" checked={episode.has_future_booking} onChange={(e) => setEpisode({ ...episode, has_future_booking: e.target.checked })} /> Already has a future booking (suppresses a new overdue recall case)</label>}
          <label className="sim-label">Doctor note / preparation instruction<textarea rows={4} maxLength={400} value={episode.doctor_note} placeholder="For example: Bring your current spectacles." onChange={(e) => setEpisode({ ...episode, doctor_note: e.target.value })} /></label>
          <label className="sim-check"><input type="checkbox" checked={episode.note_approved} onChange={(e) => setEpisode({ ...episode, note_approved: e.target.checked })} /> Mark this text approved for the synthetic demonstration</label><p className="small">Only approved text is returned by the preparation-instructions API. This checkbox is a test fixture, not clinical approval.</p>
          <label className="sim-label">Prerequisite status<select value={episode.prerequisite} onChange={(e) => setEpisode({ ...episode, prerequisite: e.target.value })}><option value="NOT_APPLICABLE">No prerequisite to check</option><option value="STAFF_REVIEW_REQUIRED">Clinic staff must review a prerequisite</option></select></label>
          <button className="primary">{episode.source_episode_ref ? "Save episode changes" : "Save new test episode"}</button>
        </form>
      </section>
      <section className="panel sim-section"><div className="sim-heading"><div><p className="eyebrow">APPOINTMENT AVAILABILITY</p><h2>{slot.id ? "Edit slot" : "Add available slot"}</h2></div>{slot.id && <button className="secondary" onClick={() => setSlot(blankSlot())}>New slot</button>}</div><p>Slots belong to the specialty. A clinic-context read returns up to 10 future available slots for that specialty.</p>
        <form onSubmit={saveSlot}>
          <div className="sim-two"><label className="sim-label">Slot specialty<select value={slot.specialty} onChange={(e) => setSlot({ ...slot, specialty: e.target.value as Specialty })}>{specialties.map((s) => <option key={s} value={s}>{labels[s]}</option>)}</select></label><label className="sim-label">Doctor / resource label<input required maxLength={80} value={slot.doctor} onChange={(e) => setSlot({ ...slot, doctor: e.target.value })} /></label></div>
          <label className="sim-label">Slot start (SGT)<input type="datetime-local" required value={slot.starts_at} onChange={(e) => setSlot({ ...slot, starts_at: e.target.value })} /></label><label className="sim-label">Slot end (SGT)<input type="datetime-local" required value={slot.ends_at} min={slot.starts_at} onChange={(e) => setSlot({ ...slot, ends_at: e.target.value })} /></label>
          <label className="sim-check"><input type="checkbox" checked={slot.available} onChange={(e) => setSlot({ ...slot, available: e.target.checked })} /> Available for testing</label><button className="primary">{slot.id ? "Save slot changes" : "Add slot"}</button>
        </form>
        <div className="sim-list"><label className="sim-label">Saved slots<select value={slotFilter} onChange={(e) => setSlotFilter(e.target.value)}><option value="all">All specialties</option>{specialties.map((s) => <option key={s} value={s}>{labels[s]}</option>)}</select></label>
          {snapshot.slots.filter((s) => slotFilter === "all" || s.specialty === slotFilter).map((s) => <article className="sim-slot" key={s.id}><div><strong>{labels[s.specialty]} · {s.doctor}</strong><p>{displayDate(s.starts_at)} – {displayDate(s.ends_at)} SGT</p><span className="pill">{!s.available ? "Unavailable" : new Date(s.starts_at) < new Date() ? "Past slot" : "Available"}</span></div><button className="secondary" onClick={() => { setSlot({ ...s, request_id: crypto.randomUUID(), starts_at: sgInput(s.starts_at), ends_at: sgInput(s.ends_at) }); setMessage(""); }}>Edit<span className="sr-only"> slot for {s.doctor} at {displayDate(s.starts_at)}</span></button></article>)}
          {!snapshot.slots.length && <p className="empty">No slots yet. Add a slot above.</p>}
        </div>
      </section>
    </div></fieldset>
    <p className="sim-footnote">The simulator stores source records separately from forget-lah. Changes appear on the next source read; previously saved traces retain the evidence used at that time. A new test episode creates a separate synthetic patient record and case.</p>
  </main>;
}
