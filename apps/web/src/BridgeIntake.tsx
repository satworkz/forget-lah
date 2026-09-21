import { useEffect, useState } from "react";
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
  confidence: number;
  issues: string[];
  status: string;
  source_episode_ref?: string | null;
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

function purpose(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}
function when(row: RecordRow) {
  const value = row.normalized.appointment_at ?? row.normalized.due_at;
  if (!value) return "Timing needs review";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadRecent() {
    try { setRecent(await api<BatchSummary[]>("/api/bridge/batches")); } catch { /* main workspace surfaces auth errors */ }
  }
  useEffect(() => { void loadRecent(); }, []);

  async function analyse() {
    if (!file || busy) return;
    setBusy(true); setError(""); setMessage("");
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
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<Batch>(`/api/bridge/batches/${batch.id}/revise`, {
        method: "POST", headers: mutationHeaders(), body: JSON.stringify({ instruction: instruction.trim() }),
      });
      setBatch(result); setInstruction("");
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
    setBusy(true); setError(""); setMessage("");
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
      <div className="bridge-boundary"><strong>Follow-up layer, not an appointment system.</strong><span>Imported sources are read-only. Appointment writes remain in the clinic’s existing system unless a separately authorised API exists.</span></div>
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
        <article className="metric"><span>Needs staff review</span><strong>{review}</strong><small>No silent guessing</small></article>
        <article className="metric"><span>Analysis version</span><strong>{batch.analysis_version}</strong><small>{batch.status.toLowerCase()}</small></article>
      </section>

      <section className="panel staff-panel">
        <div className="section-heading"><div><h2>What Forget-lah understood</h2><p className="muted">Semantic mapping uses headers and row values; source columns do not need Forget-lah names or order.</p></div></div>
        <div className="bridge-mapping-grid">{batch.mapping.map(item => <article key={`${item.canonical_field}-${item.source_columns.join()}`}>
          <strong>{item.source_columns.join(" + ") || "inferred context"}</strong><span>→ {item.canonical_field.replaceAll("_", " ")}</span><small>{item.confidence}% · {item.rationale}</small>
        </article>)}</div>
        {batch.warnings.length > 0 && <div className="bridge-warnings"><strong>AI warnings</strong>{batch.warnings.map(w => <p key={w}>{w}</p>)}</div>}
        {batch.status === "ANALYSED" && <div className="bridge-correction">
          <label>Correct the AI in plain language<textarea value={instruction} onChange={e => setInstruction(e.target.value)} maxLength={600} placeholder="Example: Phone 1 is the patient. Phone 2 is the caregiver. Review Date is the deadline, not the appointment date." /></label>
          <button className="secondary" disabled={busy || !instruction.trim()} onClick={() => void revise()}>Re-analyse with my correction</button>
        </div>}
      </section>

      <section className="panel staff-panel bridge-preview">
        <div className="section-heading"><div><h2>Follow-up preview</h2><p className="muted">Doctor notes are source-bound: Forget-lah rejects AI-generated instructions that are not present in the uploaded row.</p></div>{batch.status === "ANALYSED" && <button className="primary" disabled={busy || ready === 0} onClick={() => void approve()}>Approve {ready} ready {ready === 1 ? "record" : "records"} →</button>}</div>
        <div className="bridge-table-wrap"><table><thead><tr><th>Row</th><th>Patient</th><th>Follow-up</th><th>Clinic context</th><th>AI review</th></tr></thead><tbody>{batch.records.map(row => <tr key={row.id}>
          <td>{row.row_number}</td><td><strong>{row.normalized.patient_name ?? "Unknown"}</strong><small>{row.normalized.phone ?? "No phone mapped"}</small></td>
          <td><strong>{when(row)}</strong><small>{row.normalized.record_type} · {row.normalized.source_status}</small></td>
          <td><strong>{row.normalized.specialty ?? "general"}</strong><small>{row.normalized.doctor_notes || "No doctor instruction in row"}</small></td>
          <td><span className={`pill ${row.status === "READY" || row.status === "IMPORTED" ? "staff-completed" : "staff-paused"}`}>{row.status}</span><small>{row.confidence}% confidence</small>{row.issues.map(issue => <small className="bridge-issue" key={issue}>{issue}</small>)}</td>
        </tr>)}</tbody></table></div>
      </section>
    </>}

    {recent.length > 0 && <section className="panel staff-panel"><h2>Recent intelligent intakes</h2><div className="staff-case-grid">{recent.map(item => <button className="staff-case" key={item.id} onClick={() => void openBatch(item.id)}><span className="pill">{item.status}</span><h3>{item.filename}</h3><p className="capitalize">{purpose(item.purpose)} · {item.row_count} rows</p><strong>{item.confidence}% understood →</strong></button>)}</div></section>}
  </div>;
}
