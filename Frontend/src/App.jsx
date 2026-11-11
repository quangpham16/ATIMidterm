import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { API_URL, ApiError, request, TOKEN_KEY } from "./api.js";
import { normalizeSuite } from "./test-suites.js";
import { projectPath, returnPath, suitePath } from "./routes.js";

function Icon({ name, size = 20 }) {
  const paths = {
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    panel: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>,
    trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7" />,
    logout: <><path d="M10 4H5v16h5M9 12h12m-4-4 4 4-4 4" /></>,
    file: <><path d="M14 3H6v18h12V7l-4-4Z" /><path d="M14 3v5h4M9 12h6m-6 4h6" /></>,
    folder: <path d="M3 7V5h6l2 3h10v12H3V7Z" />,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" /></>,
    play: <path d="m9 5 11 7-11 7V5Z" />,
    code: <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18" />,
    copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function Brand({ className = "", to, onClick, disabled = false }) {
  const Element = to ? Link : "div";
  return <Element className={`brand ${to ? "brand-home " : ""}${className}`} to={to} onClick={disabled ? (event) => event.preventDefault() : onClick} aria-disabled={disabled || undefined} aria-label={to ? "Case Foundry home" : undefined}><span className="brand-mark" aria-hidden="true"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M7 4H4v16h3M17 4h3v16h-3M9 12l2 2 4-4" /></svg></span><span>Case Foundry</span></Element>;
}
function suiteTitle(suite) { return suite?.title || `Test suite ${suite?.id?.slice(0, 8) || ""}`; }
function savedDate(value) {
  if (!value) return "Saved suite";
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? "Saved suite" : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function CopyButton({ text, label, children }) {
  const [status, setStatus] = useState("idle");

  useEffect(() => { setStatus("idle"); }, [text]);
  useEffect(() => {
    if (status !== "copied") return;
    const timeout = setTimeout(() => setStatus("idle"), 2000);
    return () => clearTimeout(timeout);
  }, [status]);

  async function copy() {
    setStatus("copying");
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("error");
    }
  }

  return <div className="copy-control">
    <button type="button" className="copy-button" onClick={copy} disabled={status === "copying"} aria-label={`Copy ${label}`}>
      <Icon name={status === "copied" ? "check" : "copy"} size={14} />
      {status === "copied" ? "Copied" : status === "copying" ? "Copying…" : children}
    </button>
    <span className={status === "error" ? "copy-error" : "sr-only"} role="status">{status === "error" ? "Could not copy. Select the text and copy manually." : status === "copied" ? `${label} copied to clipboard.` : ""}</span>
  </div>;
}

function AuthScreen({ mode, onAuthenticated, notice = "" }) {
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(notice);
  const [loading, setLoading] = useState(false);
  const registering = mode === "register";

  async function submit(event) {
    event.preventDefault();
    if (loading) return;
    setError("");
    if (registering && password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const payload = await request(`/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim(), password }) });
      onAuthenticated(payload);
    } catch (authError) { setError(authError.message); } finally { setLoading(false); }
  }

  function switchMode() {
    setPassword("");
    setConfirmation("");
    setShowPassword(false);
    setError("");
  }

  return <main className="auth-shell">
    <div className="auth-panel">
      <Brand className="auth-brand" />
      <h1>{registering ? "Create an account" : "Welcome back"}</h1>
      <p className="auth-intro">{registering ? "A home for your projects and test suites." : "Sign in to your testing workspace."}</p>
      <form onSubmit={submit} className="auth-form" aria-busy={loading}>
        <label htmlFor="auth-email">Email address
          <input id="auth-email" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={254} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={loading} placeholder="you@company.com" />
        </label>
        <div className="password-field">
          <label htmlFor="auth-password">Password</label>
          <div className="password-input">
            <input id="auth-password" name="password" type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={registering ? 8 : 1} maxLength={128} autoComplete={registering ? "new-password" : "current-password"} disabled={loading} aria-describedby={registering ? "password-hint" : undefined} placeholder={registering ? "At least 8 characters" : "Enter your password"} />
            <button type="button" className="password-toggle" onClick={() => setShowPassword(!showPassword)} disabled={loading} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}>{showPassword ? "Hide" : "Show"}</button>
          </div>
          {registering && <p id="password-hint" className="password-hint">Use 8–128 characters.</p>}
        </div>
        {registering && <label htmlFor="auth-confirmation">Confirm password
          <input id="auth-confirmation" name="confirmPassword" type={showPassword ? "text" : "password"} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required minLength={8} maxLength={128} autoComplete="new-password" disabled={loading} placeholder="Enter your password again" />
        </label>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button disabled={loading} type="submit">{loading ? registering ? "Creating account…" : "Signing in…" : registering ? "Create account" : "Sign in"}</button>
      </form>
      <Link className="mode-toggle" to={registering ? "/login" : "/register"} state={location.state} aria-disabled={loading || undefined} onClick={(event) => { if (loading) event.preventDefault(); else switchMode(); }}>{registering ? "Already have an account? Sign in" : "Need an account? Create one"}</Link>
    </div>
  </main>;
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [notice, setNotice] = useState("");
  const [sessionError, setSessionError] = useState("");
  const [sessionAttempt, setSessionAttempt] = useState(0);

  const clearSession = useCallback((message = "") => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setSessionError("");
    setNotice(message);
  }, []);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    request("/auth/me", { signal: controller.signal }, token).then((profile) => {
      if (!controller.signal.aborted) {
        setUser(profile);
        setSessionError("");
      }
    }).catch((sessionFailure) => {
      if (controller.signal.aborted) return;
      if (sessionFailure.status === 401) clearSession("Your session has expired. Please sign in again.");
      else setSessionError(sessionFailure.message);
    });
    return () => controller.abort();
  }, [token, sessionAttempt, clearSession]);

  function authenticated(payload) {
    localStorage.setItem(TOKEN_KEY, payload.token);
    setUser(payload.user);
    setToken(payload.token);
    setNotice("");
    setSessionError("");
  }

  function logout() {
    clearSession();
    navigate("/login", { replace: true });
    request("/auth/logout", { method: "POST" }, token).catch(() => {});
  }

  const sessionExpired = useCallback(() => clearSession("Your session has expired. Please sign in again."), [clearSession]);

  const sessionScreen = <main className="session-screen"><Brand />
    {sessionError ? <><p role="alert">{sessionError}</p><button onClick={() => { setSessionError(""); setSessionAttempt((attempt) => attempt + 1); }}>Try again</button><button onClick={logout}>Back to sign in</button></> : <p role="status">Opening your workspace…</p>}
  </main>;
  const workspace = !token
    ? <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}${location.hash}` }} />
    : !user ? sessionScreen
      : <Workspace key={`${token}:${location.pathname}`} token={token} user={user} logout={logout} onSessionExpired={sessionExpired} />;
  const authPage = (mode) => token
    ? user ? <Navigate to={returnPath(location.state?.from)} replace /> : sessionScreen
    : <AuthScreen key={mode} mode={mode} onAuthenticated={authenticated} notice={notice} />;

  return <Routes>
    <Route path="/login" element={authPage("login")} />
    <Route path="/register" element={authPage("register")} />
    <Route path="/" element={workspace} />
    <Route path="/projects/:projectId" element={workspace} />
    <Route path="/suites/:suiteId" element={workspace} />
    <Route path="*" element={<main className="session-screen"><Brand /><h1>Page not found</h1><p>This address does not match a page.</p><Link to={token ? "/" : "/login"}>Back to {token ? "workspace" : "sign in"}</Link></main>} />
  </Routes>;
}

function Workspace({ token, user, logout, onSessionExpired }) {
  const { projectId, suiteId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const active = useRef(true);
  const resultRef = useRef(null);
  const errorRef = useRef(null);
  const fileInputRef = useRef(null);
  const composerRef = useRef(null);
  const sourceInputRef = useRef(null);
  const [sourceLanguage, setSourceLanguage] = useState("python");
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [historyVersion, setHistoryVersion] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [routeLoading, setRouteLoading] = useState(Boolean(projectId || suiteId));
  const [routeFailed, setRouteFailed] = useState(false);
  const [routeVersion, setRouteVersion] = useState(0);
  const openingId = routeLoading && suiteId ? suiteId : null;
  const [deleting, setDeleting] = useState(false);
  const showEditor = !suiteId && !routeLoading && !routeFailed;
  const [operationMessage, setOperationMessage] = useState(location.state?.message || "");
  const newSuiteHeadingRef = useRef(null);
  const sidebarCloseRef = useRef(null);
  const sidebarRef = useRef(null);
  const historyToggleRef = useRef(null);
  const projectDialogRef = useRef(null);
  const projectNameRef = useRef(null);
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState("");
  const [projectsVersion, setProjectsVersion] = useState(0);
  const [selectedProject, setSelectedProject] = useState(null);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectCreateError, setProjectCreateError] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [file, setFile] = useState(null); const [sourceCode, setSourceCode] = useState(""); const [result, setResult] = useState(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  const selectedProjectId = projectId || result?.project_id || "";

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (!projectId && !suiteId) return;
    const controller = new AbortController();
    setRouteLoading(true); setRouteFailed(false); setError("");
    async function loadRoute() {
      try {
        const saved = suiteId ? normalizeSuite(await request(`/testcases/${encodeURIComponent(suiteId)}`, { signal: controller.signal }, token)) : null;
        if (controller.signal.aborted) return;
        const id = projectId || saved?.project_id;
        const project = id ? await request(`/projects/${encodeURIComponent(id)}`, { signal: controller.signal }, token) : null;
        if (controller.signal.aborted) return;
        setSelectedProject(project); setResult(saved);
      } catch (routeError) {
        if (controller.signal.aborted) return;
        if (routeError.status === 401) onSessionExpired();
        else { setError(routeError.message); setRouteFailed(true); }
      } finally { if (!controller.signal.aborted) setRouteLoading(false); }
    }
    loadRoute();
    return () => controller.abort();
  }, [projectId, suiteId, routeVersion, token, onSessionExpired]);

  useEffect(() => {
    const input = sourceInputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 320)}px`;
  }, [sourceCode, showEditor]);

  useEffect(() => {
    const controller = new AbortController();
    setHistoryLoading(true);
    setHistoryError("");
    const path = selectedProjectId ? `/testcases/history?project_id=${encodeURIComponent(selectedProjectId)}` : "/testcases/history";
    request(path, { signal: controller.signal }, token).then((items) => {
      if (!controller.signal.aborted) setHistory(items);
    }).catch((historyFailure) => {
      if (controller.signal.aborted) return;
      if (historyFailure.status === 401) onSessionExpired();
      else setHistoryError(historyFailure.message);
    }).finally(() => {
      if (!controller.signal.aborted) setHistoryLoading(false);
    });
    return () => controller.abort();
  }, [token, historyVersion, selectedProjectId, onSessionExpired]);

  useEffect(() => {
    const controller = new AbortController();
    setProjectsLoading(true); setProjectsError("");
    request("/projects", { signal: controller.signal }, token).then((items) => {
      if (!controller.signal.aborted) setProjects(items);
    }).catch((projectFailure) => {
      if (controller.signal.aborted) return;
      if (projectFailure.status === 401) onSessionExpired();
      else setProjectsError(projectFailure.message);
    }).finally(() => { if (!controller.signal.aborted) setProjectsLoading(false); });
    return () => controller.abort();
  }, [token, projectsVersion, onSessionExpired]);

  useEffect(() => {
    const dialog = projectDialogRef.current;
    if (projectDialogOpen && !dialog.open) { dialog.showModal(); projectNameRef.current?.focus(); }
    else if (!projectDialogOpen && dialog.open) dialog.close();
  }, [projectDialogOpen]);

  useEffect(() => {
    if (!sidebarOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarCloseRef.current?.focus();
    function escape(event) {
      if (event.key === "Escape") { setSidebarOpen(false); historyToggleRef.current?.focus(); }
      if (event.key === "Tab") {
        const controls = Array.from(sidebarRef.current?.querySelectorAll("a[href], button:not(:disabled)") || []).filter((control) => control.getClientRects().length);
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    const desktop = window.matchMedia("(min-width: 901px)");
    function closeOnDesktop() { if (desktop.matches) setSidebarOpen(false); }
    window.addEventListener("keydown", escape);
    desktop.addEventListener("change", closeOnDesktop);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", escape);
      desktop.removeEventListener("change", closeOnDesktop);
    };
  }, [sidebarOpen]);

  useEffect(() => {
    if (loading || routeLoading) return;
    const target = error ? errorRef.current : result ? resultRef.current : showEditor ? newSuiteHeadingRef.current : null;
    if (!target) return;
    target.focus({ preventScroll: true });
    target.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      block: "start",
    });
  }, [result, error, loading, routeLoading, showEditor]);

  function handleError(requestError) {
    if (!active.current) return;
    if (requestError.status === 401) onSessionExpired();
    else setError(requestError.message);
  }
  const busy = loading || routeLoading || deleting || creatingProject;
  const editorPath = selectedProjectId ? projectPath(selectedProjectId) : "/";

  function handleNavigation(event, path) {
    if (busy) { event.preventDefault(); return; }
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    setSidebarOpen(false);
    if (path === location.pathname) {
      if (suiteId) resultRef.current?.focus();
      else resetEditor();
    }
  }

  function openProjectDialog() {
    setSidebarOpen(false); setProjectName(""); setProjectCreateError(""); setProjectDialogOpen(true);
  }

  async function createProject(event) {
    event.preventDefault();
    if (creatingProject || !projectName.trim()) return;
    setCreatingProject(true); setProjectCreateError("");
    try {
      const project = await request("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: projectName.trim() }) }, token);
      if (!active.current) return;
      setProjectDialogOpen(false); setProjectName("");
      navigate(projectPath(project.id));
    } catch (createError) {
      if (!active.current) return;
      if (createError.status === 401) onSessionExpired();
      else setProjectCreateError(createError.message);
    } finally { if (active.current) setCreatingProject(false); }
  }

  function resetEditor() {
    setResult(null); setFile(null); setSourceCode(""); setSourceLanguage("python");
    setError(""); setOperationMessage(""); setSidebarOpen(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    window.scrollTo({ top: 0, behavior: "instant" });
    requestAnimationFrame(() => newSuiteHeadingRef.current?.focus({ preventScroll: true }));
    if (location.pathname !== editorPath) navigate(editorPath);
  }

  async function deleteSuite() {
    if (!result || busy || !window.confirm(`Delete "${suiteTitle(result)}"? This permanently removes the saved suite and its exports.`)) return;
    const id = result.id;
    setDeleting(true); setError("");
    try {
      await request(`/testcases/${encodeURIComponent(id)}`, { method: "DELETE" }, token);
      if (!active.current) return;
      navigate(editorPath, { replace: true, state: { message: "Saved suite deleted." } });
    } catch (deleteError) { handleError(deleteError); }
    finally { if (active.current) setDeleting(false); }
  }
  async function downloadExport(format) {
    try {
      const response = await fetch(`${API_URL}/exports/${result.id}.${format}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new ApiError(response.status === 401 ? "Your session has expired. Please sign in again." : "Export could not be downloaded.", response.status);
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = format === "py" ? "test_generated.py" : ["js", "ts"].includes(format) ? `test_generated.test.${format}` : `test-suite.${format}`; link.click(); URL.revokeObjectURL(url);
    } catch (downloadError) { handleError(downloadError); }
  }
  async function generate(event) {
    event.preventDefault();
    if (busy) return;
    if (!file && !sourceCode.trim()) return setError("Add an OpenAPI file or paste source code to begin.");
    const body = new FormData(); if (file) body.append("swagger_file", file);
    if (sourceCode.trim()) { body.append("source_code", sourceCode); body.append("source_language", sourceLanguage); }
    if (selectedProjectId) body.append("project_id", selectedProjectId);
    setLoading(true); setError(""); setResult(null); setOperationMessage("");
    try {
      const payload = await request("/testcases/generate", { method: "POST", body }, token);
      if (active.current) {
        const saved = normalizeSuite(payload);
        navigate(suitePath(saved.id));
      }
    } catch (requestError) { handleError(requestError); } finally { setLoading(false); }
  }
  const apiCases = result?.api_test_cases || []; const unitCases = result?.unit_test_cases || [];
  const unitCode = result?.unit_test_code || result?.unit_pytest_code || "";
  const codeExtension = result?.source_language === "typescript" ? "ts" : result?.source_language === "javascript" ? "js" : "py";
  const sourceFileName = `source_under_test.${codeExtension}`;
  const testCommand = codeExtension === "py" ? "python -m pytest test_generated.py" : `npx vitest run test_generated.test.${codeExtension}`;
  return <main className="app-shell">
    {sidebarOpen && <button className="sidebar-overlay" aria-label="Close suite history" onClick={() => { setSidebarOpen(false); historyToggleRef.current?.focus(); }} />}
    <aside ref={sidebarRef} className={`rail ${sidebarOpen ? "is-open" : ""}`} role={sidebarOpen ? "dialog" : undefined} aria-modal={sidebarOpen || undefined} aria-label="Suite history">
      <div className="sidebar-brand"><Brand to="/" onClick={(event) => handleNavigation(event, "/")} disabled={busy} /><button ref={sidebarCloseRef} className="icon-button sidebar-close" aria-label="Close history" onClick={() => { setSidebarOpen(false); historyToggleRef.current?.focus(); }}><Icon name="panel" /></button></div>
      <Link className="new-suite" to={editorPath} aria-disabled={busy || undefined} onClick={(event) => handleNavigation(event, editorPath)}><Icon name="plus" /> New test suite</Link>
      <nav className="suite-history" aria-label="Saved test suites">
        <Link className="project-link all-suites" to="/" aria-current={!selectedProjectId && !suiteId ? "page" : undefined} aria-disabled={busy || undefined} onClick={(event) => handleNavigation(event, "/")}><Icon name="grid" size={17} /><span>All suites</span></Link>
        <div className="projects-heading"><span>Projects</span><button className="icon-button" aria-label="New project" title="New project" disabled={busy} onClick={openProjectDialog}><Icon name="plus" size={17} /></button></div>
        {projectsLoading && !projects.length && <p className="sidebar-note" role="status">Loading projects…</p>}
        {projectsError && <div className="sidebar-error" role="alert"><p>{projectsError}</p><button onClick={() => setProjectsVersion((version) => version + 1)}>Try projects again</button></div>}
        {!projectsLoading && !projectsError && !projects.length && <p className="sidebar-note">No projects yet</p>}
        <ul className="project-list">{projects.map((project) => <li key={project.id}><Link className="project-link" to={projectPath(project.id)} aria-current={selectedProjectId === project.id ? "page" : undefined} aria-disabled={busy || undefined} onClick={(event) => handleNavigation(event, projectPath(project.id))} title={project.name}><Icon name="folder" size={17} /><span>{project.name}</span><small>{project.suite_count}</small></Link></li>)}</ul>
        <div className="suite-history-heading">{selectedProject ? "Project suites" : "Recent suites"}</div>
        {historyLoading && !history.length && <p className="sidebar-note" role="status">Loading saved suites…</p>}
        {historyError && <div className="sidebar-error" role="alert"><p>{historyError}</p><button onClick={() => setHistoryVersion((version) => version + 1)}>Try again</button></div>}
        {!historyLoading && !historyError && !history.length && <p className="sidebar-note">{selectedProjectId ? "No suites in this project yet" : "No saved suites yet"}</p>}
        <ul className="suite-list">{history.map((item) => <li key={item.id}>
          <Link className="suite-link" to={suitePath(item.id)} aria-disabled={busy || undefined} title={`${suiteTitle(item)} — ${savedDate(item.created_at)}`} aria-current={suiteId === item.id ? "page" : undefined} onClick={(event) => handleNavigation(event, suitePath(item.id))}>
            <Icon name="file" size={16} /><span className="suite-link-title">{suiteTitle(item)}</span>{openingId === item.id && <span className="opening-indicator" role="status">Opening…</span>}
          </Link>
        </li>)}</ul>
      </nav>
      <div className="sidebar-account"><span className="account-avatar" aria-hidden="true">{user.email.slice(0, 2).toUpperCase()}</span><span className="account-email" title={user.email}>{user.email}</span><button className="icon-button" onClick={logout} aria-label="Sign out" title="Sign out"><Icon name="logout" size={18} /></button></div>
    </aside>
    <div className="content">
      <header className="topbar"><div className="page-heading"><button ref={historyToggleRef} className="icon-button history-toggle" aria-label="Open history" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Icon name="panel" /></button><span className="page-title">{routeLoading ? suiteId ? "Opening suite…" : "Opening project…" : routeFailed ? "Unable to open page" : showEditor ? selectedProject?.name || "Test workspace" : suiteTitle(result)}</span>{selectedProject && !showEditor && <span className="suite-project-name">{selectedProject.name}</span>}</div><div className="account">
        {result && <button className="icon-button delete-suite" aria-label="Delete saved suite" title="Delete suite" disabled={busy} onClick={deleteSuite}><Icon name="trash" /></button>}
      </div></header>
      {operationMessage && <p className="sr-only" role="status">{operationMessage}</p>}
      <div className={`workspace-body ${showEditor ? "is-new" : ""}`}>
      {routeLoading && <p className="route-status" role="status">{suiteId ? "Loading saved suite…" : "Loading project…"}</p>}
      {routeFailed && <div className="route-actions"><button type="button" onClick={() => setRouteVersion((version) => version + 1)}>Try again</button><Link to="/">Back to workspace</Link></div>}
      {showEditor && <section className="new-suite-view">
        {selectedProject && <p className="project-context"><Icon name="folder" size={15} />New suites will be saved to <strong>{selectedProject.name}</strong></p>}
        <form ref={composerRef} className="composer" onSubmit={generate} onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); }} onDrop={(event) => { if (!event.dataTransfer.files.length) return; event.preventDefault(); if (busy) return; const dropped = event.dataTransfer.files[0]; if (!/\.(json|ya?ml)$/i.test(dropped.name)) { setError("Attach an OpenAPI file in JSON or YAML format."); return; } setFile(dropped); setError(""); }}>
          <div className="composer-heading"><h2 ref={newSuiteHeadingRef} tabIndex={-1}>Test inputs</h2><span>Add either or both</span></div>
          <input ref={fileInputRef} id="openapi-file" type="file" className="file-picker" aria-label="OpenAPI file" accept=".json,.yaml,.yml" disabled={loading} onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="input-section upload-section">
            <label className="input-label" htmlFor="openapi-file">API specification</label>
            {file ? <div className="attachment"><Icon name="file" size={22} /><div className="attachment-info"><span>{file.name}</span><small>OpenAPI specification attached</small></div><button type="button" className="icon-button" aria-label="Remove file" disabled={loading} onClick={() => { setFile(null); if (fileInputRef.current) fileInputRef.current.value = ""; }}><Icon name="close" size={17} /></button></div> : <button id="openapi-upload" type="button" className="upload-button" aria-label="Attach OpenAPI file" disabled={loading} onClick={() => fileInputRef.current?.click()}><span className="upload-icon"><Icon name="upload" size={23} /></span><span className="upload-copy"><strong>Upload an OpenAPI file</strong><span>Choose a JSON or YAML file, or drop it here</span></span><span className="upload-action">Browse files</span></button>}
          </div>
          <div className="input-section source-section">
            <div className="source-heading"><label className="input-label" htmlFor="source-code"><Icon name="code" size={17} />Source code</label>
            <select className="language-select" aria-label="Source language" value={sourceLanguage} disabled={loading} onChange={(event) => setSourceLanguage(event.target.value)}>
              <option value="python">Python</option><option value="javascript">JavaScript</option><option value="typescript">TypeScript</option>
            </select>
            </div>
            <textarea ref={sourceInputRef} id="source-code" className={sourceCode ? "with-code" : ""} value={sourceCode} disabled={loading} onChange={(event) => setSourceCode(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); composerRef.current?.requestSubmit(); } }} placeholder={`Paste ${sourceLanguage === "python" ? "Python" : sourceLanguage === "javascript" ? "JavaScript" : "TypeScript"} functions or classes to generate unit tests…`} rows={7} />
          </div>
          <div className="composer-tools">
            {loading && <span className="generation-status" role="status">Generating…</span>}
            <button className="generate-button" disabled={busy || (!file && !sourceCode.trim())} type="submit" aria-label={loading ? "Generating test suite" : sourceCode.trim() && !file ? "Generate unit tests" : "Generate test suite"} title="Generate tests (Ctrl+Enter)">{loading ? <span className="spinner" /> : <Icon name="play" size={17} />}<span>{loading ? "Generating…" : "Generate tests"}</span></button>
          </div>
        </form>
        {error && <div className="error" ref={errorRef} role="alert" tabIndex={-1}>{error}</div>}
      </section>}
      {!showEditor && error && <div className="error" ref={errorRef} role="alert" tabIndex={-1}>{error}</div>}
      {result && <section key={result.id} className="results saved-results" ref={resultRef} tabIndex={-1} aria-labelledby="results-heading">
        <div className="results-top"><div><h2 id="results-heading">Generated tests</h2><p className="result-summary">{apiCases.length} API {apiCases.length === 1 ? "case" : "cases"} · {unitCases.length} unit {unitCases.length === 1 ? "case" : "cases"}{result.created_at ? ` · ${savedDate(result.created_at)}` : ""}</p></div>
          <div className="exports" aria-label="Download suite"><button onClick={() => downloadExport("json")}>JSON</button>
            {result.pytest_code?.trim() && <button onClick={() => downloadExport("py")}>Python</button>}
            {unitCode && codeExtension !== "py" && <button onClick={() => downloadExport(codeExtension)}>{codeExtension === "ts" ? "TypeScript" : "JavaScript"}</button>}
            <button onClick={() => downloadExport("csv")}>CSV</button>
          </div>
        </div>
        {unitCode && <div className="result-block">
          <div className="block-head"><h3>Generated unit test code</h3><div className="block-actions"><span>{result.unit_test_framework || "pytest"}</span><CopyButton text={unitCode} label="unit test code">Copy</CopyButton></div></div>
          <details className="test-instructions"><summary>How to run these tests</summary><p>Save your original code as <code>{sourceFileName}</code> beside the downloaded test file{codeExtension !== "py" ? " and export the functions or classes under test" : ""}. Install {codeExtension === "py" ? "pytest" : "Vitest"} and your code’s dependencies, then run <code>{testCommand}</code>.</p></details>
          <pre aria-label="Generated unit test code">{unitCode}</pre>
        </div>}
        {apiCases.length > 0 && <div className="result-block"><div className="block-head"><h3>API / contract tests</h3><div className="block-actions"><span>{apiCases.length} {apiCases.length === 1 ? "case" : "cases"}</span><CopyButton text={JSON.stringify(apiCases, null, 2)} label="API test cases">Copy</CopyButton></div></div>
          <details className="test-instructions"><summary>How to run downloaded API tests</summary><p>Download Python, then install pytest and httpx. Set <code>API_BASE_URL</code> to your API URL, including its path prefix, and optionally set <code>API_BEARER_TOKEN</code> or <code>API_HEADERS_JSON</code>. Run <code>python -m pytest test_generated.py</code>. Requests that change data require <code>API_ALLOW_MUTATIONS=true</code>.</p>{result.pytest_code?.trim() && <><div className="code-actions"><CopyButton text={result.pytest_code} label="API test code">Copy code</CopyButton></div><pre aria-label="Generated API test code">{result.pytest_code}</pre></>}</details>
          <pre aria-label="Generated API test cases">{JSON.stringify(apiCases, null, 2)}</pre></div>}
        {unitCases.length > 0 && <div className="result-block"><div className="block-head"><h3>Unit test cases</h3><div className="block-actions"><span>{unitCases.length} {unitCases.length === 1 ? "case" : "cases"}</span><CopyButton text={JSON.stringify(unitCases, null, 2)} label="unit test cases">Copy</CopyButton></div></div><pre aria-label="Generated unit test cases">{JSON.stringify(unitCases, null, 2)}</pre></div>}
      </section>}
      </div>
    </div>
    <dialog ref={projectDialogRef} className="project-dialog" aria-labelledby="project-dialog-title" onCancel={(event) => { if (creatingProject) event.preventDefault(); else setProjectDialogOpen(false); }}>
      <form onSubmit={createProject}>
        <h2 id="project-dialog-title">Create project</h2>
        <label htmlFor="project-name">Project name</label>
        <input ref={projectNameRef} id="project-name" name="projectName" value={projectName} onChange={(event) => setProjectName(event.target.value)} maxLength={100} required disabled={creatingProject} autoComplete="off" placeholder="e.g. Task manager" />
        {projectCreateError && <p className="project-form-error" role="alert">{projectCreateError}</p>}
        <div className="project-dialog-actions"><button type="button" disabled={creatingProject} onClick={() => setProjectDialogOpen(false)}>Cancel</button><button className="primary-button" type="submit" disabled={creatingProject || !projectName.trim()}>{creatingProject ? "Creating…" : "Create project"}</button></div>
      </form>
    </dialog>
  </main>;
}
