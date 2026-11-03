import assert from "node:assert/strict";
import { test } from "node:test";
import { normalizeSuite } from "./test-suites.js";

const apiCase = { id: "API-HEALTH-001", api_method: "GET", title: "Health succeeds" };
const unitCase = { id: "UNIT-ANSWER-001", api_method: "UNIT", title: "Answer returns a value" };

test("keeps separate API and unit cases from generation", () => {
  const suite = normalizeSuite({ id: "saved-suite", api_test_cases: [apiCase], unit_test_cases: [unitCase] });
  assert.deepEqual(suite.api_test_cases, [apiCase]);
  assert.deepEqual(suite.unit_test_cases, [unitCase]);
});

test("combined cases display even when the split arrays are empty", () => {
  const suite = normalizeSuite({ id: "saved-suite", test_cases: [apiCase, unitCase], api_test_cases: [], unit_test_cases: [] });
  assert.deepEqual(suite.api_test_cases, [apiCase]);
  assert.deepEqual(suite.unit_test_cases, [unitCase]);
});

test("source-only suites have unit cases without API cases", () => {
  const suite = normalizeSuite({ id: "saved-suite", unit_test_cases: [unitCase] });
  assert.deepEqual(suite.api_test_cases, []);
  assert.deepEqual(suite.unit_test_cases, [unitCase]);
});

test("missing or empty suites surface an error instead of a success screen", () => {
  for (const payload of [null, {}, { id: "" }, { id: "saved-suite" }, { id: "saved-suite", test_cases: [] }]) {
    assert.throws(() => normalizeSuite(payload), /test cases|test suite/);
  }
});

test("invalid case entries surface an error", () => {
  for (const item of [null, "case", []]) {
    assert.throws(() => normalizeSuite({ id: "saved-suite", api_test_cases: [item] }), /invalid test cases/);
  }
});


