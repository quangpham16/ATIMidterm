import ast
import re
from typing import Any, Protocol

from pydantic import ValidationError

from app.schemas import GenerationResult, TestCase
from app.services.api_tests import build_api_pytest_code
from app.services.prompt_builder import build_generation_prompt, build_unit_test_repair_prompt


class JsonLLMClient(Protocol):
    def generate_json(self, prompt: str) -> dict[str, Any]: ...


def _validate_unit_code(raw: Any, source_language: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Gemini returned unit cases without runnable test code.")
    code = re.sub(r"^```(?:python|py|javascript|js|typescript|ts)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    if source_language == "python":
        try:
            tree = ast.parse(code)
            # Parsing alone accepts invalid contexts such as a top-level return.
            # Compilation checks these without executing the generated code.
            compile(tree, "test_generated.py", "exec")
        except SyntaxError as exc:
            raise RuntimeError(f"Gemini returned invalid Python test code at line {exc.lineno}, column {exc.offset}: {exc.msg}.") from exc
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
            raise RuntimeError("Gemini's tests did not call the source module.")
        instructions = "# Save your original source as source_under_test.py beside this file.\n# Install pytest, then run: python -m pytest test_generated.py\n\n"
    else:
        extension = "ts" if source_language == "typescript" else "js"
        if not re.search(r"from\s+['\"]\./source_under_test(?:\.(?:js|ts))?['\"]", code) or not re.search(r"\b(?:it|test)\s*(?:\.\w+\s*)?\(", code):
            raise RuntimeError("Gemini's tests did not import the source module or define tests.")
        instructions = f"// Save your source as source_under_test.{extension} and export the targets under test.\n// Install vitest, then run: npx vitest run test_generated.test.{extension}\n\n"
    return instructions + code + "\n"


def _unit_code_with_repair(
    raw: dict[str, Any], unit_cases: list[TestCase], generation_prompt: str,
    source_language: str, llm_client: JsonLLMClient,
) -> str:
    code = raw.get("unit_test_code", raw.get("unit_pytest_code"))
    for _ in range(2):
        try:
            return _validate_unit_code(code, source_language)
        except RuntimeError as exc:
            repair_prompt = build_unit_test_repair_prompt(
                generation_prompt, [case.model_dump() for case in unit_cases], code, str(exc)
            )

        # Keep the original cases and use the latest file/error for each repair.
        # Transport errors propagate instead of triggering more generation.
        repaired = llm_client.generate_json(repair_prompt)
        if not isinstance(repaired, dict):
            raise RuntimeError("Gemini returned an invalid unit-test repair response. Please generate again.")
        code = repaired.get("unit_test_code", repaired.get("unit_pytest_code"))
    try:
        return _validate_unit_code(code, source_language)
    except RuntimeError as exc:
        raise RuntimeError(f"{exc} Automatic repair failed after 2 attempts. Please generate again.") from exc


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

    generation_prompt = build_generation_prompt(swagger, source_code, source_language)
    raw = llm_client.generate_json(generation_prompt)
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

    api_code = build_api_pytest_code(api_cases, swagger) if api_cases else ""
    unit_code = _unit_code_with_repair(raw, unit_cases, generation_prompt, source_language, llm_client) if unit_cases else ""
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
