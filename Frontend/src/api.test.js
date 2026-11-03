import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import { ApiError, request } from "./api.js";

afterEach(() => mock.restoreAll());

test("authenticated requests preserve headers and include the session", async () => {
  mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.headers.get("Authorization"), "Bearer session-token");
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.equal(options.method, "POST");
    return Response.json({ user: { email: "qa@example.com" } });
  });
  assert.deepEqual(await request("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" } }, "session-token"), { user: { email: "qa@example.com" } });
});

test("validation responses become readable field errors", async () => {
  mock.method(globalThis, "fetch", async () => Response.json({ detail: [{ loc: ["body", "password"], msg: "String should have at least 8 characters" }] }, { status: 422 }));
  await assert.rejects(request("/auth/register"), (error) => error.status === 422 && error.message === "Password: String should have at least 8 characters");
});

test("expired sessions retain their HTTP status", async () => {
  mock.method(globalThis, "fetch", async () => Response.json({ detail: "Your session has expired; sign in again" }, { status: 401 }));
  await assert.rejects(request("/auth/me"), (error) => error instanceof ApiError && error.status === 401);
});

test("connection failures have a readable message", async () => {
  mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(request("/auth/login"), (error) => error.status === 0 && /Unable to connect/.test(error.message));
});

test("aborted session checks stay aborted", async () => {
  mock.method(globalThis, "fetch", async () => { throw new DOMException("Aborted", "AbortError"); });
  await assert.rejects(request("/auth/me"), { name: "AbortError" });
});

test("non-JSON failures never expose raw HTML", async () => {
  mock.method(globalThis, "fetch", async () => new Response("<h1>Bad Gateway</h1>", { status: 502 }));
  await assert.rejects(request("/auth/login"), (error) => error.status === 502 && error.message === "Something went wrong. Please try again.");
});

test("invalid success responses are rejected", async () => {
  mock.method(globalThis, "fetch", async () => new Response("<h1>Fallback page</h1>"));
  await assert.rejects(request("/auth/login"), /invalid response/);
});
