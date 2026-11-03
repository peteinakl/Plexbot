from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, ensure_data_dirs

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT 'users',
    description TEXT NOT NULL DEFAULT '',
    inherit_shared_history INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
    machine_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owned INTEGER NOT NULL DEFAULT 0,
    owner_name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    access_token TEXT NOT NULL DEFAULT '',
    is_local_conn INTEGER NOT NULL DEFAULT 0,
    is_relay INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    online INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    movie_count INTEGER NOT NULL DEFAULT 0,
    show_count INTEGER NOT NULL DEFAULT 0,
    last_synced_at INTEGER
);

CREATE TABLE IF NOT EXISTS media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT UNIQUE NOT NULL,
    media_type TEXT NOT NULL,
    plex_guid TEXT,
    discover_rating_key TEXT,
    imdb_id TEXT,
    tmdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    tagline TEXT,
    summary TEXT,
    content_rating TEXT,
    duration_min INTEGER,
    critic_rating REAL,
    audience_rating REAL,
    genres_json TEXT NOT NULL DEFAULT '[]',
    directors_json TEXT NOT NULL DEFAULT '[]',
    writers_json TEXT NOT NULL DEFAULT '[]',
    cast_json TEXT NOT NULL DEFAULT '[]',
    countries_json TEXT NOT NULL DEFAULT '[]',
    studios_json TEXT NOT NULL DEFAULT '[]',
    collections_json TEXT NOT NULL DEFAULT '[]',
    poster_server_id TEXT,
    poster_path TEXT,
    poster_url_external TEXT,
    art_path TEXT,
    is_watched INTEGER NOT NULL DEFAULT 0,
    max_view_count INTEGER NOT NULL DEFAULT 0,
    max_user_rating REAL,
    leaf_count INTEGER NOT NULL DEFAULT 0,
    viewed_leaf_count INTEGER NOT NULL DEFAULT 0,
    max_progress_ratio REAL NOT NULL DEFAULT 0.0,
    is_abandoned INTEGER NOT NULL DEFAULT 0,
    last_viewed_at INTEGER,
    latest_added_at INTEGER,
    on_watchlist INTEGER NOT NULL DEFAULT 0,
    is_external_only INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_media_type ON media_items(media_type);
CREATE INDEX IF NOT EXISTS idx_media_watched ON media_items(is_watched);
CREATE INDEX IF NOT EXISTS idx_media_discover_rk ON media_items(discover_rating_key);
CREATE INDEX IF NOT EXISTS idx_media_external ON media_items(is_external_only);

CREATE TABLE IF NOT EXISTS media_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    machine_id TEXT NOT NULL REFERENCES servers(machine_id) ON DELETE CASCADE,
    rating_key TEXT NOT NULL,
    section_id TEXT NOT NULL DEFAULT '',
    section_title TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    video_codec TEXT NOT NULL DEFAULT '',
    hdr INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    view_offset_ms INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    viewed_leaf_count INTEGER NOT NULL DEFAULT 0,
    leaf_count INTEGER NOT NULL DEFAULT 0,
    user_rating REAL,
    last_viewed_at INTEGER,
    added_at INTEGER,
    UNIQUE(machine_id, rating_key)
);

CREATE INDEX IF NOT EXISTS idx_sources_media ON media_sources(media_id);
CREATE INDEX IF NOT EXISTS idx_sources_machine ON media_sources(machine_id);

