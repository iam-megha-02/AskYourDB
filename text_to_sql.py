import os
import streamlit as st
import re
import time
import sqlite3
from langchain_community.utilities import SQLDatabase
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

def get_secret(key: str) -> str:
    """Works both locally (.env) and on Streamlit Cloud (st.secrets)."""
    if key in os.environ:
        return os.environ[key]
    try:
        return st.secrets[key]
    except Exception:
        raise RuntimeError(f"{key} not found in environment or Streamlit secrets.")

GROQ_API_KEY = get_secret("GROQ_API_KEY")

DB_PATH = "ecommerce.db"

VALID_TYPES = [
    "INTEGER", "TEXT", "REAL", "BLOB",
    "VARCHAR(255)", "DATE", "DATETIME", "BOOLEAN", "NUMERIC", "FLOAT"
]

VALID_SQL_STARTS = {"SELECT", "DELETE", "UPDATE", "INSERT", "WITH"}


# ---------------- Structured output schema ----------------

class SQLGenerationResult(BaseModel):
    """SQL arrives as a validated field, not free text requiring markdown/
    prefix parsing — this replaces the old create_sql_query_chain + regex
    clean_sql() approach with LangChain's structured output."""
    sql: str = Field(
        description="A single syntactically correct SQLite statement that answers "
                    "the question. No markdown formatting, no explanation — just the SQL."
    )
    reasoning: str = Field(
        description="One brief sentence explaining why this query answers the question."
    )


CUSTOM_SUFFIX = """
When a question asks for "the most", "the highest", "the top", or similar
superlative phrasing, use RANK() OVER (ORDER BY <metric> DESC) and filter
WHERE rank = 1, instead of ORDER BY ... LIMIT 1. This ensures ties are
returned together rather than picking one arbitrarily.

Only use a plain LIMIT when the user explicitly asks for a specific count
(e.g. "top 5", "the first 3").

When counting how many groups satisfy a HAVING condition (e.g. "how many
customers ordered from more than 3 categories"), do NOT try to count within
each group. Instead, wrap the grouped query in an outer SELECT COUNT(*)
FROM (...) around the qualifying groups.

Window functions (RANK, ROW_NUMBER, etc.) cannot be filtered directly in a
WHERE or HAVING clause in the same query where they are calculated. Always
compute the window function in a subquery or CTE first, then filter on it
in an outer query.
"""

SQL_PROMPT_TEMPLATE = """You are a SQLite expert. Given an input question, create a
syntactically correct SQLite query to answer it, then explain briefly why it answers
the question.

Unless the question specifies a number of results, do not add an arbitrary LIMIT —
only limit results when the question implies a specific count (e.g. "top 5").
Never select all columns — only the ones needed to answer the question.
Wrap column names in double quotes to denote them as delimited identifiers.
Use only the column names visible in the schema below — do not invent columns.
Use date('now') for "today" if the question involves the current date.

{custom_suffix}

Recent conversation history (use this to resolve follow-up references like
"those", "it", "the same but...", or an implicit filter continuing a prior
question — ignore it if the current question is fully self-contained):
{conversation_history}

Only use the following tables:
{table_info}

Question: {question}"""


# ---------------- Model/chain setup ----------------

def build_sql_chain(target_db):
    """Structured-output SQL generation chain, replacing the previous
    create_sql_query_chain + regex-based clean_sql() approach."""
    table_info = target_db.get_table_info()

    prompt = ChatPromptTemplate.from_template(SQL_PROMPT_TEMPLATE)
    structured_llm = llm.with_structured_output(SQLGenerationResult)

    return prompt.partial(custom_suffix=CUSTOM_SUFFIX, table_info=table_info) | structured_llm


db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, groq_api_key=GROQ_API_KEY)
summarizer_llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, groq_api_key=GROQ_API_KEY)

sql_chain = build_sql_chain(db)


# ---------------- Database switching (sample DB vs. user-uploaded) ----------------

def load_database(path: str):
    """Point the app at a different SQLite file — used when the user uploads their own .db."""
    global db, sql_chain, DB_PATH
    DB_PATH = path
    db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
    sql_chain = build_sql_chain(db)


