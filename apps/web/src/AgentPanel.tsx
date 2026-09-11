import { useEffect, useRef, useState } from "react";
import { api, modelLabel, mutationHeaders } from "./client";

type Step = {
  id: string;
  sequence: number;
  role: string;
  origin: string;
  status: string;
  attempts: number;
  goal: string;
  event_kind: string;
  error_code: string | null;
  decision: Record<string, unknown> | null;
  policy: { decision: string; risk: string; reason_codes: string[] } | null;
  tool_result: {
    tool_name: string;
    status: string;
    source_version: string | null;
    data: unknown;
    error_code: string | null;
  } | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
};
type View = {
  case_version: number;
  run: {
    id: string;
    status: string;
    mode: string;
    active_role: string;
    goal: string;
    step_count: number;
    step_limit: number;
    wait_reason: string | null;
    pause_reason: string | null;
    outcome: string | null;
    available_at: string | null;
  } | null;
  steps: Step[];
  delegations: {
    id: string;
    target: string;
    goal: string;
    status: string;
    evidence_ids: string[];
  }[];
  events: { id: string; kind: string; content: string }[];
  handoff: {
    reason_code: string;
    risk: string;
    accepted: boolean;
    owner: string | null;
    staff_task_status: string;
  } | null;
};
const readable = (value: unknown) =>
  String(value ?? "")
    .replaceAll("_", " ")
    .toLowerCase();
const originLabel = (origin: string) =>
  origin === "mock"
    ? "Simulated decision"
    : origin === "model"
      ? "Claude model"
      : "Application rule";

