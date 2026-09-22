import { useState } from "react";
import { api, mutationHeaders } from "./client";

export type ManagedFollowup = {
  version: number;
  followup_status: string;
  appointment_at: string | null;
  options: { id: string; starts_at: string; ends_at: string; doctor: string }[];
};
const displayTime = (value: string) => new Date(value).toLocaleString("en-SG", { timeZone: "Asia/Singapore" });

export function BridgeFollowupOptions({ caseId, state, reload }: {
  caseId: string; state: ManagedFollowup; reload: () => Promise<void>;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [doctor, setDoctor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function change(path: string, body: unknown) {
    setBusy(true); setError("");
    try {
      await api(`/api/bridge/cases/${caseId}/options${path}`, {
        method: "POST", headers: mutationHeaders(), body: JSON.stringify(body),
      });
      await reload();
      if (!path) { setStart(""); setEnd(""); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="sim-conversation" aria-label="Forget-lah managed follow-up">
    <h3>Follow-up managed in Forget-lah</h3>
    <p>Status: {state.followup_status.replaceAll("_", " ")}{state.appointment_at && <> · Appointment: {displayTime(state.appointment_at)} SGT</>}</p>
    <details open>
      <summary>Available slots for this patient</summary>
      <p>Enter times the clinic has reserved for this patient. The agent can offer these options and save the patient’s choice in Forget-lah after checking the doctor’s instructions.</p>
      <p className="small">Adding an option does not move an appointment or send a message. Times below use Singapore time.</p>
      {state.options.map(slot => <p key={slot.id}>
        {displayTime(slot.starts_at)} SGT · {slot.doctor}{" "}
        <button className="secondary" disabled={busy} onClick={() => void change(`/${slot.id}/withdraw`, { expected_version: state.version })}>Withdraw option</button>
      </p>)}
      {!state.options.length && <p>No alternative times supplied yet.</p>}
      <form onSubmit={e => {
        e.preventDefault();
        void change("", { expected_version: state.version, starts_at: `${start}:00+08:00`, ends_at: `${end}:00+08:00`, doctor });
      }}>
        <label>Start (SGT)<input type="datetime-local" required value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>End (SGT)<input type="datetime-local" required value={end} onChange={e => setEnd(e.target.value)} /></label>
        <label>Doctor or clinic team<input required maxLength={80} value={doctor} onChange={e => setDoctor(e.target.value)} /></label>
        <button disabled={busy}>Add available slot</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </details>
  </section>;
}
