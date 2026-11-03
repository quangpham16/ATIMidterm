export function normalizeSuite(payload) {
  if (!payload || typeof payload.id !== "string" || !payload.id.trim()) {
    throw new Error("The server did not return a saved test suite. Please try again.");
  }

  const combined = Array.isArray(payload.test_cases) ? payload.test_cases : [];
  const isUnitCase = (item) => item?.api_method === "UNIT" || item?.id?.startsWith("UNIT-");
  const apiCases = Array.isArray(payload.api_test_cases) && payload.api_test_cases.length
    ? payload.api_test_cases : combined.filter((item) => !isUnitCase(item));
  const unitCases = Array.isArray(payload.unit_test_cases) && payload.unit_test_cases.length
    ? payload.unit_test_cases : combined.filter(isUnitCase);

  if (!apiCases.length && !unitCases.length) {
    throw new Error("No test cases were returned. Please try generating the suite again.");
  }
  if ([...apiCases, ...unitCases].some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("The server returned invalid test cases. Please try again.");
  }

  return { ...payload, api_test_cases: apiCases, unit_test_cases: unitCases };
}
