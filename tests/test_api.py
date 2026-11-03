import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.routers import auth, export, testcases
from app.services.llm_client import GeminiClient


class GenerationApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DATABASE_PATH", Path(directory) / "test.db"))
        database.init_db()
        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(testcases.router)
        app.include_router(export.router)
        self.client = self.enterContext(TestClient(app))
        registered = self.client.post("/auth/register", json={"email": "qa@example.com", "password": "test password"})
        self.headers = {"Authorization": f"Bearer {registered.json()['token']}"}
        self.enterContext(patch.object(testcases, "GeminiClient", return_value=GeminiClient(api_key="test-key")))
        self.urlopen = self.enterContext(patch("app.services.llm_client.urlopen"))
        self.suite = {
            "api_test_cases": [{
                "id": "API-HEALTH-001", "title": "Health endpoint succeeds", "api_method": "GET",
                "endpoint": "/health", "expected_result": "Returns a healthy response", "expected_status_code": 200,
            }],
            "unit_test_cases": [],
        }
        self.spec = {"openapi": "3.0.3", "info": {"title": "Example", "version": "1.0"}, "paths": {"/health": {"get": {"responses": {"200": {"description": "OK"}}}}}}

    def provider_response(self, text=None, reason="STOP", parts=None):
        response = MagicMock()
        body = {"candidates": [{"finishReason": reason, "content": {"parts": parts if parts is not None else [{"text": text if text is not None else json.dumps(self.suite)}]}}]}
        response.__enter__.return_value.read.return_value = json.dumps(body).encode()
        return response

    def generate(self):
        return self.client.post("/testcases/generate", files={"swagger_file": ("example.json", json.dumps(self.spec), "application/json")}, headers=self.headers)

    def assert_nothing_saved(self):
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers).json(), [])

    def test_upload_with_a_multipart_gemini_answer_generates_and_exports_a_suite(self):
        encoded = json.dumps(self.suite)
        self.urlopen.return_value = self.provider_response(parts=[
            {"text": "A summary", "thought": True}, {"text": encoded[:40]}, {"text": encoded[40:]},
        ])
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["api_test_cases"][0]["id"], "API-HEALTH-001")
        compile(payload["pytest_code"], "test_generated.py", "exec")
        exported = self.client.get(f"/exports/{payload['id']}.json", headers=self.headers)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["test_cases"][0]["id"], "API-HEALTH-001")

    def test_truncated_first_answer_is_retried_before_saving(self):
        self.urlopen.side_effect = [self.provider_response('{"api_test_cases":[', "MAX_TOKENS"), self.provider_response()]
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(len(self.client.get("/testcases/history", headers=self.headers).json()), 1)

    def test_persistently_truncated_answers_return_502_without_saving(self):
        self.urlopen.return_value = self.provider_response('{"api_test_cases":[', "MAX_TOKENS")
        response = self.generate()
        self.assertEqual(response.status_code, 502)
        self.assertIn("GEMINI_MAX_OUTPUT_TOKENS", response.json()["detail"])
        self.assertEqual(self.urlopen.call_count, 2)
        self.assert_nothing_saved()

    def test_persistently_malformed_answers_return_502_without_saving(self):
        self.urlopen.return_value = self.provider_response("not JSON")
        response = self.generate()
        self.assertEqual(response.status_code, 502)
        self.assertIn("malformed test-suite JSON", response.json()["detail"])
        self.assertEqual(self.urlopen.call_count, 2)
        self.assert_nothing_saved()

    def test_blocked_response_reports_the_reason_without_retrying(self):
        self.urlopen.return_value = self.provider_response(reason="SAFETY")
        response = self.generate()
        self.assertEqual(response.status_code, 502)
        self.assertIn("SAFETY", response.json()["detail"])
        self.assertEqual(self.urlopen.call_count, 1)
        self.assert_nothing_saved()

    def test_invalid_upload_is_rejected_before_calling_gemini(self):
        response = self.client.post("/testcases/generate", files={"swagger_file": ("bad.json", "not JSON", "application/json")}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.urlopen.assert_not_called()
        self.assert_nothing_saved()

    def test_pasted_python_without_a_file_returns_real_tests_and_preserves_exports(self):
        self.suite = {
            "api_test_cases": [],
            "unit_test_cases": [{"id": "UNIT-ADD-001", "title": "Adds numbers", "api_method": "UNIT", "expected_result": "Returns their sum"}],
            "unit_test_code": "import source_under_test as sut\n\ndef test_add():\n    assert sut.add(2, 3) == 5\n",
        }
        self.urlopen.return_value = self.provider_response()
        response = self.client.post("/testcases/generate", data={"source_code": "def add(a, b): return a + b", "source_language": "python"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["api_test_cases"], [])
        self.assertEqual(len(payload["unit_test_cases"]), 1)
        self.assertIn("sut.add(2, 3)", payload["unit_test_code"])
        exported = self.client.get(f"/exports/{payload['id']}.json", headers=self.headers)
        self.assertEqual(exported.json()["unit_test_code"], payload["unit_test_code"])
        self.assertEqual(exported.json()["unit_test_cases"], payload["unit_test_cases"])
        python_export = self.client.get(f"/exports/{payload['id']}.py", headers=self.headers)
        self.assertIn("sut.add(2, 3)", python_export.text)
        self.assertIn('filename="test_generated.py"', python_export.headers["content-disposition"])

    def test_pasted_typescript_download_keeps_language_after_database_save(self):
        self.suite = {
            "api_test_cases": [],
            "unit_test_cases": [{"id": "UNIT-ADD-001", "title": "Adds numbers", "api_method": "UNIT", "expected_result": "Returns their sum"}],
            "unit_test_code": "import { it, expect } from 'vitest';\nimport { add } from './source_under_test.ts';\nit('adds', () => { expect(add(2, 3)).toBe(5); });",
        }
        self.urlopen.return_value = self.provider_response()
        response = self.client.post("/testcases/generate", data={"source_code": "export function add(a: number, b: number) { return a + b; }", "source_language": "typescript"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        downloaded = self.client.get(f"/exports/{payload['id']}.ts", headers=self.headers)
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("expect(add(2, 3))", downloaded.text)
        self.assertIn('filename="test_generated.test.ts"', downloaded.headers["content-disposition"])
        self.assertEqual(self.client.get(f"/exports/{payload['id']}.py", headers=self.headers).status_code, 400)

    def test_invalid_source_language_is_rejected_before_calling_gemini(self):
        response = self.client.post("/testcases/generate", data={"source_code": "code", "source_language": "unknown"}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
