"""Build deterministic pytest files that exercise a configured API."""
from pathlib import Path
from pprint import pformat
import re

from app.schemas import TestCase


def _resolve(value: dict, spec: dict) -> dict:
    if "$ref" not in value:
        return value
    ref = value["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError("Bundle external OpenAPI references into one file before generating API tests")
    result = spec
    for part in ref[2:].split("/"):
        result = result[part.replace("~1", "/").replace("~0", "~")]
    return result


def build_api_pytest_code(cases: list[TestCase], spec: dict) -> str:
    records = []
    security = (spec.get("components") or {}).get("securitySchemes", spec.get("securityDefinitions", {}))
    security_headers = ["Authorization"] + [s["name"] for s in security.values() if s.get("type") == "apiKey" and s.get("in") == "header"]
    security_query = [s["name"] for s in security.values() if s.get("type") == "apiKey" and s.get("in") == "query"]
    functions, names = [], set()
    for case in cases:
        if not case.endpoint.startswith("/") or case.endpoint.startswith("//") or any(c in case.endpoint for c in "?#\\\r\n"):
            raise ValueError(f"{case.id}: API endpoint must be a relative path beginning with /")
        if case.api_method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError(f"{case.id}: unsupported API method")
        if case.expected_status_code is None or not 100 <= case.expected_status_code <= 599:
            raise ValueError(f"{case.id}: API cases need an expected HTTP status code")
        path_item = (spec.get("paths") or {}).get(case.endpoint, {})
        operation = path_item.get(case.api_method.lower(), {})
        parameters = [_resolve(p, spec) for p in path_item.get("parameters", []) + operation.get("parameters", [])]
        data = dict(case.request_data)
        if any(k in data for k in ("path_params", "query_params", "headers", "body", "auth_mode")):
            request = {k: data.get(k, {}) for k in ("path_params", "query_params", "headers")}
            request["body"] = data.get("body")
            request["auth_mode"] = data.get("auth_mode", "default")
            if any(not isinstance(request[k], dict) for k in ("path_params", "query_params", "headers")):
                raise ValueError(f"{case.id}: path_params, query_params and headers must be objects")
        else:
            request = {"path_params": {}, "query_params": {}, "headers": {}, "body": None, "auth_mode": "default"}
            for parameter in parameters:
                name, location = parameter.get("name"), parameter.get("in")
                if name in data and location in ("path", "query", "header"):
                    key = {"path": "path_params", "query": "query_params", "header": "headers"}[location]
                    request[key][name] = data.pop(name)
            for name in re.findall(r"\{([^{}]+)\}", case.endpoint):
                if name in data:
                    request["path_params"][name] = data.pop(name)
            if case.api_method.upper() in ("GET", "HEAD", "OPTIONS", "DELETE"):
                request["query_params"].update(data)
            elif data:
                request["body"] = data
        if request["auth_mode"] not in ("default", "missing", "invalid"):
            raise ValueError(f"{case.id}: auth_mode must be default, missing or invalid")
        records.append({**case.model_dump(), "request": request, "security_headers": security_headers, "security_query": security_query})
        name = re.sub(r"[^a-zA-Z0-9_]+", "_", case.id.lower()).strip("_") or "case"
        name = f"test_api_{name}"
        stem, suffix = name, 2
        while name in names:
            name = f"{stem}_{suffix}"
            suffix += 1
        names.add(name)
        functions.append(f"\ndef {name}():\n    _cf_run_case(API_TEST_CASES[{len(records) - 1}])\n")
    template = Path(__file__).with_name("api_runner.txt").read_text(encoding="utf-8")
    return template.replace("__CASE_FOUNDRY_CASES__", pformat(records, sort_dicts=False), 1) + "\n".join(functions)
