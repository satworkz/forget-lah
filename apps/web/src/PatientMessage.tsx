import { useState } from "react";
import { api, mutationHeaders } from "./client";

export type StaffTranslation = { language: string; status: string; body?: string; error?: string } | null;

export function PatientMessage({ original, translation, caseId, eventId, enabled = false }: {
  original: string; translation?: StaffTranslation; caseId: string; eventId?: string; enabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function requestTranslation() {
    if (!eventId || busy) return;
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/events/${eventId}/staff-translation`, { method: "POST", headers: mutationHeaders() });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="patient-message">
    <p><strong>Original patient message</strong><br />{original}</p>
    <div className="staff-translation" lang="en">
      <strong>English translation</strong>
      {translation?.status === "ready" ? <><p>{translation.body}</p><small>Machine translated · check the original if unclear.</small></>
        : <p role="status">{busy || ["pending", "processing"].includes(translation?.status ?? "") ? "Translating… Original message remains available."
          : translation?.status === "failed" ? "Translation unavailable. Review the original message."
            : "No English translation saved yet."}</p>}
      {enabled && eventId && (!translation || translation.status === "failed") && <button type="button" className="secondary" disabled={busy} onClick={() => void requestTranslation()}>{translation ? "Retry English translation" : "Translate to English"}</button>}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  </div>;
}
