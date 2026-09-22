import { Fragment, useEffect, useState } from "react";
import { api, mutationHeaders } from "./client";

type Mapping = {
  canonical_field: string;
  source_columns: string[];
  confidence: number;
  rationale: string;
};
type RecordRow = {
  id: string;
  row_number: number;
  normalized: {
    external_ref?: string | null;
    patient_name?: string | null;
    phone?: string | null;
    appointment_at?: string | null;
    due_at?: string | null;
    record_type?: string;
    source_status?: string;
    specialty?: string;
    doctor_notes?: string | null;
    preferred_language?: string;
  };
  raw?: Record<string, string>;
  confidence: number;
  issues: string[];
  status: string;
  source_episode_ref?: string | null;
  staff_overrides?: { changes?: Record<string, { from: unknown; to: unknown }>; review_note?: string | null };
  reviewed_by?: string | null;
  reviewed_at?: string | null;
};
type Batch = {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  purpose: string;
  confidence: number;
  row_count: number;
  analysis_version: number;
  mapping: Mapping[];
  warnings: string[];
  staff_instruction?: string | null;
  records: RecordRow[];
  imported_records?: number;
  cases_created?: number;
};
type BatchSummary = Pick<Batch, "id" | "filename" | "status" | "purpose" | "confidence" | "row_count"> & { created_at: string };
type ReviewDraft = {
  external_ref: string;
  patient_name: string;
  phone: string;
  appointment_at: string;
  due_at: string;
  record_type: "appointment" | "recall";
  source_status: "scheduled" | "no_show" | "due" | "cancelled" | "completed";
  specialty: "dental" | "myopia" | "antenatal" | "general";
  doctor_notes: string;
  preferred_language: "en" | "zh" | "ms" | "ta" | "und";
  review_note: string;
};

function purpose(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}
function when(row: RecordRow) {
  const value = row.normalized.appointment_at ?? row.normalized.due_at;
  if (!value) return "Timing needs review";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function datetimeInput(value?: string | null) {
  if (!value) return "";
  return value.length >= 16 ? value.slice(0, 16) : value;
}
function reviewDraft(row: RecordRow): ReviewDraft {
  return {
    external_ref: row.normalized.external_ref ?? "",
    patient_name: row.normalized.patient_name ?? "",
    phone: row.normalized.phone ?? "",
    appointment_at: datetimeInput(row.normalized.appointment_at),
    due_at: datetimeInput(row.normalized.due_at),
    record_type: (row.normalized.record_type as ReviewDraft["record_type"]) ?? "appointment",
    source_status: (row.normalized.source_status as ReviewDraft["source_status"]) ?? "scheduled",
    specialty: (row.normalized.specialty as ReviewDraft["specialty"]) ?? "general",
    doctor_notes: row.normalized.doctor_notes ?? "",
    preferred_language: (row.normalized.preferred_language as ReviewDraft["preferred_language"]) ?? "und",
    review_note: row.staff_overrides?.review_note ?? "",
  };
}
async function fileToBase64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary);
}

