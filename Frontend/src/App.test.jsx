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
    const saved = { ...fixture, id: "generated-suite", project_id: options.body.get("project_id") || null };
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
