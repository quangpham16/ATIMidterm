import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { ApiError, request, TOKEN_KEY } from "./api.js";

vi.mock("./api.js", async (importOriginal) => ({
  ...await importOriginal(),
  request: vi.fn(),
}));

const user = { id: "owner", email: "owner@example.test" };
const unitCase = { id: "UNIT-ANSWER-001", api_method: "UNIT", title: "Returns an answer", expected_result: "Returns 42" };
const fixture = {
  id: "first-suite", title: "Payment checks", project_id: "project-1",
  created_at: "2026-01-01 00:00:00", test_cases: [unitCase], unit_test_cases: [unitCase],
  unit_test_code: "import source_under_test as sut\ndef test_answer(): assert sut.answer() == 42", pytest_code: "# pytest code",
};
let projects;
let suites;

async function backend(path, options = {}) {
  if (path === "/auth/me") return user;
  if (path === "/auth/login" || path === "/auth/register") return { token: "new-session", user };
  if (path === "/auth/logout") return { status: "logged out" };
  if (path === "/projects" && options.method === "POST") {
    const project = { id: "new-project", name: JSON.parse(options.body).name, suite_count: 0 };
    projects.push(project);
    return project;
  }
  if (path === "/projects") return [...projects];
  if (path.startsWith("/projects/")) {
    const project = projects.find((item) => item.id === decodeURIComponent(path.slice("/projects/".length)));
    if (!project) throw new ApiError("Project not found", 404);
    return project;
  }
  if (path.startsWith("/testcases/history")) {
    const projectId = new URL(path, "http://localhost").searchParams.get("project_id");
    return Object.values(suites).filter((item) => !projectId || item.project_id === projectId);
  }
  if (path === "/testcases/generate") {
    const sourceFiles = Object.fromEntries(options.body.getAll("source_files").map((file) => [file.name, "# uploaded source"]));
    const saved = {
      ...fixture, id: "generated-suite", project_id: options.body.get("project_id") || null,
      ...(Object.keys(sourceFiles).length ? { source_files: sourceFiles, source_entrypoint: options.body.get("source_entrypoint"), source_language: "python" } : {}),
    };
    suites[saved.id] = saved;
    return saved;
  }
  if (path.startsWith("/testcases/")) {
    const id = decodeURIComponent(path.slice("/testcases/".length));
    if (!suites[id]) throw new ApiError("Saved suite not found", 404);
    if (options.method === "DELETE") { delete suites[id]; return { id, status: "deleted" }; }
    return suites[id];
  }
  throw new Error(`Unexpected request: ${path}`);
}

beforeEach(() => {
  projects = [{ id: "project-1", name: "Payments", suite_count: 1 }];
  suites = { [fixture.id]: { ...fixture } };
  request.mockReset();
  request.mockImplementation(backend);
});

function BrowserControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return <>
    <output data-testid="url">{location.pathname}{location.search}{location.hash}</output>
    <button onClick={() => navigate(-1)}>Browser back</button>
    <button onClick={() => navigate(1)}>Browser forward</button>
  </>;
}

function mount(path = "/", { signedIn = true, entries = [path] } = {}) {
  if (signedIn) localStorage.setItem(TOKEN_KEY, "test-session");
  return render(<MemoryRouter initialEntries={entries}><App /><BrowserControls /></MemoryRouter>);
}

function expectUrl(path) {
  expect(screen.getByTestId("url").textContent).toBe(path);
}

function fillCredentials(register = false) {
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: user.email } });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "test password" } });
  if (register) fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "test password" } });
}

