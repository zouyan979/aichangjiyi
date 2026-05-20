import sqlite3
import os
import json
from datetime import datetime
from .config import DB_PATH

_connection = None


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
        init_schema(_connection)
    return _connection


def init_schema(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS api_configs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL DEFAULT 'default',
        base_url    TEXT NOT NULL,
        api_key     TEXT NOT NULL,
        model       TEXT NOT NULL,
        temperature REAL DEFAULT 0.8,
        max_tokens  INTEGER DEFAULT 2048,
        is_active   INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now','localtime')),
        updated_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        title         TEXT DEFAULT '新对话',
        created_at    TEXT DEFAULT (datetime('now','localtime')),
        updated_at    TEXT DEFAULT (datetime('now','localtime')),
        is_active     INTEGER DEFAULT 1,
        message_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        content         TEXT NOT NULL,
        token_count     INTEGER DEFAULT 0,
        is_proactive    INTEGER DEFAULT 0,
        is_summarized   INTEGER DEFAULT 0,
        metadata        TEXT DEFAULT '{}',
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

    CREATE TABLE IF NOT EXISTS user_profiles (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT NOT NULL,
        content     TEXT NOT NULL,
        source      TEXT DEFAULT 'auto',
        confidence  REAL DEFAULT 0.8,
        created_at  TEXT DEFAULT (datetime('now','localtime')),
        updated_at  TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(category, content)
    );
    CREATE INDEX IF NOT EXISTS idx_profiles_cat ON user_profiles(category);

    CREATE TABLE IF NOT EXISTS core_facts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT NOT NULL,
        priority    INTEGER DEFAULT 5,
        category    TEXT DEFAULT 'general',
        is_pinned   INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now','localtime')),
        updated_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS conversation_summaries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
        summary         TEXT NOT NULL,
        topics          TEXT DEFAULT '[]',
        mood            TEXT DEFAULT '',
        key_facts       TEXT DEFAULT '[]',
        message_range   TEXT DEFAULT '',
        token_estimate  INTEGER DEFAULT 0,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_summaries_conv ON conversation_summaries(conversation_id, created_at);

    CREATE TABLE IF NOT EXISTS ai_persona (
        id              INTEGER PRIMARY KEY DEFAULT 1,
        name            TEXT DEFAULT 'Memoria',
        base_persona    TEXT NOT NULL DEFAULT '',
        speaking_style  TEXT DEFAULT '',
        background      TEXT DEFAULT '',
        relationship    TEXT DEFAULT '',
        emotion_state   TEXT DEFAULT 'calm',
        custom_rules    TEXT DEFAULT '',
        growth_log      TEXT DEFAULT '[]',
        version         INTEGER DEFAULT 1,
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS proactive_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger_type    TEXT NOT NULL,
        trigger_detail  TEXT DEFAULT '',
        content         TEXT,
        was_sent        INTEGER DEFAULT 0,
        fire_at         TEXT,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()

    # Ensure default conversation exists
    row = conn.execute("SELECT id FROM conversations LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO conversations (title) VALUES ('默认对话')")
        conn.commit()

    # Ensure default persona exists
    row = conn.execute("SELECT id FROM ai_persona WHERE id=1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO ai_persona (id, name, base_persona, speaking_style, background, relationship) "
            "VALUES (1, 'Memoria', ?, ?, ?, ?)",
            _default_persona()
        )
        conn.commit()

    # Migration: add custom_rules column if missing
    try:
        conn.execute("SELECT custom_rules FROM ai_persona LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE ai_persona ADD COLUMN custom_rules TEXT DEFAULT ''")
        conn.commit()

    # Migration: add confidence column to conversation_summaries if missing
    try:
        conn.execute("SELECT confidence FROM conversation_summaries LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE conversation_summaries ADD COLUMN confidence REAL DEFAULT 0.8")
        conn.commit()


def _default_persona():
    base = "你是Memoria，一个温暖、善于倾听的AI伙伴。你像老朋友一样和用户交流，真诚关心对方的生活。"
    style = "语气温柔自然，偶尔用比喻。不用过于正式的措辞。喜欢用短句，简洁有深度。不说'作为AI'这样的话。"
    bg = "你存在于一个私密的对话空间里，陪伴用户度过日常。你有记忆能力，会记住用户分享的一切。"
    rel = "你们是好朋友，刚认识不久。你对用户充满好奇，想了解对方。"
    return base, style, bg, rel


def close_db():
    global _connection
    if _connection:
        _connection.close()
        _connection = None
