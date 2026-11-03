import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import GenerationResult


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/testcases.db"))


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(name)) BETWEEN 1 AND 100),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_results (
                id TEXT PRIMARY KEY,
                test_cases_json TEXT NOT NULL,
                pytest_code TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(generated_results)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE generated_results ADD COLUMN user_id TEXT REFERENCES users(id)")
        if "result_json" not in columns:
            connection.execute("ALTER TABLE generated_results ADD COLUMN result_json TEXT")
        if "title" not in columns:
            connection.execute("ALTER TABLE generated_results ADD COLUMN title TEXT NOT NULL DEFAULT 'Test suite'")
        if "project_id" not in columns:
            connection.execute("ALTER TABLE generated_results ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
        connection.execute("CREATE INDEX IF NOT EXISTS results_owner_project ON generated_results(user_id, project_id, created_at)")


def create_user(user_id: str, email: str, password_hash: str) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)", (user_id, email, password_hash))


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,)).fetchone()


def create_session(token_hash: str, user_id: str, expires_at: str) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (token_hash, user_id, expires_at))


def get_user_by_session(token_hash: str) -> sqlite3.Row | None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT users.id, users.email FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()


def delete_session(token_hash: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def save_result(result_id: str, result: GenerationResult, user_id: str, title: str = "Test suite", project_id: str | None = None) -> None:
    with get_connection() as connection:
        if project_id is not None and connection.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is None:
            raise ValueError("Project not found")
        connection.execute(
            """
            INSERT INTO generated_results (id, test_cases_json, pytest_code, user_id, result_json, title, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (result_id, json.dumps([case.model_dump() for case in result.test_cases]), result.pytest_code, user_id, result.model_dump_json(), title, project_id),
        )


def load_result(result_id: str, user_id: str | None = None) -> GenerationResult | None:
    with get_connection() as connection:
        query = "SELECT test_cases_json, pytest_code, result_json FROM generated_results WHERE id = ?"
        params: tuple[str, ...] = (result_id,)
        if user_id is not None:
            query += " AND user_id = ?"
            params += (user_id,)
        row = connection.execute(query, params).fetchone()
    if row is None:
        return None
    if row["result_json"]:
        return GenerationResult.model_validate_json(row["result_json"])
    return GenerationResult(
        test_cases=json.loads(row["test_cases_json"]),
        pytest_code=row["pytest_code"],
    )


def list_results(user_id: str, project_id: str | None = None) -> list[dict[str, str | None]]:
    with get_connection() as connection:
        query = "SELECT id, title, created_at, project_id FROM generated_results WHERE user_id = ?"
        params = (user_id,)
        if project_id is not None:
            query += " AND project_id = ?"
            params += (project_id,)
        rows = connection.execute(query + " ORDER BY created_at DESC, rowid DESC", params).fetchall()
    return [dict(row) for row in rows]


def result_metadata(result_id: str, user_id: str) -> dict[str, str | None] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, title, created_at, project_id FROM generated_results WHERE id = ? AND user_id = ?",
            (result_id, user_id),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_result(result_id: str, user_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM generated_results WHERE id = ? AND user_id = ?", (result_id, user_id))
        return cursor.rowcount > 0


def create_project(project_id: str, user_id: str, name: str) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO projects (id, user_id, name) VALUES (?, ?, ?)", (project_id, user_id, name))


def get_project(project_id: str, user_id: str) -> dict[str, object] | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT p.id, p.name, p.created_at,
                (SELECT COUNT(*) FROM generated_results r WHERE r.project_id = p.id AND r.user_id = p.user_id) AS suite_count
                FROM projects p WHERE p.id = ? AND p.user_id = ?""",
            (project_id, user_id),
        ).fetchone()
    return dict(row) if row is not None else None


def list_projects(user_id: str) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT p.id, p.name, p.created_at, COUNT(r.id) AS suite_count
                FROM projects p LEFT JOIN generated_results r ON r.project_id = p.id AND r.user_id = p.user_id
                WHERE p.user_id = ? GROUP BY p.id ORDER BY p.created_at DESC, p.rowid DESC""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]
