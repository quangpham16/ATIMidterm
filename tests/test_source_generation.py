import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from app.services.exporter import export_result
from app.services.generator import generate_test_cases
from app.services.prompt_builder import build_generation_prompt


PYTHON_SOURCE = "def add(a, b):\n    return a + b\n"
PYTHON_TESTS = "import source_under_test as sut\n\ndef test_add_positive():\n    assert sut.add(2, 3) == 5\n\ndef test_add_negative():\n    assert sut.add(-2, -3) == -5\n"
UNIT_CASE = {"id": "UNIT-ADD-001", "title": "Adds two numbers", "api_method": "UNIT", "endpoint": "add", "expected_result": "Returns their sum"}


def fake_client(code=PYTHON_TESTS):
    return Mock(generate_json=Mock(return_value={"api_test_cases": [], "unit_test_cases": [UNIT_CASE], "unit_test_code": code}))


class SourceGenerationTests(unittest.TestCase):
    def test_python_export_calls_the_real_source_and_detects_broken_behaviour(self):
        client = fake_client()
        result = generate_test_cases({}, PYTHON_SOURCE, client)
        client.generate_json.assert_called_once()
        self.assertEqual(result.api_test_cases, [])
        self.assertEqual(result.unit_test_framework, "pytest")
        self.assertEqual(result.unit_pytest_code, result.unit_test_code)
        module = types.ModuleType("source_under_test")
        exec(PYTHON_SOURCE, module.__dict__)
        with patch.dict(sys.modules, {"source_under_test": module}):
            namespace = {}
            exec(compile(result.pytest_code, "test_generated.py", "exec"), namespace)
            namespace["test_add_positive"]()
            namespace["test_add_negative"]()
            module.add = lambda a, b: a - b
            with self.assertRaises(AssertionError):
                namespace["test_add_positive"]()

    def test_invalid_python_source_is_rejected_before_sending_a_prompt(self):
        client = fake_client()
        with self.assertRaisesRegex(ValueError, "syntax error at line"):
            generate_test_cases({}, "def broken(:", client)
        client.generate_json.assert_not_called()

    def test_missing_generated_test_code_is_an_upstream_failure(self):
        with self.assertRaisesRegex(RuntimeError, "without runnable test code"):
            generate_test_cases({}, PYTHON_SOURCE, fake_client(""))

    def test_generated_code_must_be_valid_python(self):
        client = fake_client("def test_broken(:")
        with self.assertRaisesRegex(RuntimeError, "invalid Python test code"):
            generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertEqual(client.generate_json.call_count, 3)

    def test_invalid_generated_python_is_repaired_without_replacing_the_cases(self):
        broken = "# generated\n" * 21 + "import source_under_test as sut\n\ndef test_add(:\n    assert sut.add(2, 3) == 5\n"
        client = fake_client(broken)
        client.generate_json.side_effect = [
            client.generate_json.return_value,
            {"api_test_cases": [], "unit_test_cases": [], "unit_test_code": PYTHON_TESTS},
        ]

        result = generate_test_cases({}, PYTHON_SOURCE, client)

        self.assertEqual(client.generate_json.call_count, 2)
        repair_prompt = client.generate_json.call_args.args[0]
        self.assertIn(PYTHON_SOURCE.strip(), repair_prompt)
        self.assertIn("line 24", repair_prompt)
        self.assertIn("invalid syntax", repair_prompt)
        self.assertIn("UNIT-ADD-001", repair_prompt)
        self.assertIn(broken, repair_prompt)
        self.assertEqual([case.id for case in result.unit_test_cases], ["UNIT-ADD-001"])
        self.assertNotIn("def test_add(:", result.unit_test_code)
        module = types.ModuleType("source_under_test")
        exec(PYTHON_SOURCE, module.__dict__)
        with patch.dict(sys.modules, {"source_under_test": module}):
            namespace = {}
            exec(compile(result.pytest_code, "test_generated.py", "exec"), namespace)
            namespace["test_add_positive"]()
            namespace["test_add_negative"]()

    def test_second_repair_uses_the_latest_code_and_error(self):
        client = fake_client("def test_add(:")
        second_code = "import source_under_test as sut\nBROKEN = f'value }'\n\ndef test_add():\n    assert sut.add(2, 3) == 5\n"
        client.generate_json.side_effect = [
            client.generate_json.return_value,
            {"api_test_cases": [], "unit_test_cases": [], "unit_test_code": second_code},
            {"api_test_cases": [], "unit_test_cases": [], "unit_test_code": PYTHON_TESTS},
        ]
        result = generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertEqual(client.generate_json.call_count, 3)
        last_prompt = client.generate_json.call_args.args[0]
        self.assertIn(second_code, last_prompt)
        self.assertIn("line 2", last_prompt)
        self.assertNotIn("def test_add(:", last_prompt)
        compile(result.pytest_code, "test_generated.py", "exec")
        self.assertEqual([case.id for case in result.unit_test_cases], ["UNIT-ADD-001"])

    def test_missing_generated_code_can_be_repaired(self):
        client = fake_client(None)
        client.generate_json.side_effect = [
            client.generate_json.return_value,
            {"api_test_cases": [], "unit_test_cases": [], "unit_test_code": PYTHON_TESTS},
        ]
        result = generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertIn("sut.add(2, 3)", result.unit_test_code)

    def test_python_that_parses_but_cannot_compile_is_not_exported(self):
        client = fake_client("import source_under_test as sut\nreturn 1\n\ndef test_add():\n    assert sut.add(2, 3) == 5\n")
        with self.assertRaisesRegex(RuntimeError, "outside function"):
            generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertEqual(client.generate_json.call_count, 3)

    def test_repair_transport_failure_is_reported_without_further_generation(self):
        client = fake_client("def test_broken(:")
        client.generate_json.side_effect = [client.generate_json.return_value, RuntimeError("Gemini API returned HTTP 503")]
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertEqual(client.generate_json.call_count, 2)

    def test_malformed_repair_response_is_reported_as_an_upstream_failure(self):
        client = fake_client("def test_broken(:")
        client.generate_json.side_effect = [client.generate_json.return_value, []]
        with self.assertRaisesRegex(RuntimeError, "repair response"):
            generate_test_cases({}, PYTHON_SOURCE, client)
        self.assertEqual(client.generate_json.call_count, 2)

    def test_tests_that_only_assert_a_mock_are_rejected(self):
        tautology = "from unittest.mock import Mock\n\ndef test_fake():\n    dependency = Mock(return_value=5)\n    assert dependency() == 5\n"
        with self.assertRaisesRegex(RuntimeError, "did not call the source module"):
            generate_test_cases({}, PYTHON_SOURCE, fake_client(tautology))

    def test_external_dependency_can_be_mocked_while_calling_the_real_target(self):
        source = "repository = None\n\ndef lookup(user_id):\n    return repository.get(user_id)\n"
        code = "import source_under_test as sut\nfrom unittest.mock import patch\n\ndef test_lookup():\n    with patch.object(sut, 'repository') as repo:\n        repo.get.return_value = {'id': 1}\n        assert sut.lookup(1) == {'id': 1}\n        repo.get.assert_called_once_with(1)\n"
        result = generate_test_cases({}, source, fake_client(code))
        module = types.ModuleType("source_under_test")
        exec(source, module.__dict__)
        with patch.dict(sys.modules, {"source_under_test": module}):
            namespace = {}
            exec(result.pytest_code, namespace)
            namespace["test_lookup"]()

    def test_javascript_and_typescript_use_vitest_and_matching_exports(self):
        for language, extension in [("javascript", "js"), ("typescript", "ts")]:
            with self.subTest(language=language):
                code = f"import {{ it, expect }} from 'vitest';\nimport {{ add }} from './source_under_test.{extension}';\nit('adds numbers', () => {{ expect(add(2, 3)).toBe(5); }});\n"
                result = generate_test_cases({}, "export function add(a, b) { return a + b; }", fake_client(code), language)
                self.assertEqual(result.source_language, language)
                self.assertEqual(result.unit_test_framework, "Vitest")
                self.assertEqual(result.pytest_code, "")
                exported, _, filename = export_result(result, extension)
                self.assertIn("expect(add(2, 3))", exported)
                self.assertEqual(filename, f"test_generated.test.{extension}")
                self.assertEqual(json.loads(export_result(result, "json")[0])["source_language"], language)
                with self.assertRaises(ValueError):
                    export_result(result, "py")

    def test_wrong_language_code_is_not_exported_as_javascript(self):
        with self.assertRaisesRegex(RuntimeError, "did not import the source module"):
            generate_test_cases({}, "export function add(a, b) { return a + b; }", fake_client(), "javascript")

    def test_wrong_language_code_can_be_repaired_as_vitest(self):
        for language, extension in [("javascript", "js"), ("typescript", "ts")]:
            with self.subTest(language=language):
                code = f"import {{ it, expect }} from 'vitest';\nimport {{ add }} from './source_under_test.{extension}';\nit('adds', () => {{ expect(add(2, 3)).toBe(5); }});\n"
                client = fake_client()
                client.generate_json.side_effect = [
                    client.generate_json.return_value,
                    {"api_test_cases": [], "unit_test_cases": [], "unit_test_code": code},
                ]
                result = generate_test_cases({}, "export function add(a, b) { return a + b; }", client, language)
                self.assertEqual(client.generate_json.call_count, 2)
                self.assertEqual(result.pytest_code, "")
                self.assertIn(code.strip(), result.unit_test_code)
                self.assertEqual(result.unit_test_framework, "Vitest")

    def test_prompt_preserves_user_placeholders_and_requests_real_target_calls(self):
        prompt = build_generation_prompt({}, "def label(): return '{module} {language}'", "python")
        self.assertIn("def label(): return '{module} {language}'", prompt)
        self.assertIn("Source language: python. Test framework: pytest", prompt)
        self.assertIn("Never mock the function or class under test", prompt)
        self.assertIn('return "api_test_cases": []', prompt)


if __name__ == "__main__":
    unittest.main()
