import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { FileCode2, FolderGit2, GitBranch, Save, RefreshCw, Plus, AlertCircle, CheckCircle2, Pencil, Upload, Trash2 } from "lucide-react";

const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: true,
  timeout: 30000,
});

export default function CodeEditor({ repositoryRefreshKey = 0 }) {
  const [repositories, setRepositories] = useState([]);
  const [repository, setRepository] = useState("");
  const [repositorySearch, setRepositorySearch] = useState("");
  const [repositoryDropdownOpen, setRepositoryDropdownOpen] = useState(false);
  const repositoryDropdownRef = useRef(null);
  const [branches, setBranches] = useState([]);
  const [branch, setBranch] = useState("");
  const [files, setFiles] = useState([]);
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  const [newPath, setNewPath] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [commitMessage, setCommitMessage] = useState("Update Python file using CodeGuard");
  const [prTitle, setPrTitle] = useState("CodeGuard changes");
  const [prBody, setPrBody] = useState("Changes created and committed using the CodeGuard editor.");
  const [creatingPR, setCreatingPR] = useState(false);
  const [pullRequest, setPullRequest] = useState(null);
  const [existingPullRequest, setExistingPullRequest] = useState(null);
  const [newBranchName, setNewBranchName] = useState("");
  const [creatingBranch, setCreatingBranch] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewData, setReviewData] = useState(null);
  const [reviewError, setReviewError] = useState("");
  const reviewRequestRef = useRef(0);
  const saveLockRef = useRef(false);
  const createPRLockRef = useRef(false);
  const fileInputRef = useRef(null);

  const explainError = (err) => err.response?.data?.detail || err.message || "Something went wrong.";

  const normalizeRepositorySearch = (value) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");

  const filteredRepositories = repositories.filter((repo) => {
    const query = normalizeRepositorySearch(repositorySearch);
    const fullName = normalizeRepositorySearch(repo.full_name || "");
    return !query || fullName.includes(query);
  });

  const selectRepository = (repo) => {
    setRepositorySearch(repo.full_name);
    setRepositoryDropdownOpen(false);
    setError("");
    if (repo.full_name !== repository) {
      setRepository(repo.full_name);
    }
  };

  const handleRepositorySearch = (event) => {
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

    // Clear the active repository while the user searches for another one.
    if (repository) {
      setRepository("");
    }
  };

  // Review the exact source loaded into the editor. The request ID prevents
  // a slow response for an older file from replacing the currently selected file's review.
  const runAiReview = async (filePath, fileContent) => {
    const requestId = ++reviewRequestRef.current;
    setReviewData(null);
    setReviewError("");

    if (!filePath || !filePath.toLowerCase().endsWith(".py") || !fileContent.trim()) {
      setReviewLoading(false);
      return;
    }

    setReviewLoading(true);
    try {
      const res = await api.post("/code-editor/review", {
        repository_full_name: repository,
        branch,
        path: filePath,
        content: fileContent,
      });
      if (requestId === reviewRequestRef.current) setReviewData(res.data);
    } catch (err) {
      if (requestId === reviewRequestRef.current) setReviewError(explainError(err));
    } finally {
      if (requestId === reviewRequestRef.current) setReviewLoading(false);
    }
  };


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

  useEffect(() => {
    let cancelled = false;
    const loadRepositories = () => {
      api.get("/github-installations/repositories")
        .then((res) => {
          if (!cancelled) setRepositories(res.data.repositories || []);
        })
        .catch((err) => {
          if (!cancelled) setError(explainError(err));
        });
    };
    loadRepositories();
    window.addEventListener("codeguard:repositories-updated", loadRepositories);
    return () => {
      cancelled = true;
      window.removeEventListener("codeguard:repositories-updated", loadRepositories);
    };
  }, [repositoryRefreshKey]);

  useEffect(() => {
    let cancelled = false;
    // A repository change must immediately clear data from the previous selection.
    setBranches([]);
    setBranch("");
    setFiles([]);
    setPath("");
    setContent("");
    setCreating(false);
    reviewRequestRef.current += 1;
    setReviewData(null);
    setReviewError("");
    setReviewLoading(false);
    if (!repository) {
      setLoading(false);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setError("");
    setMessage("");
    api.get("/code-editor/branches", { params: { repository_full_name: repository } })
      .then((res) => {
        if (cancelled) return;
        // Do not silently choose a branch: require the user to select one.
        setBranches(res.data.branches || []);
      })
      .catch((err) => { if (!cancelled) setError(explainError(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [repository]);

  useEffect(() => {
    let cancelled = false;
    // Never retain or show files from a previously selected branch.
    setFiles([]);
    setPath("");
    setContent("");
    setCreating(false);
    reviewRequestRef.current += 1;
    setReviewData(null);
    setReviewError("");
    setReviewLoading(false);
    if (!repository || !branch) {
      setLoading(false);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setError("");
    setPullRequest(null);
    setExistingPullRequest(null);
    api.get("/code-editor/files", { params: { repository_full_name: repository, branch } })
      .then((res) => { if (!cancelled) setFiles(res.data.files || []); })
      .catch((err) => { if (!cancelled) setError(explainError(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    if (branch !== "main") {
      api.get("/code-editor/pull-requests/existing", {
        params: { repository_full_name: repository, head_branch: branch },
      }).then((res) => {
        if (!cancelled) setExistingPullRequest(res.data.exists ? res.data.pull_request : null);
      }).catch((err) => {
        if (!cancelled) setError(explainError(err));
      });
    }

    return () => { cancelled = true; };
  }, [repository, branch]);

  const openFile = async (filePath) => {
    setError(""); setMessage(""); setLoading(true);
    try {
      const res = await api.get("/code-editor/file", { params: { repository_full_name: repository, branch, path: filePath } });
      setPath(filePath); setContent(res.data.content); setCreating(false);
      await runAiReview(filePath, res.data.content);
    } catch (err) { setError(explainError(err)); }
    finally { setLoading(false); }
  };

  const startNewFile = () => {
    reviewRequestRef.current += 1;
    setReviewData(null); setReviewError(""); setReviewLoading(false);
    setPath(""); setContent(""); setNewPath(""); setCreating(true); setMessage(""); setError("");
  };

  const uploadLocalFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".py")) {
      setError("Only Python files ending in .py can be uploaded.");
      return;
    }
    try {
      const text = await file.text();
      if (!text.trim()) {
        setError("Python file content cannot be empty or whitespace-only.");
        return;
      }
      setPath("");
      setNewPath(file.name);
      setContent(text);
      setCreating(true);
      setMessage(`Loaded ${file.name}. AI review started automatically.`);
      setError("");
      await runAiReview(file.name, text);
    } catch {
      setError("Unable to read the selected local file.");
    }
  };

  const createBranch = async () => {
    const name = newBranchName.trim();
    if (!repository) { setError("Select a repository first."); return; }
    if (!name) { setError("Enter a name for the new branch."); return; }
    if (branches.some((item) => item.name === name)) {
      setError(`Branch '${name}' already exists in repository '${repository}'.`);
      return;
    }
    setCreatingBranch(true); setError(""); setMessage("");
    try {
      const res = await api.post("/code-editor/branches", {
        repository_full_name: repository,
        branch_name: name,
      });
      const createdName = res.data.name;
      const refreshed = await api.get("/code-editor/branches", { params: { repository_full_name: repository } });
      setBranches(refreshed.data.branches || []);
      setBranch(createdName);
      setNewBranchName("");
      setMessage(`Branch ${createdName} created successfully.`);
    } catch (err) { setError(explainError(err)); }
    finally { setCreatingBranch(false); }
  };

  const createPullRequest = async () => {
    // Lock synchronously so rapid clicks cannot submit duplicate requests.
    if (createPRLockRef.current) return;
    if (!repository || !branch) { setError("Select a repository and source branch first."); return; }
    if (branch === "main") { setError("Select a source branch other than main. The target branch is main."); return; }
    if (!prTitle.trim()) { setError("Pull Request title cannot be empty."); return; }

    createPRLockRef.current = true;
    setCreatingPR(true); setError(""); setMessage(""); setPullRequest(null);
    try {
      // The backend compares this branch with main on GitHub and rejects
      // empty branches before it sends a create-PR request to GitHub.
      const res = await api.post("/code-editor/pull-requests", {
        repository_full_name: repository,
        head_branch: branch,
        title: prTitle.trim(),
        body: prBody,
      });
      setPullRequest(res.data);
      if (res.data.status === "existing") {
        setExistingPullRequest(res.data);
        setMessage(`Existing Pull Request #${res.data.number} found. New commits to this branch will update it.`);
      } else {
        setExistingPullRequest(null);
        setMessage(`Pull Request #${res.data.number} created successfully.`);
      }
    } catch (err) { setError(explainError(err)); }
    finally {
      createPRLockRef.current = false;
      setCreatingPR(false);
    }
  };

  const deleteFile = async (filePath) => {
    if (!repository || !branch || !filePath) return;
    const confirmed = window.confirm(`Delete ${filePath} from ${repository} (${branch})? This creates a commit on GitHub and cannot be undone from CodeGuard.`);
    if (!confirmed) return;
    setSaving(true); setError(""); setMessage(""); setPullRequest(null);
    try {
      const res = await api.delete("/code-editor/file", {
        params: { repository_full_name: repository, branch, path: filePath },
        data: { commit_message: `Delete ${filePath} using CodeGuard` },
      });
      if (path === filePath) { setPath(""); setContent(""); setCreating(false); }
      const refreshed = await api.get("/code-editor/files", { params: { repository_full_name: repository, branch } });
      setFiles(refreshed.data.files || []);
      setMessage(`File ${filePath} deleted successfully. Commit: ${res.data.commit_sha?.slice(0, 7) || "created"}`);
    } catch (err) { setError(explainError(err)); }
    finally { setSaving(false); }
  };

  const saveFile = async () => {
    // A ref blocks rapid clicks immediately, before React can re-render the disabled button.
    if (saveLockRef.current) return;
    saveLockRef.current = true;

    const targetPath = (creating ? newPath : path).trim();
    if (!targetPath.toLowerCase().endsWith(".py")) { setError("Filename must end with .py (example: hello.py)."); saveLockRef.current = false; return; }
    if (!content.trim()) { setError("Python file content cannot be empty or whitespace-only."); saveLockRef.current = false; return; }
    if (!repository || !branch) { setError("Select a repository and branch first."); saveLockRef.current = false; return; }
    setSaving(true); setError(""); setMessage(""); setPullRequest(null);
    try {
      const res = await api.post("/code-editor/save", {
        repository_full_name: repository,
        branch,
        path: targetPath,
        content,
        create_only: creating,
        commit_message: commitMessage.trim() || "Update Python file using CodeGuard",
      });
      setPath(targetPath); setCreating(false); setMessage(`File ${res.data.action} successfully. Commit: ${res.data.commit_sha?.slice(0, 7) || "created"}`);
      await runAiReview(targetPath, content);
      const refreshed = await api.get("/code-editor/files", { params: { repository_full_name: repository, branch } });
      setFiles(refreshed.data.files || []);
    } catch (err) { setError(explainError(err)); }
    finally { setSaving(false); saveLockRef.current = false; }
  };

  return (
    <section style={{ display: "grid", gap: 18 }}>
      <div className="panel" style={{ padding: 22 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <FolderGit2 size={22} /><div><h2 style={{ margin: 0 }}>GitHub Code Editor</h2><p style={{ margin: "5px 0 0", color: "#94a3b8" }}>Edit Python files and commit directly to your selected GitHub branch.</p></div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <input value={newBranchName} onChange={(e) => setNewBranchName(e.target.value)} placeholder="feature/my-new-branch" aria-label="New branch name" style={{ ...fieldStyle, width: 220 }} disabled={!repository || !!branch} />
            <button type="button" onClick={createBranch} disabled={!repository || !!branch || creatingBranch} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 13px", border: 0, borderRadius: 8, color: "#ffffff", background: !repository || !!branch || creatingBranch ? "#64748b" : "#16a34a", cursor: !repository || !!branch || creatingBranch ? "not-allowed" : "pointer", fontWeight: 600 }}>
              <GitBranch size={15} /> {creatingBranch ? "Creating..." : "Create branch"}
            </button>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12 }}>
          <label style={{ display: "grid", gap: 7, color: "#cbd5e1", fontSize: 13 }}>Repository
            <div
              ref={repositoryDropdownRef}
              style={{ position: "relative", width: "100%" }}
            >
              <input
                type="text"
                value={repositorySearch}
                onChange={handleRepositorySearch}
                onFocus={() => setRepositoryDropdownOpen(true)}
                placeholder="Search and select a repository..."
                autoComplete="off"
                aria-label="Search GitHub repositories"
                aria-expanded={repositoryDropdownOpen}
                aria-controls="code-editor-repository-menu"
                style={fieldStyle}
              />
              {repositoryDropdownOpen && (
                <div
                  id="code-editor-repository-menu"
                  role="listbox"
                  aria-label="Connected GitHub repositories"
                  style={{
                    position: "absolute",
                    zIndex: 1000,
                    top: "calc(100% + 6px)",
                    left: 0,
                    right: 0,
                    maxHeight: 240,
                    overflowY: "auto",
                    background: "#0f172a",
                    border: "1px solid #475569",
                    borderRadius: 8,
                    boxShadow: "0 8px 24px rgba(0, 0, 0, 0.35)",
                    padding: 5,
                  }}
                >
                  {filteredRepositories.length > 0 ? (
                    filteredRepositories.map((repo) => {
                      const isSelected = repo.full_name === repository;
                      return (
                        <button
                          key={repo.id || repo.full_name}
                          type="button"
                          role="option"
                          aria-selected={isSelected}
                          onClick={() => selectRepository(repo)}
                          style={{
                            display: "block",
                            width: "100%",
                            textAlign: "left",
                            padding: "9px 10px",
                            border: "none",
                            borderRadius: 5,
                            background: isSelected ? "#1d4ed8" : "transparent",
                            color: "#e2e8f0",
                            cursor: "pointer",
                            fontSize: 13,
                          }}
                          onMouseEnter={(event) => {
                            event.currentTarget.style.background = "#1e40af";
                          }}
                          onMouseLeave={(event) => {
                            event.currentTarget.style.background = isSelected
                              ? "#1d4ed8"
                              : "transparent";
                          }}
                        >
                          {repo.full_name}
                        </button>
                      );
                    })
                  ) : (
                    <p style={{ margin: 0, padding: 10, color: "#94a3b8", fontSize: 13 }}>
                      No matching repositories found.
                    </p>
                  )}
                </div>
              )}
            </div>
          </label>
          <label style={{ display: "grid", gap: 7, color: "#cbd5e1", fontSize: 13 }}><span><GitBranch size={14} style={{ verticalAlign: "middle" }} /> Branch</span>
            <select value={branch} onChange={(e) => setBranch(e.target.value)} disabled={!branches.length} style={fieldStyle}>
              <option value="">Select a branch</option>{branches.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 0.32fr) minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <div className="panel" style={{ padding: 16, minHeight: 420 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}><h3 style={{ margin: 0 }}>Python files</h3><div style={{ display: "flex", gap: 6 }}><button className="secondary-button" type="button" onClick={startNewFile} disabled={!repository || !branch}><Plus size={15} /> New file</button><button className="secondary-button" type="button" onClick={() => fileInputRef.current?.click()} disabled={!repository || !branch}><Upload size={15} /> From PC</button><input ref={fileInputRef} type="file" accept=".py,text/x-python,text/plain" onChange={uploadLocalFile} style={{ display: "none" }} /></div></div>
          <div style={{ marginTop: 14, display: "grid", gap: 6 }}>
            {files.map((file) => <div key={file.path} style={{ display: "flex", alignItems: "center", gap: 5, border: `1px solid ${path === file.path ? "#3b82f6" : "transparent"}`, background: path === file.path ? "rgba(59,130,246,.18)" : "transparent", borderRadius: 8, padding: "2px 5px" }}><button type="button" onClick={() => openFile(file.path)} disabled={!repository || !branch || loading} style={{ ...fileButtonStyle, flex: 1, minWidth: 0 }}><FileCode2 size={16} /> <span style={{ overflowWrap: "anywhere", textAlign: "left" }}>{file.path}</span></button><button type="button" title={`Edit ${file.path}`} aria-label={`Edit ${file.path}`} onClick={() => openFile(file.path)} className="secondary-button" style={{ padding: "7px" }} disabled={!repository || !branch || loading}><Pencil size={14} /></button><button type="button" title={`Delete ${file.path}`} aria-label={`Delete ${file.path}`} onClick={() => deleteFile(file.path)} className="secondary-button" style={{ padding: "7px", color: "#fca5a5" }} disabled={!repository || !branch || saving || loading}><Trash2 size={14} /></button></div>)}
            {!files.length && <p style={{ color: "#94a3b8", fontSize: 13 }}>{repository && branch ? "No Python files found on this branch." : "Select a repository and branch to browse files."}</p>}
          </div>
        </div>

        <div className="panel" style={{ padding: 18, minHeight: 420 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}><h3 style={{ margin: 0 }}>{creating ? "Create Python file" : path || "Editor"}</h3><button type="button" className="primary-button" onClick={saveFile} disabled={saving || (!creating && !path)}><Save size={16} /> {saving ? "Saving..." : creating ? "Create & Commit" : "Save Changes"}</button></div>
          {creating && <label style={{ display: "grid", gap: 6, marginBottom: 12, color: "#cbd5e1", fontSize: 13 }}>File path<input value={newPath} onChange={(e) => setNewPath(e.target.value)} placeholder="src/example.py" style={fieldStyle} /></label>}
          <label style={{ display: "grid", gap: 6, marginBottom: 12, color: "#cbd5e1", fontSize: 13 }}>Commit message<input value={commitMessage} onChange={(e) => setCommitMessage(e.target.value)} style={fieldStyle} /></label>
          <textarea value={content} onChange={(e) => setContent(e.target.value)} spellCheck={false} disabled={!repository || !branch} placeholder={repository && branch ? "Select a Python file or create a new one..." : "Select a repository and branch first..."} style={{ width: "100%", minHeight: 310, resize: "vertical", boxSizing: "border-box", padding: 16, borderRadius: 10, border: "1px solid #334155", background: "#0b1220", color: "#e2e8f0", fontFamily: "Consolas, monospace", fontSize: 13, lineHeight: 1.6, opacity: repository && branch ? 1 : 0.55, cursor: repository && branch ? "text" : "not-allowed" }} />
          {error && <p role="alert" style={{ color: "#fca5a5", display: "flex", gap: 8, alignItems: "center" }}><AlertCircle size={16} />{error}</p>}
          {message && <p role="status" style={{ color: "#86efac", display: "flex", gap: 8, alignItems: "center" }}><CheckCircle2 size={16} />{message}</p>}
          {loading && <p style={{ color: "#93c5fd" }}><RefreshCw size={14} /> Loading GitHub data...</p>}
          <p style={{ color: "#94a3b8", fontSize: 12 }}>Only non-empty .py files can be committed through this editor. Commits are written to the selected branch.</p>
        </div>
      </div>

      <div className="panel" style={{ padding: 18, display: "grid", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: 0 }}>Automatic AI Review</h3>
            <p style={{ margin: "5px 0 0", color: "#94a3b8", fontSize: 13 }}>
              CodeGuard reviews a Python file automatically when you open or upload it.
            </p>
          </div>
          {reviewLoading && <span style={{ color: "#93c5fd", fontSize: 13 }}><RefreshCw size={14} style={{ verticalAlign: "middle" }} /> Reviewing with Ruff, Bandit and Claude...</span>}
        </div>

        {!path && !newPath && !reviewLoading && !reviewData && !reviewError && (
          <p style={{ color: "#94a3b8", margin: 0 }}>Open a Python file or upload one to start its automatic review.</p>
        )}
        {reviewError && <p role="alert" style={{ color: "#fca5a5", margin: 0 }}><AlertCircle size={15} style={{ verticalAlign: "middle" }} /> {reviewError}</p>}
        {reviewData && (
          <>
            <div style={{ padding: 12, borderRadius: 9, border: `1px solid ${reviewData.total_issues ? "#7f1d1d" : "#166534"}`, background: reviewData.total_issues ? "rgba(127,29,29,.16)" : "rgba(22,101,52,.14)" }}>
              <strong style={{ color: reviewData.total_issues ? "#fca5a5" : "#86efac" }}>
                {reviewData.total_issues ? `${reviewData.total_issues} finding${reviewData.total_issues === 1 ? "" : "s"} found` : "No issues found"}
              </strong>
              <p style={{ color: "#cbd5e1", margin: "5px 0 0", fontSize: 13 }}>{reviewData.summary}</p>
            </div>
            {reviewData.findings?.length > 0 ? reviewData.findings.map((finding, index) => (
              <article key={`${finding.line_number ?? "na"}-${finding.title}-${index}`} style={{ border: "1px solid #334155", borderRadius: 10, padding: 14, display: "grid", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ color: "#f8fafc" }}>{finding.title}</strong>
                  <span style={{ color: "#93c5fd", fontSize: 12 }}>{String(finding.issue_type || "issue").replaceAll("_", " ")}</span>
                  <span style={{ color: "#cbd5e1", fontSize: 12 }}>Line {finding.line_number ?? "not specified"}</span>
                </div>
                <p style={{ color: "#cbd5e1", margin: 0, fontSize: 13 }}>{finding.description}</p>
                {finding.original_code !== null && finding.original_code !== undefined && (
                  <div style={{ borderRadius: 8, overflow: "hidden", border: "1px solid #7f1d1d" }}>
                    <div style={{ background: "rgba(127,29,29,.30)", color: "#fca5a5", padding: "6px 10px", fontSize: 11, fontWeight: 700 }}>ORIGINAL CODE — REMOVE / FIX</div>
                    <pre style={{ margin: 0, padding: 11, background: "rgba(127,29,29,.16)", color: "#fecaca", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "Consolas, monospace", fontSize: 13 }}>{`${finding.line_number}: ${finding.original_code}`}</pre>
                  </div>
                )}
                {finding.replacement_code ? (
                  <div style={{ borderRadius: 8, overflow: "hidden", border: "1px solid #166534" }}>
                    <div style={{ background: "rgba(22,101,52,.30)", color: "#86efac", padding: "6px 10px", fontSize: 11, fontWeight: 700 }}>REPLACEMENT CODE — SUGGESTED</div>
                    <pre style={{ margin: 0, padding: 11, background: "rgba(22,101,52,.16)", color: "#bbf7d0", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "Consolas, monospace", fontSize: 13 }}>{finding.replacement_code}</pre>
                  </div>
                ) : (
                  <div style={{ borderRadius: 8, padding: 11, background: "rgba(22,101,52,.12)", border: "1px solid #166534", color: "#bbf7d0", fontSize: 13 }}>
                    <strong>Suggested correction:</strong> {finding.suggestion}
                    <p style={{ margin: "6px 0 0", color: "#86efac", fontSize: 11 }}>Claude did not provide a safe exact replacement snippet for this finding.</p>
                  </div>
                )}
              </article>
            )) : (
              <p style={{ color: "#86efac", margin: 0 }}>The selected Python file passed the AI review.</p>
            )}
          </>
        )}
      </div>

      <div className="panel" style={{ padding: 18, display: "grid", gap: 12 }}>
        <div>
          <h3 style={{ margin: 0 }}>Create Pull Request</h3>
          <p style={{ margin: "5px 0 0", color: "#94a3b8", fontSize: 13 }}>
            Open a GitHub Pull Request from <strong>{branch || "your source branch"}</strong> into <strong>main</strong>.
          </p>
        </div>
        <label style={{ display: "grid", gap: 6, color: "#cbd5e1", fontSize: 13 }}>Pull Request title
          <input value={prTitle} onChange={(e) => setPrTitle(e.target.value)} placeholder="Describe your changes" style={fieldStyle} />
        </label>
        <label style={{ display: "grid", gap: 6, color: "#cbd5e1", fontSize: 13 }}>Description
          <textarea value={prBody} onChange={(e) => setPrBody(e.target.value)} rows={4} style={{ ...fieldStyle, resize: "vertical", fontFamily: "inherit" }} />
        </label>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button type="button" className="primary-button" onClick={createPullRequest} disabled={creatingPR || !repository || !branch || branch === "main"}>
            <GitBranch size={16} /> {creatingPR ? "Checking..." : existingPullRequest ? "Open Existing Pull Request" : "Create Pull Request to main"}
          </button>
          {(existingPullRequest || pullRequest)?.html_url && (
            <a href={(existingPullRequest || pullRequest).html_url} target="_blank" rel="noreferrer" style={{ color: "#93c5fd" }}>
              Open PR #{(existingPullRequest || pullRequest).number} on GitHub
            </a>
          )}
        </div>
        {existingPullRequest && (
          <div role="status" style={{ padding: 12, borderRadius: 8, border: "1px solid #16a34a", background: "rgba(22,163,74,.10)", color: "#86efac" }}>
            <strong>Existing Pull Request Found</strong>
            <div>PR #{existingPullRequest.number}: {existingPullRequest.title}</div>
            <div>Commits pushed to <strong>{branch}</strong> will automatically update this Pull Request.</div>
          </div>
        )}
        {branch === "main" && <p style={{ margin: 0, color: "#fbbf24", fontSize: 12 }}>Select a feature branch to create a Pull Request into main.</p>}
      </div>
    </section>
  );
}

const fieldStyle = { width: "100%", boxSizing: "border-box", padding: "11px 12px", borderRadius: 9, border: "1px solid #334155", background: "#0f172a", color: "#e2e8f0" };
const fileButtonStyle = { display: "flex", alignItems: "center", gap: 9, width: "100%", padding: "9px 8px", border: "1px solid transparent", borderRadius: 8, color: "#cbd5e1", background: "transparent", cursor: "pointer", fontSize: 13, textAlign: "left" };
