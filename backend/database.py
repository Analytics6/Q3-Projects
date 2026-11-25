"""SQLite storage. Turso/libSQL supplies durable hosted SQLite on Vercel."""
import os
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        name TEXT NOT NULL, password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
        sources_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at)""",
    """CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, filename TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
        category TEXT NOT NULL, status TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0, sha256 TEXT, uploaded_by TEXT,
        created_at TEXT NOT NULL, indexed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS ingestion_runs (
        id TEXT PRIMARY KEY, filenames_json TEXT NOT NULL, status TEXT NOT NULL,
        page_count INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT, triggered_by TEXT, started_at TEXT NOT NULL, finished_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS evaluations (
        id TEXT PRIMARY KEY, metrics_json TEXT NOT NULL, rows_json TEXT NOT NULL,
        questions_json TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL)""",
]


def connect_database():
    remote_url = current_app.config.get("TURSO_DATABASE_URL")
    auth_token = current_app.config.get("TURSO_AUTH_TOKEN")
    if remote_url:
        if not auth_token:
            raise RuntimeError("TURSO_AUTH_TOKEN is required when TURSO_DATABASE_URL is set")
        try:
            import libsql_experimental as libsql
        except ImportError as error:
            raise RuntimeError("Install libsql-experimental for hosted SQLite persistence") from error
        connection = libsql.connect(remote_url, auth_token=auth_token)
        try:
            connection.row_factory = sqlite3.Row
        except (AttributeError, TypeError):
            pass
        return connection

    path = Path(current_app.config["DATABASE_PATH"]).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect_database()
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database(app):
    with app.app_context():
        connection = connect_database()
        try:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()
