import csv
import io
import json

from app.schemas import GenerationResult


def export_result(result: GenerationResult, fmt: str) -> tuple[str, str, str]:
    if fmt == "json":
        return result.model_dump_json(indent=2), "application/json", "generated-tests.json"
    if fmt == "py":
        if not result.pytest_code.strip():
            raise ValueError("This suite contains JavaScript/TypeScript tests. Download its matching test-code format.")
        return result.pytest_code, "text/x-python", "test_generated.py"
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
    raise ValueError("format must be one of: py, js, ts, csv, json")
