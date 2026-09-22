import { useState } from "react";
import { api, mutationHeaders } from "./client";

export function DemoReset({ caseIds, onReset }: { caseIds: string[]; onReset: () => Promise<void> }) {
  const [includeIntake, setIncludeIntake] = useState(true);
  const [intakeIds, setIntakeIds] = useState<string[]>([]);
  const [batchIds, setBatchIds] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [expectedIds, setExpectedIds] = useState<string[]>([]);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function reset(event: React.FormEvent) {
    event.preventDefault();
    if (busy || confirmation !== "RESET") return;
    setBusy(true); setError("");
    try {
      await api("/api/demo/reset", {
        method: "POST", headers: mutationHeaders(),
        body: JSON.stringify({ confirmation, expected_case_ids: [...expectedIds, ...(includeIntake ? intakeIds : [])], include_intake: includeIntake, expected_intake_batch_ids: includeIntake ? batchIds : [] }),
      });
      setOpen(false); setConfirmation(""); setSuccess(true);
      await onReset();
    } catch (e) {
      setError((e as Error).message);
    } finally { setBusy(false); }
  }

  return <section className="demo-reset" aria-label="Demo controls">
    {!open && <button className="secondary" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        const system = await api<{ demo_reset_case_ids: string[]; demo_reset_intake_case_ids: string[]; demo_reset_intake_batch_ids: string[] }>("/api/system");
        setExpectedIds(system.demo_reset_case_ids ?? [...caseIds]); setIntakeIds(system.demo_reset_intake_case_ids ?? []); setBatchIds(system.demo_reset_intake_batch_ids ?? []);
        setIncludeIntake(true); setConfirmation(""); setSuccess(false); setOpen(true);
      } catch (e) { setError((e as Error).message); }
      finally { setBusy(false); }
    }}>Reset demo data</button>}
    {!open && error && <p className="error" role="alert">{error}</p>}
    {success && <p role="status">Demo history was reset. {includeIntake ? "Intelligent Intake uploads, managed appointments, available slots and follow-up history were cleared. Upload your test file again to start over." : "Intelligent Intake records were kept."} Eligible simulator episodes will be reviewed automatically.</p>}
    {open && <form className="demo-reset-confirm" onSubmit={reset} aria-labelledby="demo-reset-title">
      <p className="eyebrow">SYNTHETIC DEMO ONLY</p>
      <h2 id="demo-reset-title">Start with fresh demo data?</h2>
      <p>This permanently removes simulator patients’ cases, reviews, decisions, replies and handoffs, then recreates eligible cases from the current clinic simulator records. The option below also clears Intelligent Intake uploads, imported patients, managed appointments, available slots, saved mappings and follow-up history.</p>
      <p>Simulator schedules, slots and notes are preserved, as are your login, API settings and usage accounting. New automatic reviews may call Claude. Pause any queued or processing reviews first.</p>
      <p>A connected WhatsApp test phone stays linked to the same simulator patient’s recreated cases. Connections to cleared imported patients are disconnected. New reminders are sent automatically while the WhatsApp reply window is active. A disconnected phone stays disconnected. Provider message identifiers are retained to prevent duplicate replies being replayed.</p>
      <label><input type="checkbox" checked={includeIntake} disabled={busy} onChange={e => setIncludeIntake(e.target.checked)} /> Also clear Intelligent Intake test records (upload files again after reset)</label>
      <label htmlFor="reset-confirmation">Type RESET to confirm</label>
      <input id="reset-confirmation" value={confirmation} onChange={e => setConfirmation(e.target.value)} autoComplete="off" disabled={busy} />
      <div className="agent-actions">
        <button className="danger-button" disabled={busy || confirmation !== "RESET"}>{busy ? "Resetting demo…" : "Clear history and recreate cases"}</button>
        <button className="secondary" type="button" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>}
  </section>;
}
