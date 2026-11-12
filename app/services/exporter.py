import csv
import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

from app.schemas import GenerationResult
from app.services.source_project import validate_source_project


def export_result(result: GenerationResult, fmt: str) -> tuple[str | bytes, str, str]:
    if fmt == "json":
        return result.model_dump_json(indent=2), "application/json", "generated-tests.json"
    if fmt == "py":
        if not result.pytest_code.strip():
            raise ValueError("This suite contains JavaScript/TypeScript tests. Download its matching test-code format.")
        return result.pytest_code, "text/x-python", "test_generated.py"
    if fmt == "zip":
        if result.source_language != "python" or not result.source_files or not result.pytest_code.strip():
            raise ValueError("This suite has no uploaded Python source bundle")
        sources, entrypoint = validate_source_project(result.source_files, result.source_entrypoint)
        output = io.BytesIO()
        readme = (
            f"Python test bundle\n\nEntry module: {entrypoint}\n\n"
            "1. Extract all files into the same project folder. Keep their original filenames.\n"
            "2. Install pytest and any external dependencies imported by your source:\n"
            "   python -m pip install pytest\n"
            "3. Run the generated tests from that folder:\n"
            "   python -m pytest test_generated.py -q\n\n"
            "The supplied Python modules are included. External packages and services are not.\n"
            "These tests were generated and statically checked, not executed by Case Foundry.\n"
        )
        if result.api_test_cases:
            readme += (
                "\nThis suite also contains API tests. Install httpx and set API_BASE_URL.\n"
                "Optional: API_BEARER_TOKEN, API_HEADERS_JSON, API_TIMEOUT_SECONDS.\n"
                "State-changing API requests require API_ALLOW_MUTATIONS=true.\n"
            )
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for name, content in sources.items():
                archive.writestr(name, content)
            archive.writestr("test_generated.py", result.pytest_code)
            archive.writestr("README.txt", readme)
        return output.getvalue(), "application/zip", "python-test-bundle.zip"
    if fmt in ("js", "ts"):
        language = "typescript" if fmt == "ts" else "javascript"
        if result.source_language != language or not result.unit_test_code.strip():
            raise ValueError(f"This suite has no {language} unit test code")
        return result.unit_test_code, "text/javascript" if fmt == "js" else "text/plain", f"test_generated.test.{fmt}"
    if fmt == "csv":
        output = io.StringIO()
        fields = ["id", "title", "api_method", "endpoint", "priority", "test_type", "prerequisites", "request_data", "steps", "expected_result", "expected_status_code"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for case in result.test_cases:
            row = case.model_dump()
            for key in ("prerequisites", "request_data", "steps"):
                row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)
        return output.getvalue(), "text/csv", "generated-tests.csv"
    raise ValueError("format must be one of: py, js, ts, csv, json, zip")
