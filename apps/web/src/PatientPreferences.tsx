import { useState } from "react";
import { api, mutationHeaders } from "./client";

type Memory = { id: string; key: string; value: string | number[] | string[]; scope: string; status: string; quote: string };
export type Preferences = { records?: Memory[]; earliest_minute?: number | null; latest_minute?: number | null; updated_at?: string; excluded_minutes?: number[]; reported_concern?: { quote: string } };
const clock = (minute: number | null | undefined) => minute == null ? "" : `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const minutes = (value: string) => value ? Number(value.split(":")[0]) * 60 + Number(value.split(":")[1]) : null;

export function PatientPreferences({ caseId, version, preferences, onSaved, disabled }: {
  caseId: string; version: number; preferences: Preferences; onSaved: () => Promise<void>; disabled: boolean;
}) {
  const [from, setFrom] = useState(clock(preferences.earliest_minute));
  const [until, setUntil] = useState(clock(preferences.latest_minute));
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(clear: boolean) {
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/preferences`, {
        method: "POST", headers: mutationHeaders(),
        body: JSON.stringify({ expected_case_version: version, consent, clear, earliest_minute: minutes(from), latest_minute: minutes(until) }),
      });
      await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove(record: Memory) {
    const resume = record.key === "contact_permission";
    if (resume && !window.confirm("Has the simulated patient explicitly agreed to resume automated reminders?")) return;
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/preferences/${record.id}/remove`, {
        method: "POST", headers: mutationHeaders(),
        body: JSON.stringify({ expected_case_version: version, resume_contact: resume }),
      });
      await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <details className="agent-actions">
    <summary>Patient preferences and concerns</summary>
    <p>Optional Singapore appointment times. A request for this visit overrides these preferences. Changing or forgetting them does not change any booking.</p>
    <p className="small">Synthetic conversation only. Recurring scheduling restrictions can be saved from the patient’s statement. This is editable memory, not model training.</p>
    {!!preferences.excluded_minutes?.length && <p><strong>Times to avoid:</strong> {preferences.excluded_minutes.map(clock).join(", ")} SGT</p>}
    {preferences.reported_concern && <p><strong>Reported concern:</strong> {preferences.reported_concern.quote}</p>}
    {preferences.records?.map(record => <div className="agent-actions" key={record.id}>
      <strong>{record.key.replaceAll("_", " ")}</strong>: {record.key === "excluded_weekdays" && Array.isArray(record.value)
        ? record.value.map(day => ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][Number(day)]).join(", ")
        : record.key === "excluded_minutes" && Array.isArray(record.value) ? record.value.map(v => clock(Number(v))).join(", ") : String(record.value)}
      <p>{record.scope === "future" ? "Current and future follow-ups" : "This visit only"} · {record.status === "pending" ? "Needs clarification" : "Active"}</p>
      <p>Patient said: “{record.quote}”</p>
      <button className="secondary" disabled={disabled || busy} onClick={() => void remove(record)}>{record.key === "contact_permission" ? "Resume reminders with patient agreement" : "Remove this preference"}</button>
    </div>)}
    <label>Appointments from <input aria-label="Preferred start time" type="time" value={from} onChange={e => setFrom(e.target.value)} /></label>
    <label>Appointments until <input aria-label="Preferred end time" type="time" value={until} onChange={e => setUntil(e.target.value)} /></label>
    <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} /> In this simulation, the patient agrees to remember these times for future follow-ups.</label>
    <button className="secondary" disabled={disabled || busy || !consent} onClick={() => void save(false)}>Remember preferences</button>
    <button className="secondary" disabled={disabled || busy || !preferences.updated_at} onClick={() => void save(true)}>Forget saved time window</button>
    {preferences.updated_at && <p className="small">Last updated on {new Date(preferences.updated_at).toLocaleString()}.</p>}
    {error && <p role="alert" className="error">{error}</p>}
  </details>;
}
