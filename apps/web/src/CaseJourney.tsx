import { useEffect, useState } from "react";
import { api, modelLabel } from "./client";

type Stage = {
  component: string; title: string; input: unknown; output: unknown; basis: string;
};
type Entry = {
  id: string; at: string; title: string; summary: string; kind: string;
  status?: string; origin?: string; action?: string; attempts?: number; stages: Stage[];
};
type Journey = {
  case: { id: string; patient: string; specialty: string; trigger: string; source_episode_ref: string; created_at: string };
  runs: { id: string; created_at: string; status: string; mode: string }[];
  selected_run_id: string | null;
  entries: Entry[];
  current: {
    status: string; active_role: string | null; steps_used: number; captured_at: string;
    checkpoint: Record<string, unknown>;
    handoff: { accepted: boolean; owner: string | null; risk: string; staff_task_status: string } | null;
  };
};
const words = (s: string) => s.replaceAll("_", " ").toLowerCase();
const time = (s: string) => new Date(s).toLocaleString();
const origin = (s?: string) => s === "model" ? "Claude decision" : s === "mock" ? "Simulated decision" : s === "rule" ? "Application rule" : "Application record";

function Messages({ stage, expanded }: { stage: Stage; expanded: boolean }) {
  return <details className="journey-messages" open={expanded}>
    <summary>Inspect input and output</summary>
    <div className="journey-io">
      <div><h4>Input · what this component received</h4><pre>{JSON.stringify(stage.input, null, 2)}</pre></div>
      <div><h4>Output · what it returned or saved</h4><pre>{JSON.stringify(stage.output, null, 2)}</pre></div>
    </div>
  </details>;
}

