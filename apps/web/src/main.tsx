import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type FollowupCase = {
  id: string;
  patient: string;
  specialty: string;
  trigger: string;
  state: string;
  source_episode_ref: string;
  case_version: number;
};
type AuditEvent = {
  id: string;
  event_type: string;
  origin: string;
  details: Record<string, string>;
  created_at: string;
};
type Agent = { role: string; name: string; goal: string; status: string };
const triggerLabels: Record<string, string> = {
  UPCOMING: "Upcoming visit",
  MISSED: "Missed appointment",
  RECALL_OVERDUE: "Overdue recall",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

function App() {
  const [signedIn, setSignedIn] = useState(false);
  const [checking, setChecking] = useState(true);
  const [email, setEmail] = useState("staff@forget-lah.example");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionEpoch = useRef(0);
  const [cases, setCases] = useState<FollowupCase[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<FollowupCase | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(false);

  async function refresh() {
    const epoch = sessionEpoch.current;
    setBusy(true);
    setError("");
    try {
      const [rows, system] = await Promise.all([
        api<FollowupCase[]>("/api/cases"),
        api<{ agents: Agent[] }>("/api/system"),
      ]);
      if (epoch !== sessionEpoch.current) return;
      setCases(rows);
      setAgents(system.agents);
    } catch (e) {
      if (epoch === sessionEpoch.current) {
        setCases([]);
        setAgents([]);
        setSelected(null);
        setError((e as Error).message);
      }
    } finally {
      if (epoch === sessionEpoch.current) setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    api<{ email: string }>("/api/me")
      .then(() => {
        if (active) setSignedIn(true);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (signedIn) void refresh();
  }, [signedIn]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    setLoadingEvents(true);
    setEvents([]);
    api<AuditEvent[]>(`/api/cases/${selected.id}/events`)
      .then((rows) => {
        if (active) setEvents(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoadingEvents(false);
      });
    return () => {
      active = false;
    };
  }, [selected]);

  async function login(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setPassword("");
      sessionEpoch.current += 1;
      setSignedIn(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setError("");
    const csrf =
      document.cookie
        .split("; ")
        .find((c) => c.startsWith("forget_lah_csrf="))
        ?.split("=")[1] ?? "";
    try {
      await api("/api/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
      });
      sessionEpoch.current += 1;
      setSignedIn(false);
      setCases([]);
      setAgents([]);
      setSelected(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (checking)
    return (
      <main className="login-shell">
        <p role="status">Opening forget-lah…</p>
      </main>
    );
  if (!signedIn)
    return (
      <main className="login-shell">
        <div className="login-intro">
          <div className="wordmark">
            forget-lah<span>●</span>
          </div>
          <p className="eyebrow">PATIENT FOLLOW-UP</p>
          <h1>
            A clear next step.
            <br />
            For every patient.
          </h1>
          <p>
            Accessible follow-up, informed preparation and accountable staff
            handoffs.
          </p>
          <div className="intro-note">
            NUS-ISS · Show Me Your Agents
            <br />
            Local development foundation
          </div>
        </div>
        <section className="login-card" aria-labelledby="sign-in">
          <span className="tag">SYNTHETIC DEMONSTRATION</span>
          <h2 id="sign-in">Clinic workspace</h2>
          <p>Sign in with the local staff credentials created during setup.</p>
          <form onSubmit={login}>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button className="primary" disabled={busy}>
              {busy ? "Signing in…" : "Open workspace →"}
            </button>
          </form>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <p className="small">
            Find your generated credentials in the local .env file. This version
            contains synthetic patients only.
          </p>
        </section>
      </main>
    );

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="wordmark">
          forget-lah<span>●</span>
        </div>
        <p className="sidebar-label">CLINIC WORKSPACE</p>
        <div className="nav-current">◉ &nbsp; Follow-up overview</div>
        <div className="sidebar-bottom">
          <span className="tag">MILESTONE 01</span>
          <p>Foundation ready for the agent journey.</p>
          <button className="text-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <header>
          <div>
            <p className="eyebrow">FORGET-LAH DEMONSTRATION CLINIC</p>
            <h1>Patient follow-up</h1>
            <p className="muted">
              One view of the people who need a next step.
            </p>
          </div>
          <button className="secondary" onClick={refresh} disabled={busy}>
            {busy ? "Refreshing…" : "Refresh cases"}
          </button>
        </header>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="notice">
          <span className="status-dot" />
          <div>
            <strong>Local foundation · synthetic data</strong>
            <p>
              This milestone includes source detection and background
              processing. Model reasoning, patient conversations and outbound
              messaging are the next milestone.
            </p>
          </div>
        </div>
        <section className="metrics" aria-label="Follow-up totals">
          {(["RECALL_OVERDUE", "UPCOMING", "MISSED"] as const).map(
            (trigger) => (
              <div className="metric" key={trigger}>
                <span>{triggerLabels[trigger]}</span>
                <strong>
                  {busy
                    ? "—"
                    : cases.filter((c) => c.trigger === trigger).length}
                </strong>
                <small>Source-defined follow-up</small>
              </div>
            ),
          )}
        </section>
        <section className="panel">
          <div className="section-heading">
            <div>
              <h2>Follow-up cases</h2>
              <p>
                Dental, myopia and antenatal journeys share the same foundation.
              </p>
            </div>
            <span className="count">{cases.length} cases</span>
          </div>
          {cases.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Patient</th>
                    <th>Specialty</th>
                    <th>Follow-up reason</th>
                    <th>Stage</th>
                    <th>
                      <span className="sr-only">Details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.patient}</strong>
                        <small>{c.source_episode_ref}</small>
                      </td>
                      <td className="capitalize">{c.specialty}</td>
                      <td>{triggerLabels[c.trigger]}</td>
                      <td>
                        <span className="pill">Ready for agent</span>
                      </td>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => setSelected(c)}
                        >
                          View evidence →
                          <span className="sr-only"> for {c.patient}</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty" role="status">
              {busy
                ? "Loading cases…"
                : "No cases yet. Allow the worker a few seconds, then refresh. If this persists, check the worker logs."}
            </p>
          )}
        </section>
        {selected && (
          <section className="panel evidence" aria-labelledby="evidence-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">SOURCE AND PROCESSING EVIDENCE</p>
                <h2 id="evidence-title">{selected.patient}</h2>
              </div>
              <button className="text-button" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
            {loadingEvents ? (
              <p role="status">Loading evidence…</p>
            ) : (
              <ol className="timeline">
                {events.map((e) => (
                  <li key={e.id}>
                    <span className="pill">
                      {e.origin === "rule" ? "Application rule" : e.origin}
                    </span>
                    <strong>{e.event_type.replaceAll("_", " ")}</strong>
                    <p>
                      {e.details.note ??
                        `${triggerLabels[e.details.trigger] ?? e.details.trigger} identified from the clinic source.`}
                    </p>
                    <time>{new Date(e.created_at).toLocaleString()}</time>
                  </li>
                ))}
              </ol>
            )}
          </section>
        )}
        <section className="agents-section">
          <div className="section-heading">
            <div>
              <h2>The agent team</h2>
              <p>
                Defined responsibilities for the next implementation milestone.
              </p>
            </div>
          </div>
          <div className="agent-grid">
            {agents.map((a, i) => (
              <article className="agent-card" key={a.role}>
                <span className="agent-number">0{i + 1}</span>
                <span className="planned">Planned</span>
                <h3>{a.name}</h3>
                <p>{a.goal}</p>
              </article>
            ))}
          </div>
        </section>
        <footer>
          forget-lah · Patient Follow-up · Foundation v0.1.0{" "}
          <span>All patient records shown are synthetic.</span>
        </footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
