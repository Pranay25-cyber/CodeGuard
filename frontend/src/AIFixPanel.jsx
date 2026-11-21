import { useEffect, useRef, useState } from "react";
import axios from "axios";
import {
  Sparkles,
  Loader2,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  FileCode,
  GitPullRequest,
  ShieldCheck,
  XCircle,
  Info,
} from "lucide-react";

const API_BASE_URL = "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  timeout: 180000,
});

function ValidationCheck({ name, check }) {
  if (!check) return null;

  const passed = check.passed === true;

  return (
    <div className={`validation-check ${passed ? "passed" : "failed"}`}>
      <div className="validation-check-heading">
        {passed ? <CheckCircle size={17} /> : <XCircle size={17} />}
        <strong>{name}</strong>
        <span>{passed ? "Passed" : "Failed"}</span>
      </div>

      {check.message && <p>{check.message}</p>}

      {Array.isArray(check.issues) && check.issues.length > 0 && (
        <ul className="validation-issues">
          {check.issues.map((issue, index) => (
            <li
              key={`${issue.code || "issue"}-${issue.location?.row ?? index}-${index}`}
            >
              <strong>{issue.code || "Issue"}</strong>

              {issue.location?.row != null && (
                <span>
                  {" "}· Line {issue.location.row}
                  {issue.location.column != null
                    ? `, column ${issue.location.column}`
                    : ""}
                </span>
              )}

              <p>{issue.message || "No issue description provided."}</p>

              {issue.fix?.message && (
                <small>Suggested correction: {issue.fix.message}</small>
              )}
            </li>
          ))}
        </ul>
      )}

      {check.errors && (
        <details className="validation-technical-details">
          <summary>Technical details</summary>
          <pre>{check.errors}</pre>
        </details>
      )}
    </div>
  );
}

function ValidationResult({ validation }) {
  if (!validation) return null;

  const syntax = validation.syntax;
  const ruff = validation.ruff;
  const bandit = validation.bandit;

  const checks = [syntax, ruff, bandit].filter(Boolean);
  const passed =
    validation.status === "passed" &&
    checks.length > 0 &&
    checks.every((check) => check.passed === true);

  return (
    <div className="validation-result">
      <div className="validation-result-title">
        <ShieldCheck size={18} />
        <strong>Code Validation</strong>
        <span className={`validation-status ${passed ? "passed" : "failed"}`}>
          {passed ? "All checks passed" : "Validation failed"}
        </span>
      </div>

      <div className="validation-checks">
        <ValidationCheck name="Python syntax" check={syntax} />
        <ValidationCheck name="Ruff" check={ruff} />
        <ValidationCheck name="Bandit" check={bandit} />
      </div>

      {!passed && (
        <p className="validation-guidance">
          <Info size={15} />
          This fix did not pass all required checks. Review the issues above
          and generate a corrected fix. A failed validation result is not
          ready for developer approval.
        </p>
      )}
    </div>
  );
}

