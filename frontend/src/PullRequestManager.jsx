import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { ExternalLink, GitPullRequest, RefreshCw, XCircle, AlertCircle, CheckCircle2 } from "lucide-react";

const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: true,
  timeout: 30000,
});

const panelStyle = {
  background: "#191a29",
  border: "1px solid #303247",
  borderRadius: 12,
  padding: 16,
};

const fieldStyle = {
  width: "100%",
  minHeight: 40,
  padding: "9px 11px",
  color: "#e5e7eb",
  background: "#101827",
  border: "1px solid #3b4058",
  borderRadius: 8,
};

export default function PullRequestManager({ onUpdated }) {
  const [repositories, setRepositories] = useState([]);
  const [repository, setRepository] = useState("");
  const [branches, setBranches] = useState([]);
  const [branch, setBranch] = useState("");
  const [state, setState] = useState("open");
  const [pullRequests, setPullRequests] = useState([]);
  const [loadingRepositories, setLoadingRepositories] = useState(false);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [loadingPRs, setLoadingPRs] = useState(false);
  const [closingNumber, setClosingNumber] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const explainError = (err) => err.response?.data?.detail || err.message || "Unable to complete the request.";

  useEffect(() => {
    let cancelled = false;
    setLoadingRepositories(true);
    api.get("/github-installations/repositories")
      .then((res) => {
        if (cancelled) return;
        const items = res.data.repositories || res.data.items || [];
        setRepositories(items);
        if (items.length) setRepository(items[0].full_name || items[0].name || "");
      })
      .catch((err) => { if (!cancelled) setError(explainError(err)); })
      .finally(() => { if (!cancelled) setLoadingRepositories(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!repository) {
      setBranches([]);
      setBranch("");
      return undefined;
    }
    let cancelled = false;
    setLoadingBranches(true);
    setBranches([]);
    setBranch("");
    setPullRequests([]);
    api.get("/code-editor/branches", { params: { repository_full_name: repository } })
      .then((res) => {
        if (cancelled) return;
        const items = res.data.branches || [];
        setBranches(items);
        const preferred = items.find((item) => item.name === "main") || items[0];
        setBranch(preferred?.name || "");
      })
      .catch((err) => { if (!cancelled) setError(explainError(err)); })
      .finally(() => { if (!cancelled) setLoadingBranches(false); });
    return () => { cancelled = true; };
  }, [repository]);

  const fetchPullRequests = useCallback(async () => {
    if (!repository) {
      setPullRequests([]);
      return;
    }
    setLoadingPRs(true);
    setError("");
    try {
      const res = await api.get("/code-editor/pull-requests/list", {
        params: {
          repository_full_name: repository,
          state,
          ...(branch ? { head_branch: branch } : {}),
        },
      });
      setPullRequests(res.data.pull_requests || []);
    } catch (err) {
      setError(explainError(err));
      setPullRequests([]);
    } finally {
      setLoadingPRs(false);
    }
  }, [repository, branch, state]);

  useEffect(() => {
    if (repository && !loadingBranches) fetchPullRequests();
  }, [repository, branch, state, loadingBranches, fetchPullRequests]);

  const closePullRequest = async (pr) => {
    if (!window.confirm(`Close Pull Request #${pr.number} on GitHub?`)) return;
    setClosingNumber(pr.number);
    setError("");
    setMessage("");
    try {
      const res = await api.patch(
        `/code-editor/pull-requests/${pr.number}/close`,
        null,
        { params: { repository_full_name: repository } }
      );
      setMessage(res.data.message || `Pull Request #${pr.number} closed on GitHub.`);
      await fetchPullRequests();
      if (onUpdated) await onUpdated();
    } catch (err) {
      setError(explainError(err));
    } finally {
      setClosingNumber(null);
    }
  };

  return (
    <section style={{ ...panelStyle, marginTop: 22, display: "grid", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: "#f8fafc", fontSize: 19 }}>Manage Pull Requests</h2>
          <p style={{ margin: "5px 0 0", color: "#94a3b8", fontSize: 13 }}>View live GitHub pull requests and close open requests directly from CodeGuard.</p>
        </div>
        <button type="button" onClick={fetchPullRequests} disabled={!repository || loadingPRs} style={{ ...fieldStyle, width: "auto", display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <label style={{ display: "grid", gap: 6, color: "#cbd5e1", fontSize: 12 }}>
          Repository
          <select value={repository} onChange={(e) => setRepository(e.target.value)} style={fieldStyle} disabled={loadingRepositories}>
            <option value="">{loadingRepositories ? "Loading repositories..." : "Select repository"}</option>
            {repositories.map((repo) => {
              const fullName = repo.full_name || repo.name;
              return <option key={fullName} value={fullName}>{fullName}</option>;
            })}
          </select>
        </label>
        <label style={{ display: "grid", gap: 6, color: "#cbd5e1", fontSize: 12 }}>
          Branch
          <select value={branch} onChange={(e) => setBranch(e.target.value)} style={fieldStyle} disabled={!repository || loadingBranches}>
            <option value="">All branches</option>
            {branches.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
          </select>
        </label>
      </div>

      <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #303247", paddingBottom: 10 }}>
        {[{ value: "open", label: "Open Pull Requests" }, { value: "closed", label: "Closed Pull Requests" }].map((tab) => (
          <button key={tab.value} type="button" onClick={() => setState(tab.value)} style={{ border: state === tab.value ? "1px solid #8b5cf6" : "1px solid #3b4058", background: state === tab.value ? "rgba(139,92,246,.16)" : "#101827", color: state === tab.value ? "#c4b5fd" : "#cbd5e1", borderRadius: 8, padding: "9px 13px", cursor: "pointer", fontWeight: 650 }}>
            {tab.label}
          </button>
        ))}
      </div>

      {error && <div role="alert" style={{ color: "#fecaca", background: "rgba(127,29,29,.25)", border: "1px solid #7f1d1d", borderRadius: 8, padding: 11, display: "flex", gap: 8 }}><AlertCircle size={17} />{error}</div>}
      {message && <div role="status" style={{ color: "#86efac", background: "rgba(22,163,74,.10)", border: "1px solid rgba(22,163,74,.35)", borderRadius: 8, padding: 11, display: "flex", gap: 8 }}><CheckCircle2 size={17} />{message}</div>}

      {loadingPRs || loadingBranches ? (
        <p style={{ color: "#93c5fd" }}>Loading pull requests from GitHub...</p>
      ) : !repository ? (
        <p style={{ color: "#94a3b8" }}>Select a repository to view its pull requests.</p>
      ) : pullRequests.length === 0 ? (
        <div style={{ color: "#94a3b8", padding: 22, textAlign: "center", border: "1px dashed #3b4058", borderRadius: 10 }}>
          <GitPullRequest size={24} style={{ marginBottom: 8 }} />
          <div>No {state} pull requests found for this selection.</div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {pullRequests.map((pr) => (
            <article key={pr.number} style={{ border: "1px solid #303247", borderRadius: 10, padding: 14, display: "flex", justifyContent: "space-between", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ minWidth: 220, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "#e5e7eb" }}>#{pr.number} {pr.title}</strong>
                  <span style={{ color: pr.state === "open" ? "#86efac" : "#cbd5e1", background: pr.state === "open" ? "rgba(34,197,94,.12)" : "rgba(148,163,184,.12)", borderRadius: 20, padding: "3px 8px", fontSize: 11 }}>{pr.state}</span>
                  {pr.draft && <span style={{ color: "#c4b5fd", fontSize: 11 }}>Draft</span>}
                </div>
                <p style={{ margin: "7px 0 0", color: "#94a3b8", fontSize: 12 }}>{pr.head_branch} → {pr.base_branch} · by {pr.user || "GitHub user"}</p>
                {pr.updated_at && <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 11 }}>Updated {new Date(pr.updated_at).toLocaleString()}</p>}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {pr.html_url && <a href={pr.html_url} target="_blank" rel="noopener noreferrer" style={{ color: "#93c5fd", display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, textDecoration: "none" }}>View on GitHub <ExternalLink size={13} /></a>}
                {state === "open" && <button type="button" onClick={() => closePullRequest(pr)} disabled={closingNumber !== null} style={{ border: "1px solid rgba(248,113,113,.45)", background: "rgba(127,29,29,.22)", color: "#fca5a5", borderRadius: 8, padding: "8px 11px", display: "inline-flex", alignItems: "center", gap: 6, cursor: closingNumber !== null ? "not-allowed" : "pointer", opacity: closingNumber !== null && closingNumber !== pr.number ? .55 : 1 }}>
                  <XCircle size={14} /> {closingNumber === pr.number ? "Closing..." : "Close PR"}
                </button>}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
