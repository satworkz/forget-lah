import { PatientMessage, type StaffTranslation } from "./PatientMessage";
import { useEffect, useRef, useState } from "react";
import { api, modelLabel, mutationHeaders } from "./client";
import { BridgeFollowupOptions, type ManagedFollowup } from "./BridgeFollowupOptions";
import { PatientPreferences, type Preferences } from "./PatientPreferences";

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
  validation_failures?: unknown[];
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
  source_kind: "bridge_upload" | "clinic_api";
  bridge: ManagedFollowup | null;
  preferences: Preferences;
  plan?: { goal: string; learned: string[]; constraint_source: string; next_action: string; attendance: string; instructions: string; preparation: string; source_prerequisites: string[]; decision_step_id: string | null };
  case_version: number;
  auto_start: { enabled: boolean; authorised: boolean };
  run: {
    id: string;
    status: string;
    mode: string;
    active_role: string;
    goal: string;
    step_count: number;
    turn_step_count?: number;
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
  events: { id: string; kind: string; content: string; staff_translation?: StaffTranslation; created_at: string; channel?: string }[];
  patient_simulator: { available: boolean; enabled: boolean; messages: { id: string; kind: string; body: string; created_at: string; delivery_status?: string | null }[] };
  handoff: {
    reason_code: string;
    risk: string;
    accepted: boolean;
    owner: string | null;
    staff_task_status: string;
    legacy_bridge_capabilities?: boolean;
    callback?: { status: string; question: string; topic?: string; resolution?: string } | null;
    clinical_review?: { status: string; patient_message: string; reply_event_id?: string; symptom_quotes: string[]; attendance_intent: string; attendance_quote?: string | null; resolution?: string } | null;
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
  onJourney,
}: {
  caseId: string;
  modelMode: string;
  onStatus: (status: string | null) => void;
  onJourney: () => void;
}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolution, setResolution] = useState("");
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
    if (!view?.run || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/cases/${caseId}/agent/events`, {
        method: "POST",
        headers: mutationHeaders(),
        body: JSON.stringify({
          expected_case_version: view.case_version,
          run_id: view.run.id,
          kind,
          content: kind === "demo_reply" ? reply : ["resolve_callback", "resolve_clinical"].includes(kind) ? resolution : "",
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
  const conversation = view ? [
    ...(view.patient_simulator?.messages ?? []).map(m => ({...m, text: m.body, label: m.delivery_status ? `Clinic · WhatsApp test · ${m.delivery_status}` : m.kind === "reminder" ? "Clinic reminder · simulated" : m.kind === "options" ? "Clinic availability update · simulated" : m.kind === "clarification" ? "Clinic question · simulated" : m.kind === "preference_saved" ? "Scheduling preference saved · simulated" : "Clinic acknowledgement · simulated"})),
    ...view.events.filter(e => e.kind === "demo_reply").map(e => ({...e, text: e.content, label: e.channel === "whatsapp_test" ? "Patient reply · WhatsApp test phone" : "Patient reply · simulated"})),
  ].sort((a,b) => a.created_at.localeCompare(b.created_at)) : [];
  async function freshSimulation() {
    if (!view || busy) return;
    setBusy(true); setError("");
    try {
      await api(`/api/cases/${caseId}/agent/runs`, {method: "POST", headers: mutationHeaders(), body: JSON.stringify({expected_case_version: view.case_version, fresh_simulation: true})});
      setReply("I confirm my attendance");
      await reloadRef.current();
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
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
      <button className="secondary" onClick={onJourney}>View full case journey →</button>
      <p className="muted">
        {reviewMode === "mock"
          ? "Decisions follow a deterministic demo script. Source reads, saved progress and permission checks really run."
          : "Decisions use the configured Claude provider. A failed model call pauses or retries; it never switches to simulation."}{" "}
        All clinic records are synthetic. Dashboard messages remain simulated unless explicitly connected to the WhatsApp test phone; delivery status is shown on each connected message.
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
          {view.bridge && <BridgeFollowupOptions key={caseId} caseId={caseId} state={view.bridge} reload={() => reloadRef.current()} />}
          {!run && (
            <div className="agent-actions">
              <p role="status">
                {!view.auto_start.enabled
                  ? "Automatic review is disabled in the app configuration."
                  : !view.auto_start.authorised
                    ? "Automatic review needs an active clinic service identity. Check bootstrap and clinic access."
                    : "Waiting for the worker to finish case setup and queue the review automatically. No start action is needed."}
              </p>
            </div>
          )}
          {run && (
            <>
              <div className="run-summary" aria-live="polite">
                <span className="pill capitalize">{run.status}</span>
                <strong className="capitalize">{run.active_role}</strong>
                <span>
                  {run.turn_step_count ?? run.step_count} steps for this reply · maximum {run.step_limit}
                </span>
              </div>
              <p><strong>Assigned goal:</strong> {run.goal}</p>
              {view.plan && <section className="agent-actions" aria-label="Follow-up plan and readiness">
                <h3>Plan and visit readiness</h3>
                <p>{view.plan.goal}</p>
                {view.plan.learned.length > 0 && <p><strong>Patient told us:</strong> {view.plan.learned.join("; ")}</p>}
                <p><strong>Scheduling preferences:</strong> {view.plan.constraint_source}</p>
                <p><strong>Attendance:</strong> {view.plan.attendance}</p>
                <p><strong>Instructions:</strong> {view.plan.instructions}</p>
                <p><strong>Preparation:</strong> {view.plan.preparation}</p>
                {view.plan.source_prerequisites.length > 0 && <p><strong>Clinic prerequisite record:</strong> {view.plan.source_prerequisites.map(readable).join(", ")}</p>}
                <p><strong>Next:</strong> {view.plan.next_action}</p>
                <p className="small">Summary of saved evidence, not a medical readiness assessment. See the full journey for decisions and tool results.</p>
              </section>}
              {view.patient_simulator?.available && <PatientPreferences key={`${caseId}-${view.preferences.updated_at ?? "none"}`} caseId={caseId} version={view.case_version} preferences={view.preferences} onSaved={() => reloadRef.current()} disabled={busy || ["queued", "running"].includes(run.status)} />}
              {view.patient_simulator?.available && ["waiting", "paused", "escalated", "completed"].includes(run.status) && !run.available_at && <div className="agent-actions">
                <button className="secondary" disabled={busy} onClick={() => void freshSimulation()}>{view.source_kind === "bridge_upload" ? "Start fresh conversation test" : "Start fresh simulator test"}</button>
                <p className="small">Uses the current appointment records in a new review. Earlier reviews remain in the case journey.</p>
              </div>}
              {(view.patient_simulator?.enabled || conversation.length > 0) && <section className="sim-conversation" aria-label="Patient conversation simulator">
                <h3>Patient conversation simulator</h3>
                <p className="small">{view.source_kind === "bridge_upload"
                  ? "Test conversation for an imported appointment managed by Forget-lah. Confirmations are saved in Forget-lah. Appointment changes require clinic-provided availability or a staff decision."
                  : "Local test conversation. Bookings and confirmations update only the synthetic clinic system."}</p>
                {conversation.map(m => <article key={m.id} className="sim-message">
                  <strong>{m.label}</strong><time>{new Date(m.created_at).toLocaleString()}</time>
                  <p>{m.text}</p>
                </article>)}
                {!conversation.length && <p>Waiting for the first simulated reminder…</p>}
              </section>}
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
                    {view.patient_simulator?.enabled && !view.patient_simulator.messages.some(m => m.kind === "options") && <button type="button" className="secondary" disabled={busy} onClick={() => setReply("I confirm my attendance")}>Use attendance confirmation</button>}
                    {view.patient_simulator?.enabled && <button type="button" className="secondary" disabled={busy} onClick={() => setReply("I dont think I can make it, what are all the available slots?")}>Ask for available slots</button>}
                    {view.patient_simulator?.messages.some(m => m.kind === "options") && <button type="button" className="secondary" disabled={busy} onClick={() => setReply("Book option 1")}>Choose option 1 from the latest offer</button>}
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
                    symptom reports in demo text now create a clinical callback task; voice triage is not implemented.
                  </p>
                </div>
              )}
              {view.handoff && (
                <div
                  className={`handoff ${view.handoff.risk === "RED" ? "handoff-red" : ""}`}
                >
                  <strong>
                    {view.handoff.risk} ·{" "}
                    {view.handoff.staff_task_status === "resolved" ? "Staff review resolved" : view.handoff.accepted
                      ? "Handoff accepted"
                      : "Staff owner needed"}
                  </strong>
                  <p className="capitalize">
                    {view.handoff.legacy_bridge_capabilities ? "Earlier Bridge confirmation limitation" : readable(view.handoff.reason_code)}
                  </p>
                  {view.handoff.reason_code === "SLOT_SELECTION_CHANGED" && <p>The selected option changed before confirmation. This request did not move the appointment. Review the current alternatives in the conversation and help the patient choose another time.</p>}
                  {view.handoff.reason_code === "NO_AVAILABLE_SLOTS" && <p>The clinic source currently lists no available slots. The existing appointment has not been changed. Staff can help arrange a suitable time.</p>}
                  {view.handoff.callback && <div>
                    <p><strong>Attendance: {view.plan?.attendance ?? "Check source evidence"}</strong></p>
                    <p><strong>{view.handoff.callback.topic === "preparation" ? "Preparation help" : "Patient question"}: {view.handoff.callback.status === "resolved" ? "Resolved by staff" : "Awaiting clinic response"}</strong></p>
                    <p>Patient asked: {view.handoff.callback.question}</p>
                    <p>Callback {view.handoff.callback.status}. Accepting ownership does not resolve the question.</p>
                    {view.handoff.callback.resolution && <p>Recorded contact outcome: {view.handoff.callback.resolution}</p>}
                    {view.handoff.callback.status === "accepted" && <>
                      <label htmlFor="callback-resolution">After contacting the patient, record what you clarified</label>
                      <textarea id="callback-resolution" value={resolution} maxLength={600} onChange={e => setResolution(e.target.value)} />
                      <button className="primary" disabled={busy || !resolution.trim()} onClick={() => void act("resolve_callback")}>Record contact and resolve callback</button>
                      <p className="small">Only the staff member who accepted this callback can resolve it. This records staff-reported contact; it does not place a phone call.</p>
                    </>}
                  </div>}
                  {view.handoff.clinical_review && <div>
                    <p><strong>Clinical callback: {view.handoff.clinical_review.status}</strong></p>
                    <PatientMessage original={view.handoff.clinical_review.patient_message} translation={view.events.find(e => e.id === view.handoff?.clinical_review?.reply_event_id)?.staff_translation} caseId={caseId} eventId={view.handoff.clinical_review.reply_event_id} />
                    <p>Symptoms: {view.handoff.clinical_review.symptom_quotes.join("; ")}</p>
                    <p>Attendance intention: {view.handoff.clinical_review.attendance_intent === "stated" ? "Patient says they plan to attend" : "Not confirmed in this message"}. This is separate from a clinic-system confirmation.</p>
                    <p>Clinical review is required. RED marks a clinical handoff; it is not an automated diagnosis or urgency assessment. Accepting ownership keeps the task open until contact and review are recorded.</p>
                    {view.handoff.clinical_review.resolution && <p>Recorded contact and review outcome: {view.handoff.clinical_review.resolution}</p>}
                    {view.handoff.clinical_review.status === "accepted" && <>
                      <label htmlFor="clinical-resolution">After contacting the patient and arranging clinical review, record the outcome and any further follow-up</label>
                      <textarea id="clinical-resolution" value={resolution} maxLength={600} onChange={e => setResolution(e.target.value)} />
                      <button className="primary" disabled={busy || !resolution.trim()} onClick={() => void act("resolve_clinical")}>Record contact and resolve review</button>
                      <p className="small">Only the assigned owner can resolve this task. Recording an outcome does not place a phone call or establish that symptoms have resolved.</p>
                    </>}
                  </div>}
                  {view.handoff.reason_code === "CAPABILITY_UNAVAILABLE" && <p>
                    {view.handoff.legacy_bridge_capabilities
                      ? "This review stopped before Forget-lah supported confirmation of imported appointments. That support is now available. Start a fresh conversation test above to try the updated flow; this earlier review remains in the case history."
                      : view.source_kind === "bridge_upload"
                      ? "Forget-lah manages this imported appointment. Check the saved tool evidence for the action that needs staff help. Confirmations can be recorded in Forget-lah; booking or rescheduling requires clinic-provided availability. A handoff from an earlier review remains part of its history."
                      : view.patient_simulator?.enabled ? "This scenario needs clinic help. Check the tool evidence for an unavailable action, changed slot or preparation issue. The simulator supports recall and missed-appointment follow-up bookings, attendance confirmations and rescheduling future appointments through the clinic API." : "This older review used read-only capabilities. Start a fresh simulator test to exercise attendance confirmation and acknowledgement."}
                  </p>}
                  {view.handoff.accepted ? (
                    <p>
                      Owner: {view.handoff.owner}. The staff task is {view.handoff.staff_task_status}.
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
                  {run.outcome === "SIMULATED_ATTENDANCE_CONFIRMED" ? "Follow-up complete: attendance confirmation is recorded in the mock clinic system and the acknowledgement is displayed above. This records an intention to attend, not actual attendance." : "Automation complete: a named staff member owns the follow-up. Clinical work and appointment changes remain with the clinic."}
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
                    {step.origin === "rule" && step.decision?.step_type === "TOOL" && (
                      <p>{step.decision.tool_name === "read_followup_context"
                        ? "The worker requested the initial clinic context automatically."
                        : step.decision.tool_name === "record_simulated_confirmation"
                        ? "The worker submitted the explicitly confirmed simulator action through the policy gateway."
                        : "The worker retried the interrupted simulated action using its saved evidence."}
                        {" "}This step uses 0 model calls. Check the tool result below.</p>
                    )}
                    {step.origin === "rule" && step.decision?.step_type === "WAIT" && (
                      <p>{view.patient_simulator.messages.some((message) => message.kind === "reminder")
                        ? "The worker displayed the simulated reminder and saved this wait automatically."
                        : "The worker saved this wait automatically; this review has no outgoing reminder."}
                        {" "}No Claude call was needed for this step. Submit a demo reply to continue.</p>
                    )}
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
                    {!!step.validation_failures?.length && (
                      <details>
                        <summary>Inspect rejected proposal and validation errors</summary>
                        <p className="small">These proposals were rejected before policy or tool execution.</p>
                        <pre>{JSON.stringify(step.validation_failures, null, 2)}</pre>
                      </details>
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
