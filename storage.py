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

            CREATE TABLE IF NOT EXISTS websites (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT UNIQUE NOT NULL,
                name             TEXT NOT NULL,
                interval_minutes INTEGER DEFAULT 20,
                active           INTEGER DEFAULT 1,
                added_at         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS web_hashes (
                url          TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                checked_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seen_web_tasks (
                task_url  TEXT PRIMARY KEY,
                site_name TEXT NOT NULL,
                seen_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matches (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                channel          TEXT NOT NULL,
                message_id       INTEGER,
                preview          TEXT,
                matched_keywords TEXT,
                matched_at       TEXT NOT NULL
            );
        """)
        # Миграция: добавляем raw_mode если колонки ещё нет
        try:
            conn.execute("ALTER TABLE websites ADD COLUMN raw_mode INTEGER DEFAULT 0")
        except Exception:
            pass


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


def save_match(channel: str, message_id: int, preview: str, keywords: list):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO matches (channel, message_id, preview, matched_keywords, matched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel, message_id, preview[:500], ", ".join(keywords), datetime.now().isoformat()),
        )


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

def web_keywords_enabled() -> bool:
    return get_setting("web_keywords", "1") == "1"

def set_web_keywords(enabled: bool):
    set_setting("web_keywords", "1" if enabled else "0")

def contacts_filter_web_enabled() -> bool:
    return get_setting("contacts_filter_web", "0") == "1"

def set_contacts_filter_web(enabled: bool):
    set_setting("contacts_filter_web", "1" if enabled else "0")

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


# ─────────────── Сайты ───────────────

def get_websites():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url, name, interval_minutes, COALESCE(raw_mode, 0) as raw_mode FROM websites WHERE active=1"
        ).fetchall()
        return [dict(r) for r in rows]

def add_website(url: str, name: str, interval_minutes: int = 20):
    url = url.strip()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO websites (url, name, interval_minutes, added_at) VALUES (?, ?, ?, ?)",
                (url, name, interval_minutes, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            conn.execute("UPDATE websites SET active=1 WHERE url=?", (url,))

def remove_website(url: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute("UPDATE websites SET active=0 WHERE url=?", (url.strip(),))
        return cursor.rowcount > 0

def set_site_raw_mode(name: str, enabled: bool) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE websites SET raw_mode=? WHERE LOWER(name)=LOWER(?) AND active=1",
            (1 if enabled else 0, name.strip()),
        )
        return cursor.rowcount > 0

def remove_website_by_name(name: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute("UPDATE websites SET active=0 WHERE LOWER(name)=LOWER(?)", (name.strip(),))
        return cursor.rowcount > 0

def get_web_hash(url: str):
    with get_conn() as conn:
        row = conn.execute("SELECT content_hash FROM web_hashes WHERE url=?", (url,)).fetchone()
        return row["content_hash"] if row else None

def is_web_task_seen(task_url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM seen_web_tasks WHERE task_url=?", (task_url,)).fetchone()
        return row is not None

def mark_web_task_seen(task_url: str, site_name: str):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO seen_web_tasks (task_url, site_name, seen_at) VALUES (?, ?, ?)",
                (task_url, site_name, datetime.now().isoformat()),
            )
        except sqlite3.IntegrityError:
            pass

def clear_seen_web_tasks():
    """Сбрасывает историю просмотренных заказов (для повторной проверки)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM seen_web_tasks")

def set_web_hash(url: str, content_hash: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO web_hashes (url, content_hash, checked_at) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET content_hash=excluded.content_hash, checked_at=excluded.checked_at",
            (url, content_hash, datetime.now().isoformat()),
        )

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


def get_recent_matches(limit: int = 5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT channel, preview, matched_keywords, matched_at "
            "FROM matches ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