export default function AIFixPanel({ selectedRepository = "" }) {
  const [repositoryFullName, setRepositoryFullName] = useState(
    selectedRepository
  );
  const [repositories, setRepositories] = useState([]);
  const [repositorySearch, setRepositorySearch] = useState(selectedRepository);
  const [loadingRepositories, setLoadingRepositories] = useState(false);
  const [repositoryDropdownOpen, setRepositoryDropdownOpen] = useState(false);
  const repositoryDropdownRef = useRef(null);

  const [pullRequests, setPullRequests] = useState([]);
  const [prNumber, setPrNumber] = useState("");
  const [changedFiles, setChangedFiles] = useState([]);
  const [filename, setFilename] = useState("");

  const [loadingPRs, setLoadingPRs] = useState(false);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [loadingFix, setLoadingFix] = useState(false);

  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  // Load repositories available to the signed-in user's GitHub installation.
  useEffect(() => {
    let cancelled = false;

    const fetchGitHubRepositories = async () => {
      setLoadingRepositories(true);

      try {
        const response = await api.get("/github-installations/repositories");
        const data = response.data;
        const repositoryList = Array.isArray(data)
          ? data
          : data?.repositories || data?.items || [];

        if (!cancelled) {
          setRepositories(repositoryList);
        }
      } catch (err) {
        console.error("GitHub repository loading error:", err);
        if (!cancelled) {
          setError(
            err.response?.data?.detail ||
              "Unable to load GitHub repositories."
          );
        }
      } finally {
        if (!cancelled) setLoadingRepositories(false);
      }
    };

    fetchGitHubRepositories();

    return () => {
      cancelled = true;
    };
  }, []);

  // Keep the panel synchronized if a repository is supplied by the parent.
  useEffect(() => {
    if (!selectedRepository) return;

    setRepositoryFullName(selectedRepository);
    setRepositorySearch(selectedRepository);
    setPullRequests([]);
    setPrNumber("");
    setChangedFiles([]);
    setFilename("");
    setResult(null);
    setError("");
  }, [selectedRepository]);

  // Close the repository menu when the user clicks outside it.
  useEffect(() => {
    const handleOutsideClick = (event) => {
      if (
        repositoryDropdownRef.current &&
        !repositoryDropdownRef.current.contains(event.target)
      ) {
        setRepositoryDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const normalizeRepositorySearch = (value) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");

  const filteredRepositories = repositories.filter((repo) => {
    const query = normalizeRepositorySearch(repositorySearch);
    const fullName = normalizeRepositorySearch(repo.full_name || "");
    return !query || fullName.includes(query);
  });

  const selectRepository = (repository) => {
    setRepositorySearch(repository.full_name);
    setRepositoryDropdownOpen(false);
    setError("");

    if (repository.full_name !== repositoryFullName) {
      setRepositoryFullName(repository.full_name);
      setPullRequests([]);
      setPrNumber("");
      setChangedFiles([]);
      setFilename("");
      setResult(null);
    }
  };

  const loadPullRequests = async (selectedRepositoryName = repositoryFullName) => {
    const repository = selectedRepositoryName.trim();

    if (!repository) {
      setError("Select a GitHub repository first.");
      return;
    }

    setLoadingPRs(true);
    setError("");
    setResult(null);
    setPullRequests([]);
    setChangedFiles([]);
    setPrNumber("");
    setFilename("");

    try {
      const response = await api.get("/github/pull-requests", {
        params: {
          repository_full_name: repository,
          limit: 20,
        },
      });

      const prs = response.data?.pull_requests || [];
      setPullRequests(prs);
      if (prs.length === 0) {
  setError("No Pull Requests available in this repository.");
}
    } catch (err) {
      console.error("Pull Request loading error:", err);
      setError(
        err.response?.data?.detail ||
          "Unable to load Pull Requests from GitHub."
      );
    } finally {
      setLoadingPRs(false);
    }
  };

  // Automatically load pull requests whenever the selected repository changes.
  useEffect(() => {
    if (repositoryFullName.trim()) {
      loadPullRequests(repositoryFullName);
    }
    // loadPullRequests is intentionally invoked only when repositoryFullName changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositoryFullName]);

  const handleRepositoryChange = (event) => {
    const value = event.target.value;
    setRepositorySearch(value);
    setRepositoryDropdownOpen(true);

    const selected = repositories.find(
      (repo) => repo.full_name?.toLowerCase() === value.trim().toLowerCase()
    );

    if (selected) {
      selectRepository(selected);
      return;
    }

    // Clear the previous selection while searching for another repository.
    if (repositoryFullName) {
      setRepositoryFullName("");
      setPullRequests([]);
      setPrNumber("");
      setChangedFiles([]);
      setFilename("");
      setResult(null);
      setError("");
    }
  };

  
  const loadChangedFiles = async (selectedPR) => {
    setPrNumber(selectedPR);
    setChangedFiles([]);
    setFilename("");
    setResult(null);
    setError("");

    if (!selectedPR) return;

    setLoadingFiles(true);

    try {
      // 1. Get the changed files from GitHub.
      const filesResponse = await api.get(
        `/github/pull-request/${Number(selectedPR)}`,
        {
          params: {
            repository_full_name: repositoryFullName.trim(),
          },
        }
      );

      const files = filesResponse.data?.changed_files || [];

      const pythonFiles = files.filter(
        (file) =>
          file.filename?.endsWith(".py") &&
          file.status !== "removed"
      );

      if (pythonFiles.length === 0) {
        setError("This Pull Request has no supported Python files.");
        return;
      }

      // 2. Retrieve saved reviews for this exact Pull Request
      // in the currently selected repository.
      const reviewResponse = await api.get(
        `/reviews/pull-request/${Number(selectedPR)}`,
        {
          params: {
            repository_full_name: repositoryFullName.trim(),
          },
        }
      );

      const pullRequestRecord = Array.isArray(reviewResponse.data)
        ? reviewResponse.data[0]
        : reviewResponse.data;

      const reviews = pullRequestRecord?.reviews || [];

      // 3. Select the latest completed review.
      const completedReviews = reviews
        .filter((review) =>
          ["passed", "issues_found", "completed"].includes(
            review.overall_status
          )
        )
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() -
            new Date(a.created_at).getTime()
        );

      const latestReview = completedReviews[0];

      if (!latestReview) {
        setError(
          "No completed code review found for this Pull Request. Run the code review first."
        );
        return;
      }

      // 4. Collect Python file paths that contain findings.
      const normalizeFilePath = (path) =>
        typeof path === "string"
          ? path.replace(/\\/g, "/").replace(/^\.\//, "")
          : "";

      const issueFiles = new Set(
        (latestReview.issues || [])
          .map((issue) => normalizeFilePath(issue.file_path))
          .filter((path) => path.endsWith(".py"))
      );

      // 5. Show only changed Python files that have findings.
      const filesWithErrors = pythonFiles.filter((file) =>
        issueFiles.has(normalizeFilePath(file.filename))
      );

      setChangedFiles(filesWithErrors);

      if (filesWithErrors.length === 0) {
        const reviewFilePaths = (latestReview.files || [])
          .map((file) => file.file_path)
          .filter(Boolean);

        if (latestReview.issues?.length > 0) {
          setError(
            "The latest review contains findings, but none matched the changed Python file paths returned by GitHub. " +
              "Review issue paths: " +
              [...issueFiles].join(", ")
          );
        } else {
          setError(
            "The latest saved review has no findings. " +
              (reviewFilePaths.length
                ? `Reviewed files: ${reviewFilePaths.join(", ")}.`
                : "No reviewed file records were returned.") +
              " If this Pull Request has new changes, run the code review again."
          );
        }
      }
    } catch (err) {
      console.error("Changed files or review loading error:", err);

      setError(
        err.response?.data?.detail ||
          "Unable to retrieve changed files or saved review results."
      );
    } finally {
      setLoadingFiles(false);
    }
  };

  const generateFix = async () => {
    if (!repositoryFullName.trim()) {
      setError("Select a GitHub repository first.");
      return;
    }

    if (!prNumber || !filename) {
      setError("Select a Pull Request and a Python file.");
      return;
    }

    setLoadingFix(true);
    setResult(null);
    setError("");

    try {
      const response = await api.post(
        `/github/pull-request/${Number(prNumber)}/fix`,
        {
          repository_full_name: repositoryFullName.trim(),
          filename,
        }
      );

      setResult(response.data);
    } catch (err) {
      console.error("AI Fix error:", err.response?.data || err);
      const detail = err.response?.data?.detail;

      if (typeof detail === "string") {
        setError(detail);
      } else if (Array.isArray(detail)) {
        setError(
          detail
            .map((item) => {
              const field = Array.isArray(item.loc)
                ? item.loc.join(" → ")
                : "";
              return `${field}: ${item.msg || "Invalid value"}`;
            })
            .join("\n")
        );
      } else {
        setError(
          err.response?.data?.message ||
            err.message ||
            "Unable to generate AI fix."
        );
      }
    } finally {
      setLoadingFix(false);
    }
  };

  const fixId = result?.fix_id ?? result?.id;
  const validation = result?.validation;
  const validationFailed =
    result?.status === "validation_failed" || validation?.status === "failed";

  return (
    <section className="ai-fix-panel">
      <div className="ai-fix-heading">
        <div>
          <h2>
            <Sparkles size={22} />
            AI Automatic Fix
          </h2>
          <p>
            Select a GitHub repository and Pull Request, inspect changed files,
            and generate an AI-powered fix proposal.
          </p>
        </div>
      </div>

      <div className="ai-fix-form">
        <label>
          GitHub Repository
          <div
            ref={repositoryDropdownRef}
            className="repository-search-dropdown"
            style={{ position: "relative", width: "100%" }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                position: "relative",
                width: "100%",
              }}
            >
              <input
                type="text"
                value={repositorySearch}
                onChange={handleRepositoryChange}
                onFocus={() => setRepositoryDropdownOpen(true)}
                placeholder={
                  loadingRepositories
                    ? "Loading repositories..."
                    : "Search and select a repository..."
                }
                disabled={loadingRepositories}
                autoComplete="off"
                aria-label="Search GitHub repositories"
                aria-expanded={repositoryDropdownOpen}
                aria-controls="github-repository-menu"
                style={{ width: "100%", paddingRight: "42px" }}
              />
              <button
                type="button"
                aria-label={
                  repositoryDropdownOpen
                    ? "Close repository list"
                    : "Open repository list"
                }
                onClick={() => {
                  if (repositoryDropdownOpen) {
                    setRepositoryDropdownOpen(false);
                  } else {
                    setRepositorySearch("");
                    setRepositoryDropdownOpen(true);
                  }
                }}
                disabled={loadingRepositories || repositories.length === 0}
                style={{
                  position: "absolute",
                  right: "4px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  border: "none",
                  background: "transparent",
                  color: "inherit",
                  cursor: "pointer",
                  padding: "8px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    borderLeft: "5px solid transparent",
                    borderRight: "5px solid transparent",
                    borderTop: "6px solid currentColor",
                    transform: repositoryDropdownOpen ? "rotate(180deg)" : "none",
                    transition: "transform 150ms ease",
                  }}
                />
              </button>
            </div>

            {repositoryDropdownOpen && !loadingRepositories && (
              <div
                id="github-repository-menu"
                role="listbox"
                aria-label="GitHub repositories"
                style={{
                  position: "absolute",
                  zIndex: 1000,
                  top: "calc(100% + 6px)",
                  left: 0,
                  right: 0,
                  maxHeight: "240px",
                  overflowY: "auto",
                  background: "#202033",
                  border: "1px solid #6650b5",
                  borderRadius: "8px",
                  boxShadow: "0 8px 24px rgba(0, 0, 0, 0.35)",
                  padding: "5px",
                }}
              >
                {filteredRepositories.length > 0 ? (
                  filteredRepositories.map((repo) => {
                    const isSelected = repo.full_name === repositoryFullName;

                    return (
                      <button
                        key={repo.id || repo.full_name}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => selectRepository(repo)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          width: "100%",
                          textAlign: "left",
                          padding: "10px 12px",
                          border: "none",
                          borderRadius: "5px",
                          background: isSelected ? "#40346f" : "transparent",
                          color: "#f5f3ff",
                          cursor: "pointer",
                          fontSize: "14px",
                        }}
                        onMouseEnter={(event) => {
                          event.currentTarget.style.background = "#40346f";
                        }}
                        onMouseLeave={(event) => {
                          event.currentTarget.style.background = isSelected
                            ? "#40346f"
                            : "transparent";
                        }}
                      >
                        <span>{repo.full_name}</span>
                        {isSelected && <CheckCircle size={16} />}
                      </button>
                    );
                  })
                ) : (
                  <p
                    style={{
                      margin: 0,
                      padding: "12px",
                      color: "#c4bfd8",
                      fontSize: "13px",
                    }}
                  >
                    No matching repositories found.
                  </p>
                )}
              </div>
            )}
          </div>
        </label>

        {loadingRepositories && (
          <p className="ai-fix-loading">
            <Loader2 className="spin" size={16} />
            Loading GitHub repositories...
          </p>
        )}

        {!loadingRepositories && repositories.length === 0 && !error && (
          <p className="ai-fix-help">
            <Info size={15} />
            No GitHub repositories were returned. Check your GitHub App
            installation and try refreshing the page.
          </p>
        )}

        {repositoryFullName && (
          <p className="ai-fix-help">
            <Info size={15} />
            Selected repository: <strong>{repositoryFullName}</strong>
          </p>
        )}

        <button
          type="button"
          className="ai-fix-button"
          onClick={() => loadPullRequests()}
          disabled={loadingPRs || !repositoryFullName.trim()}
        >
          {loadingPRs ? (
            <>
              <Loader2 className="spin" size={18} />
              Loading Pull Requests...
            </>
          ) : (
            <>
              <RefreshCw size={18} />
              Refresh Pull Requests
            </>
          )}
        </button>

        <label>
          <GitPullRequest size={16} />
          GitHub Pull Request
          <select
            value={prNumber}
            onChange={(event) => loadChangedFiles(event.target.value)}
            disabled={pullRequests.length === 0 || loadingPRs}
          >
            <option value="">
              {loadingPRs ? "Loading Pull Requests..." : "Select a Pull Request"}
            </option>
            {pullRequests.map((pr) => (
              <option key={pr.number} value={pr.number}>
                #{pr.number} - {pr.title}
              </option>
            ))}
          </select>
        </label>

        {loadingFiles && (
          <p className="ai-fix-loading">
            <Loader2 className="spin" size={16} />
            Loading changed files...
          </p>
        )}

        <label>
          <FileCode size={16} />
          Changed Python File
          <select
            value={filename}
            onChange={(event) => {
              setFilename(event.target.value);
              setResult(null);
              setError("");
            }}
            disabled={changedFiles.length === 0 || loadingFiles}
          >
            <option value="">Select a changed file</option>
            {changedFiles.map((file) => (
              <option key={file.filename} value={file.filename}>
                {file.filename}
              </option>
            ))}
          </select>
        </label>

        {filename && (
          <div className="selected-file-info">
            <strong>Selected file:</strong> {filename}
          </div>
        )}

        <button
          type="button"
          className="ai-fix-button"
          onClick={generateFix}
          disabled={
            loadingFix ||
            !repositoryFullName.trim() ||
            !prNumber ||
            !filename ||
            loadingFiles
          }
        >
          {loadingFix ? (
            <>
              <Loader2 className="spin" size={18} />
              Generating AI Fix...
            </>
          ) : (
            <>
              <Sparkles size={18} />
              Generate AI Fix
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="ai-fix-error" role="alert">
          <AlertTriangle size={20} />
          <pre style={{ whiteSpace: "pre-wrap" }}>{error}</pre>
        </div>
      )}

      {result && (
        <div className="ai-fix-result">
          <h3>
            <CheckCircle color="green" />
            Changes Summary
          </h3>
          <p>
            {result.changes_summary || "No changes summary was returned."}
          </p>
        </div>
      )}
    </section>
  );
}