def is_valid_sqlite_file(path: str) -> bool:
    """Sanity-check the uploaded file is actually a SQLite database, not just
    something renamed .db — avoids a confusing failure later on first query."""
    try:
        conn = sqlite3.connect(path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


# ---------------- SQL cleanup / validation ----------------

def clean_sql(sql_text):
    """Light normalization for structured-output SQL. Markdown fences aren't
    expected anymore (the model fills a typed field, not free text) but we
    defensively strip them anyway, then confirm the result actually starts
    with a real SQL keyword rather than a refusal stuffed into the field."""
    if not sql_text or not sql_text.strip():
        return None

    text = sql_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:sql)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    if not text:
        return None

    first_word = text.split()[0].upper() if text.split() else ""
    if first_word not in VALID_SQL_STARTS:
        return None

    return text.strip().strip(";") + ";"


def references_real_schema(query: str, target_db: SQLDatabase) -> bool:
    real_tables = [t.lower() for t in target_db.get_usable_table_names()]
    return any(table in query.lower() for table in real_tables)


def get_query_type(sql: str) -> str:
    """Checks for write keywords ANYWHERE in the query, not just the first word."""
    upper_sql = sql.upper()
    for keyword in ("DELETE", "UPDATE", "INSERT"):
        if keyword in upper_sql:
            return keyword
    return "READ"


def has_where_clause(sql: str) -> bool:
    return "WHERE" in sql.upper()


def is_forbidden_structural(sql: str) -> bool:
    """Never allowed via the LLM path, no confirmation can override these."""
    forbidden = ["DROP", "TRUNCATE", "ALTER", "CREATE"]
    upper_sql = sql.upper()
    return any(word in upper_sql for word in forbidden)


def is_safe_write(sql: str, query_type: str):
    """Returns (is_safe, reason_if_blocked)."""
    if query_type in ("DELETE", "UPDATE") and not has_where_clause(sql):
        return False, f"{query_type} with no WHERE clause would affect the ENTIRE table — blocked."
    return True, ""


def describe_write(sql: str, query_type: str) -> str:
    prompt = f"""In one short, plain sentence, describe what this SQL query will do.
Be specific about which rows are affected (mention actual values/conditions from the WHERE clause if present).
SQL: {sql}"""
    return summarizer_llm.invoke(prompt).content


# ---------------- Core generation + validation (single attempt) ----------------

def generate_sql(question: str, conversation_history: str = ""):
    """One LLM call + cleaning + guardrail checks. Does NOT execute anything.
    Returns (sql, query_type, block_reason):
      - block_reason is None and query_type is set  -> safe to proceed
      - block_reason is set                          -> caller should stop and show it
    """
    try:
        result = sql_chain.invoke({"question": question, "conversation_history": conversation_history})
    except Exception as e:
        return None, None, f"LLM call failed: {e}"

    if not result or not result.sql:
        return None, None, "Model did not return SQL."

    sql = clean_sql(result.sql)
    if sql is None:
        return None, None, "Model declined to generate valid SQL for this question."

    if is_forbidden_structural(sql):
        return sql, None, "That would alter the database structure — not allowed."

    if not references_real_schema(sql, db):
        return sql, None, "Generated query didn't reference real data — blocked."

    return sql, get_query_type(sql), None


# ---------------- Retry-on-real-error (READ queries only) ----------------

def execute_read_with_retry(question: str, conversation_history: str = "", max_retries: int = 2):
    """Generates and executes a READ query. If execution fails with a real
    database error, feeds that error back to the model and retries with a
    corrected query — bounded, not infinite. Writes are handed back to the
    caller unexecuted, for the confirmation flow instead.

    Returns a dict with a 'status' field:
      'success'   -> columns, rows, sql, attempts
      'blocked'   -> sql (maybe None), reason
      'not_read'  -> sql, query_type (caller routes to write-confirmation UI)
      'failed'    -> sql, reason (exhausted retries)
    """
    current_question = question
    last_sql = None
    last_error = None

    for attempt in range(max_retries + 1):
        sql, query_type, block_reason = generate_sql(current_question, conversation_history)
        last_sql = sql

        if block_reason:
            return {"status": "blocked", "sql": sql, "reason": block_reason}

        if query_type != "READ":
            return {"status": "not_read", "sql": sql, "query_type": query_type}

        try:
            columns, rows = run_query_with_columns(sql)
            return {
                "status": "success", "sql": sql, "columns": columns,
                "rows": rows, "attempts": attempt + 1
            }
        except Exception as e:
            last_error = str(e)
            print(f"Attempt {attempt + 1} failed: {last_error}. Retrying with error feedback...")
            current_question = (
                f"{question}\n\n"
                f"(A previous attempt generated this SQL, which failed:\n{sql}\n"
                f"Database error: {last_error}\nPlease generate a corrected query that fixes this.)"
            )

    return {
        "status": "failed", "sql": last_sql,
        "reason": f"Failed after {max_retries + 1} attempts. Last error: {last_error}"
    }