export function CaseJourney({ caseId, onBack }: { caseId: string; onBack: () => void }) {
  const [data, setData] = useState<Journey | null>(null);
  const [runId, setRunId] = useState("");
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState("all");
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    setData(null);
    async function load() {
      if (loading) return;
      loading = true;
      try {
        const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
        const next = await api<Journey>(`/api/cases/${caseId}/journey${query}`, { signal: controller.signal });
        if (!controller.signal.aborted) { setData(next); setError(""); }
      } catch (e) {
        if (!controller.signal.aborted) { setData(null); setError((e as Error).message); }
      } finally { loading = false; }
    }
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [caseId, runId, refreshKey]);
  const run = data?.runs.find(r => r.id === data.selected_run_id);
  const entries = data?.entries.filter(e => filter === "all" || (filter === "decisions" ? e.kind === "decision" : e.kind !== "decision")) ?? [];
  return <main className="journey-page">
    <header className="journey-header">
      <div><button className="text-button" onClick={onBack}>← Back to dashboard</button>
        <p className="eyebrow">CASE JOURNEY · SAVED EVIDENCE</p>
        <h1>How this follow-up unfolded</h1>
        <p className="muted">From the source record to the current state. See who acted, what went in, and what came out.</p>
      </div>
      <button className="secondary" onClick={() => setRefreshKey(k => k + 1)}>Refresh journey</button>
    </header>
    {error && <p className="error" role="alert">{error}. Return to the dashboard to sign in again if your session expired.</p>}
    {!data && !error && <p role="status">Loading saved case history…</p>}
    {data && <>
      <section className="panel journey-overview">
        <div><p className="eyebrow">{data.case.specialty} · {words(data.case.trigger)}</p>
          <h2>{data.case.patient}</h2><p className="small">Source reference: {data.case.source_episode_ref}</p></div>
        <div><span className="pill capitalize">{words(data.current.status)}</span>
          <p><strong>{data.current.steps_used}</strong> decision steps used in this review</p>
          {run && <span className="tag">{modelLabel(run.mode)}</span>}</div>
      </section>
      <div className="journey-map" aria-label="Components in this implementation">
        <span>Clinic source</span><span aria-hidden="true">→</span><span>Detector & PostgreSQL</span><span aria-hidden="true">→</span>
        <span>Worker & agent roles</span><span aria-hidden="true">↔</span><span>Claude / simulation</span><span aria-hidden="true">→</span>
        <span>Policy gateway & tools</span><span aria-hidden="true">→</span><span>Saved progress / staff</span>
      </div>
      <p className="journey-explainer">The worker runs the Python code. The selected agent role proposes the next action; the gateway checks it before execution. A tool call, its result and a database save are activities within one decision step, not three Claude decisions.</p>
      <div className="journey-toolbar">
        <label>Review history<select aria-label="Review history" value={runId} onChange={e => { setRunId(e.target.value); setExpanded(false); }}>
          <option value="">Latest review</option>
          {data.runs.map((r, i) => <option key={r.id} value={r.id}>Review {data.runs.length - i} · {time(r.created_at)} · {r.status} · {modelLabel(r.mode)}</option>)}
        </select></label>
        <label>Show<select aria-label="Filter journey" value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="all">All saved events</option><option value="decisions">Agent decisions</option><option value="events">Case and staff events</option>
        </select></label>
        <button className="secondary" aria-pressed={expanded} onClick={() => setExpanded(v => !v)}>{expanded ? "Collapse messages" : "Expand all messages"}</button>
      </div>
      <div className="journey-note">
        <strong>How to read this page</strong>
        <p>Read down the page, then through each activity in order. Times show when the main record was created; activities within a decision are shown in logical execution order, not as separately timed network logs. The last card is the selected review’s current saved state.</p>
        <details><summary>What is captured, and what is not?</summary><p>These are persisted application messages and results. Historical exact prompts, raw HTTP headers, individual retry responses and empty worker polls were not retained. They cannot be reconstructed reliably. No new Claude calls are made by this page. Invalid model text and private reasoning are not displayed. New case detections include the synthetic candidate snapshot; older cases may have only a source reference.</p></details>
      </div>
      <ol className="journey-timeline">
        {entries.map(e => <li key={e.id} className="journey-entry">
          <div className="journey-entry-header"><div><span className="eyebrow">{origin(e.origin)}</span><h2>{e.title}</h2></div><time>{time(e.at)}</time></div>
          <p className="journey-summary">{e.summary}</p>
          {e.status && <p className="small">Step status: <strong>{e.status}</strong>{e.origin === "model" ? ` · ${e.attempts} model attempt(s)` : e.origin === "rule" ? " · 0 model calls" : ""}</p>}
          <ol className="journey-stages">{e.stages.map((stage, i) => <li key={`${e.id}-${i}`}>
            <div className="journey-component">{stage.component}</div>
            <h3>{stage.title}</h3>
            <p className="journey-basis">{stage.basis}</p>
            <Messages stage={stage} expanded={expanded} />
          </li>)}</ol>
        </li>)}
      </ol>
      {!entries.length && <p>No saved events match this filter.</p>}
      <section className="panel journey-current">
        <p className="eyebrow">WHERE THIS REVIEW IS NOW</p><h2 className="capitalize">{words(data.current.status)}</h2>
        <p>{data.current.status === "completed" ? (data.current.checkpoint.outcome === "SIMULATED_ATTENDANCE_CONFIRMED"
          ? "The mock clinic recorded attendance confirmation and the simulator displayed an acknowledgement. No staff handoff was needed. This is an intention to attend, not actual attendance."
          : "Automation has finished. A named staff member owns the follow-up; appointment changes and clinical work remain with the clinic.")
          : data.current.status === "waiting" ? "Progress is saved. The worker can resume when the expected reply or retry time arrives."
          : data.current.status === "paused" ? `Processing stopped: ${words(String(data.current.checkpoint.pause_reason ?? "check the saved evidence"))}. Use the dashboard to investigate and retry.`
          : data.current.status === "escalated" ? "Staff action is needed. The review has not completed; accept the handoff on the dashboard."
          : "Use the dashboard to start or control the review. This page only reads its saved history."}</p>
        {data.current.handoff && <p><strong>{data.current.handoff.risk}</strong> · {data.current.handoff.accepted ? `Accepted by ${data.current.handoff.owner}. Staff task remains open.` : "No staff owner yet."}</p>}
        <details><summary>Inspect current saved state</summary><pre>{JSON.stringify(data.current, null, 2)}</pre></details>
        <p className="small">Last refreshed: {time(data.current.captured_at)} · refreshes every four seconds</p>
      </section>
    </>}
  </main>;
}
