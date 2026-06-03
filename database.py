import os
import sqlite3
import time
import uuid

from config import settings

DB_PATH = "./upload_service.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)

    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS codes (
                id          TEXT PRIMARY KEY,
                code        TEXT UNIQUE NOT NULL,
                created_at  INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL,
                is_revoked  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token       TEXT PRIMARY KEY,
                code_id     TEXT NOT NULL,
                created_at  INTEGER NOT NULL,
                FOREIGN KEY (code_id) REFERENCES codes(id)
            );

            CREATE TABLE IF NOT EXISTS pending_uploads (
                id                TEXT PRIMARY KEY,
                code_id           TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                total_chunks      INTEGER NOT NULL,
                created_at        INTEGER NOT NULL,
                FOREIGN KEY (code_id) REFERENCES codes(id)
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id                TEXT PRIMARY KEY,
                code_id           TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename   TEXT NOT NULL,
                file_size         INTEGER NOT NULL,
                mime_type         TEXT,
                uploaded_at       INTEGER NOT NULL,
                FOREIGN KEY (code_id) REFERENCES codes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_codes_code      ON codes(code);
            CREATE INDEX IF NOT EXISTS idx_uploads_code_id ON uploads(code_id);
        """)


# ── Codes ────────────────────────────────────────────────────────────────────

def create_code(code: str, ttl: int = 3600) -> dict:
    now = int(time.time())
    code_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO codes (id, code, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (code_id, code, now, now + ttl),
        )
    return {"id": code_id, "code": code, "created_at": now, "expires_at": now + ttl, "is_revoked": 0}


def get_code(code: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None


def get_code_by_id(code_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM codes WHERE id = ?", (code_id,)).fetchone()
        return dict(row) if row else None


def list_codes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(u.id) AS upload_count
            FROM   codes c
            LEFT JOIN uploads u ON u.code_id = c.id
            GROUP  BY c.id
            ORDER  BY c.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def revoke_code(code_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE codes SET is_revoked = 1 WHERE id = ?", (code_id,))


# ── Sessions ─────────────────────────────────────────────────────────────────

def create_session(token: str, code_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, code_id, created_at) VALUES (?, ?, ?)",
            (token, code_id, int(time.time())),
        )


def get_session(token: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None


# ── Pending uploads ───────────────────────────────────────────────────────────

def create_pending_upload(upload_id: str, code_id: str, original_filename: str, total_chunks: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_uploads (id, code_id, original_filename, total_chunks, created_at) VALUES (?, ?, ?, ?, ?)",
            (upload_id, code_id, original_filename, total_chunks, int(time.time())),
        )


def get_pending_upload(upload_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM pending_uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None


def delete_pending_upload(upload_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_uploads WHERE id = ?", (upload_id,))


# ── Completed uploads ─────────────────────────────────────────────────────────

def create_upload(
    code_id: str,
    original_filename: str,
    stored_filename: str,
    file_size: int,
    mime_type: str,
) -> str:
    upload_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO uploads (id, code_id, original_filename, stored_filename, file_size, mime_type, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, code_id, original_filename, stored_filename, file_size, mime_type, int(time.time())),
        )
    return upload_id


def list_uploads(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT u.*, c.code
            FROM   uploads u
            JOIN   codes c ON c.id = u.code_id
            ORDER  BY u.uploaded_at DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_conn() as conn:
        now = int(time.time())
        total_codes = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
        active_codes = conn.execute(
            "SELECT COUNT(*) FROM codes WHERE is_revoked = 0 AND expires_at > ?", (now,)
        ).fetchone()[0]
        total_uploads = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
        total_size = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM uploads").fetchone()[0]
    return {
        "total_codes": total_codes,
        "active_codes": active_codes,
        "total_uploads": total_uploads,
        "total_size": total_size,
    }


# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup_expired() -> None:
    now = int(time.time())
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_uploads WHERE created_at < ?", (now - 7200,))
        conn.execute(
            "DELETE FROM sessions WHERE code_id IN "
            "(SELECT id FROM codes WHERE expires_at < ? OR is_revoked = 1)",
            (now,),
        )
