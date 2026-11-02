"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Summary = Record<string, Record<string, number>>;
type HazardRow = {
  district: string;
  state_name: string;
  hazard: string;
  risk_score: number | string;
  risk_level: string;
  [key: string]: unknown;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

function isSummary(value: unknown): value is Summary {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) &&
    Object.values(value).every((levels) => levels && typeof levels === "object" && !Array.isArray(levels) &&
      Object.values(levels).every((count) => typeof count === "number" && Number.isFinite(count))));
}

function isHazardRows(value: unknown): value is HazardRow[] {
  return Array.isArray(value) && value.every((row) => row && typeof row === "object" &&
    typeof row.district === "string" && typeof row.state_name === "string" &&
    typeof row.hazard === "string" && typeof row.risk_level === "string" &&
    Number.isFinite(Number(row.risk_score)));
}

export default function Home() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<HazardRow[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState("");

  const hazards = useMemo(() => summary ? Object.keys(summary).sort() : [], [summary]);

  const loadSummary = useCallback(async (accessToken: string) => {
    setLoading(true);
    setError("");
    setValidation("");
    try {
      const response = await fetch(`${API_BASE}/hazards`, { headers: { Authorization: `Bearer ${accessToken}` } });
      if (!response.ok) throw new Error(`Hazard summary request failed (${response.status}).`);
      const payload: unknown = await response.json();
      if (!isSummary(payload)) throw new Error("The API returned a summary that does not match the expected hazard/risk-count schema.");
      setSummary(payload);
      const first = Object.keys(payload).sort()[0] || "";
      setSelected(first);
      setRows([]);
      if (!first) setValidation("The API returned a valid summary with no hazard categories.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load hazard data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!token || !selected) return;
    let active = true;
    const loadingTimer = window.setTimeout(() => { if (active) setLoading(true); }, 0);
    fetch(`${API_BASE}/hazards/${encodeURIComponent(selected)}?limit=100`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`Hazard data request failed (${response.status}).`);
      const payload: unknown = await response.json();
      if (!isHazardRows(payload)) throw new Error("The API returned records that do not match the expected district hazard schema.");
      if (active) {
        setRows(payload);
        if (payload.length === 0) setValidation("No records are available for this hazard category.");
      }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Unable to load hazard records.");
    }).finally(() => { window.clearTimeout(loadingTimer); if (active) setLoading(false); });
    return () => { active = false; window.clearTimeout(loadingTimer); };
  }, [token, selected]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setValidation("");
    if (!username.trim() || !password) {
      setValidation("Enter both a username and password to connect to the protected hazard API.");
      return;
    }
    setLoading(true);
    try {
      const body = new URLSearchParams({ username: username.trim(), password });
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
      });
      if (!response.ok) throw new Error(`Sign-in failed (${response.status}). Check the account and backend status.`);
      const payload: unknown = await response.json();
      if (!payload || typeof payload !== "object" || !("access_token" in payload) || typeof payload.access_token !== "string") {
        throw new Error("The sign-in response is missing the expected access_token field.");
      }
      setToken(payload.access_token);
      setPassword("");
      await loadSummary(payload.access_token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in to RescueMesh.");
    } finally {
      setLoading(false);
    }
  }

  function signOut() {
    setToken(""); setSummary(null); setRows([]); setSelected(""); setError(""); setValidation("");
  }

  function chooseHazard(hazard: string) {
    setError(""); setValidation(""); setRows([]); setSelected(hazard);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="RescueMesh home"><span className="brand-mark">R</span><span>RescueMesh<span className="brand-ai">AI</span></span></a>
        <div className="connection"><span className={`status-dot ${token ? "online" : ""}`} />{token ? "Connected to hazard API" : "Hazard intelligence dashboard"}</div>
      </header>

      <section className="hero" id="home">
        <div><p className="eyebrow">DISASTER RESPONSE · INDIA</p><h1>Hazard overview</h1><p className="subtitle">District risk data supplied by the RescueMesh API.</p></div>
        {token ? <button className="button secondary" onClick={signOut}>Sign out</button> : null}
      </section>

      {!token && <section className="panel sign-in">
        <div><h2>Connect to RescueMesh</h2><p>Sign in to view the hazard summary and district records. Credentials are sent only to the configured backend.</p></div>
        <form onSubmit={login} className="login-form">
          <label>Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <button className="button primary" disabled={loading}>{loading ? "Connecting…" : "Sign in"}</button>
        </form>
        <p className="api-note">API: <code>{API_BASE}</code></p>
      </section>}

      {error && <div className="notice error" role="alert"><strong>Unable to load data</strong><span>{error} Check that the backend is running and its CORS settings allow this frontend origin.</span></div>}
      {validation && <div className="notice validation" role="status"><strong>Data validation</strong><span>{validation}</span></div>}

      {token && <>
        <section className="summary-head"><div><p className="eyebrow">CURRENT DATA</p><h2>Risk distribution</h2></div><span className="freshness">Live from configured API</span></section>
        {loading && !summary && <div className="panel state-panel" role="status">Loading hazard summary…</div>}
        {summary && <div className="summary-grid">
          {hazards.map((hazard) => {
            const levels = summary[hazard];
            const count = Object.values(levels).reduce((sum, n) => sum + n, 0);
            return <button key={hazard} className={`summary-card ${selected === hazard ? "selected" : ""}`} onClick={() => chooseHazard(hazard)}>
              <span className="card-label">{hazard}</span><strong>{count.toLocaleString()}</strong><span className="card-foot">district records · select to inspect</span>
            </button>;
          })}
        </div>}

        {selected && summary && <section className="panel records-panel">
          <div className="records-header"><div><p className="eyebrow">TOP API RESULTS · UP TO 100</p><h2>{selected} districts</h2></div>
            <label className="select-label">Hazard<select value={selected} onChange={(e) => chooseHazard(e.target.value)}>{hazards.map((hazard) => <option key={hazard} value={hazard}>{hazard}</option>)}</select></label>
          </div>
          {loading && <div className="table-state">Loading district records…</div>}
          {!loading && !error && rows.length === 0 && <div className="table-state">No district records were returned for this hazard.</div>}
          {rows.length > 0 && <div className="table-wrap"><table><thead><tr><th>District</th><th>State</th><th>Hazard</th><th>Risk level</th><th className="numeric">Risk score</th></tr></thead>
            <tbody>{rows.map((row, index) => <tr key={`${row.state_name}-${row.district}-${index}`}><td>{row.district}</td><td>{row.state_name}</td><td>{row.hazard}</td><td><span className={`risk-badge ${row.risk_level.toLowerCase()}`}>{row.risk_level}</span></td><td className="numeric">{Number(row.risk_score).toFixed(4)}</td></tr>)}</tbody>
          </table></div>}
        </section>}
      </>}
      <footer>RescueMesh AI <span>·</span> Values shown are returned by the configured backend.</footer>
    </main>
  );
}
