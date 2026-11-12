import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.routers import auth, export, testcases
from app.schemas import GenerationResult


class PythonSourceUploadTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DATABASE_PATH", Path(directory) / "test.db"))
        database.init_db()
        app = FastAPI()
        for router in (auth.router, testcases.router, export.router):
            app.include_router(router)
        self.client = self.enterContext(TestClient(app))
        account = self.client.post("/auth/register", json={
            "email": "qa@example.com", "password": "test password",
        }).json()
        self.headers = {"Authorization": f"Bearer {account['token']}"}
        self.sources = {
            "student_service.py": "from repository import get_score\n\ndef passed(student_id):\n    return get_score(student_id) >= 5\n",
            "repository.py": "def get_score(student_id):\n    return {1: 8, 2: 4}[student_id]\n",
        }
        self.unit_code = (
            "import pytest\nimport student_service as sut\n\n"
            "def test_passes():\n    assert sut.passed(1) is True\n\n"
            "def test_dependency_error(monkeypatch):\n"
            "    def unavailable(student_id):\n        raise ConnectionError('Database unavailable')\n"
            "    monkeypatch.setattr(sut, 'get_score', unavailable)\n"
            "    with pytest.raises(ConnectionError):\n        sut.passed(1)\n"
        )
        self.llm = Mock()
        self.llm.generate_json.return_value = {
            "api_test_cases": [],
            "unit_test_cases": [
                {"id": "UNIT-PASS-001", "title": "A student passes", "api_method": "UNIT", "expected_result": "Returns True"},
                {"id": "UNIT-ERROR-001", "title": "Dependency error propagates", "api_method": "UNIT", "expected_result": "Raises ConnectionError"},
            ],
            "unit_test_code": self.unit_code,
        }
        self.enterContext(patch.object(testcases, "GeminiClient", return_value=self.llm))

    def generate(self, sources=None, **data):
        items = list(self.sources.items()) if sources is None else sources
        fields = {"source_language": "python", "source_entrypoint": "student_service.py", **data}
        return self.client.post(
            "/testcases/generate", data=fields, headers=self.headers,
            files=[("source_files", (name, content, "text/x-python")) for name, content in items],
        )

    def test_uploaded_project_survives_history_and_downloaded_bundle_runs(self):
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        suite = response.json()
        self.assertEqual(suite["source_files"], self.sources)
        self.assertEqual(suite["source_entrypoint"], "student_service.py")
        self.assertEqual(suite["title"], "student_service.py unit tests")
        saved = self.client.get(f"/testcases/{suite['id']}", headers=self.headers).json()
        self.assertEqual(saved["source_files"], self.sources)
        self.assertEqual(saved["source_entrypoint"], suite["source_entrypoint"])
        self.assertEqual(len(self.client.get("/testcases/history", headers=self.headers).json()), 1)
        downloaded = self.client.get(f"/exports/{suite['id']}.zip", headers=self.headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text if downloaded.status_code != 200 else "")
        self.assertEqual(downloaded.headers["content-type"], "application/zip")
        with ZipFile(io.BytesIO(downloaded.content)) as archive:
            self.assertEqual(set(archive.namelist()), {*self.sources, "test_generated.py", "README.txt"})
            for name, source in self.sources.items():
                self.assertEqual(archive.read(name).decode(), source)
            with tempfile.TemporaryDirectory() as folder:
                archive.extractall(folder)
                run = subprocess.run(
                    [sys.executable, "-m", "pytest", "test_generated.py", "-q"],
                    cwd=folder, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("2 passed", run.stdout)

    def test_first_uploaded_file_is_the_default_entrypoint(self):
        response = self.generate(source_entrypoint="")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source_entrypoint"], "student_service.py")

    def test_generation_does_not_execute_uploaded_modules(self):
        sources = list(self.sources.items())
        sources[1] = ("repository.py", "raise AssertionError('Must never execute during generation')\n")
        response = self.generate(sources)
        self.assertEqual(response.status_code, 200, response.text)

    def test_invalid_files_are_rejected_before_gemini_and_not_saved(self):
        scenarios = [
            ([("student_service.py", "def broken(:")], {}, "student_service.py"),
            ([("../student_service.py", "x = 1")], {}, "filename"),
            ([("student_service.py", b"\xff")], {}, "UTF-8"),
            (list(self.sources.items()), {"source_entrypoint": "missing.py"}, "entry"),
            (list(self.sources.items()), {"source_language": "javascript"}, "Python"),
            (list(self.sources.items()), {"source_code": "def other(): return 1"}, "both"),
        ]
        for sources, fields, detail in scenarios:
            with self.subTest(sources=[name for name, _ in sources], fields=fields):
                response = self.generate(sources, **fields)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(detail.lower(), response.json()["detail"].lower())
        self.llm.generate_json.assert_not_called()
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers).json(), [])

    def test_duplicate_filenames_are_not_silently_overwritten(self):
        for duplicate in ("student_service.py", "Student_Service.py"):
            with self.subTest(duplicate=duplicate):
                response = self.generate([
                    ("student_service.py", "x = 1"), (duplicate, "x = 2"),
                ])
                self.assertEqual(response.status_code, 400)
                self.assertIn("Duplicate", response.json()["detail"])
        self.llm.generate_json.assert_not_called()

    def test_upload_limits_are_checked_before_gemini(self):
        scenarios = [
            [(f"module_{i}.py", "x = 1") for i in range(21)],
            [("student_service.py", "#" + "x" * (128 * 1024))],
            [(f"module_{i}.py", "#" + "x" * (110 * 1024)) for i in range(5)],
        ]
        for sources in scenarios:
            with self.subTest(count=len(sources)):
                response = self.generate(sources)
                self.assertEqual(response.status_code, 400, response.text)
        self.llm.generate_json.assert_not_called()

    def test_bundle_is_private_to_its_owner(self):
        suite = self.generate().json()
        anonymous = self.client.get(f"/exports/{suite['id']}.zip")
        self.assertEqual(anonymous.status_code, 401)
        other = self.client.post("/auth/register", json={
            "email": "other@example.com", "password": "test password",
        }).json()
        response = self.client.get(f"/exports/{suite['id']}.zip", headers={
            "Authorization": f"Bearer {other['token']}",
        })
        self.assertEqual(response.status_code, 404)

    def test_legacy_suite_does_not_offer_a_source_bundle(self):
        account = self.client.get("/auth/me", headers=self.headers).json()
        result = GenerationResult(test_cases=[], pytest_code="def test_old(): assert True")
        database.save_result("legacy", result, account["id"])
        response = self.client.get("/exports/legacy.zip", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("bundle", response.json()["detail"])

