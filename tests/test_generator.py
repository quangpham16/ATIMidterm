import json
import unittest

from app.schemas import TestCase as GeneratedCase
from app.services.exporter import export_result
from app.services.generator import generate_test_cases


class FakeGemini:
    def generate_json(self, prompt: str) -> dict:
        assert "<spec>" in prompt and "</spec>" in prompt
        assert "<code>" in prompt and "</code>" in prompt
        return {
            "test_cases": [
                {
                    "id": "TC-001",
                    "title": "GET users succeeds",
                    "api_method": "GET",
                    "endpoint": "/users",
                    "priority": "high",
                    "test_type": "positive",
                    "prerequisites": [],
                    "request_data": {},
                    "steps": ["Mock GET /users"],
                    "expected_result": "Users are returned",
                    "expected_status_code": 200,
                }
            ]
        }


def test_generate_test_cases_returns_pytest_code():
    result = generate_test_cases({"openapi": "3.0.0", "paths": {}}, "def handler(): pass", FakeGemini())
    assert isinstance(result.test_cases[0], GeneratedCase)
    assert "def test_api_tc_001" in result.pytest_code
    assert "Mock" in result.pytest_code


def test_exports_are_available_in_required_formats():
    result = generate_test_cases({"openapi": "3.0.0", "paths": {}}, "def handler(): pass", FakeGemini())
    json_content, _, _ = export_result(result, "json")
    csv_content, _, _ = export_result(result, "csv")
    py_content, _, _ = export_result(result, "py")
    assert json.loads(json_content)["test_cases"][0]["id"] == "TC-001"
    assert "TC-001" in csv_content
    assert "test_api_tc_001" in py_content


class GeneratorRegressionTests(unittest.TestCase):
    def test_generated_api_code_executes_with_mocks(self):
        test_generate_test_cases_returns_pytest_code()
        result = generate_test_cases({"openapi": "3.0.0", "paths": {}}, "", FakeGemini())
        namespace = {}
        exec(compile(result.pytest_code, "test_generated.py", "exec"), namespace)
        namespace["test_api_tc_001"]()

    def test_export_formats(self):
        test_exports_are_available_in_required_formats()

    def test_source_only_response_can_omit_the_api_array(self):
        class UnitOnlyGemini:
            def generate_json(self, prompt):
                return {
                    "unit_test_cases": [{"id": "UNIT-001", "title": "Function returns a value", "expected_result": "Returns 42"}],
                    "unit_test_code": "import source_under_test as sut\n\ndef test_answer():\n    assert sut.answer() == 42\n",
                }

        result = generate_test_cases({}, "def answer(): return 42", UnitOnlyGemini())
        self.assertEqual(result.api_test_cases, [])
        self.assertEqual(len(result.unit_test_cases), 1)


if __name__ == "__main__":
    unittest.main()
