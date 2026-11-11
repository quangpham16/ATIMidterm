import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.routers import auth, export, testcases
from app.schemas import GenerationResult, TestCase as GeneratedCase


class SavedSuiteTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DATABASE_PATH", Path(directory) / "test.db"))
        database.init_db()
        app = FastAPI()
        for router in (auth.router, testcases.router, export.router):
            app.include_router(router)
        self.client = self.enterContext(TestClient(app))
        self.owner = self.client.post("/auth/register", json={"email": "owner@example.com", "password": "test password"}).json()
        self.other = self.client.post("/auth/register", json={"email": "other@example.com", "password": "test password"}).json()
        case = GeneratedCase(id="UNIT-ANSWER-001", title="Returns an answer", api_method="UNIT", expected_result="Returns 42")
        self.result = GenerationResult(test_cases=[case], api_test_cases=[], unit_test_cases=[case], pytest_code="import source_under_test as sut\ndef test_answer(): assert sut.answer() == 42", unit_test_code="import source_under_test as sut\ndef test_answer(): assert sut.answer() == 42", unit_test_framework="pytest")
        database.save_result("owner-suite", self.result, self.owner["user"]["id"], "Python unit tests")
        database.save_result("other-suite", self.result, self.other["user"]["id"], "Other user's suite")

    @staticmethod
    def headers(account):
        return {"Authorization": f"Bearer {account['token']}"}

    def test_history_lists_only_the_current_users_suites_with_titles(self):
        response = self.client.get("/testcases/history", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], "owner-suite")
        self.assertEqual(response.json()[0]["title"], "Python unit tests")
        self.assertIn("created_at", response.json()[0])

    def test_history_returns_the_complete_array_beyond_twenty_suites(self):
        for number in range(24):
            database.save_result(f"suite-{number}", self.result, self.owner["user"]["id"])
        response = self.client.get("/testcases/history", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertEqual(len(response.json()), 25)
        self.assertNotIn("other-suite", [item["id"] for item in response.json()])

    def test_opening_saved_suite_restores_cases_code_and_metadata(self):
        response = self.client.get("/testcases/owner-suite", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], "owner-suite")
        self.assertEqual(payload["title"], "Python unit tests")
        self.assertEqual(payload["unit_test_code"], self.result.unit_test_code)
        self.assertEqual(len(payload["unit_test_cases"]), 1)

    def test_other_users_cannot_open_or_delete_a_suite(self):
        for method in ("GET", "DELETE"):
            with self.subTest(method=method):
                response = self.client.request(method, "/testcases/owner-suite", headers=self.headers(self.other))
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/testcases/owner-suite", headers=self.headers(self.owner)).status_code, 200)

    def test_delete_removes_history_details_and_exports_but_keeps_other_users_suites(self):
        response = self.client.delete("/testcases/owner-suite", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "deleted")
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers(self.owner)).json(), [])
        self.assertEqual(self.client.get("/testcases/owner-suite", headers=self.headers(self.owner)).status_code, 404)
        self.assertEqual(self.client.get("/exports/owner-suite.json", headers=self.headers(self.owner)).status_code, 404)
        self.assertEqual(self.client.get("/testcases/other-suite", headers=self.headers(self.other)).status_code, 200)
        self.assertEqual(self.client.delete("/testcases/owner-suite", headers=self.headers(self.owner)).status_code, 404)

    def test_unauthenticated_requests_cannot_read_or_delete_saved_suites(self):
        for method in ("GET", "DELETE"):
            self.assertEqual(self.client.request(method, "/testcases/owner-suite").status_code, 401)

    def test_legacy_suites_can_still_be_opened(self):
        with database.get_connection() as connection:
            connection.execute("UPDATE generated_results SET result_json = NULL WHERE id = ?", ("owner-suite",))
        response = self.client.get("/testcases/owner-suite", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["test_cases"][0]["id"], "UNIT-ANSWER-001")
        self.assertEqual(response.json()["pytest_code"], self.result.pytest_code)

    def test_newest_suite_comes_first_when_timestamps_match(self):
        database.save_result("new-suite", self.result, self.owner["user"]["id"], "New suite")
        history = self.client.get("/testcases/history", headers=self.headers(self.owner)).json()
        self.assertEqual([item["id"] for item in history], ["new-suite", "owner-suite"])

    def test_generation_returns_a_title_and_immediately_updates_history(self):
        with patch.object(testcases, "generate_test_cases", return_value=self.result):
            response = self.client.post("/testcases/generate", files={"swagger_file": ("contract.json", json.dumps({"openapi": "3.0.3"}), "application/json")}, headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "contract.json")
        self.assertIn("created_at", response.json())
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers(self.owner)).json()[0]["id"], response.json()["id"])


if __name__ == "__main__":
    unittest.main()
