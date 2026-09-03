import sqlite3
from datetime import datetime

HISTORY_DB_PATH = "conversation_history.db"


def init_history_db():
    """Creates the persistent history table if it doesn't exist yet."""
    conn = sqlite3.connect(HISTORY_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            db_name TEXT,
            question TEXT,
            sql TEXT,
            summary TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_exchange(db_name: str, question: str, sql: str, summary: str):
    """Persists one Q&A exchange, scoped to whichever database was active —
    so switching databases doesn't mix unrelated conversation histories."""
    conn = sqlite3.connect(HISTORY_DB_PATH)
    conn.execute(
        "INSERT INTO conversation_log (timestamp, db_name, question, sql, summary) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), db_name, question, sql or "", summary or "")
    )
    conn.commit()
    conn.close()


def load_recent_history(db_name: str, limit: int = 5):
    """Returns the most recent `limit` exchanges for a given database,
    oldest first — ready to display or feed into a prompt."""
    conn = sqlite3.connect(HISTORY_DB_PATH)
    cursor = conn.execute(
        "SELECT question, sql, summary FROM conversation_log WHERE db_name = ? ORDER BY id DESC LIMIT ?",
        (db_name, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return list(reversed(rows))


def format_history_for_prompt(history_rows) -> str:
    """Turns saved history rows into text the rewriting step can use to
    resolve follow-up references like 'those', 'it', 'the same but...'."""
    if not history_rows:
        return "(no prior questions this session)"
    lines = []
    for question, sql, summary in history_rows:
        lines.append(f"Q: {question}\nSQL: {sql}\nAnswer: {summary}")
    return "\n\n".join(lines)


def clear_history(db_name: str):
    """Used when the user explicitly wants to reset conversation memory
    for the current database."""
    conn = sqlite3.connect(HISTORY_DB_PATH)
    conn.execute("DELETE FROM conversation_log WHERE db_name = ?", (db_name,))
    conn.commit()
    conn.close()