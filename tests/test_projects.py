import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.routers import auth, projects, testcases
from app.schemas import GenerationResult, TestCase as GeneratedCase


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DATABASE_PATH", Path(self.directory) / "test.db"))
        database.init_db()
        app = FastAPI()
        for router in (auth.router, projects.router, testcases.router):
            app.include_router(router)
        self.client = self.enterContext(TestClient(app))
        self.owner = self.client.post("/auth/register", json={"email": "owner@example.com", "password": "test password"}).json()
        self.other = self.client.post("/auth/register", json={"email": "other@example.com", "password": "test password"}).json()
        case = GeneratedCase(id="UNIT-ANSWER-001", title="Returns an answer", api_method="UNIT", expected_result="Returns 42")
        code = "import source_under_test as sut\ndef test_answer(): assert sut.answer() == 42"
        self.result = GenerationResult(test_cases=[case], unit_test_cases=[case], pytest_code=code, unit_test_code=code)

    @staticmethod
    def headers(account):
        return {"Authorization": f"Bearer {account['token']}"}

    def create(self, name="Task manager", account=None):
        response = self.client.post("/projects", json={"name": name}, headers=self.headers(account or self.owner))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_project_is_normalized_and_persisted_for_its_owner(self):
        project = self.create("  Task   manager \n ")
        self.assertEqual(project["name"], "Task manager")
        self.assertEqual(project["suite_count"], 0)
        self.assertIn("created_at", project)
        with database.get_connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()
        self.assertEqual(row["user_id"], self.owner["user"]["id"])
        self.assertEqual(row["name"], "Task manager")
        database.init_db()
        self.assertEqual(self.client.get("/projects", headers=self.headers(self.owner)).json(), [project])
        self.assertEqual(self.client.get(f"/projects/{project['id']}", headers=self.headers(self.owner)).json(), project)

    def test_projects_are_private_to_each_user(self):
        project = self.create()
        self.assertEqual(self.client.get("/projects", headers=self.headers(self.other)).json(), [])
        self.assertEqual(self.client.get(f"/projects/{project['id']}", headers=self.headers(self.other)).status_code, 404)
        self.assertEqual(self.client.get("/testcases/history", params={"project_id": project["id"]}, headers=self.headers(self.other)).status_code, 404)

    def test_project_list_returns_the_complete_array_beyond_twenty_projects(self):
        for number in range(25):
            database.create_project(f"project-{number}", self.owner["user"]["id"], f"Project {number}")
        database.create_project("foreign-project", self.other["user"]["id"], "Private project")
        response = self.client.get("/projects", headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertEqual(len(response.json()), 25)
        self.assertNotIn("foreign-project", [item["id"] for item in response.json()])

    def test_duplicate_names_are_case_insensitive_within_one_account(self):
        self.create()
        response = self.client.post("/projects", json={"name": " TASK MANAGER "}, headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get("/projects", headers=self.headers(self.owner)).json()), 1)
        self.assertEqual(self.create("Task manager", self.other)["name"], "Task manager")

    def test_invalid_names_are_rejected_without_saving_projects(self):
        for payload in [{}, {"name": ""}, {"name": " \t\n "}, {"name": "x" * 101}, {"name": 42}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/projects", json=payload, headers=self.headers(self.owner)).status_code, 422)
        self.assertEqual(self.client.get("/projects", headers=self.headers(self.owner)).json(), [])

    def test_generation_saves_the_project_link_and_history_filters_by_project(self):
        selected = self.create()
        unrelated = self.create("Other project")
        database.save_result("unrelated-suite", self.result, self.owner["user"]["id"], project_id=unrelated["id"])
        database.save_result("unassigned-suite", self.result, self.owner["user"]["id"])
        with patch.object(testcases, "generate_test_cases", return_value=self.result):
            response = self.client.post("/testcases/generate", data={"source_code": "def answer(): return 42", "project_id": selected["id"]}, headers=self.headers(self.owner))
        self.assertEqual(response.status_code, 200, response.text)
        generated = response.json()
        self.assertEqual(generated["project_id"], selected["id"])
        saved = self.client.get(f"/testcases/{generated['id']}", headers=self.headers(self.owner))
        self.assertEqual(saved.json()["project_id"], selected["id"])
        filtered = self.client.get("/testcases/history", params={"project_id": selected["id"]}, headers=self.headers(self.owner)).json()
        self.assertEqual([item["id"] for item in filtered], [generated["id"]])
        self.assertEqual(len(self.client.get("/testcases/history", headers=self.headers(self.owner)).json()), 3)
        self.assertEqual(self.client.get(f"/projects/{selected['id']}", headers=self.headers(self.owner)).json()["suite_count"], 1)

    def test_foreign_or_missing_project_is_rejected_before_generation(self):
        foreign = self.create(account=self.other)
        with patch.object(testcases, "generate_test_cases") as generate:
            for project_id in (foreign["id"], "missing-project"):
                with self.subTest(project_id=project_id):
                    response = self.client.post("/testcases/generate", data={"source_code": "def answer(): return 42", "project_id": project_id}, headers=self.headers(self.owner))
                    self.assertEqual(response.status_code, 404)
            generate.assert_not_called()
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers(self.owner)).json(), [])

    def test_storage_layer_also_prevents_cross_user_project_links(self):
        foreign = self.create(account=self.other)
        with self.assertRaisesRegex(ValueError, "Project not found"):
            database.save_result("invalid-suite", self.result, self.owner["user"]["id"], project_id=foreign["id"])
        self.assertIsNone(database.load_result("invalid-suite"))

    def test_deleting_a_suite_updates_the_project_count_and_preserves_project(self):
        project = self.create()
        database.save_result("project-suite", self.result, self.owner["user"]["id"], project_id=project["id"])
        self.assertEqual(self.client.delete("/testcases/project-suite", headers=self.headers(self.owner)).status_code, 200)
        self.assertEqual(self.client.get(f"/projects/{project['id']}", headers=self.headers(self.owner)).json()["suite_count"], 0)

    def test_project_endpoints_require_authentication(self):
        for method, path in [("GET", "/projects"), ("POST", "/projects"), ("GET", "/projects/missing")]:
            self.assertEqual(self.client.request(method, path, json={"name": "Project"}).status_code, 401)

    def test_migration_keeps_old_saved_suites_and_is_idempotent(self):
        path = Path(self.directory) / "legacy.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE generated_results (id TEXT PRIMARY KEY, test_cases_json TEXT NOT NULL, pytest_code TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO generated_results (id, test_cases_json, pytest_code) VALUES (?, ?, ?)", ("legacy-suite", json.dumps([self.result.test_cases[0].model_dump()]), self.result.pytest_code))
            connection.commit()
        finally:
            connection.close()
        with patch.object(database, "DATABASE_PATH", path):
            database.init_db()
            database.init_db()
            with database.get_connection() as connection:
                row = connection.execute("SELECT * FROM generated_results WHERE id = ?", ("legacy-suite",)).fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row["project_id"])
            self.assertEqual(row["pytest_code"], self.result.pytest_code)
            self.assertEqual(database.load_result("legacy-suite").test_cases[0].id, "UNIT-ANSWER-001")


if __name__ == "__main__":
    unittest.main()