test("a signed-out suite link returns to its full URL after sign-in", async () => {
  const url = "/suites/first-suite?tab=code#unit-tests";
  mount(url, { signedIn: false });
  await screen.findByRole("heading", { name: "Welcome back" });
  expectUrl("/login");
  fillCredentials();
  fireEvent.click(screen.getByRole("button", { name: "Sign in", exact: true }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl(url);
  expect(localStorage.getItem(TOKEN_KEY)).toBe("new-session");
});

test("switching to registration preserves the requested project URL", async () => {
  mount("/projects/project-1", { signedIn: false });
  fireEvent.click(await screen.findByRole("link", { name: "Need an account? Create one" }));
  expectUrl("/register");
  fillCredentials(true);
  fireEvent.click(screen.getByRole("button", { name: "Create account", exact: true }));
  await screen.findByLabelText("Source code");
  expectUrl("/projects/project-1");
});

test("a project direct link loads its details and filtered suite list", async () => {
  mount("/projects/project-1");
  await screen.findByLabelText("Source code");
  expect(document.querySelector(".page-title").textContent).toBe("Payments");
  expect(request.mock.calls.some(([path]) => path === "/testcases/history?project_id=project-1")).toBe(true);
  expect(screen.getByRole("link", { name: "Payment checks" }).getAttribute("href")).toBe("/suites/first-suite");
  expect(screen.queryByRole("group", { name: /pagination/ })).toBeNull();
  expect(request.mock.calls.some(([path]) => /page_size|[?&]page=/.test(path))).toBe(false);
});

test("sidebar links and browser Back/Forward follow the current URL", async () => {
  mount();
  fireEvent.click(await screen.findByRole("link", { name: /Payments/ }));
  await screen.findByLabelText("Source code");
  expectUrl("/projects/project-1");
  fireEvent.click(await screen.findByRole("link", { name: "Payment checks" }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/first-suite");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByLabelText("Source code");
  expectUrl("/projects/project-1");
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByLabelText("Source code");
  expectUrl("/");
  fireEvent.click(screen.getByRole("button", { name: "Browser forward" }));
  await screen.findByLabelText("Source code");
  expectUrl("/projects/project-1");
  fireEvent.click(screen.getByRole("button", { name: "Browser forward" }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/first-suite");
});

test("remounting a saved-suite URL restores its data without sidebar state", async () => {
  const first = mount("/suites/first-suite");
  await screen.findByRole("heading", { name: "Generated tests" });
  first.unmount();
  mount("/suites/first-suite");
  await screen.findByRole("heading", { name: "Generated tests" });
  expect(document.querySelector(".page-title").textContent).toBe("Payment checks");
  expect(screen.getByRole("link", { name: "New test suite" }).getAttribute("href")).toBe("/projects/project-1");
  expect(request.mock.calls.filter(([path]) => path === "/testcases/first-suite")).toHaveLength(2);
});

test.each([
  ["/suites/missing", "Saved suite not found"],
  ["/projects/missing", "Project not found"],
])("an unavailable record at %s has a recovery link", async (path, message) => {
  mount(path);
  expect((await screen.findByRole("alert")).textContent).toBe(message);
  expect(screen.queryByLabelText("Source code")).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Back to workspace" }));
  await screen.findByLabelText("Source code");
  expectUrl("/");
});

test("a failed suite route can be retried at the same URL", async () => {
  mount("/suites/missing");
  await screen.findByRole("alert");
  suites.missing = { ...fixture, id: "missing" };
  fireEvent.click(screen.getByRole("button", { name: "Try again", exact: true }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/missing");
});

test("creating a project navigates to its editor", async () => {
  mount();
  await screen.findByLabelText("Source code");
  fireEvent.click(screen.getByRole("button", { name: "New project" }));
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "New service" } });
  fireEvent.click(screen.getByRole("button", { name: "Create project", exact: true }));
  await waitFor(() => expectUrl("/projects/new-project"));
  await screen.findByLabelText("Source code");
  expect(document.querySelector(".page-title").textContent).toBe("New service");
});

test("generation keeps the routed project and opens the saved-suite URL", async () => {
  mount("/projects/project-1");
  fireEvent.change(await screen.findByLabelText("Source code"), { target: { value: "def answer(): return 42" } });
  fireEvent.click(screen.getByRole("button", { name: "Generate unit tests" }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/generated-suite");
  const [, options] = request.mock.calls.find(([path]) => path === "/testcases/generate");
  expect(options.body.get("project_id")).toBe("project-1");
});

test("Python uploads accumulate and submit the selected module in multipart data", async () => {
  mount("/projects/project-1");
  const filesInput = await screen.findByLabelText("Python source files");
  fireEvent.change(filesInput, { target: { files: [new File(["def helper(): return 42"], "helpers.py")] } });
  fireEvent.change(filesInput, { target: { files: [new File(["from helpers import helper"], "service.py")] } });
  expect(screen.getByLabelText("Module to test").value).toBe("helpers.py");
  fireEvent.change(screen.getByLabelText("Module to test"), { target: { value: "service.py" } });
  expect(screen.getByLabelText("Source code").disabled).toBe(true);
  expect(screen.getByLabelText("Source language").disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Generate unit tests" }));
  expect(filesInput.disabled).toBe(true);
  expect(screen.getByLabelText("Module to test").disabled).toBe(true);
  expect(screen.getByRole("button", { name: "Remove helpers.py" }).disabled).toBe(true);
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/generated-suite");
  const [, options] = request.mock.calls.find(([path]) => path === "/testcases/generate");
  expect(options.body.getAll("source_files").map((file) => file.name)).toEqual(["helpers.py", "service.py"]);
  expect(options.body.get("source_entrypoint")).toBe("service.py");
  expect(options.body.get("source_language")).toBe("python");
  expect(options.body.has("source_code")).toBe(false);
  expect(options.body.get("project_id")).toBe("project-1");
  expect(screen.getByRole("button", { name: "Python bundle (.zip)" })).toBeDefined();
});

test("removing Python files updates the entry module and new-suite clears the remaining files", async () => {
  mount();
  fireEvent.change(await screen.findByLabelText("Python source files"), { target: { files: [new File(["# main"], "main.py"), new File(["# helper"], "helpers.py")] } });
  fireEvent.click(screen.getByRole("button", { name: "Remove main.py" }));
  expect(screen.getByLabelText("Module to test").value).toBe("helpers.py");
  expect(screen.queryByRole("button", { name: "Remove main.py" })).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "New test suite" }));
  expect(screen.queryByRole("list", { name: "Selected Python files" })).toBeNull();
  expect(screen.queryByLabelText("Module to test")).toBeNull();
  expect(screen.getByLabelText("Source code").disabled).toBe(false);
  expect(screen.getByLabelText("Source language").disabled).toBe(false);
  expect(screen.getByRole("button", { name: "Generate test suite" }).disabled).toBe(true);
});

test("Python files cannot overwrite duplicate names or discard pasted code", async () => {
  mount();
  const sourceInput = await screen.findByLabelText("Source code");
  const filesInput = screen.getByLabelText("Python source files");
  fireEvent.change(sourceInput, { target: { value: "def answer(): return 42" } });
  fireEvent.change(filesInput, { target: { files: [new File(["# replacement"], "main.py")] } });
  expect(screen.getByRole("alert").textContent).toContain("Your pasted code has been kept");
  expect(sourceInput.value).toBe("def answer(): return 42");
  expect(screen.queryByLabelText("Module to test")).toBeNull();
  fireEvent.change(sourceInput, { target: { value: "" } });
  fireEvent.change(filesInput, { target: { files: [new File(["# original"], "main.py")] } });
  fireEvent.change(filesInput, { target: { files: [new File(["# replacement"], "MAIN.py")] } });
  expect(screen.getByRole("alert").textContent).toContain("already selected");
  expect(screen.getByLabelText("Module to test").options).toHaveLength(1);
  expect(screen.getByLabelText("Module to test").value).toBe("main.py");
});

test.each([
  ["not-python.js", "not supported"],
  ["bad-module.py", "not supported"],
  ["class.py", "not supported"],
  ["test_generated.py", "reserved"],
  ["PYTEST.py", "reserved"],
  ["__main__.py", "reserved"],
])("invalid upload %s is rejected without adding it", async (filename, message) => {
  mount();
  fireEvent.change(await screen.findByLabelText("Python source files"), { target: { files: [new File(["# source"], filename)] } });
  expect(screen.getByRole("alert").textContent).toContain(message);
  expect(screen.queryByLabelText("Module to test")).toBeNull();
});

test.each([
  [() => Array.from({ length: 21 }, (_, index) => new File(["# source"], `module_${index}.py`)), "at most 20"],
  [() => [new File(["x".repeat(128 * 1024 + 1)], "main.py")], "128 KiB per-file"],
  [() => Array.from({ length: 5 }, (_, index) => new File(["x".repeat(110 * 1024)], `module_${index}.py`)), "512 KiB total"],
])("Python uploads enforce their count and size limits", async (makeFiles, message) => {
  mount();
  fireEvent.change(await screen.findByLabelText("Python source files"), { target: { files: makeFiles() } });
  expect(screen.getByRole("alert").textContent).toContain(message);
  expect(screen.queryByLabelText("Module to test")).toBeNull();
});

test("restoring a saved Python bundle offers ZIP download with original module instructions", async () => {
  suites[fixture.id] = { ...fixture, source_language: "python", source_files: { "service.py": "from helpers import answer", "helpers.py": "def answer(): return 42" }, source_entrypoint: "service.py" };
  const first = mount("/suites/first-suite");
  await screen.findByRole("heading", { name: "Generated tests" });
  first.unmount();
  mount("/suites/first-suite");
  const zipButton = await screen.findByRole("button", { name: "Python bundle (.zip)" });
  expect(screen.getByText(/Module under test:/).textContent).toContain("service.py");
  expect(screen.getByText(/Keep the original module filenames/).textContent).toContain("extract it");
  expect(screen.queryByText(/Save your original code as/)).toBeNull();
  const createObjectURL = vi.fn(() => "blob:test-suite");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  });
  const fetchMock = vi.fn(async () => ({ ok: true, blob: async () => new Blob(["zip"]) }));
  vi.stubGlobal("fetch", fetchMock);
  const linkClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  fireEvent.click(zipButton);
  await waitFor(() => expect(linkClick).toHaveBeenCalledOnce());
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/exports/first-suite.zip"), { headers: { Authorization: "Bearer test-session" } });
  expect(linkClick.mock.instances[0].download).toBe("test-suite.zip");
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-suite");
});

test("deleting a suite replaces its route with its project editor", async () => {
  mount("/suites/first-suite", { entries: ["/", "/suites/first-suite"] });
  await screen.findByRole("heading", { name: "Generated tests" });
  fireEvent.click(screen.getByRole("button", { name: "Delete saved suite" }));
  await screen.findByLabelText("Source code");
  expectUrl("/projects/project-1");
  expect(suites["first-suite"]).toBeUndefined();
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByLabelText("Source code");
  expectUrl("/");
});

test("a late response cannot overwrite the view reached with browser Back", async () => {
  let complete;
  let signal;
  request.mockImplementation((path, options) => {
    if (path === "/testcases/slow") {
      signal = options.signal;
      return new Promise((resolve) => { complete = resolve; });
    }
    return backend(path, options);
  });
  mount("/suites/slow", { entries: ["/", "/suites/slow"] });
  await waitFor(() => expect(complete).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByLabelText("Source code");
  expect(signal.aborted).toBe(true);
  await act(async () => complete({ ...fixture, id: "slow" }));
  expectUrl("/");
  expect(screen.queryByRole("heading", { name: "Generated tests" })).toBeNull();
});

test("expired sessions return to sign-in and preserve the suite destination", async () => {
  request.mockImplementation((path, options) => path === "/testcases/first-suite"
    ? Promise.reject(new ApiError("Your session has expired; sign in again", 401)) : backend(path, options));
  mount("/suites/first-suite");
  await screen.findByRole("heading", { name: "Welcome back" });
  expectUrl("/login");
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  request.mockImplementation(backend);
  fillCredentials();
  fireEvent.click(screen.getByRole("button", { name: "Sign in", exact: true }));
  await screen.findByRole("heading", { name: "Generated tests" });
  expectUrl("/suites/first-suite");
});

test("sign-out returns to login and Back cannot display a protected view", async () => {
  mount("/suites/first-suite", { entries: ["/", "/suites/first-suite"] });
  await screen.findByRole("heading", { name: "Generated tests" });
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByRole("heading", { name: "Welcome back" });
  expectUrl("/login");
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
  await screen.findByRole("heading", { name: "Welcome back" });
  expect(screen.queryByRole("heading", { name: "Generated tests" })).toBeNull();
});

test("unknown URLs show a page-not-found view", () => {
  mount("/unknown/path", { signedIn: false });
  expect(screen.getByRole("heading", { name: "Page not found" })).not.toBeNull();
  expect(screen.getByRole("link", { name: "Back to sign in" }).getAttribute("href")).toBe("/login");
});

test.each(["https://example.com", "//example.com", "/login", "/unknown"])("sign-in rejects an invalid return destination %s", async (from) => {
  mount("/login", { entries: [{ pathname: "/login", state: { from } }] });
  await screen.findByLabelText("Source code");
  expectUrl("/");
});
