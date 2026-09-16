import { useState } from "react";
import { api, mutationHeaders } from "./client";

export function DemoReset({ caseIds, onReset }: { caseIds: string[]; onReset: () => Promise<void> }) {
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
        body: JSON.stringify({ confirmation, expected_case_ids: expectedIds }),
      });
      setOpen(false); setConfirmation(""); setSuccess(true);
      await onReset();
    } catch (e) {
      setError((e as Error).message);
    } finally { setBusy(false); }
  }

  return <section className="demo-reset" aria-label="Demo controls">
    {!open && <button className="secondary" disabled={busy} onClick={() => {
      setExpectedIds([...caseIds]); setConfirmation(""); setError(""); setSuccess(false); setOpen(true);
    }}>Reset demo data</button>}
    {success && <p role="status">Case history was reset from the saved clinic source. Eligible episodes will be reviewed automatically.</p>}
    {open && <form className="demo-reset-confirm" onSubmit={reset} aria-labelledby="demo-reset-title">
      <p className="eyebrow">LOCAL DEMO ONLY</p>
      <h2 id="demo-reset-title">Start with fresh demo data?</h2>
      <p>This permanently removes the demo clinic’s patient references, cases, reviews, decisions, replies and handoffs, then recreates eligible cases from the current clinic simulator records.</p>
      <p>Simulator schedules, slots and notes are preserved, as are your login, API settings and usage accounting. New automatic reviews may call Claude. Pause any queued or processing reviews first.</p>
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
