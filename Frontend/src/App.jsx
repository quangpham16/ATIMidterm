import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, ApiError, request, TOKEN_KEY } from "./api.js";
import { normalizeSuite } from "./test-suites.js";

function Icon({ name, size = 20 }) {
  const paths = {
    plus: <path d="M12 5v14M5 12h14" />,
    send: <path d="M12 19V5m-6 6 6-6 6 6" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    panel: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>,
    edit: <><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" /><path d="m15 4 5 5M10 14l1-5 8-8 4 4-8 8-5 1Z" transform="translate(-1 2) scale(.9)" /></>,
    trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7" />,
    logout: <><path d="M10 4H5v16h5M9 12h12m-4-4 4 4-4 4" /></>,
    file: <><path d="M14 3H6v18h12V7l-4-4Z" /><path d="M14 3v5h4M9 12h6m-6 4h6" /></>,
    folder: <path d="M3 7V5h6l2 3h10v12H3V7Z" />,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function suiteTitle(suite) { return suite?.title || `Test suite ${suite?.id?.slice(0, 8) || ""}`; }
function savedDate(value) {
  if (!value) return "Saved suite";
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? "Saved suite" : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function AuthScreen({ onAuthenticated, notice = "" }) {
  const [mode, setMode] = useState("login");
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
    setMode(registering ? "login" : "register");
    setPassword("");
    setConfirmation("");
    setShowPassword(false);
    setError("");
  }

  return <main className="auth-shell">
    <div className="auth-panel">
      <div className="brand auth-brand">Case Foundry</div>
      <h1>{registering ? "Create an account" : "Welcome back"}</h1>
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
      <button className="mode-toggle" disabled={loading} onClick={switchMode}>{registering ? "Already have an account? Sign in" : "Need an account? Create one"}</button>
    </div>
  </main>;
}

export default function App() {
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
    request("/auth/logout", { method: "POST" }, token).catch(() => {});
  }

  const sessionExpired = useCallback(() => clearSession("Your session has expired. Please sign in again."), [clearSession]);

  if (!token) return <AuthScreen onAuthenticated={authenticated} notice={notice} />;
  if (!user) return <main className="session-screen"><div className="brand">Case Foundry</div>
    {sessionError ? <><p role="alert">{sessionError}</p><button onClick={() => { setSessionError(""); setSessionAttempt((attempt) => attempt + 1); }}>Try again</button><button onClick={logout}>Back to sign in</button></> : <p role="status">Opening your workspace…</p>}
  </main>;
  return <Workspace key={token} token={token} user={user} logout={logout} onSessionExpired={sessionExpired} />;
}

function Workspace({ token, user, logout, onSessionExpired }) {
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
  const [openingId, setOpeningId] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [showEditor, setShowEditor] = useState(true);
  const [operationMessage, setOperationMessage] = useState("");
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
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectCreateError, setProjectCreateError] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [file, setFile] = useState(null); const [sourceCode, setSourceCode] = useState(""); const [result, setResult] = useState(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

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
        const controls = Array.from(sidebarRef.current?.querySelectorAll("button:not(:disabled)") || []).filter((button) => button.getClientRects().length);
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
    if (loading || openingId) return;
    const target = error ? errorRef.current : result ? resultRef.current : null;
    if (!target) return;
    target.focus({ preventScroll: true });
    target.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      block: "start",
    });
  }, [result, error, loading, openingId]);

  function handleError(requestError) {
    if (!active.current) return;
    if (requestError.status === 401) onSessionExpired();
    else setError(requestError.message);
  }
  const busy = loading || Boolean(openingId) || deleting || creatingProject;
  const selectedProject = projects.find((project) => project.id === selectedProjectId);

  function selectProject(id) {
    if (busy) return;
    if (id !== selectedProjectId) setHistory([]);
    setSelectedProjectId(id); resetEditor();
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
      setProjects((items) => [project, ...items.filter((item) => item.id !== project.id)]);
      setSelectedProjectId(project.id); setHistory([]); resetEditor();
      setProjectDialogOpen(false); setProjectName("");
      setProjectsVersion((version) => version + 1);
    } catch (createError) {
      if (!active.current) return;
      if (createError.status === 401) onSessionExpired();
      else setProjectCreateError(createError.message);
    } finally { if (active.current) setCreatingProject(false); }
  }

  function resetEditor() {
    setResult(null); setFile(null); setSourceCode(""); setSourceLanguage("python");
    setError(""); setOperationMessage(""); setShowEditor(true); setSidebarOpen(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    window.scrollTo({ top: 0, behavior: "instant" });
    requestAnimationFrame(() => newSuiteHeadingRef.current?.focus({ preventScroll: true }));
  }

  async function openSuite(id) {
    if (busy) return;
    if (!showEditor && result?.id === id) { setSidebarOpen(false); resultRef.current?.focus(); return; }
    setOpeningId(id); setError(""); setOperationMessage("");
    try {
      const saved = normalizeSuite(await request(`/testcases/${encodeURIComponent(id)}`, {}, token));
      if (!active.current) return;
      if ((saved.project_id || "") !== selectedProjectId) setHistory([]);
      setSelectedProjectId(saved.project_id || "");
      setResult(saved); setShowEditor(false); setSidebarOpen(false);
      setFile(null); setSourceCode("");
    } catch (openError) {
      if (openError.status === 404) setHistory((items) => items.filter((item) => item.id !== id));
      handleError(openError);
    } finally { if (active.current) setOpeningId(null); }
  }

  async function deleteSuite() {
    if (!result || busy || !window.confirm(`Delete "${suiteTitle(result)}"? This permanently removes the saved suite and its exports.`)) return;
    const id = result.id;
    setDeleting(true); setError("");
    try {
      await request(`/testcases/${encodeURIComponent(id)}`, { method: "DELETE" }, token);
      if (!active.current) return;
      setHistory((items) => items.filter((item) => item.id !== id));
      resetEditor(); setOperationMessage("Saved suite deleted.");
      setHistoryVersion((version) => version + 1);
      setProjectsVersion((version) => version + 1);
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
        setResult(normalizeSuite(payload)); setShowEditor(false);
        setHistoryVersion((version) => version + 1);
        setProjectsVersion((version) => version + 1);
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
      <div className="sidebar-brand"><div className="brand">Case Foundry</div><button ref={sidebarCloseRef} className="icon-button sidebar-close" aria-label="Close history" onClick={() => { setSidebarOpen(false); historyToggleRef.current?.focus(); }}><Icon name="panel" /></button></div>
      <button className="new-suite" disabled={busy} onClick={resetEditor}><Icon name="edit" /> New test suite</button>
      <nav className="suite-history" aria-label="Saved test suites">
        <button className="project-link all-suites" aria-current={!selectedProjectId ? "page" : undefined} disabled={busy} onClick={() => selectProject("")}><Icon name="grid" size={17} /><span>All suites</span></button>
        <div className="projects-heading"><span>Projects</span><button className="icon-button" aria-label="New project" title="New project" disabled={busy} onClick={openProjectDialog}><Icon name="plus" size={17} /></button></div>
        {projectsLoading && !projects.length && <p className="sidebar-note" role="status">Loading projects…</p>}
        {projectsError && <div className="sidebar-error" role="alert"><p>{projectsError}</p><button onClick={() => setProjectsVersion((version) => version + 1)}>Try projects again</button></div>}
        {!projectsLoading && !projectsError && !projects.length && <p className="sidebar-note">No projects yet</p>}
        <ul className="project-list">{projects.map((project) => <li key={project.id}><button className="project-link" aria-current={selectedProjectId === project.id ? "page" : undefined} disabled={busy} onClick={() => selectProject(project.id)} title={project.name}><Icon name="folder" size={17} /><span>{project.name}</span><small>{project.suite_count}</small></button></li>)}</ul>
        <div className="suite-history-heading">{selectedProject ? "Project suites" : "Recents"}</div>
        {historyLoading && !history.length && <p className="sidebar-note" role="status">Loading saved suites…</p>}
        {historyError && <div className="sidebar-error" role="alert"><p>{historyError}</p><button onClick={() => setHistoryVersion((version) => version + 1)}>Try again</button></div>}
        {!historyLoading && !historyError && !history.length && <p className="sidebar-note">{selectedProjectId ? "No suites in this project yet" : "No saved suites yet"}</p>}
        <ul className="suite-list">{history.map((item) => <li key={item.id}>
          <button className="suite-link" disabled={busy} title={`${suiteTitle(item)} — ${savedDate(item.created_at)}`} aria-current={!showEditor && result?.id === item.id ? "page" : undefined} onClick={() => openSuite(item.id)}>
            <span className="suite-link-title">{suiteTitle(item)}</span>{openingId === item.id && <span className="opening-indicator" role="status">Opening…</span>}
          </button>
        </li>)}</ul>
      </nav>
      <div className="sidebar-account"><span className="account-avatar" aria-hidden="true">{user.email.slice(0, 2).toUpperCase()}</span><span className="account-email" title={user.email}>{user.email}</span><button className="icon-button" onClick={logout} aria-label="Sign out" title="Sign out"><Icon name="logout" size={18} /></button></div>
    </aside>
    <div className="content">
      <header className="topbar"><div className="page-heading"><button ref={historyToggleRef} className="icon-button history-toggle" aria-label="Open history" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Icon name="panel" /></button><span className="page-title">{openingId ? "Opening suite…" : showEditor ? selectedProject?.name || "Case Foundry" : suiteTitle(result)}</span>{selectedProject && !showEditor && <span className="suite-project-name">{selectedProject.name}</span>}</div><div className="account">
        {!showEditor && result && <button className="icon-button delete-suite" aria-label="Delete saved suite" title="Delete suite" disabled={busy} onClick={deleteSuite}><Icon name="trash" /></button>}
      </div></header>
      {operationMessage && <p className="sr-only" role="status">{operationMessage}</p>}
      <div className={`workspace-body ${showEditor ? "is-new" : ""}`}>
      {showEditor && <section className="new-suite-view">
        <h1 ref={newSuiteHeadingRef} tabIndex={-1}>What would you like to test?</h1>
        {selectedProject && <p className="project-context"><Icon name="folder" size={15} />New suites will be saved to <strong>{selectedProject.name}</strong></p>}
        <form ref={composerRef} className="composer" onSubmit={generate} onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); }} onDrop={(event) => { if (!event.dataTransfer.files.length) return; event.preventDefault(); if (busy) return; const dropped = event.dataTransfer.files[0]; if (!/\.(json|ya?ml)$/i.test(dropped.name)) { setError("Attach an OpenAPI file in JSON or YAML format."); return; } setFile(dropped); setError(""); }}>
          <input ref={fileInputRef} type="file" className="file-picker" aria-label="OpenAPI file" accept=".json,.yaml,.yml" disabled={loading} onChange={(event) => setFile(event.target.files?.[0] || null)} />
          {file && <div className="attachment"><Icon name="file" size={18} /><span>{file.name}</span><button type="button" className="icon-button" aria-label="Remove file" disabled={loading} onClick={() => { setFile(null); if (fileInputRef.current) fileInputRef.current.value = ""; }}><Icon name="close" size={15} /></button></div>}
          <textarea ref={sourceInputRef} id="source-code" aria-label="Source code" className={sourceCode ? "with-code" : ""} value={sourceCode} disabled={loading} onChange={(event) => setSourceCode(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); composerRef.current?.requestSubmit(); } }} placeholder={`Paste your ${sourceLanguage === "python" ? "Python" : sourceLanguage === "javascript" ? "JavaScript" : "TypeScript"} code, or attach an OpenAPI file…`} rows={1} />
          <div className="composer-tools">
            <button type="button" className="icon-button attach-button" aria-label="Attach OpenAPI file" title="Attach OpenAPI file" disabled={loading} onClick={() => fileInputRef.current?.click()}><Icon name="plus" size={23} /></button>
            <select className="language-select" aria-label="Source language" value={sourceLanguage} disabled={loading} onChange={(event) => setSourceLanguage(event.target.value)}>
              <option value="python">Python</option><option value="javascript">JavaScript</option><option value="typescript">TypeScript</option>
            </select>
            {loading && <span className="generation-status" role="status">Generating…</span>}
            <button className="generate-button" disabled={busy || (!file && !sourceCode.trim())} type="submit" aria-label={loading ? "Generating test suite" : sourceCode.trim() && !file ? "Generate unit tests" : "Generate test suite"} title="Generate tests (Ctrl+Enter)">{loading ? <span className="spinner" /> : <Icon name="send" size={21} />}</button>
          </div>
        </form>
        {error && <div className="error" ref={errorRef} role="alert" tabIndex={-1}>{error}</div>}
      </section>}
      {!showEditor && error && <div className="error" ref={errorRef} role="alert" tabIndex={-1}>{error}</div>}
      {result && <section className="results saved-results" ref={resultRef} tabIndex={-1} aria-labelledby="results-heading">
        <div className="results-top"><div><h2 id="results-heading">Generated tests</h2><p className="result-summary">{apiCases.length} API {apiCases.length === 1 ? "case" : "cases"} · {unitCases.length} unit {unitCases.length === 1 ? "case" : "cases"}{result.created_at ? ` · ${savedDate(result.created_at)}` : ""}</p></div>
          <div className="exports" aria-label="Download suite"><button onClick={() => downloadExport("json")}>JSON</button>
            {result.pytest_code?.trim() && <button onClick={() => downloadExport("py")}>Python</button>}
            {unitCode && codeExtension !== "py" && <button onClick={() => downloadExport(codeExtension)}>{codeExtension === "ts" ? "TypeScript" : "JavaScript"}</button>}
            <button onClick={() => downloadExport("csv")}>CSV</button>
          </div>
        </div>
        {unitCode && <div className="result-block">
          <div className="block-head"><h3>Generated unit test code</h3><span>{result.unit_test_framework || "pytest"}</span></div>
          <details className="test-instructions"><summary>How to run these tests</summary><p>Save your original code as <code>{sourceFileName}</code> beside the downloaded test file{codeExtension !== "py" ? " and export the functions or classes under test" : ""}. Install {codeExtension === "py" ? "pytest" : "Vitest"} and your code’s dependencies, then run <code>{testCommand}</code>.</p></details>
          <pre aria-label="Generated unit test code">{unitCode}</pre>
        </div>}
        {apiCases.length > 0 && <div className="result-block"><div className="block-head"><h3>API / contract tests</h3><span>{apiCases.length} {apiCases.length === 1 ? "case" : "cases"}</span></div><pre>{JSON.stringify(apiCases, null, 2)}</pre></div>}
        {unitCases.length > 0 && <div className="result-block"><div className="block-head"><h3>Unit test cases</h3><span>{unitCases.length} {unitCases.length === 1 ? "case" : "cases"}</span></div><pre>{JSON.stringify(unitCases, null, 2)}</pre></div>}
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