export function AgentPanel({
  caseId,
  modelMode,
  onStatus,
}: {
  caseId: string;
  modelMode: string;
  onStatus: (status: string | null) => void;
}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState(
    "Can I come next Friday? What should I bring?",
  );
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  const reloadRef = useRef<() => Promise<void>>(async () => {});
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let loading = false;
    async function load() {
      if (loading) return;
      loading = true;
      try {
        const next = await api<View>(`/api/cases/${caseId}/agent`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setView(next);
          setLoadError("");
          statusCallback.current(next.run?.status ?? null);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setLoadError((e as Error).message);
          setView(null); // Do not leave actionable stale patient data on an auth/network failure.
        }
      } finally {
        loading = false;
      }
    }
    reloadRef.current = load;
    void load();
    const timer = window.setInterval(() => void load(), 1500);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [caseId]);

  async function act(kind: string) {
    if (!view || busy) return;
    setBusy(true);
    setError("");
    try {
      const start = kind === "start";
      await api(`/api/cases/${caseId}/agent/${start ? "runs" : "events"}`, {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({
          expected_case_version: view.case_version,
          ...(start
            ? {}
            : {
                run_id: view.run!.id,
                kind,
                content: kind === "demo_reply" ? reply : "",
              }),
        }),
      });
      if (mounted.current) await reloadRef.current();
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  const run = view?.run;
  const reviewMode = run?.mode ?? modelMode;
  return (
    <section className="panel agent-workspace" aria-labelledby="agent-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">AGENT ACTIVITY</p>
          <h2 id="agent-title">Follow the next decision</h2>
        </div>
        <span className="tag">
          {modelLabel(reviewMode)}
        </span>
      </div>
      <p className="muted">
        {reviewMode === "mock"
          ? "Decisions follow a deterministic demo script. Source reads, saved progress and permission checks really run."
          : "Decisions use the configured Claude provider. A failed model call pauses or retries; it never switches to simulation."}{" "}
        All records and replies here are fictional. No messages or booking
        changes are sent.
      </p>
      {run && run.mode !== modelMode && (
        <p className="muted">
          This saved review used {modelLabel(run.mode)}. New reviews use {modelLabel(modelMode)}.
        </p>
      )}
      {(error || loadError) && (
        <p className="error" role="alert">
          {error || loadError}
        </p>
      )}
      {!view ? (
        <p role="status">Loading the latest agent state…</p>
      ) : (
        <>
          {!run && (
            <div className="agent-actions">
              <button
                className="primary"
                disabled={busy}
                onClick={() => void act("start")}
              >
                Start agent review
              </button>
              <p>
                The Coordinator will inspect this case and choose a specialist.
              </p>
            </div>
          )}
          {run && (
            <>
              <div className="run-summary" aria-live="polite">
                <span className="pill capitalize">{run.status}</span>
                <strong className="capitalize">{run.active_role}</strong>
                <span>
                  {run.step_count} / {run.step_limit} decision steps
                </span>
              </div>
              <p>{run.goal}</p>
              {run.status === "waiting" && (
                <div className="agent-prompt">
                  <strong>
                    {run.wait_reason === "AWAITING_PATIENT_REPLY"
                      ? "Waiting for a fictional patient reply"
                      : "Waiting before checking the source again"}
                  </strong>
                  {run.available_at && (
                    <p>
                      Next check:{" "}
                      {new Date(run.available_at).toLocaleTimeString()}
                    </p>
                  )}
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void act("demo_reply");
                    }}
                  >
                    <label htmlFor="demo-reply">
                      Staff demo input · not an authenticated patient message
                    </label>
                    <textarea
                      id="demo-reply"
                      value={reply}
                      maxLength={600}
                      required
                      onChange={(e) => setReply(e.target.value)}
                    />
                    <button
                      className="primary"
                      disabled={busy || !reply.trim()}
                    >
                      Submit demo reply
                    </button>
                  </form>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void act("clinical_concern")}
                  >
                    Simulate staff-flagged clinical concern
                  </button>
                  <p className="small">
                    This button proves the rule-based escalation path. Automatic
                    clinical detection from text or voice is not implemented.
                  </p>
                </div>
              )}
              {view.handoff && (
                <div
                  className={`handoff ${view.handoff.risk === "RED" ? "handoff-red" : ""}`}
                >
                  <strong>
                    {view.handoff.risk} ·{" "}
                    {view.handoff.accepted
                      ? "Handoff accepted"
                      : "Staff owner needed"}
                  </strong>
                  <p className="capitalize">
                    {readable(view.handoff.reason_code)}
                  </p>
                  {view.handoff.accepted ? (
                    <p>
                      Owner: {view.handoff.owner}. The staff task remains open.
                    </p>
                  ) : (
                    <>
                      <p>
                        The handoff is unowned until a signed-in staff member
                        accepts it.
                      </p>
                      <button
                        className="primary"
                        disabled={busy || run.status !== "escalated"}
                        onClick={() => void act("accept_handoff")}
                      >
                        Accept handoff as me
                      </button>
                    </>
                  )}
                </div>
              )}
              {run.status === "paused" && (
                <div className="agent-prompt">
                  <strong>Agent paused</strong>
                  <p>
                    {readable(run.pause_reason)}. Check the evidence below
                    before retrying.
                  </p>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => void act("retry")}
                  >
                    Retry agent review
                  </button>
                </div>
              )}
              {run.status === "completed" && (
                <p className="completion">
                  Automation complete: a named staff member owns the follow-up.
                  Clinical work and appointment changes remain with the clinic.
                </p>
              )}
              {["queued", "running", "waiting"].includes(run.status) && (
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() => void act("pause")}
                >
                  Pause agent
                </button>
              )}
              {run.status === "completed" && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => void act("start")}
                >
                  Start another demo run
                </button>
              )}
              <h3>Decision and tool evidence</h3>
              {!view.steps.length && (
                <p role="status">The worker is picking up this review…</p>
              )}
              <ol className="timeline agent-timeline">
                {view.steps.map((step) => (
                  <li key={step.id}>
                    <div className="run-summary">
                      <strong>
                        #{step.sequence} ·{" "}
                        <span className="capitalize">{step.role}</span>
                      </strong>
                      <span className="pill">{originLabel(step.origin)}</span>
                      <span>{step.status}</span>
                    </div>
                    <p>{step.goal}</p>
                    {step.decision && (
                      <p>
                        <strong>{String(step.decision.step_type)}</strong>
                        {" · "}
                        {readable(step.decision.reason_code)}
                        {step.decision.target
                          ? ` → ${String(step.decision.target)}`
                          : ""}
                      </p>
                    )}
                    {step.policy && (
                      <p>
                        <strong>
                          {step.policy.risk} · {step.policy.decision}
                        </strong>
                        {" · "}
                        {step.policy.reason_codes.map(readable).join(", ")}
                      </p>
                    )}
                    {step.tool_result && (
                      <div className="tool-evidence">
                        <strong>{step.tool_result.tool_name}</strong>
                        <p>
                          {step.tool_result.status} ·{" "}
                          {step.tool_result.source_version ??
                            step.tool_result.error_code}
                        </p>
                        <details>
                          <summary>Inspect source result</summary>
                          <pre>{JSON.stringify(step.tool_result, null, 2)}</pre>
                        </details>
                      </div>
                    )}
                    {step.error_code && (
                      <p className="error">{readable(step.error_code)}</p>
                    )}
                    {step.decision && (
                      <details>
                        <summary>
                          Inspect validated decision and gateway verdict
                        </summary>
                        <pre>
                          {JSON.stringify(
                            { decision: step.decision, policy: step.policy },
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    )}
                    {step.origin === "model" && (
                      <p className="small">
                        {step.attempts} attempt(s) · reported input tokens:{" "}
                        {step.input_tokens ?? "unavailable"} · reported output
                        tokens: {step.output_tokens ?? "unavailable"}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
              {view.delegations.length > 0 && (
                <details>
                  <summary>
                    Specialist delegation history ({view.delegations.length})
                  </summary>
                  <ul>
                    {view.delegations.map((d) => (
                      <li key={d.id}>
                        <strong className="capitalize">
                          {d.target} · {d.status}
                        </strong>
                        <p>
                          {d.goal} · {d.evidence_ids.length} evidence
                          reference(s)
                        </p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {view.events.length > 0 && (
                <details>
                  <summary>Staff demo events ({view.events.length})</summary>
                  <ul>
                    {view.events.map((e) => (
                      <li key={e.id}>
                        <strong className="capitalize">
                          {readable(e.kind)}
                        </strong>
                        <p>{e.content || "Staff control action"}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
