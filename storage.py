"""
Работа с базой данных (SQLite).
Хранит: просмотренные сообщения, список каналов, ключевые слова, историю находок.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/bot.db")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы если их нет."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel    TEXT    NOT NULL,
                message_id INTEGER NOT NULL,
                seen_at    TEXT    NOT NULL,
                UNIQUE(channel, message_id)
            );

            CREATE TABLE IF NOT EXISTS channels (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                channel  TEXT UNIQUE NOT NULL,
                active   INTEGER DEFAULT 1,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword  TEXT UNIQUE NOT NULL,
                active   INTEGER DEFAULT 1,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS excluded_keywords (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword  TEXT UNIQUE NOT NULL,
                active   INTEGER DEFAULT 1,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matches (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                channel          TEXT NOT NULL,
                message_id       INTEGER,
                preview          TEXT,
                matched_keywords TEXT,
                matched_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS spam_marks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id   INTEGER,
                channel    TEXT,
                keywords   TEXT,
                preview    TEXT,
                marked_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS youdo_seen_tasks (
                task_id  TEXT PRIMARY KEY,
                seen_at  TEXT NOT NULL
            );
        """)


# ─────────────── Просмотренные сообщения ───────────────

def is_seen(channel: str, message_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_messages WHERE channel=? AND message_id=?",
            (channel, message_id),
        ).fetchone()
        return row is not None


def mark_seen(channel: str, message_id: int):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO seen_messages (channel, message_id, seen_at) VALUES (?, ?, ?)",
                (channel, message_id, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            pass


def save_match(channel: str, message_id: int, preview: str, keywords: list) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO matches (channel, message_id, preview, matched_keywords, matched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel, message_id, preview[:500], ", ".join(keywords), datetime.now().isoformat()),
        )
        return cursor.lastrowid


# ─────────────── Каналы ───────────────

def get_channels():
    with get_conn() as conn:
        rows = conn.execute("SELECT channel FROM channels WHERE active=1").fetchall()
        return [r["channel"] for r in rows]


def add_channel(channel: str):
    channel = channel.strip()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO channels (channel, added_at) VALUES (?, ?)",
                (channel, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            conn.execute("UPDATE channels SET active=1 WHERE channel=?", (channel,))


def remove_channel(channel: str) -> bool:
    channel = channel.strip()
    with get_conn() as conn:
        cursor = conn.execute("UPDATE channels SET active=0 WHERE channel=?", (channel,))
        return cursor.rowcount > 0


# ─────────────── Ключевые слова ───────────────

def get_keywords():
    with get_conn() as conn:
        rows = conn.execute("SELECT keyword FROM keywords WHERE active=1").fetchall()
        return [r["keyword"] for r in rows]


def add_keyword(keyword: str):
    keyword = keyword.strip().lower()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO keywords (keyword, added_at) VALUES (?, ?)",
                (keyword, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            conn.execute("UPDATE keywords SET active=1 WHERE keyword=?", (keyword,))


def remove_keyword(keyword: str) -> bool:
    keyword = keyword.strip().lower()
    with get_conn() as conn:
        cursor = conn.execute("UPDATE keywords SET active=0 WHERE keyword=?", (keyword,))
        return cursor.rowcount > 0

def clear_keywords() -> int:
    with get_conn() as conn:
        cursor = conn.execute("UPDATE keywords SET active=0 WHERE active=1")
        return cursor.rowcount


# ─────────────── Настройки ───────────────

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

def contacts_filter_tg_enabled() -> bool:
    return get_setting("contacts_filter_tg", "0") == "1"

def set_contacts_filter_tg(enabled: bool):
    set_setting("contacts_filter_tg", "1" if enabled else "0")


# ─────────────── Слова-исключения ───────────────

def get_excluded_keywords():
    with get_conn() as conn:
        rows = conn.execute("SELECT keyword FROM excluded_keywords WHERE active=1").fetchall()
        return [r["keyword"] for r in rows]

def add_excluded_keyword(keyword: str):
    keyword = keyword.strip().lower()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO excluded_keywords (keyword, added_at) VALUES (?, ?)",
                (keyword, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            conn.execute("UPDATE excluded_keywords SET active=1 WHERE keyword=?", (keyword,))

def remove_excluded_keyword(keyword: str) -> bool:
    keyword = keyword.strip().lower()
    with get_conn() as conn:
        cursor = conn.execute("UPDATE excluded_keywords SET active=0 WHERE keyword=?", (keyword,))
        return cursor.rowcount > 0


# ─────────────── Статистика ───────────────

def get_stats() -> dict:
    with get_conn() as conn:
        total_seen = conn.execute("SELECT COUNT(*) as c FROM seen_messages").fetchone()["c"]
        total_matches = conn.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
        today = datetime.now().strftime("%Y-%m-%d")
        today_matches = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE matched_at LIKE ?",
            (f"{today}%",),
        ).fetchone()["c"]
        return {
            "total_seen": total_seen,
            "total_matches": total_matches,
            "today_matches": today_matches,
        }


def get_matches_since(hours: float):
    from datetime import timedelta
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, message_id, preview, matched_keywords, matched_at "
            "FROM matches WHERE matched_at >= ? ORDER BY matched_at DESC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_spam(match_id: int, channel: str, keywords: str, preview: str):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO spam_marks (match_id, channel, keywords, preview, marked_at) VALUES (?, ?, ?, ?, ?)",
                (match_id, channel, keywords, preview[:500], datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            pass

def get_spam_entries() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_id, channel, keywords, preview, marked_at FROM spam_marks ORDER BY marked_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

def get_match_by_id(match_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT channel, matched_keywords, preview FROM matches WHERE id=?", (match_id,)
        ).fetchone()
        return dict(row) if row else {}


# ─────────────── YouDo задания ───────────────

def has_youdo_seen_any() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM youdo_seen_tasks LIMIT 1").fetchone()
        return row is not None


def is_youdo_seen(task_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM youdo_seen_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return row is not None


def mark_youdo_seen(task_id: str):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO youdo_seen_tasks (task_id, seen_at) VALUES (?, ?)",
                (task_id, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            pass


def get_recent_matches(limit: int = 5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, preview, matched_keywords, matched_at "
            "FROM matches ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
