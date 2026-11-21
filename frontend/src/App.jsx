

import { useCallback, useEffect, useMemo, useState } from "react";

import AIFixPanel from "./AIFixPanel";

import axios from "axios";

import FixApprovalPanel from "./FixApprovalPanel";

import CodeEditor from "./CodeEditor";
import PullRequestManager from "./PullRequestManager";



import {

  LayoutDashboard,

  GitBranch,

  GitPullRequest,

  ShieldCheck,

  Wrench,

  Settings,

  Search,

  Bell,

  ChevronDown,

  Activity,

  CircleCheck,

  CircleAlert,

  Clock,

  ArrowUpRight,

  Code2,

  Menu,

  X,

  RefreshCw,

  AlertTriangle,

  ExternalLink,

  FileCode,

  GitCommit,

  ShieldAlert,

  Database,

  CalendarDays,

  Info,

  Plus,
  FileCode2,

} from "lucide-react";



import "./App.css";



const API_BASE_URL = "http://localhost:8000";



const api = axios.create({

  baseURL: API_BASE_URL,

  timeout: 20000,

  withCredentials: true,

});



const navigation = [

  { name: "Overview", icon: LayoutDashboard },

  { name: "Repositories", icon: GitBranch },

  { name: "Code Editor", icon: FileCode2 },

  { name: "Automatic Fixes", icon: Wrench },

  { name: "Pull Requests", icon: GitPullRequest },

  { name: "Code Reviews", icon: ShieldCheck },

  { name: "Settings", icon: Settings },

];



const formatNumber = (value) =>

  Number(value || 0).toLocaleString("en-IN", {

    minimumIntegerDigits: 2,

  });



const formatDate = (value) => {

  if (!value) return "Date unavailable";



  const date = new Date(value);



  if (Number.isNaN(date.getTime())) return "Date unavailable";



  return date.toLocaleString("en-IN", {

    dateStyle: "medium",

    timeStyle: "short",

  });

};



const readableStatus = (value) => {

  if (!value) return "Unknown";



  return String(value)

    .replaceAll("_", " ")

    .replace(/\b\w/g, (letter) => letter.toUpperCase());

};



const getSeverity = (value) => {

  const severity = String(value || "Unknown").toLowerCase();



  if (severity.includes("critical")) return "Critical";

  if (severity.includes("high")) return "High";

  if (severity.includes("medium")) return "Medium";

  if (severity.includes("low")) return "Low";



  return readableStatus(severity);

};



const getStatusClass = (value) => {

  const status = String(value || "").toLowerCase();



  if (

    status.includes("published") ||

    status.includes("completed") ||

    status.includes("passed") ||

    status.includes("open")

  ) {

    return "low";

  }



  if (

    status.includes("rejected") ||

    status.includes("failed") ||

    status.includes("critical")

  ) {

    return "critical";

  }



  if (

    status.includes("pending") ||

    status.includes("processing") ||

    status.includes("received")

  ) {

    return "medium";

  }



  return "medium";

};



const unwrapList = (data, possibleKeys = []) => {

  if (Array.isArray(data)) return data;



  for (const key of possibleKeys) {

    if (Array.isArray(data?.[key])) return data[key];

  }



  return [];

};



const getRepositoryUrl = (repository) => {

  if (!repository) return null;



  if (repository.startsWith("http")) return repository;



  return `https://github.com/${repository}`;

};



const getPullRequestUrl = (repository, number) => {

  const base = getRepositoryUrl(repository);



  if (!base || !number) return null;



  return `${base.replace(/\/$/, "")}/pull/${number}`;

};



