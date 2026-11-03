import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database
from app.routers import auth, export, testcases
from app.schemas import GenerationResult
from app.security import verify_password


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database_path = patch.object(database, "DATABASE_PATH", Path(self.directory.name) / "test.db")
        database_path.start()
        self.addCleanup(database_path.stop)
        database.init_db()
        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(testcases.router)
        app.include_router(export.router)
        self.client = self.enterContext(TestClient(app))

    def register(self, email="qa@example.com", password="correct horse battery"):
        response = self.client.post("/auth/register", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def headers(payload):
        return {"Authorization": f"Bearer {payload['token']}"}

    def test_registration_stores_hashes_and_authenticates_immediately(self):
        payload = self.register("  QA@Example.com  ")
        self.assertEqual(payload["user"]["email"], "qa@example.com")
        self.assertEqual(set(payload["user"]), {"id", "email"})
        with database.get_connection() as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            session = connection.execute("SELECT * FROM sessions").fetchone()
        self.assertNotEqual(user["password_hash"], "correct horse battery")
        self.assertTrue(verify_password("correct horse battery", user["password_hash"]))
        self.assertNotEqual(session["token_hash"], payload["token"])
        self.assertEqual(session["token_hash"], hashlib.sha256(payload["token"].encode()).hexdigest())
        me = self.client.get("/auth/me", headers=self.headers(payload))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json(), payload["user"])
        self.assertEqual(me.headers["cache-control"], "no-store")

    def test_duplicate_email_is_case_insensitive(self):
        self.register()
        response = self.client.post("/auth/register", json={"email": "QA@EXAMPLE.COM", "password": "another password"})
        self.assertEqual(response.status_code, 409)

    def test_concurrent_duplicate_is_reported_as_conflict(self):
        self.register()
        existing = database.get_user_by_email("qa@example.com")
        with patch.object(auth, "get_user_by_email", side_effect=[None, existing]), patch.object(
            auth, "create_user", side_effect=sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        ):
            response = self.client.post("/auth/register", json={"email": "qa@example.com", "password": "another password"})
        self.assertEqual(response.status_code, 409)

    def test_login_issues_a_new_session(self):
        registered = self.register(password=" leading and trailing spaces ")
        response = self.client.post("/auth/login", json={"email": " QA@EXAMPLE.COM ", "password": " leading and trailing spaces "})
        self.assertEqual(response.status_code, 200)
        signed_in = response.json()
        self.assertNotEqual(signed_in["token"], registered["token"])
        self.assertEqual(signed_in["user"], registered["user"])
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(signed_in)).status_code, 200)

    def test_bad_credentials_have_the_same_error(self):
        self.register()
        for email, password in [("qa@example.com", "wrong password"), ("missing@example.com", "wrong password"), ("qa@example.com", "short")]:
            with self.subTest(email=email, password=password):
                response = self.client.post("/auth/login", json={"email": email, "password": password})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Email or password is incorrect")

    def test_invalid_registration_is_rejected_without_creating_users(self):
        invalid = [
            ("no-at-sign", "valid password"), ("a@@example.com", "valid password"),
            ("a b@example.com", "valid password"), ("a@-example.com", "valid password"),
            ("a@example..com", "valid password"), (".a@example.com", "valid password"),
            ("a@example.com", "short"), ("a@example.com", " " * 8),
            ("a@example.com", "x" * 129), ("a@example.com", ""),
        ]
        for email, password in invalid:
            with self.subTest(email=email, password=password):
                response = self.client.post("/auth/register", json={"email": email, "password": password})
                self.assertEqual(response.status_code, 422)
        with database.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_missing_or_invalid_token_cannot_access_private_routes(self):
        for authorization in [None, "Basic invalid", "Bearer invalid", "Bearer "]:
            headers = {"Authorization": authorization} if authorization else {}
            for method, path in [("GET", "/auth/me"), ("GET", "/testcases/history"), ("POST", "/testcases/generate"), ("GET", "/exports/private.json")]:
                with self.subTest(authorization=authorization, path=path):
                    self.assertEqual(self.client.request(method, path, headers=headers).status_code, 401)

    def test_expired_session_is_rejected(self):
        payload = self.register()
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.get_connection() as connection:
            connection.execute("UPDATE sessions SET expires_at = ?", (expired,))
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(payload)).status_code, 401)

    def test_logout_revokes_only_the_current_session(self):
        first = self.register()
        second = self.client.post("/auth/login", json={"email": "qa@example.com", "password": "correct horse battery"}).json()
        self.assertEqual(self.client.post("/auth/logout", headers=self.headers(first)).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(first)).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(second)).status_code, 200)

    def test_generated_suites_belong_to_the_signed_in_user(self):
        owner = self.register()
        other = self.register("other@example.com")
        generated = GenerationResult(test_cases=[], pytest_code="def test_example(): pass")
        with patch.object(testcases, "generate_test_cases", return_value=generated):
            response = self.client.post("/testcases/generate", data={"source_code": "def example(): pass"}, headers=self.headers(owner))
        self.assertEqual(response.status_code, 200)
        result_id = response.json()["id"]
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers(owner)).json()[0]["id"], result_id)
        self.assertEqual(self.client.get("/testcases/history", headers=self.headers(other)).json(), [])
        self.assertEqual(self.client.get(f"/exports/{result_id}.json", headers=self.headers(owner)).status_code, 200)
        self.assertEqual(self.client.get(f"/exports/{result_id}.json", headers=self.headers(other)).status_code, 404)


if __name__ == "__main__":
    unittest.main()