CREATE TABLE IF NOT EXISTS taste_feedback (
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    sentiment TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (profile_id, media_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_profile ON taste_feedback(profile_id);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""

DEFAULT_PROFILES = [
    (
        "together",
        "Us Together",
        "users",
        "Blends your shared Plex history with things you both enjoy",
        1,
    ),
    (
        "me",
        "Just Me",
        "user",
        "Your personal solo picks — thumbs-down anything watched by others",
        1,
    ),
    (
        "partner",
        "Partner / Family",
        "sparkles",
        "Separate taste tuning layer on top of your shared account",
        1,
    ),
]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    ensure_data_dirs()
    target = db_path or DB_PATH
    conn = sqlite3.connect(str(target), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    target = db_path or DB_PATH
    with db_session(target) as conn:
        conn.executescript(SCHEMA_SQL)
        now = int(time.time())
        for pid, name, icon, desc, inherit in DEFAULT_PROFILES:
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (id, name, icon, description, inherit_shared_history, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pid, name, icon, desc, inherit, now),
            )
        # Ensure persistent Plex client identifier
        row = conn.execute("SELECT value FROM settings WHERE key = 'plex_client_id'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("plex_client_id", f"plexbot-{uuid.uuid4()}", now),
            )

        # Hydrate API keys from environment variables if not already stored
        env_defaults = {
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        }
        for key, val in env_defaults.items():
            if val:
                existing = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                if not existing or not existing["value"]:
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                        (key, val, now),
                    )

        # Auto-select an active LLM provider if a key was provided via env and none chosen yet
        prov_row = conn.execute("SELECT value FROM settings WHERE key = 'llm_provider'").fetchone()
        if not prov_row:
            default_prov = "none"
            if env_defaults["gemini_api_key"]:
                default_prov = "gemini"
            elif env_defaults["anthropic_api_key"]:
                default_prov = "anthropic"
            elif env_defaults["openai_api_key"]:
                default_prov = "openai"
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("llm_provider", default_prov, now),
            )

    try:
        if target.exists():
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def get_setting(key: str, default: str = "", db_path: Path | None = None) -> str:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def get_all_settings(db_path: Path | None = None) -> dict[str, str]:
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str, db_path: Path | None = None) -> None:
    now = int(time.time())
    with db_session(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )


def set_settings_bulk(values: dict[str, str], db_path: Path | None = None) -> None:
    now = int(time.time())
    with db_session(db_path) as conn:
        for k, v in values.items():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (k, v, now),
            )


def json_loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed if x] if isinstance(parsed, list) else []
    except Exception:
        return []


def hydrate_media_row(
    row: sqlite3.Row | dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    feedback_sentiment: str | None = None,
) -> dict[str, Any]:
    d = dict(row)
    src_list = sources or []
    # Sort sources: owned local servers first, then highest resolution, then lowest latency
    res_rank = {"4K": 4, "1080p": 3, "720p": 2, "SD": 1, "": 0}
    src_list_sorted = sorted(
        src_list,
        key=lambda s: (
            int(s.get("owned", 0)),
            res_rank.get(s.get("resolution", ""), 0),
            -int(s.get("latency_ms", 9999)),
        ),
        reverse=True,
    )
    primary_source = src_list_sorted[0] if src_list_sorted else None

    return {
        "id": d["id"],
        "canonical_key": d["canonical_key"],
        "media_type": d["media_type"],
        "plex_guid": d.get("plex_guid"),
        "discover_rating_key": d.get("discover_rating_key"),
        "imdb_id": d.get("imdb_id"),
        "tmdb_id": d.get("tmdb_id"),
        "title": d["title"],
        "original_title": d.get("original_title"),
        "year": d.get("year"),
        "tagline": d.get("tagline") or "",
        "summary": d.get("summary") or "",
        "content_rating": d.get("content_rating") or "",
        "duration_min": d.get("duration_min"),
        "critic_rating": d.get("critic_rating"),
        "audience_rating": d.get("audience_rating"),
        "genres": json_loads_list(d.get("genres_json")),
        "directors": json_loads_list(d.get("directors_json")),
        "writers": json_loads_list(d.get("writers_json")),
        "cast": json_loads_list(d.get("cast_json")),
        "countries": json_loads_list(d.get("countries_json")),
        "studios": json_loads_list(d.get("studios_json")),
        "collections": json_loads_list(d.get("collections_json")),
        "poster_url": f"/api/poster/{d['id']}" if (d.get("poster_path") or d.get("poster_url_external")) else None,
        "is_watched": bool(d.get("is_watched")),
        "max_view_count": int(d.get("max_view_count") or 0),
        "max_user_rating": d.get("max_user_rating"),
        "leaf_count": int(d.get("leaf_count") or 0),
        "viewed_leaf_count": int(d.get("viewed_leaf_count") or 0),
        "max_progress_ratio": float(d.get("max_progress_ratio") or 0.0),
        "is_abandoned": bool(d.get("is_abandoned")),
        "last_viewed_at": d.get("last_viewed_at"),
        "latest_added_at": d.get("latest_added_at"),
        "on_watchlist": bool(d.get("on_watchlist")),
        "is_external_only": bool(d.get("is_external_only")),
        "sources": src_list_sorted,
        "primary_source": primary_source,
        "feedback": feedback_sentiment,
    }
