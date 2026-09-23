import { useEffect, useState } from "react";
import { api } from "./client";

type Notes = { source: string; instructions: { instruction_id: string; approved_text: string }[] };

export function DoctorNotes({ caseId, version }: { caseId: string; version: number }) {
  const [notes, setNotes] = useState<Notes | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setNotes(null); setError("");
    void api<Notes>(`/api/cases/${caseId}/doctor-notes`, { signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setNotes(value); })
      .catch(e => { if (!abort.signal.aborted) setError((e as Error).message); });
    return () => abort.abort();
  }, [caseId, version, refresh]);
  return <section className="panel staff-panel" aria-label="Doctor notes">
    <div className="section-heading"><h2>Doctor notes</h2><button className="secondary" onClick={() => setRefresh(n => n + 1)}>Refresh notes</button></div>
    {error ? <p role="alert" className="error">{error}</p> : !notes ? <p role="status">Loading doctor notes…</p> : <>
      <p className="muted">{notes.source} · approved instructions for this follow-up</p>
      {notes.instructions.length ? notes.instructions.map(note => <p key={note.instruction_id} style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{note.approved_text}</p>) : <p>No approved doctor notes are available for this follow-up.</p>}
    </>}
  </section>;
}
