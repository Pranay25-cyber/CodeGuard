import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import {
  ShieldCheck,
  LogOut,
  RefreshCw,
  CheckCircle,
  XCircle,
  Eye,
  Loader2,
  AlertTriangle,
  FileCode2,
  GitPullRequest,
  Clock3,
  X,
} from "lucide-react";

const api = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 30000,
  withCredentials: true,
});

const buttonBase = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "8px",
  width: "auto",
  minHeight: "38px",
  padding: "9px 16px",
  border: "1px solid transparent",
  borderRadius: "8px",
  color: "#ffffff",
  fontSize: "13px",
  fontWeight: 600,
  cursor: "pointer",
};

const buttonDisabled = {
  opacity: 0.55,
  cursor: "not-allowed",
};

export default function FixApprovalPanel() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [proposals, setProposals] = useState([]);
  const [selectedProposal, setSelectedProposal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // A synchronous lock prevents rapid double-clicks before React re-renders.
  // It is held until the server responds; after success the page reloads.
  const decisionLockRef = useRef(new Set());

  const loadProposals = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await api.get("/fixes/");
      const allProposals = Array.isArray(response.data) ? response.data : [];

      setProposals(
        allProposals.filter(
          (proposal) => proposal.status === "pending_approval"
        )
      );
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          err.message ||
          "Unable to load fix proposals."
      );

      if (err.response?.status === 401) {
        setUser(null);
        setProposals([]);
        setSelectedProposal(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const checkSession = useCallback(async () => {
    setAuthChecking(true);
    setError("");

    try {
      const response = await api.get("/auth/me");
      setUser(response.data);
    } catch (err) {
      if (err.response?.status !== 401) {
        setError(
          err.response?.data?.detail ||
            "Unable to verify your GitHub login session."
        );
      }
      setUser(null);
    } finally {
      setAuthChecking(false);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  useEffect(() => {
    if (user) loadProposals();
  }, [user, loadProposals]);

  const loginWithGitHub = () => {
    window.location.assign("http://localhost:8000/auth/github/login");
  };

  const logout = async () => {
    setError("");
    setMessage("");

    try {
      await api.post("/auth/logout");
      setUser(null);
      setProposals([]);
      setSelectedProposal(null);
      setMessage("You have signed out of GitHub.");
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Unable to sign out. Please try again."
      );
    }
  };

  const previewProposal = async (fixId) => {
    if (actionLoading !== null || decisionLockRef.current.has(fixId)) return;

    setError("");
    setMessage("");

    try {
      const response = await api.get(`/fixes/${fixId}`);
      if (response.data?.status !== "pending_approval") {
        setSelectedProposal(null);
        setMessage("This proposal has already been processed. Refreshing the list.");
        await loadProposals();
        return;
      }
      setSelectedProposal(response.data);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Unable to load proposal preview."
      );

      if (err.response?.status === 401) setUser(null);
      if (err.response?.status === 404 || err.response?.status === 409) {
        setSelectedProposal(null);
        await loadProposals();
      }
    }
  };

  const handleDecision = async (fixId, decision) => {
    // Lock synchronously before showing confirmation so a second click
    // cannot start another approval/rejection request.
    if (decisionLockRef.current.has(fixId)) return;

    const proposal = proposals.find((item) => item.id === fixId);
    if (!proposal || proposal.status !== "pending_approval") {
      setError("This proposal is no longer pending approval. Refresh the proposals.");
      setSelectedProposal(null);
      await loadProposals();
      return;
    }

    decisionLockRef.current.add(fixId);

    const action = decision === "approve" ? "approve" : "reject";
    const confirmed = window.confirm(
      decision === "approve"
        ? `Approve Fix #${fixId}? This updates the file on the existing pull request source branch. It will not create a new branch or pull request.`
        : `Reject Fix #${fixId}? No changes will be published to GitHub.`
    );

    if (!confirmed) {
      decisionLockRef.current.delete(fixId);
      return; 
    }

    setActionLoading(fixId);
    setError("");
    setMessage("");

    try {
      await api.post(`/fixes/${fixId}/${action}`);

      // Remove it locally immediately so neither action can be selected again.
      setProposals((current) =>
        current.filter((item) => item.id !== fixId)
      );
      setSelectedProposal(null);
      setMessage(
        decision === "approve"
          ? `Fix #${fixId} approved and published successfully. Reloading...`
          : `Fix #${fixId} rejected successfully. Reloading...`
      );

      // Keep the decision lock active. The fresh page will reload proposal
      // statuses from the backend, where this proposal is no longer pending.
      window.setTimeout(() => {
        window.location.reload();
      }, 800);
    } catch (err) {
      const status = err.response?.status;

      if (status === 409 || status === 404) {
        setSelectedProposal(null);
        setMessage(
          "This proposal has already been processed or is no longer available. The list has been refreshed."
        );
        await loadProposals();
      } else {
        setError(
          err.response?.data?.detail ||
            err.message ||
            `Unable to ${action} this proposal.`
        );
      }

      // Allow retry only when the server did not confirm the decision.
      decisionLockRef.current.delete(fixId);

      if (status === 401) setUser(null);
    } finally {
      setActionLoading(null);
    }
  };

  const actionInProgress = actionLoading !== null;

  if (authChecking) {
    return (
      <section className="ai-fix-panel">
        <div className="ai-fix-heading">
          <h2>
            <ShieldCheck size={22} /> Developer Approval Center
          </h2>
        </div>
        <p>Checking your GitHub login session...</p>
      </section>
    );
  }

  if (!user) {
    return (
      <section className="ai-fix-panel">
        <div className="ai-fix-heading">
          <h2>
            <ShieldCheck size={22} /> Developer Approval Center
          </h2>
          <p>
            Sign in with GitHub to review and approve your AI-generated fixes.
          </p>
        </div>

        <button
          type="button"
          onClick={loginWithGitHub}
          style={{
            ...buttonBase,
            background: "#7050dc",
            marginTop: "12px",
          }}
        >
          <ShieldCheck size={17} />
          Sign in with GitHub
        </button>

        {error && (
          <div className="ai-fix-error">
            <AlertTriangle size={20} />
            <span>{error}</span>
          </div>
        )}
        {message && <p className="approval-notice">{message}</p>}
      </section>
    );
  }

  return (
    <section className="ai-fix-panel">
      <div className="ai-fix-heading">
        <div>
          <h2>
            <ShieldCheck size={22} /> Developer Approval Center
          </h2>
          <p>
            Signed in as <strong>{user.github_login}</strong>. Review AI fixes
            before publishing them to GitHub.
          </p>
        </div>
      </div>

      <div
        className="approval-toolbar"
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "14px",
          margin: "18px 0 22px",
        }}
      >
        <button
          type="button"
          onClick={logout}
          disabled={actionInProgress}
          style={{
            ...buttonBase,
            ...(actionInProgress ? buttonDisabled : {}),
            background: "#7050dc",
            minWidth: "112px",
          }}
        >
          <LogOut size={17} />
          Sign out
        </button>

        <button
          type="button"
          onClick={loadProposals}
          disabled={loading || actionInProgress}
          style={{
            ...buttonBase,
            ...(loading || actionInProgress ? buttonDisabled : {}),
            background: "#7050dc",
            minWidth: "176px",
          }}
        >
          {loading ? (
            <Loader2 className="spin" size={17} />
          ) : (
            <RefreshCw size={17} />
          )}
          {loading ? "Refreshing..." : "Refresh Proposals"}
        </button>
      </div>

      {error && (
        <div className="ai-fix-error">
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {message && <p className="approval-notice">{message}</p>}

      <div className="approval-list">
        <h3>Pending Fix Proposals</h3>

        {loading && proposals.length === 0 && <p>Loading proposals...</p>}

        {!loading && proposals.length === 0 && (
          <p>No pending fix proposals. Generate an AI fix to see it here.</p>
        )}

        {proposals.map((proposal) => {
          const proposalLocked =
            actionInProgress || decisionLockRef.current.has(proposal.id);

          return (
            <article className="approval-card" key={proposal.id}>
              <div className="approval-card-content">
                <h4>
                  <FileCode2 size={17} />
                  Fix #{proposal.id} — {proposal.filename}
                </h4>

                <p>Repository: {proposal.repository_full_name}</p>

                <p>
                  <GitPullRequest size={14} />
                  Original PR: #{proposal.original_pr_number}
                </p>

                <p>
                  <Clock3 size={14} />
                  Status: <strong>{proposal.status}</strong>
                </p>

                {proposal.changes_summary && (
                  <p className="approval-summary">
                    {proposal.changes_summary}
                  </p>
                )}
              </div>

              <div className="approval-actions">
                <button
                  type="button"
                  className="preview-button"
                  onClick={() => previewProposal(proposal.id)}
                  disabled={proposalLocked}
                  style={{
                    ...buttonBase,
                    ...(proposalLocked ? buttonDisabled : {}),
                    background: "#3977c9",
                  }}
                >
                  <Eye size={16} />
                  Preview
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {selectedProposal && (
        <div
          className="approval-preview"
          role="dialog"
          aria-modal="true"
          aria-labelledby="fix-preview-title"
          style={{
            marginTop: "20px",
            padding: "18px",
            border: "1px solid #45445f",
            borderRadius: "10px",
            background: "#171827",
          }}
        >
          <div
            className="approval-preview-heading"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "12px",
            }}
          >
            <h3 id="fix-preview-title">
              Fix #{selectedProposal.id} — Code Preview
            </h3>

            <button
              type="button"
              onClick={() => setSelectedProposal(null)}
              aria-label="Close preview"
              disabled={actionInProgress}
              style={{
                ...buttonBase,
                ...(actionInProgress ? buttonDisabled : {}),
                background: "#45445f",
                minHeight: "32px",
                padding: "6px 9px",
              }}
            >
              <X size={17} />
            </button>
          </div>

          <p>
            <strong>Status:</strong> {selectedProposal.status}
          </p>
          <p>
            <strong>File:</strong> {selectedProposal.filename}
          </p>

          <h4>Original code</h4>
          <pre className="approval-code">
            {selectedProposal.original_code || "Not available"}
          </pre>

          <h4>AI corrected code</h4>
          <pre className="approval-code">
            {selectedProposal.fixed_code || "Not available"}
          </pre>

          {selectedProposal.status === "pending_approval" && (
            <div
              className="approval-actions"
              style={{
                display: "flex",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "12px",
                marginTop: "16px",
              }}
            >
              <button
                type="button"
                onClick={() =>
                  handleDecision(selectedProposal.id, "approve")
                }
                disabled={
                  actionInProgress ||
                  decisionLockRef.current.has(selectedProposal.id)
                }
                style={{
                  ...buttonBase,
                  ...(actionInProgress ||
                  decisionLockRef.current.has(selectedProposal.id)
                    ? buttonDisabled
                    : {}),
                  background: "#16834a",
                }}
              >
                {actionLoading === selectedProposal.id ? (
                  <Loader2 className="spin" size={16} />
                ) : (
                  <CheckCircle size={16} />
                )}
                {actionLoading === selectedProposal.id
                  ? "Processing..."
                  : "Approve Fix"}
              </button>

              <button
                type="button"
                onClick={() =>
                  handleDecision(selectedProposal.id, "reject")
                }
                disabled={
                  actionInProgress ||
                  decisionLockRef.current.has(selectedProposal.id)
                }
                style={{
                  ...buttonBase,
                  ...(actionInProgress ||
                  decisionLockRef.current.has(selectedProposal.id)
                    ? buttonDisabled
                    : {}),
                  background: "#c43d4b",
                }}
              >
                <XCircle size={16} />
                Reject Fix
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
