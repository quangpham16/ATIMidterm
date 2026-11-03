import ast
from pprint import pformat
import re
from typing import Any, Protocol

from pydantic import ValidationError

from app.schemas import GenerationResult, TestCase
from app.services.prompt_builder import build_generation_prompt


class JsonLLMClient(Protocol):
    def generate_json(self, prompt: str) -> dict[str, Any]: ...


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value.lower()).strip("_") or "case"


def _api_pytest_code(test_cases: list[TestCase]) -> str:
    serialized = pformat([case.model_dump() for case in test_cases], sort_dicts=False)
    functions = []
    for case in test_cases:
        name = _safe_name(case.id)
        expected = repr(case.expected_status_code)
        functions.append(
            f'''\n\ndef test_api_{name}():
    api_client = Mock()
    api_client.request.return_value.status_code = {expected}
    response = api_client.request({case.api_method!r}, {case.endpoint!r}, json={case.request_data!r})
    assert response.status_code == {expected}
'''
        )
    return f'''"""Generated API tests. Network calls are mocked by design."""
from unittest.mock import Mock

API_TEST_CASES = {serialized}
{''.join(functions)}
'''


def _validate_unit_code(raw: Any, source_language: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Gemini returned unit cases without runnable test code. Please generate again.")
    code = re.sub(r"^```(?:python|py|javascript|js|typescript|ts)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    if source_language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise RuntimeError(f"Gemini returned invalid Python test code at line {exc.lineno}. Please generate again.") from exc
        aliases = {
            name.asname or name.name
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for name in node.names if name.name == "source_under_test"
        }
        has_tests = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_") for node in ast.walk(tree))
        calls_source = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                while isinstance(target, ast.Attribute):
                    target = target.value
                if isinstance(target, ast.Name) and target.id in aliases:
                    calls_source = True
        if not has_tests or not calls_source:
            raise RuntimeError("Gemini's tests did not call the source module. Please generate again.")
        instructions = "# Save your original source as source_under_test.py beside this file.\n# Install pytest, then run: python -m pytest test_generated.py\n\n"
    else:
        extension = "ts" if source_language == "typescript" else "js"
        if not re.search(r"from\s+['\"]\./source_under_test(?:\.(?:js|ts))?['\"]", code) or not re.search(r"\b(?:it|test)\s*(?:\.\w+\s*)?\(", code):
            raise RuntimeError("Gemini's tests did not import the source module or define tests. Please generate again.")
        instructions = f"// Save your source as source_under_test.{extension} and export the targets under test.\n// Install vitest, then run: npx vitest run test_generated.test.{extension}\n\n"
    return instructions + code + "\n"


def _parse_cases(raw: Any, key: str) -> list[TestCase]:
    if not isinstance(raw, list):
        raise ValueError(f"Gemini returned no {key.replace('_', ' ')}")
    try:
        normalized = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"Gemini returned a non-object item in {key}")
            item = dict(item)
            # Gemini occasionally emits a sentence/list when no request data is
            # needed. The generated pytest code requires keyword arguments to be
            # represented by a dictionary, so treat that case as empty input.
            if not isinstance(item.get("request_data"), dict):
                item["request_data"] = {}
            normalized.append(TestCase.model_validate(item))
        return normalized
    except ValidationError as exc:
        first_error = exc.errors()[0]
        location = ".".join(str(part) for part in first_error["loc"])
        raise ValueError(
            f"Gemini returned invalid {key} data at {location}: {first_error['msg']}"
        ) from exc


def generate_test_cases(
    swagger: dict[str, Any], source_code: str, llm_client: JsonLLMClient, source_language: str = "python"
) -> GenerationResult:
    if not isinstance(swagger, dict):
        raise ValueError("Swagger document must be a JSON/YAML object")
    if not swagger and not source_code.strip():
        raise ValueError("Provide a Swagger/OpenAPI document or raw source code")
    if source_language not in ("python", "javascript", "typescript"):
        raise ValueError("Choose Python, JavaScript or TypeScript as the source language")
    if source_code.strip() and source_language == "python":
        try:
            ast.parse(source_code)
        except SyntaxError as exc:
            raise ValueError(f"Python source has a syntax error at line {exc.lineno}: {exc.msg}. Check the code or select its language.") from exc

    raw = llm_client.generate_json(build_generation_prompt(swagger, source_code, source_language))
    if not isinstance(raw, dict):
        raise ValueError("Gemini returned an invalid response object")

    # Accept the old response shape while new prompts transition to two arrays.
    api_raw = raw.get("api_test_cases", raw.get("test_cases", []))
    unit_raw = raw.get("unit_test_cases")
    api_cases = _parse_cases(api_raw, "api_test_cases")
    unit_cases = _parse_cases(unit_raw, "unit_test_cases") if unit_raw is not None else []
    if not api_cases and not unit_cases:
        raise ValueError("Gemini returned no API or unit test cases")
    if not swagger and not unit_cases:
        raise RuntimeError("Gemini did not return unit tests for the pasted code. Please generate again.")
    if not swagger and api_cases:
        raise RuntimeError("Gemini returned API cases without a specification. Please generate unit tests again.")
    if unit_cases and not source_code.strip():
        raise RuntimeError("Gemini returned unit tests without source code. Please generate again.")

    api_code = _api_pytest_code(api_cases) if api_cases else ""
    unit_code = _validate_unit_code(raw.get("unit_test_code", raw.get("unit_pytest_code")), source_language) if unit_cases else ""
    unit_python = unit_code if source_language == "python" else ""
    combined = "\n\n".join(part for part in (api_code, unit_python) if part)
    return GenerationResult(
        test_cases=api_cases + unit_cases,
        pytest_code=combined,
        api_test_cases=api_cases,
        unit_test_cases=unit_cases,
        unit_pytest_code=unit_python,
        unit_test_code=unit_code,
        source_language=source_language,
        unit_test_framework=("pytest" if source_language == "python" else "Vitest") if unit_code else "",
    )