function App() {

  const [activePage, setActivePage] = useState("Overview");

  const [search, setSearch] = useState("");

  const [menuOpen, setMenuOpen] = useState(false);





  // Main dashboard data

  const [dashboard, setDashboard] = useState(null);



  // Repository data

  const [repositories, setRepositories] = useState([]);

  const [repositoriesLoading, setRepositoriesLoading] = useState(false);

  const [repositoriesError, setRepositoriesError] = useState("");
  const [showCreateRepository, setShowCreateRepository] = useState(false);
  const [newRepositoryName, setNewRepositoryName] = useState("");
  const [newRepositoryDescription, setNewRepositoryDescription] = useState("");
  const [newRepositoryPrivate, setNewRepositoryPrivate] = useState(true);
  const [creatingRepository, setCreatingRepository] = useState(false);
  const [createRepositoryError, setCreateRepositoryError] = useState("");
  const [repositoryNotice, setRepositoryNotice] = useState(null);


  // Live GitHub pull request counts, grouped by repository
  const [pullRequestSummaries, setPullRequestSummaries] = useState([]);
  const [pullRequestSummariesLoading, setPullRequestSummariesLoading] = useState(false);
  const [pullRequestSummariesError, setPullRequestSummariesError] = useState("");





  // General UI state

  const [loading, setLoading] = useState(true);

  const [refreshing, setRefreshing] = useState(false);

  const [error, setError] = useState("");

  const [currentUser, setCurrentUser] = useState(null);

  const [authChecking, setAuthChecking] = useState(true);



  // --------------------------------------------------

  // DASHBOARD API

  // --------------------------------------------------



  const fetchDashboard = useCallback(async (isRefresh = false) => {

    if (isRefresh) {

      setRefreshing(true);

    } else {

      setLoading(true);

    }



    setError("");



    try {

      const response = await api.get("/dashboard/summary");

      setDashboard(response.data);

    } catch (err) {

      console.error("Dashboard API error:", err);



      setError(

        err.response?.data?.detail ||

          "Unable to connect to the backend. Check that FastAPI is running."

      );

    } finally {

      setLoading(false);

      setRefreshing(false);

    }

  }, []);



  // --------------------------------------------------

  // REPOSITORIES API

  // --------------------------------------------------



  const fetchRepositories = useCallback(async () => {

  setRepositoriesLoading(true);

  setRepositoriesError("");



  try {

    const response = await api.get(

      "/github-installations/repositories"

    );



    setRepositories(

      unwrapList(response.data, ["repositories", "items"])

    );

  } catch (err) {

    console.error("GitHub Repositories API error:", err);



    setRepositoriesError(

      err.response?.data?.detail ||

        "Unable to load GitHub repositories."

    );

  } finally {

    setRepositoriesLoading(false);

  }

}, []);



  const createRepository = async (event) => {
    event.preventDefault();
    if (creatingRepository) return;

    const name = newRepositoryName.trim();
    if (!name) {
      setCreateRepositoryError("Enter a repository name.");
      return;
    }

    setCreatingRepository(true);
    setCreateRepositoryError("");
    setRepositoryNotice(null);

    try {
      const response = await api.post("/github-installations/repositories/create", {
        name,
        description: newRepositoryDescription.trim() || null,
        private: newRepositoryPrivate,
      });
      const result = response.data;
      setRepositoryNotice({
        message: result.message || "Repository created.",
        settingsUrl: result.installation_settings_url || null,
      });
      setShowCreateRepository(false);
      setNewRepositoryName("");
      setNewRepositoryDescription("");
      setNewRepositoryPrivate(true);
      if (!result.installation_access_required) {
        await fetchRepositories();
        // Notify a mounted CodeEditor component to refresh its repository selector.
        window.dispatchEvent(new Event("codeguard:repositories-updated"));
      }
    } catch (err) {
      setCreateRepositoryError(
        err.response?.data?.detail || "Unable to create the GitHub repository."
      );
    } finally {
      setCreatingRepository(false);
    }
  };

  // --------------------------------------------------

  // LIVE PULL REQUEST SUMMARY API
  // --------------------------------------------------

  const fetchPullRequestSummaries = useCallback(async () => {
    setPullRequestSummariesLoading(true);
    setPullRequestSummariesError("");

    try {
      const response = await api.get("/github/pull-request-summary");
      setPullRequestSummaries(
        unwrapList(response.data, ["repositories", "items"])
      );
    } catch (err) {
      console.error("Pull Request summary API error:", err);
      setPullRequestSummariesError(
        err.response?.data?.detail ||
          "Unable to load live pull request counts from GitHub."
      );
    } finally {
      setPullRequestSummariesLoading(false);
    }
  }, []);

  // --------------------------------------------------
  // INITIAL DATA

  // --------------------------------------------------



  // Check the GitHub OAuth session before requesting private dashboard data.

  useEffect(() => {

    let isMounted = true;



    const checkAuthentication = async () => {

      try {

        const response = await api.get("/auth/me");

        if (isMounted) setCurrentUser(response.data);

      } catch (authError) {

        if (isMounted) setCurrentUser(null);

      } finally {

        if (isMounted) setAuthChecking(false);

      }

    };



    checkAuthentication();



    return () => {

      isMounted = false;

    };

  }, []);



  // Fetch dashboard data only after the user has an authenticated session.

  useEffect(() => {

    if (currentUser) {

      fetchDashboard();

    }

  }, [currentUser, fetchDashboard]);



  // Load repository data only for an authenticated user when the page is opened.

  useEffect(() => {

    if (currentUser && activePage === "Repositories") {

      fetchRepositories();

    }

  }, [currentUser, activePage, fetchRepositories]);



  // --------------------------------------------------

  // Load live open/closed pull request counts when the page is opened.
  useEffect(() => {
    if (currentUser && activePage === "Pull Requests") {
      fetchPullRequestSummaries();
    }
  }, [currentUser, activePage, fetchPullRequestSummaries]);

  // --------------------------------------------------
  // DASHBOARD RESPONSE DATA

  // --------------------------------------------------



  const statistics = dashboard?.statistics || {};



  const recentReviews = dashboard?.recent_reviews || [];

  const recentPullRequests = dashboard?.recent_pull_requests || [];

  const recentFixes = dashboard?.recent_fixes || [];



  const issueSources = dashboard?.issue_sources || {};

  const fixStatuses = dashboard?.fix_statuses || {};

  const webhookStatuses = dashboard?.webhook_statuses || {};



  const backendConnected = Boolean(dashboard) && !error;



  // --------------------------------------------------

  // REVIEW DATA

  // --------------------------------------------------



  const reviewRows = useMemo(() => {

    return recentReviews.flatMap((review) =>

      (review.issues || []).map((issue) => ({

        id: issue.id,

        reviewId: review.id,

        repository: review.repository,

        repositoryUrl: review.repository_url,

        pullRequestNumber: review.pull_request_number,

        pullRequestTitle: review.pull_request_title,

        commitSha: review.commit_sha,

        file: issue.file_path,

        line: issue.line_number,

        type: issue.issue_type,

        issue: issue.description,

        suggestion: issue.suggestion,

        severity: getSeverity(issue.severity),

        source: issue.source || "ai",

        status: review.status,

        createdAt: review.created_at,

      }))

    );

  }, [recentReviews]);



  const filteredReviews = useMemo(() => {

    const query = search.toLowerCase().trim();



    if (!query) return reviewRows;



    return reviewRows.filter((review) =>

      [

        review.repository,

        review.file,

        review.issue,

        review.severity,

        review.source,

        review.type,

        review.pullRequestNumber,

      ]

        .join(" ")

        .toLowerCase()

        .includes(query)

    );

  }, [reviewRows, search]);



  const filteredReviewRecords = useMemo(() => {

    const query = search.toLowerCase().trim();



    if (!query) return recentReviews;



    return recentReviews.filter((review) =>

      [

        review.repository,

        review.pull_request_title,

        review.pull_request_number,

        review.commit_sha,

        review.summary,

        review.status,

      ]

        .join(" ")

        .toLowerCase()

        .includes(query)

    );

  }, [recentReviews, search]);



  // --------------------------------------------------

  // PULL REQUEST DATA

  // --------------------------------------------------



  const filteredPullRequests = useMemo(() => {

    const query = search.toLowerCase().trim();



    if (!query) return recentPullRequests;



    return recentPullRequests.filter((pr) =>

      [

        pr.number,

        pr.title,

        pr.repository,

        pr.status,

        pr.description,

        pr.head_sha,

      ]

        .join(" ")

        .toLowerCase()

        .includes(query)

    );

  }, [recentPullRequests, search]);

  const filteredPullRequestSummaries = useMemo(() => {
    const query = search.toLowerCase().trim();
    if (!query) return pullRequestSummaries;

    return pullRequestSummaries.filter((item) =>
      String(item.repository || "").toLowerCase().includes(query)
    );
  }, [pullRequestSummaries, search]);



  // --------------------------------------------------

  // REPOSITORY SEARCH

  // --------------------------------------------------



  const filteredRepositories = useMemo(() => {

    const query = search.toLowerCase().trim();



    if (!query) return repositories;



    return repositories.filter((repository) =>

      [

        repository.name,

        repository.full_name,

        repository.html_url,

      ]

        .join(" ")

        .toLowerCase()

        .includes(query)

    );

  }, [repositories, search]);





  // --------------------------------------------------

  // DASHBOARD STATISTICS

  // --------------------------------------------------



  const stats = [

    {

      title: "Repositories",

      value: statistics.repositories,

      detail: "Connected repositories",

      icon: GitBranch,

      color: "purple",

      page: "Repositories",

    },

    {

      title: "Pull Requests",

      value: statistics.pull_requests,

      detail: "Total pull requests",

      icon: GitPullRequest,

      color: "blue",

      page: "Pull Requests",

    },

    {

      title: "Code Reviews",

      value: statistics.reviews,

      detail: "Total saved code reviews",

      icon: ShieldCheck,

      color: "green",

      page: "Code Reviews",

    },

    {

      title: "Issues Detected",

      value: statistics.issues,

      detail: "Saved review issues",

      icon: CircleAlert,

      color: "orange",

      page: "Code Reviews",

    },

    {

      title: "Automatic Fixes",

      value: statistics.fix_proposals,

      detail: "Fix proposals created",

      icon: Wrench,

      color: "purple",

      page: "Automatic Fixes",

    },

  ];



  const pipelineItems = [

    {

      title: "Pull Request Received",

      description: "GitHub webhook events",

      icon: GitPullRequest,

      color: "purple",

      count: Object.values(webhookStatuses).reduce(

        (total, count) => total + Number(count || 0),

        0

      ),

    },

    {

      title: "AI Code Analysis",

      description: "Saved code reviews",

      icon: ShieldCheck,

      color: "blue",

      count: statistics.reviews || 0,

    },

    {

      title: "Fix Validation",

      description: "Recorded fix proposals",

      icon: Wrench,

      color: "orange",

      count: statistics.fix_proposals || 0,

    },

    {

      title: "Developer Approval",

      description: "Fix proposal statuses",

      icon: GitBranch,

      color: "green",

      count: Object.values(fixStatuses).reduce(

        (total, count) => total + Number(count || 0),

        0

      ),

    },

  ];



  // --------------------------------------------------

  // REFRESH ALL

  // --------------------------------------------------



  const refreshCurrentPage = async () => {

    await fetchDashboard(true);

    if (activePage === "Repositories") await fetchRepositories();
    if (activePage === "Pull Requests") await fetchPullRequestSummaries();

  };



  const handleNavigation = (page) => {

    setActivePage(page);

    setSearch("");

    setMenuOpen(false);

  };



  // --------------------------------------------------

  // REUSABLE PAGE HEADER

  // --------------------------------------------------



  const renderPageHeader = (tag, title, description, icon) => {

    const Icon = icon;



    return (

      <div className="repository-page-heading">

        <div>

          <span className="welcome-tag">

            <Icon size={14} />

            {tag}

          </span>



          <h2>{title}</h2>

          <p>{description}</p>

        </div>



        <button

          className="repository-refresh"

          onClick={refreshCurrentPage}

          disabled={refreshing || repositoriesLoading}

        >

          <RefreshCw

            size={16}

            className={

              refreshing || repositoriesLoading

                ? "spin"

                : ""

            }

          />

          Refresh

        </button>

      </div>

    );

  };



  // ==================================================

  // AUTHENTICATION GATE

  // ==================================================



  if (authChecking) {

    return (

      <div

        style={{

          minHeight: "100vh",

          display: "grid",

          placeItems: "center",

          background: "#0b1020",

          color: "#e5e7eb",

          fontFamily: "Inter, system-ui, sans-serif",

        }}

      >

        <div style={{ textAlign: "center" }}>

          <div

            style={{

              width: 42,

              height: 42,

              margin: "0 auto 16px",

              border: "3px solid rgba(148, 163, 184, 0.25)",

              borderTopColor: "#8b5cf6",

              borderRadius: "50%",

              animation: "codeguard-auth-spin 0.8s linear infinite",

            }}

          />

          <p style={{ margin: 0, color: "#cbd5e1" }}>Checking your GitHub session...</p>

          <style>{`@keyframes codeguard-auth-spin { to { transform: rotate(360deg); } }`}</style>

        </div>

      </div>

    );

  }



  if (!currentUser) {

    return (

      <div

        style={{

          minHeight: "100vh",

          display: "grid",

          placeItems: "center",

          padding: 24,

          background:

            "radial-gradient(circle at 20% 10%, rgba(99,102,241,.20), transparent 35%), #0b1020",

          color: "#f8fafc",

          fontFamily: "Inter, system-ui, sans-serif",

        }}

      >

        <section

          style={{

            width: "100%",

            maxWidth: 440,

            padding: "42px 36px",

            textAlign: "center",

            border: "1px solid rgba(148,163,184,.22)",

            borderRadius: 22,

            background: "rgba(15,23,42,.92)",

            boxShadow: "0 24px 80px rgba(0,0,0,.35)",

          }}

        >

          <div

            style={{

              width: 64,

              height: 64,

              margin: "0 auto 22px",

              display: "grid",

              placeItems: "center",

              borderRadius: 18,

              color: "#c4b5fd",

              background: "rgba(139,92,246,.16)",

            }}

          >

            <Code2 size={32} />

          </div>

          <p

            style={{

              margin: "0 0 10px",

              color: "#a78bfa",

              fontSize: 12,

              fontWeight: 700,

              letterSpacing: 2,

            }}

          >

            AI CODE REVIEW AGENT

          </p>

          <h1 style={{ margin: "0 0 12px", fontSize: 30 }}>Welcome to CodeGuard</h1>

          <p style={{ margin: "0 0 28px", color: "#94a3b8", lineHeight: 1.7 }}>

            Sign in with your GitHub account to access your repositories,

            pull requests, code reviews, and AI fix proposals.

          </p>

          <button

            type="button"

            onClick={() => {

              window.location.assign(`${API_BASE_URL}/auth/github/login`);

            }}

            style={{

              width: "100%",

              minHeight: 50,

              border: 0,

              borderRadius: 12,

              background: "#ffffff",

              color: "#111827",

              fontSize: 15,

              fontWeight: 700,

              cursor: "pointer",

            }}

          >

            Sign in with GitHub

          </button>

          <p style={{ margin: "18px 0 0", color: "#64748b", fontSize: 12 }}>

            Secure authentication powered by GitHub OAuth

          </p>

        </section>

      </div>

    );

  }



  // ==================================================

  // APPLICATION UI

  // ==================================================



  return (

    <div className="app-layout">



      {/* SIDEBAR */}

      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>

        <div className="brand">

          <div className="brand-icon">

            <Code2 size={25} />

          </div>



          <div>

            <h2>CodeGuard</h2>

            <span>AI CODE REVIEW AGENT</span>

          </div>



          <button

            className="mobile-close"

            onClick={() => setMenuOpen(false)}

            aria-label="Close menu"

          >

            <X size={20} />

          </button>

        </div>



        <div className="workspace">

          <span className="workspace-label">WORKSPACE</span>



          <div className="workspace-card">

            <div className="workspace-avatar">P</div>



            <div>

              <strong>Personal Workspace</strong>

              <small>Developer Account</small>

            </div>



            <ChevronDown size={16} />

          </div>

        </div>



        <nav className="navigation">

          <span className="workspace-label">MENU</span>



          {navigation.map((item) => {

            const Icon = item.icon;



            return (

              <button

                key={item.name}

                className={`nav-item ${

                  activePage === item.name ? "active" : ""

                }`}

                onClick={() => handleNavigation(item.name)}

              >

                <Icon size={19} />

                <span>{item.name}</span>



                {item.name === "Pull Requests" && dashboard && (

                  <span className="nav-count">

                    {statistics.pull_requests || 0}

                  </span>

                )}

              </button>

            );

          })}

        </nav>



        <div className="sidebar-bottom">

          <div className="system-status">

            <span

              className="status-dot"

              style={{

                background: backendConnected ? "#34d399" : "#f59e0b",

              }}

            />



            <div>

              <strong>System status</strong>

              <small>

                {loading

                  ? "Connecting to backend..."

                  : backendConnected

                    ? "Backend connected"

                    : "Backend unavailable"}

              </small>

            </div>

          </div>



          <div className="profile">

            <div className="profile-avatar">P</div>



            <div>

              <strong>Developer</strong>

              <small>Administrator</small>

            </div>



            <Settings size={18} />

          </div>

        </div>

      </aside>



      {/* MAIN CONTENT */}

      <main className="main-content">



        {/* TOP BAR */}

        <header className="topbar">

          <div className="topbar-left">

            <button

              className="mobile-menu"

              onClick={() => setMenuOpen(true)}

              aria-label="Open menu"

            >

              <Menu size={22} />

            </button>



            <div>

              <span className="breadcrumb">

                Workspace / {activePage}

              </span>



              <h1>{activePage}</h1>

            </div>

          </div>



          <div className="topbar-actions">

            <label className="search-box">

              <Search size={18} />



              <input

                placeholder={`Search ${activePage.toLowerCase()}...`}

                value={search}

                onChange={(event) => setSearch(event.target.value)}

              />



              <kbd>Ctrl K</kbd>

            </label>



            <button

              className="notification-button"

              aria-label="Notifications"

              title="Notifications"

            >

              <Bell size={19} />

            </button>



            <button

              className="notification-button"

              onClick={refreshCurrentPage}

              disabled={refreshing}

              aria-label="Refresh"

              title="Refresh data"

            >

              <RefreshCw

                size={18}

                className={refreshing ? "spin" : ""}

              />

            </button>



            <div className="topbar-avatar">P</div>

          </div>

        </header>

        <div className="dashboard-content">



  {/* GENERAL BACKEND ERROR */}

  {error && (

    <div className="api-error">

      <AlertTriangle size={20} />

      <div>

        <strong>Backend connection problem</strong>

        <p>{error}</p>

      </div>



      <button onClick={() => fetchDashboard(true)}>

        Retry

      </button>

    </div>

  )}



          {/* ==================================================

              OVERVIEW PAGE

          ================================================== */}



          {activePage === "Overview" && (

            <>

              <section className="welcome-section">

                <div>

                  <div className="welcome-tag">

                    <Activity size={14} />

                    INTELLIGENT CODE ANALYSIS

                  </div>



                  <h2>

                    Welcome to your <span>AI Code Review</span>

                    <br />

                    workspace.

                  </h2>



                  <p>

                    Monitor repositories, identify vulnerabilities,

                    review pull requests, and manage AI-powered code fixes.

                  </p>

                </div>



                <div className="welcome-art">

                  <div className="art-glow" />



                  <div className="art-card art-card-back">

                    <GitBranch size={28} />

                  </div>



                  <div className="art-card art-card-front">

                    <ShieldCheck size={46} />

                    <span>AI ANALYSIS</span>

                    <strong>Code Protected</strong>

                  </div>



                  <div className="art-orbit orbit-one" />

                  <div className="art-orbit orbit-two" />

                </div>

              </section>



              <section className="section-heading">

                <div>

                  <h2>Performance Overview</h2>

                  <p>Your actual database activity at a glance</p>

                </div>



                <span className="date-label">

                  <span className="status-dot" />

                  {loading

                    ? "Loading database..."

                    : backendConnected

                      ? "Live backend data"

                      : "Waiting for backend"}

                </span>

              </section>



              {/* STATISTICS */}

              <section className="stats-grid">

                {stats.map((stat) => {

                  const Icon = stat.icon;



                  return (

                    <button

                      className="stat-card"

                      key={stat.title}

                      onClick={() => handleNavigation(stat.page)}

                    >

                      <div className={`stat-icon ${stat.color}`}>

                        <Icon size={22} />

                      </div>



                      <div className="stat-value">

                        {loading ? "..." : formatNumber(stat.value)}

                      </div>



                      <h3>{stat.title}</h3>

                      <p>{stat.detail}</p>



                      <ArrowUpRight

                        className="stat-arrow"

                        size={18}

                      />

                    </button>

                  );

                })}

              </section>



              {/* RECENT REVIEWS + PIPELINE */}

              <section className="content-grid">

                <div className="panel review-panel">

                  <div className="panel-heading">

                    <div>

                      <h2>Recent Code Reviews</h2>

                      <p>Issues from actual saved reviews</p>

                    </div>



                    <button

                      className="text-button"

                      onClick={() => handleNavigation("Code Reviews")}

                    >

                      View all <ArrowUpRight size={16} />

                    </button>

                  </div>



                  <div className="table-wrapper">

                    <table>

                      <thead>

                        <tr>

                          <th>Repository / File</th>

                          <th>Issue</th>

                          <th>Severity</th>

                          <th>Status</th>

                        </tr>

                      </thead>



                      <tbody>

                        {loading && (

                          <tr>

                            <td colSpan="4" className="empty-state">

                              Loading reviews...

                            </td>

                          </tr>

                        )}



                        {!loading &&

                          !error &&

                          filteredReviews.slice(0, 8).map((review) => (

                            <tr key={review.id}>

                              <td>

                                <div className="repo-name">

                                  <div className="repo-icon">

                                    <Code2 size={17} />

                                  </div>



                                  <div>

                                    <strong>{review.repository}</strong>

                                    <small>{review.file}</small>

                                  </div>

                                </div>

                              </td>



                              <td>

                                <span title={review.issue}>

                                  {review.issue}

                                </span>



                                <small className="issue-source">

                                  {readableStatus(review.source)}

                                </small>

                              </td>



                              <td>

                                <span

                                  className={`severity ${review.severity.toLowerCase()}`}

                                >

                                  {review.severity}

                                </span>

                              </td>



                              <td>

                                <span className="review-status">

                                  <CircleCheck size={15} />

                                  {readableStatus(review.status)}

                                </span>

                              </td>

                            </tr>

                          ))}



                        {!loading &&

                          !error &&

                          filteredReviews.length === 0 && (

                            <tr>

                              <td colSpan="4" className="empty-state">

                                No saved review issues found.

                              </td>

                            </tr>

                          )}

                      </tbody>

                    </table>

                  </div>

                </div>



                {/* REVIEW PIPELINE */}

                <div className="panel activity-panel">

                  <div className="panel-heading">

                    <div>

                      <h2>Review Pipeline</h2>

                      <p>Recorded workflow activity</p>

                    </div>



                    <Activity size={20} className="pipeline-icon" />

                  </div>



                  <div className="pipeline">

                    {pipelineItems.map((item, index) => {

                      const Icon = item.icon;



                      return (

                        <div key={item.title}>

                          <div className="pipeline-step">

                            <div

                              className={`pipeline-icon-box ${item.color}`}

                            >

                              <Icon size={19} />

                            </div>



                            <div>

                              <strong>{item.title}</strong>

                              <small>

                                {item.description} · {item.count}

                              </small>

                            </div>



                            {item.count > 0 ? (

                              <CircleCheck

                                size={17}

                                className="success-icon"

                              />

                            ) : (

                              <Clock

                                size={17}

                                className="pending-icon"

                              />

                            )}

                          </div>



                          {index !== pipelineItems.length - 1 && (

                            <div className="pipeline-line" />

                          )}

                        </div>

                      );

                    })}

                  </div>



                  <div className="pipeline-note">

                    <ShieldCheck size={18} />

                    Fixes require developer approval before publishing.

                  </div>

                </div>

              </section>



              {/* RECENT PULL REQUESTS + FIXES */}

              <section className="content-grid additional-panels">

                <div className="panel">

                  <div className="panel-heading">

                    <div>

                      <h2>Recent Pull Requests</h2>

                      <p>Actual pull requests from your database</p>

                    </div>



                    <button

                      className="text-button"

                      onClick={() => handleNavigation("Pull Requests")}

                    >

                      View all <ArrowUpRight size={16} />

                    </button>

                  </div>



                  {recentPullRequests.length === 0 ? (

                    <p className="empty-state">

                      No pull requests available.

                    </p>

                  ) : (

                    recentPullRequests.slice(0, 5).map((pr) => (

                      <div className="data-list-item" key={pr.id}>

                        <div className="repo-icon">

                          <GitPullRequest size={17} />

                        </div>



                        <div>

                          <strong>

                            #{pr.number} {pr.title}

                          </strong>

                          <small>{pr.repository}</small>

                          <small>{formatDate(pr.created_at)}</small>

                        </div>



                        <span

                          className={`severity ${getStatusClass(pr.status)}`}

                        >

                          {readableStatus(pr.status)}

                        </span>

                      </div>

                    ))

                  )}

                </div>



                <div className="panel">

                  <div className="panel-heading">

                    <div>

                      <h2>Automatic Fixes</h2>

                      <p>Actual saved fix proposals</p>

                    </div>



                    <button

                      className="text-button"

                      onClick={() => handleNavigation("Automatic Fixes")}

                    >

                      View all <ArrowUpRight size={16} />

                    </button>

                  </div>



                  {Object.entries(fixStatuses).map(([status, count]) => (

                    <div className="fix-status-row" key={status}>

                      <span>{readableStatus(status)}</span>

                      <strong>{count}</strong>

                    </div>

                  ))}



                  {recentFixes.slice(0, 4).map((fix) => (

                    <div className="data-list-item" key={fix.id}>

                      <div className="repo-icon">

                        <Wrench size={17} />

                      </div>



                      <div>

                        <strong>{fix.filename}</strong>

                        <small>{fix.repository}</small>

                        <small>{readableStatus(fix.status)}</small>

                      </div>

                    </div>

                  ))}

                </div>

              </section>



              <footer className="footer">

                <span>CodeGuard AI · Code Review Agent</span>



                <span>

                  {dashboard?.generated_at

                    ? `Data refreshed: ${formatDate(dashboard.generated_at)}`

                    : "Waiting for backend data"}

                </span>

              </footer>

            </>

          )}



          {/* ==================================================

              REPOSITORIES PAGE

          ================================================== */}



          {activePage === "Repositories" && (

            <section className="repository-page">

              {renderPageHeader(

                "GITHUB INTEGRATION",

                "Your Repositories",

                "Manage repositories connected to your AI Code Review Agent.",

                GitBranch

              )}

              <div className="repository-create-toolbar">
                <button
                  type="button"
                  className="create-repository-button"
                  onClick={() => {
                    setCreateRepositoryError("");
                    setShowCreateRepository(true);
                  }}
                >
                  <Plus size={17} />
                  Create Repository
                </button>
              </div>

              {repositoryNotice && (
                <div className="repository-notice" role="status">
                  <span>{repositoryNotice.message}</span>
                  {repositoryNotice.settingsUrl && (
                    <a href={repositoryNotice.settingsUrl} target="_blank" rel="noopener noreferrer">
                      Update GitHub App access <ExternalLink size={14} />
                    </a>
                  )}
                </div>
              )}



              <div className="repository-summary">

                <div className="stat-icon purple">

                  <GitBranch size={22} />

                </div>



                <div>

                  <strong>

                    {repositoriesLoading ? "..." : repositories.length}

                  </strong>

                  <span>Registered repositories</span>

                </div>

              </div>



              {repositoriesError && (

                <div className="api-error">

                  <AlertTriangle size={20} />

                  <div>

                    <strong>Unable to load repositories</strong>

                    <p>{repositoriesError}</p>

                  </div>

                  <button onClick={fetchRepositories}>Retry</button>

                </div>

              )}



              {repositoriesLoading ? (

                <div className="repository-empty">

                  Loading repositories from the backend...

                </div>

              ) : !repositoriesError &&

                filteredRepositories.length === 0 ? (

                <div className="repository-empty">

                  {repositories.length === 0

                    ? "No repositories have been registered yet."

                    : "No matching repositories found."}

                </div>

              ) : (

                <div className="repository-grid">

                  {filteredRepositories.map((repository) => (

                    <article

                      className="repository-card"

                      key={repository.id}

                    >

                      <div className="repository-card-top">

                        <div className="repo-icon">

                          <GitBranch size={21} />

                        </div>



                        <span className="repository-connected">

                          <span className="status-dot" />

                          Registered

                        </span>

                      </div>



                      <h3>

                        {repository.name || repository.full_name}

                      </h3>



                      <p className="repository-full-name">

                        {repository.full_name}

                      </p>



                      <div className="repository-id">

                        Database ID: #{repository.id}

                      </div>



                      {repository.html_url && (

                        <a

                          className="repository-github-link"

                          href={repository.html_url}

                          target="_blank"

                          rel="noopener noreferrer"

                        >

                          View on GitHub

                          <ExternalLink size={15} />

                        </a>

                      )}

                    </article>

                  ))}

                </div>

              )}

            </section>

          )}
              {showCreateRepository && (
                <div className="create-repository-overlay" role="presentation" onMouseDown={(event) => {
                  if (event.target === event.currentTarget && !creatingRepository) setShowCreateRepository(false);
                }}>
                  <section className="create-repository-modal" role="dialog" aria-modal="true" aria-labelledby="create-repository-title">
                    <div className="create-repository-modal-header">
                      <div>
                        <span className="welcome-tag"><GitBranch size={14} /> GITHUB REPOSITORY</span>
                        <h2 id="create-repository-title">Create Repository</h2>
                        <p>Create a repository in your connected personal GitHub account.</p>
                      </div>
                      <button type="button" className="create-repository-close" aria-label="Close" disabled={creatingRepository} onClick={() => setShowCreateRepository(false)}><X size={20} /></button>
                    </div>
                    <form onSubmit={createRepository} className="create-repository-form">
                      <label htmlFor="new-repository-name">Repository name</label>
                      <input id="new-repository-name" value={newRepositoryName} onChange={(event) => setNewRepositoryName(event.target.value)} placeholder="my-python-project" maxLength={100} required autoFocus />
                      <label htmlFor="new-repository-description">Description <span>(optional)</span></label>
                      <textarea id="new-repository-description" value={newRepositoryDescription} onChange={(event) => setNewRepositoryDescription(event.target.value)} placeholder="What is this repository about?" maxLength={350} rows={3} />
                      <fieldset
                        className="create-repository-visibility-options"
                        style={{
                          border: "1px solid rgba(148, 163, 184, 0.25)",
                          borderRadius: 12,
                          padding: 14,
                          margin: "12px 0",
                          minWidth: 0,
                        }}
                      >
                        <legend style={{ padding: "0 6px", fontWeight: 700 }}>
                          Repository visibility
                        </legend>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                            gap: 10,
                          }}
                        >
                          <label
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              gap: 9,
                              padding: 12,
                              borderRadius: 9,
                              border: newRepositoryPrivate
                                ? "1px solid #8b5cf6"
                                : "1px solid rgba(148, 163, 184, 0.25)",
                              background: newRepositoryPrivate
                                ? "rgba(139, 92, 246, 0.12)"
                                : "rgba(148, 163, 184, 0.05)",
                              cursor: "pointer",
                            }}
                          >
                            <input
                              type="radio"
                              name="repository-visibility"
                              checked={newRepositoryPrivate}
                              onChange={() => setNewRepositoryPrivate(true)}
                            />
                            <span>
                              <strong>Private</strong>
                              <small style={{ display: "block", marginTop: 5 }}>
                                Only you and people you grant access can view it.
                              </small>
                            </span>
                          </label>
                          <label
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              gap: 9,
                              padding: 12,
                              borderRadius: 9,
                              border: !newRepositoryPrivate
                                ? "1px solid #8b5cf6"
                                : "1px solid rgba(148, 163, 184, 0.25)",
                              background: !newRepositoryPrivate
                                ? "rgba(139, 92, 246, 0.12)"
                                : "rgba(148, 163, 184, 0.05)",
                              cursor: "pointer",
                            }}
                          >
                            <input
                              type="radio"
                              name="repository-visibility"
                              checked={!newRepositoryPrivate}
                              onChange={() => setNewRepositoryPrivate(false)}
                            />
                            <span>
                              <strong>Public</strong>
                              <small style={{ display: "block", marginTop: 5 }}>
                                Anyone can view this repository on GitHub.
                              </small>
                            </span>
                          </label>
                        </div>
                        <small style={{ display: "block", marginTop: 10, opacity: 0.75 }}>
                          Private is selected by default. You can change this before creating the repository.
                        </small>
                      </fieldset>
                      {createRepositoryError && <div className="create-repository-error" role="alert">{createRepositoryError}</div>}
                      <div className="create-repository-actions">
                        <button type="button" className="create-repository-cancel" disabled={creatingRepository} onClick={() => setShowCreateRepository(false)}>Cancel</button>
                        <button type="submit" className="create-repository-submit" disabled={creatingRepository || !newRepositoryName.trim()}>{creatingRepository ? "Creating..." : `Create ${newRepositoryPrivate ? "private" : "public"} repository`}</button>
                      </div>
                    </form>
                  </section>
                </div>
              )}




          {activePage === "Code Editor" && <CodeEditor />}

          {/* ==================================================

              PULL REQUESTS PAGE

          ================================================== */}



          {activePage === "Pull Requests" && (
            <section className="pull-requests-page">
              {renderPageHeader(
                "GITHUB INTEGRATION",
                "Pull Requests",
                "View live open and closed pull request counts for each connected repository.",
                GitPullRequest
              )}

              {/* Manage Pull Requests appears at the top of this page. */}
              <PullRequestManager
                onUpdated={async () => {
                  await fetchDashboard(true);
                  await fetchPullRequestSummaries();
                }}
              />

              <div className="repository-summary">
                <div className="stat-icon blue">
                  <GitPullRequest size={22} />
                </div>
                <div>
                  <strong>
                    {pullRequestSummariesLoading
                      ? "..."
                      : formatNumber(pullRequestSummaries.length)}
                  </strong>
                  <span>Connected repositories</span>
                </div>
              </div>

              {pullRequestSummariesError && (
                <div className="api-error">
                  <AlertTriangle size={20} />
                  <div>
                    <strong>Unable to load pull request counts</strong>
                    <p>{pullRequestSummariesError}</p>
                  </div>
                  <button onClick={fetchPullRequestSummaries}>Retry</button>
                </div>
              )}

              {pullRequestSummariesLoading ? (
                <div className="repository-empty">
                  Loading live pull request counts from GitHub...
                </div>
              ) : pullRequestSummariesError ? null : filteredPullRequestSummaries.length === 0 ? (
                <div className="repository-empty">
                  {pullRequestSummaries.length === 0
                    ? "No connected repositories found."
                    : "No matching repositories found."}
                </div>
              ) : (
                <div className="repository-grid">
                  {filteredPullRequestSummaries.map((item) => {
                    const repositoryName = item.repository || "Unknown repository";
                    const repositoryUrl =
                      item.html_url || getRepositoryUrl(repositoryName);
                    const openUrl = repositoryUrl
                      ? `${repositoryUrl.replace(/\/$/, "")}/pulls?q=is%3Aopen`
                      : null;
                    const closedUrl = repositoryUrl
                      ? `${repositoryUrl.replace(/\/$/, "")}/pulls?q=is%3Aclosed`
                      : null;

                    return (
                      <article className="repository-card" key={repositoryName}>
                        <div className="repository-card-top">
                          <div className="repo-icon">
                            <GitBranch size={21} />
                          </div>
                          <span className="repository-connected">
                            <span className="status-dot" />
                            GitHub repository
                          </span>
                        </div>

                        <h3>{repositoryName}</h3>
                        <p className="repository-full-name">
                          Live pull request status
                        </p>

                        {item.error ? (
                          <div className="api-error">
                            <AlertTriangle size={18} />
                            <span>{item.error}</span>
                          </div>
                        ) : (
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                              gap: 12,
                              marginTop: 18,
                            }}
                          >
                            <a
                              href={openUrl || undefined}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-disabled={!openUrl}
                              onClick={(event) => {
                                if (!openUrl) event.preventDefault();
                              }}
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 6,
                                padding: "14px",
                                borderRadius: 12,
                                textDecoration: "none",
                                background: "rgba(34, 197, 94, 0.10)",
                                border: "1px solid rgba(34, 197, 94, 0.25)",
                                color: "inherit",
                                cursor: openUrl ? "pointer" : "default",
                                opacity: openUrl ? 1 : 0.6,
                              }}
                            >
                              <span style={{ fontSize: 12, color: "#86efac" }}>
                                Open PRs
                              </span>
                              <strong style={{ fontSize: 25 }}>
                                {item.open_count ?? "—"}
                              </strong>
                              <span style={{ fontSize: 12 }}>
                                View on GitHub <ExternalLink size={12} />
                              </span>
                            </a>

                            <a
                              href={closedUrl || undefined}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-disabled={!closedUrl}
                              onClick={(event) => {
                                if (!closedUrl) event.preventDefault();
                              }}
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 6,
                                padding: "14px",
                                borderRadius: 12,
                                textDecoration: "none",
                                background: "rgba(148, 163, 184, 0.10)",
                                border: "1px solid rgba(148, 163, 184, 0.25)",
                                color: "inherit",
                                cursor: closedUrl ? "pointer" : "default",
                                opacity: closedUrl ? 1 : 0.6,
                              }}
                            >
                              <span style={{ fontSize: 12, color: "#cbd5e1" }}>
                                Closed PRs
                              </span>
                              <strong style={{ fontSize: 25 }}>
                                {item.closed_count ?? "—"}
                              </strong>
                              <span style={{ fontSize: 12 }}>
                                View on GitHub <ExternalLink size={12} />
                              </span>
                            </a>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}

            </section>
          )}

                    {activePage === "Code Reviews" && (

            <section className="code-reviews-page">

              {renderPageHeader(

                "AI CODE ANALYSIS",

                "Code Reviews",

                "Explore saved AI reviews and detected code issues.",

                ShieldCheck

              )}



              <div className="review-summary-grid">

                <div className="repository-summary">

                  <div className="stat-icon green">

                    <ShieldCheck size={22} />

                  </div>

                  <div>

                    <strong>{formatNumber(statistics.reviews)}</strong>

                    <span>Saved code reviews</span>

                  </div>

                </div>



                <div className="repository-summary">

                  <div className="stat-icon orange">

                    <ShieldAlert size={22} />

                  </div>

                  <div>

                    <strong>{formatNumber(statistics.issues)}</strong>

                    <span>Detected issues</span>

                  </div>

                </div>

              </div>



              {/* Finding sources */}

              <div className="panel source-panel">

                <div className="panel-heading">

                  <div>

                    <h2>Finding Sources</h2>

                    <p>Sources recorded in your database</p>

                  </div>

                </div>



                <div className="source-counts">

                  {Object.entries(issueSources).length === 0 ? (

                    <p className="empty-state">

                      No issue source information available.

                    </p>

                  ) : (

                    Object.entries(issueSources).map(([source, count]) => (

                      <div className="source-count-item" key={source}>

                        <div className="repo-icon">

                          <Code2 size={17} />

                        </div>



                        <div>

                          <strong>{readableStatus(source)}</strong>

                          <small>Recorded findings</small>

                        </div>



                        <span>{count}</span>

                      </div>

                    ))

                  )}

                </div>

              </div>



              {/* Review records */}

              <div className="panel review-records-panel">

                <div className="panel-heading">

                  <div>

                    <h2>Saved Review Records</h2>

                    <p>Review history stored in PostgreSQL</p>

                  </div>



                  <span className="record-count">

                    {filteredReviewRecords.length} records

                  </span>

                </div>



                {loading ? (

                  <div className="repository-empty">

                    Loading saved reviews...

                  </div>

                ) : filteredReviewRecords.length === 0 ? (

                  <div className="repository-empty">

                    No matching review records found.

                  </div>

                ) : (

                  <div className="review-record-list">

                    {filteredReviewRecords.map((review) => (

                      <article

                        className="review-record-card"

                        key={review.id}

                      >

                        <div className="review-record-top">

                          <div className="repo-icon">

                            <FileCode size={19} />

                          </div>



                          <div className="review-record-title">

                            <strong>

                              {review.pull_request_title ||

                                `Pull Request #${review.pull_request_number}`}

                            </strong>



                            <small>{review.repository}</small>

                          </div>



                          <span

                            className={`severity ${

                              review.status === "passed" ? "low" : "medium"

                            }`}

                          >

                            {readableStatus(review.status)}

                          </span>

                        </div>



                        <p className="review-record-summary">

                          {review.summary || "No review summary available."}

                        </p>



                        <div className="review-record-meta">

                          <span>

                            <GitPullRequest size={14} />

                            PR #{review.pull_request_number ?? "—"}

                          </span>



                          <span>

                            <CircleAlert size={14} />

                            {review.issue_count ?? review.issues?.length ?? 0}

                            {" "}issues

                          </span>



                          <span>

                            <CalendarDays size={14} />

                            {formatDate(review.created_at)}

                          </span>

                        </div>



                        {review.repository_url && (

                          <a

                            className="repository-github-link"

                            href={getPullRequestUrl(

                              review.repository,

                              review.pull_request_number

                            ) || review.repository_url}

                            target="_blank"

                            rel="noopener noreferrer"

                          >

                            View on GitHub

                            <ExternalLink size={14} />

                          </a>

                        )}

                      </article>

                    ))}

                  </div>

                )}

              </div>



              {/* Detailed issue list */}

              <div className="panel review-panel detailed-issues-panel">

                <div className="panel-heading">

                  <div>

                    <h2>Detected Issues</h2>

                    <p>Individual findings from saved code reviews</p>

                  </div>



                  <span className="record-count">

                    {filteredReviews.length} findings

                  </span>

                </div>



                <div className="table-wrapper">

                  <table>

                    <thead>

                      <tr>

                        <th>Repository / File</th>

                        <th>Issue Description</th>

                        <th>Severity</th>

                        <th>Source</th>

                        <th>Line</th>

                      </tr>

                    </thead>



                    <tbody>

                      {filteredReviews.map((review) => (

                        <tr key={review.id}>

                          <td>

                            <div className="repo-name">

                              <div className="repo-icon">

                                <Code2 size={17} />

                              </div>



                              <div>

                                <strong>{review.repository}</strong>

                                <small>{review.file}</small>

                              </div>

                            </div>

                          </td>



                          <td>

                            <span title={review.issue}>

                              {review.issue}

                            </span>

                          </td>



                          <td>

                            <span

                              className={`severity ${review.severity.toLowerCase()}`}

                            >

                              {review.severity}

                            </span>

                          </td>



                          <td>

                            <span className="issue-source-label">

                              {readableStatus(review.source)}

                            </span>

                          </td>



                          <td>{review.line ?? "—"}</td>

                        </tr>

                      ))}



                      {filteredReviews.length === 0 && (

                        <tr>

                          <td colSpan="5" className="empty-state">

                            No issues found.

                          </td>

                        </tr>

                      )}

                    </tbody>

                  </table>

                </div>

              </div>

            </section>

          )}



          {/* ==================================================

              AUTOMATIC FIXES PAGE

          ================================================== */}



          {activePage === "Automatic Fixes" && (

            <section className="automatic-fixes-page">

              {renderPageHeader(

                "AI CODE FIXING",

                "Automatic Fixes",

                "Generate a fix, review its preview, then approve or reject it.",

                Wrench

              )}

              <AIFixPanel />

              <FixApprovalPanel />

            </section>

          )}



          {/* ==================================================

              SETTINGS PAGE

          ================================================== */}



          {activePage === "Settings" && (

            <section className="settings-page">

              {renderPageHeader(

                "APPLICATION CONFIGURATION",

                "Settings",

                "Application and backend connection information.",

                Settings

              )}



              <div className="panel settings-panel">

                <div className="panel-heading">

                  <div>

                    <h2>Backend Connection</h2>

                    <p>Current API connection information</p>

                  </div>



                  <span

                    className={`severity ${backendConnected ? "low" : "critical"}`}

                  >

                    {backendConnected ? "Connected" : "Unavailable"}

                  </span>

                </div>



                <div className="settings-row">

                  <Database size={19} />

                  <div>

                    <strong>FastAPI backend</strong>

                    <small>{API_BASE_URL}</small>

                  </div>

                </div>



                <div className="settings-row">

                  <Activity size={19} />

                  <div>

                    <strong>Dashboard endpoint</strong>

                    <small>/dashboard/summary</small>

                  </div>

                </div>



                <div className="settings-row">

                  <GitBranch size={19} />

                  <div>

                    <strong>Repository endpoint</strong>

                    <small>/repositories/</small>

                  </div>

                </div>



                <div className="settings-row">

                  <Wrench size={19} />

                  <div>

                    <strong>Fix proposals endpoint</strong>

                    <small>/fixes/</small>

                  </div>

                </div>



                <div className="pipeline-note">

                  <Info size={18} />

                  API credentials and approval tokens must remain on the

                  backend, not in frontend source code.

                </div>

              </div>

            </section>

          )}

        </div>

      </main>



    </div>

  );

}



export default App;