export function BridgeIntake({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [recent, setRecent] = useState<BatchSummary[]>([]);
  const [instruction, setInstruction] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadRecent() {
    try { setRecent(await api<BatchSummary[]>("/api/bridge/batches")); } catch { /* main workspace surfaces auth errors */ }
  }
  useEffect(() => { void loadRecent(); }, []);

  async function analyse() {
    if (!file || busy) return;
    setBusy(true); setError(""); setMessage(""); setEditingId(null); setDraft(null);
    try {
      const content_base64 = await fileToBase64(file);
      const result = await api<Batch>("/api/bridge/analyse", {
        method: "POST", headers: mutationHeaders(), body: JSON.stringify({ filename: file.name, content_base64 }),
      });
      setBatch(result); setInstruction(""); await loadRecent();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function revise() {
    if (!batch || !instruction.trim() || busy) return;
    setBusy(true); setError(""); setMessage(""); setEditingId(null); setDraft(null);
    try {
      const result = await api<Batch>(`/api/bridge/batches/${batch.id}/revise`, {
        method: "POST", headers: mutationHeaders(), body: JSON.stringify({ instruction: instruction.trim() }),
      });
      setBatch(result); setInstruction("");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function startReview(row: RecordRow) {
    setEditingId(row.id); setDraft(reviewDraft(row)); setError(""); setMessage("");
  }

  async function saveReview(row: RecordRow) {
    if (!batch || !draft || editingId !== row.id || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<Batch>(`/api/bridge/batches/${batch.id}/records/${row.id}/review`, {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({
          ...draft,
          external_ref: draft.external_ref.trim() || null,
          patient_name: draft.patient_name.trim(),
          phone: draft.phone.trim() || null,
          appointment_at: draft.appointment_at || null,
          due_at: draft.due_at || null,
          doctor_notes: draft.doctor_notes.trim() || null,
          review_note: draft.review_note.trim() || null,
        }),
      });
      setBatch(result);
      const updated = result.records.find(item => item.id === row.id);
      setMessage(updated?.status === "READY"
        ? `Row ${row.row_number} reviewed and ready to import.`
        : `Row ${row.row_number} saved but still needs review.`);
      setEditingId(null); setDraft(null);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!batch || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<Batch>(`/api/bridge/batches/${batch.id}/approve`, {
        method: "POST", headers: mutationHeaders(), body: JSON.stringify({ include_review_rows: false }),
      });
      setBatch(result);
      setMessage(`${result.imported_records ?? 0} source records approved; ${result.cases_created ?? 0} follow-up cases are ready now.`);
      await loadRecent(); onImported();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function openBatch(id: string) {
    setBusy(true); setError(""); setMessage(""); setEditingId(null); setDraft(null);
    try { setBatch(await api<Batch>(`/api/bridge/batches/${id}`)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const ready = batch?.records.filter(r => r.status === "READY").length ?? 0;
  const review = batch?.records.filter(r => r.status === "REVIEW").length ?? 0;

  return <div className="bridge-intake">
    <section className="panel staff-panel bridge-hero">
      <p className="eyebrow">FORGET-LAH BRIDGE</p>
      <h2>Intelligent follow-up intake</h2>
      <p className="muted">No fixed import template. Upload the clinic export you already have; Forget-lah infers its meaning, normalises follow-up context and asks staff to approve it before any case is created.</p>
      <div className="bridge-boundary"><strong>Follow-up layer, not an appointment system.</strong><span>After staff approval, Forget-lah manages these imported follow-ups, including confirmations and rescheduling using staff-provided available slots. Clinics with an existing appointment API use that separate integration.</span></div>
      <div className="bridge-upload-row">
        <label className="bridge-file">Clinic export<input type="file" accept=".csv,.tsv,.xlsx" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
        <button className="primary" disabled={!file || busy} onClick={() => void analyse()}>{busy ? "Working…" : "Understand this file →"}</button>
      </div>
      {file && <p className="small">Selected: {file.name}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="success" role="status">{message}</p>}
    </section>

    {batch && <>
      <section className="metrics staff-metrics bridge-metrics">
        <article className="metric"><span>AI understanding</span><strong>{batch.confidence}%</strong><small>{purpose(batch.purpose)}</small></article>
        <article className="metric"><span>Rows understood</span><strong>{batch.row_count}</strong><small>{ready} ready to approve</small></article>
        <article className="metric"><span>Needs staff review</span><strong>{review}</strong><small>Edit these rows here; no re-upload required</small></article>
        <article className="metric"><span>Analysis version</span><strong>{batch.analysis_version}</strong><small>{batch.status.toLowerCase()}</small></article>
      </section>

      <section className="panel staff-panel">
        <div className="section-heading"><div><h2>What Forget-lah understood</h2><p className="muted">Semantic mapping uses headers and row values; source columns do not need Forget-lah names or order.</p></div></div>
        <div className="bridge-mapping-grid">{batch.mapping.map(item => <article key={`${item.canonical_field}-${item.source_columns.join()}`}>
          <strong>{item.source_columns.join(" + ") || "inferred context"}</strong><span>→ {item.canonical_field.replaceAll("_", " ")}</span><small>{item.confidence}% · {item.rationale}</small>
        </article>)}</div>
        {batch.warnings.length > 0 && <div className="bridge-warnings"><strong>AI warnings</strong>{batch.warnings.map(w => <p key={w}>{w}</p>)}</div>}
        {batch.status === "ANALYSED" && <div className="bridge-correction">
          <label>Correct the AI mapping in plain language<textarea value={instruction} onChange={e => setInstruction(e.target.value)} maxLength={600} placeholder="Example: Phone 1 is the patient. Phone 2 is the caregiver. Review Date is the deadline, not the appointment date." /></label>
          <button className="secondary" disabled={busy || !instruction.trim()} onClick={() => void revise()}>Re-analyse mapping</button>
        </div>}
      </section>

      <section className="panel staff-panel bridge-preview">
        <div className="section-heading"><div><h2>Follow-up preview</h2><p className="muted">Review uncertain rows directly below. Administrative fields can be corrected by staff; doctor notes remain source-bound to the uploaded row.</p></div>{batch.status === "ANALYSED" && <button className="primary" disabled={busy || ready === 0} onClick={() => void approve()}>Approve {ready} ready {ready === 1 ? "record" : "records"} →</button>}</div>
        <div className="bridge-table-wrap"><table><thead><tr><th>Row</th><th>Patient</th><th>Follow-up</th><th>Clinic context</th><th>AI review</th></tr></thead><tbody>{batch.records.map(row => {
          const editing = editingId === row.id && draft;
          return <Fragment key={row.id}><tr>
            <td>{row.row_number}</td><td><strong>{row.normalized.patient_name ?? "Unknown"}</strong><small>{row.normalized.phone ?? "No phone mapped"}</small></td>
            <td><strong>{when(row)}</strong><small>{row.normalized.record_type} · {row.normalized.source_status}</small></td>
            <td><strong>{row.normalized.specialty ?? "general"}</strong><small>{row.normalized.doctor_notes || "No doctor instruction in row"}</small></td>
            <td><span className={`pill ${row.status === "READY" || row.status === "IMPORTED" ? "staff-completed" : "staff-paused"}`}>{row.status}</span><small>{row.confidence}% AI confidence</small>{row.reviewed_at && <small className="bridge-reviewed">Staff reviewed</small>}{row.issues.map(issue => <small className="bridge-issue" key={issue}>{issue}</small>)}{batch.status === "ANALYSED" && row.status !== "IMPORTED" && row.status !== "SKIPPED" && <button className="bridge-edit-button secondary" onClick={() => startReview(row)}>{row.status === "REVIEW" ? "Review & edit" : "Edit"}</button>}</td>
          </tr>
          {editing && <tr className="bridge-review-row"><td colSpan={5}>
            <div className="bridge-review-shell">
              <div className="bridge-raw"><strong>Original uploaded row</strong><div>{Object.entries(row.raw ?? {}).map(([key, value]) => <p key={key}><span>{key}</span><code>{value || "—"}</code></p>)}</div></div>
              <div className="bridge-review-form">
                <div className="section-heading"><div><h3>Review row {row.row_number}</h3><p className="muted">Your edits become the approved Forget-lah follow-up context. They do not write back to the clinic system.</p></div></div>
                <div className="bridge-edit-grid">
                  <label>Patient name<input value={draft.patient_name} onChange={e => setDraft({ ...draft, patient_name: e.target.value })} /></label>
                  <label>Phone<input value={draft.phone} onChange={e => setDraft({ ...draft, phone: e.target.value })} /></label>
                  <label>External / visit reference<input value={draft.external_ref} onChange={e => setDraft({ ...draft, external_ref: e.target.value })} /></label>
                  <label>Specialty<select value={draft.specialty} onChange={e => setDraft({ ...draft, specialty: e.target.value as ReviewDraft["specialty"] })}><option value="general">General</option><option value="antenatal">Antenatal</option><option value="myopia">Myopia</option><option value="dental">Dental</option></select></label>
                  <label>Record type<select value={draft.record_type} onChange={e => setDraft({ ...draft, record_type: e.target.value as ReviewDraft["record_type"] })}><option value="appointment">Appointment</option><option value="recall">Recall</option></select></label>
                  <label>Status<select value={draft.source_status} onChange={e => setDraft({ ...draft, source_status: e.target.value as ReviewDraft["source_status"] })}><option value="scheduled">Scheduled</option><option value="no_show">No-show</option><option value="due">Due</option><option value="cancelled">Cancelled</option><option value="completed">Completed</option></select></label>
                  <label>Appointment time (SGT)<input type="datetime-local" value={draft.appointment_at} onChange={e => setDraft({ ...draft, appointment_at: e.target.value })} /></label>
                  <label>Recall due time (SGT)<input type="datetime-local" value={draft.due_at} onChange={e => setDraft({ ...draft, due_at: e.target.value })} /></label>
                  <label>Preferred language<select value={draft.preferred_language} onChange={e => setDraft({ ...draft, preferred_language: e.target.value as ReviewDraft["preferred_language"] })}><option value="und">Unknown</option><option value="en">English</option><option value="zh">Chinese</option><option value="ms">Malay</option><option value="ta">Tamil</option></select></label>
                </div>
                <label className="bridge-wide-field">Doctor note / preparation instruction<textarea value={draft.doctor_notes} onChange={e => setDraft({ ...draft, doctor_notes: e.target.value })} maxLength={600} /></label>
                <p className="small muted">Safety boundary: doctor-note text must still be present in the original uploaded row. Clear it if the source row does not support it.</p>
                <label className="bridge-wide-field">Optional review note<textarea value={draft.review_note} onChange={e => setDraft({ ...draft, review_note: e.target.value })} maxLength={240} placeholder="Why did you change this row?" /></label>
                <div className="bridge-review-actions"><button className="secondary" disabled={busy} onClick={() => { setEditingId(null); setDraft(null); }}>Cancel</button><button className="primary" disabled={busy || !draft.patient_name.trim()} onClick={() => void saveReview(row)}>{busy ? "Saving…" : "Save reviewed row"}</button></div>
              </div>
            </div>
          </td></tr>}
          </Fragment>;
        })}</tbody></table></div>
      </section>
    </>}

    {recent.length > 0 && <section className="panel staff-panel"><h2>Recent intelligent intakes</h2><div className="staff-case-grid">{recent.map(item => <button className="staff-case" key={item.id} onClick={() => void openBatch(item.id)}><span className="pill">{item.status}</span><h3>{item.filename}</h3><p className="capitalize">{purpose(item.purpose)} · {item.row_count} rows</p><strong>{item.confidence}% understood →</strong></button>)}</div></section>}
  </div>;
}
