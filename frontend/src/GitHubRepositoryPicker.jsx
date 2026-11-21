
import { useEffect, useState } from "react";
import axios from "axios";
import {
  
  Search,
  RefreshCw,
  Loader2,
  GitBranch,
  Lock,
  Globe,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";

const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: true,
  timeout: 20000,
});

export default function GitHubRepositoryPicker({
  selectedRepository = "",
  onRepositorySelect,
}) {
  const [installed, setInstalled] = useState(false);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [repositories, setRepositories] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);

  const checkInstallation = async () => {
    setCheckingStatus(true);
    setError("");
    setLoginRequired(false);

    try {
      const response = await api.get("/github-installations/status");
      const connected = Boolean(
        response.data?.installed ||
        response.data?.connected ||
        response.data?.installation_id
      );

      setInstalled(connected);
    } catch (err) {
      if (err.response?.status === 401) {
        setLoginRequired(true);
      } else {
        setError(
          err.response?.data?.detail ||
          "Unable to check GitHub App installation."
        );
      }
      setInstalled(false);
    } finally {
      setCheckingStatus(false);
    }
  };

  const loadRepositories = async (query = "") => {
    setLoading(true);
    setError("");

    try {
      const response = await api.get(
        "/github-installations/repositories",
        {
          params: { search: query },
        }
      );

      setRepositories(response.data.repositories || []);
    } catch (err) {
      if (err.response?.status === 401) {
        setLoginRequired(true);
      }

      setError(
        err.response?.data?.detail ||
        "Unable to load GitHub repositories."
      );
      setRepositories([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkInstallation();
  }, []);

  useEffect(() => {
    if (!installed) return;

    const timeoutId = setTimeout(() => {
      loadRepositories(search.trim());
    }, 350);

    return () => clearTimeout(timeoutId);
  }, [search, installed]);

  const connectGitHubApp = () => {
    window.location.href =
      "http://localhost:8000/github-installations/connect";
  };

  const signInWithGitHub = () => {
    window.location.href =
      "http://localhost:8000/auth/github/login";
  };

  return (
    <section className="github-picker">
      <div className="github-picker-heading">
        <div>
          <h3>
            <GitBranch size={21} />
            GitHub App Connection
          </h3>
          <p>
            Connect your GitHub account and select a repository
            that you want CodeGuard to review.
          </p>
        </div>

        <button
          type="button"
          className="github-picker-refresh"
          onClick={checkInstallation}
          disabled={checkingStatus}
          title="Refresh installation status"
        >
          <RefreshCw
            size={17}
            className={checkingStatus ? "spin" : ""}
          />
        </button>
      </div>

      {checkingStatus ? (
        <div className="github-picker-message">
          <Loader2 className="spin" size={18} />
          Checking GitHub connection...
        </div>
      ) : loginRequired ? (
        <div className="github-picker-connect">
          <p>Sign in with GitHub before connecting the GitHub App.</p>
          <button type="button" onClick={signInWithGitHub}>
            <GitBranch size={18} />
            Sign in with GitHub
          </button>
        </div>
      ) : !installed ? (
        <div className="github-picker-connect">
          <p>
            Your GitHub App is not connected yet. Install CodeGuard
            on your GitHub account or organization to continue.
          </p>

          <button type="button" onClick={connectGitHubApp}>
            <GitBranch size={18} />
            Connect GitHub Repositories
          </button>
        </div>
      ) : (
        <>
          <div className="github-picker-connected">
            <CheckCircle2 size={17} />
            GitHub App connected
          </div>

          <label className="github-picker-search">
            <Search size={18} />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search repositories by name or owner..."
            />
          </label>

          {error && (
            <div className="github-picker-error">
              <AlertTriangle size={18} />
              {error}
            </div>
          )}

          {loading ? (
            <div className="github-picker-message">
              <Loader2 className="spin" size={18} />
              Searching GitHub repositories...
            </div>
          ) : repositories.length === 0 ? (
            <div className="github-picker-message">
              No repositories found. Check the search term or
              GitHub App installation permissions.
            </div>
          ) : (
            <div className="github-repository-list">
              {repositories.map((repository) => {
                const fullName = repository.full_name;
                const selected = selectedRepository === fullName;

                return (
                  <button
                    type="button"
                    key={repository.id}
                    className={`github-repository-option ${
                      selected ? "selected" : ""
                    }`}
                    onClick={() => onRepositorySelect?.(repository)}
                  >
                    <span className="github-repository-icon">
                      <GitBranch size={20} />
                    </span>

                    <span className="github-repository-details">
                      <strong>{fullName}</strong>
                      <small>
                        {repository.private ? (
                          <>
                            <Lock size={13} /> Private
                          </>
                        ) : (
                          <>
                            <Globe size={13} /> Public
                          </>
                        )}
                        {repository.default_branch
                          ? ` · ${repository.default_branch}`
                          : ""}
                      </small>
                    </span>

                    {selected && (
                      <CheckCircle2
                        className="github-repository-selected"
                        size={19}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}
