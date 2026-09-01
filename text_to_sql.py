import os
import streamlit as st
import re
import time
import sqlite3
from langchain_community.utilities import SQLDatabase
from langchain_groq import ChatGroq
from langchain.chains import create_sql_query_chain
from langchain_core.prompts import PromptTemplate
from langchain.chains.sql_database.prompt import SQL_PROMPTS
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "ecommerce.db"

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
def build_sql_chain(target_db):
    """Builds the SQL generation chain with our custom instructions inserted
    BEFORE the format/question section of LangChain's default SQLite prompt —
    appending after {input} would place instructions after the question,
    where the model is already expected to start answering."""
    base_prompt = SQL_PROMPTS["sqlite"]
    marker = "Use the following format:"
    original_template = base_prompt.template

    if marker in original_template:
        before, after = original_template.split(marker, 1)
        new_template = before + CUSTOM_SUFFIX + "\n" + marker + after
    else:
        # Fallback: prepend at the very start if the expected marker isn't found
        new_template = CUSTOM_SUFFIX + "\n" + original_template

    custom_prompt = PromptTemplate(
        input_variables=base_prompt.input_variables,
        template=new_template,
    )
    return create_sql_query_chain(llm, target_db, prompt=custom_prompt)

db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, groq_api_key=GROQ_API_KEY)
summarizer_llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0)

sql_chain = build_sql_chain(db)

VALID_TYPES = [
    "INTEGER", "TEXT", "REAL", "BLOB",
    "VARCHAR(255)", "DATE", "DATETIME", "BOOLEAN", "NUMERIC", "FLOAT"
]


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

def clean_sql(raw_output: str):
    """Extract just the SQL from the LLM's raw output. Returns None if
    the model responded in plain English instead of SQL."""
    if "SQLQuery:" in raw_output:
        raw_output = raw_output.split("SQLQuery:")[-1]
    raw_output = raw_output.strip()
    if raw_output.startswith("```"):
        raw_output = re.sub(r"^```(?:sql)?\s*", "", raw_output)
        raw_output = re.sub(r"\s*```$", "", raw_output)
    raw_output = raw_output.strip()
    if not raw_output or raw_output.lower().startswith(("answer:", "i cannot", "the provided")):
        return None
    return raw_output.strip().strip(";") + ";"


def references_real_schema(query: str, db: SQLDatabase) -> bool:
    real_tables = [t.lower() for t in db.get_usable_table_names()]
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
        columns = [(row[1], row[2], bool(row[5])) for row in cursor.fetchall()]  # name, type, is_pk

        cursor.execute(f"PRAGMA foreign_key_list({table})")
        fks = [(row[3], row[2], row[4]) for row in cursor.fetchall()]  # from_col, to_table, to_col

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
    """Read-only, headless usage — writes stay fully blocked here,
    since there's no confirmation UI outside the Streamlit app."""
    for attempt in range(retries + 1):
        try:
            raw_sql = sql_chain.invoke({"question": question})
        except Exception as e:
            print("ERROR calling LLM:", e)
            return None
        if raw_sql.strip():
            break
        print(f"Empty output (attempt {attempt + 1}/{retries + 1}), retrying...")
        time.sleep(3)
    else:
        print("LLM returned empty output after retries.")
        return None

    print("RAW OUTPUT:", repr(raw_sql))
    sql = clean_sql(raw_sql)
    if sql is None:
        print("Model declined to generate SQL.")
        return None
    print("Generated SQL:", sql)

    if is_forbidden_structural(sql) or get_query_type(sql) != "READ":
        print("Blocked: this is a script context with no confirmation flow — writes not allowed here.")
        return None

    if not references_real_schema(sql, db):
        print("Query doesn't reference any real table — blocked.")
        return None

    try:
        return db.run(sql)
    except Exception as e:
        print("ERROR executing SQL:", e)
        return None

def get_secret(key: str) -> str:
    """Works both locally (.env) and on Streamlit Cloud (st.secrets)."""
    if key in os.environ:
        return os.environ[key]
    try:
        return st.secrets[key]
    except Exception:
        raise RuntimeError(f"{key} not found in environment or Streamlit secrets.")

GROQ_API_KEY = get_secret("GROQ_API_KEY")