# ---------------- Create-table intent + form-driven DDL ----------------

def is_create_table_request(text: str) -> bool:
    """Deterministic keyword check — deliberately not LLM-based, so this
    is predictable rather than varying run to run."""
    text_lower = text.lower()
    triggers = ["create a table", "create table", "new table", "add a table", "make a table"]
    return any(trigger in text_lower for trigger in triggers)


def is_valid_identifier(name: str) -> bool:
    """Only letters, numbers, underscores — no spaces, quotes, semicolons, etc."""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def build_create_table_sql(table_name: str, columns: list) -> str:
    """columns = [{'name': str, 'type': str, 'is_pk': bool,
                    'fk_table': str|None, 'fk_column': str|None}, ...]"""
    if not is_valid_identifier(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    col_defs = []
    fk_defs = []
    for col in columns:
        if not is_valid_identifier(col["name"]):
            raise ValueError(f"Invalid column name: {col['name']}")
        if col["type"] not in VALID_TYPES:
            raise ValueError(f"Invalid type: {col['type']}")

        line = f'"{col["name"]}" {col["type"]}'
        if col["is_pk"]:
            line += " PRIMARY KEY"
        col_defs.append(line)

        if col.get("fk_table") and col.get("fk_column"):
            fk_defs.append(
                f'FOREIGN KEY ("{col["name"]}") REFERENCES "{col["fk_table"]}"("{col["fk_column"]}")'
            )

    all_defs = col_defs + fk_defs
    return f'CREATE TABLE "{table_name}" (\n    ' + ",\n    ".join(all_defs) + "\n);"


def refresh_schema():
    """Re-sync LangChain's SQLDatabase after a schema change — it caches
    table metadata at init and won't see new tables otherwise."""
    global db, sql_chain
    db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
    sql_chain = build_sql_chain(db)


# ---------------- Schema introspection ----------------

def get_schema_details():
    """Returns {table_name: {'columns': [(name, type, is_pk)], 'foreign_keys': [(col, ref_table, ref_col)]}}"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tables = [row[0] for row in cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]

    schema = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [(row[1], row[2], bool(row[5])) for row in cursor.fetchall()]

        cursor.execute(f"PRAGMA foreign_key_list({table})")
        fks = [(row[3], row[2], row[4]) for row in cursor.fetchall()]

        schema[table] = {"columns": columns, "foreign_keys": fks}

    conn.close()
    return schema


# ---------------- Result fetching with real column names ----------------

def run_query_with_columns(sql: str):
    """Execute SQL directly and return (column_names, rows) — gives us
    real headers for a proper results table, which db.run() doesn't expose."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    rows = cursor.fetchall()
    conn.commit()
    conn.close()
    return columns, rows


# ---------------- Headless usage (scripts / eval_set.py) ----------------

def ask_question(question: str, retries: int = 2):
    """Read-only, headless usage — thin wrapper around execute_read_with_retry,
    kept for eval_set.py's existing call signature (expects a string result)."""
    outcome = execute_read_with_retry(question, conversation_history="", max_retries=retries)

    if outcome["status"] == "success":
        print("Generated SQL:", outcome["sql"])
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(outcome["sql"])
            return str(cursor.fetchall())
        finally:
            conn.close()
    else:
        print(f"[{outcome['status']}] {outcome.get('reason', outcome.get('query_type'))}")
        return None