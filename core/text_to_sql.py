import os
import streamlit as st
import re
import time
import sqlite3
from sqlglot import exp, parse
from sqlglot.errors import ParseError
from langchain_community.utilities import SQLDatabase
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

def get_secret(key: str) -> str:
    if key in os.environ:
        return os.environ[key]
    try:
        return st.secrets[key]
    except Exception:
        raise RuntimeError(f"{key} not found in environment or Streamlit secrets.")

GROQ_API_KEY = get_secret("GROQ_API_KEY")

DB_PATH = "data/ecommerce.db"

VALID_TYPES = [
    "INTEGER", "TEXT", "REAL", "BLOB",
    "VARCHAR(255)", "DATE", "DATETIME", "BOOLEAN", "NUMERIC", "FLOAT"
]

VALID_SQL_STARTS = {"SELECT", "DELETE", "UPDATE", "INSERT", "WITH"}


# ---------------- Connection helper (enforces foreign keys) ----------------

def get_connection():
    """All writes should go through this — SQLite has foreign key enforcement
    OFF by default per connection, so without this, an insert/update could
    silently reference a row that doesn't exist in the parent table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------- Structured output schema (SQL generation) ----------------

class SQLGenerationResult(BaseModel):
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

Only use the following tables:
{table_info}

Question: {question}"""


class RewrittenQuestion(BaseModel):
    standalone_question: str = Field(
        description="The user's question, rewritten to be fully self-contained — resolve any "
                    "pronoun or implicit reference (e.g. 'they', 'those', 'the same') using the "
                    "conversation history. If the question is already self-contained, return it "
                    "unchanged."
    )
    was_rewritten: bool = Field(
        description="True if the question actually contained a reference that needed resolving, "
                    "False if it was already self-contained and returned unchanged."
    )


REWRITE_PROMPT_TEMPLATE = """Given this conversation history and a follow-up question, rewrite the
follow-up into a fully self-contained, standalone question — resolve any pronoun or implicit
reference using the history. If the question doesn't reference anything from the history, return
it exactly as given.

Conversation history:
{conversation_history}

Follow-up question: {question}"""


def build_sql_chain(target_db):
    table_info = target_db.get_table_info()
    prompt = ChatPromptTemplate.from_template(SQL_PROMPT_TEMPLATE)
    structured_llm = llm.with_structured_output(SQLGenerationResult)
    return prompt.partial(custom_suffix=CUSTOM_SUFFIX, table_info=table_info) | structured_llm


db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, groq_api_key=GROQ_API_KEY)
summarizer_llm = ChatGroq(model="qwen/qwen3.8-27b", temperature=0, groq_api_key=GROQ_API_KEY)

sql_chain = build_sql_chain(db)


def load_database(path: str):
    global db, sql_chain, DB_PATH
    DB_PATH = path
    db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
    sql_chain = build_sql_chain(db)


def is_valid_sqlite_file(path: str) -> bool:
    try:
        conn = sqlite3.connect(path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


def clean_sql(sql_text):
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

    sql = text.strip().strip(";") + ";"
    return sql if parse_sql_statement(sql) is not None else None


def parse_sql_statement(sql: str):
    """Returns one SQLite SQL AST, or None when parsing fails or the input has multiple statements."""
    try:
        statements = parse(sql, read="sqlite")
    except ParseError:
        return None

    return statements[0] if len(statements) == 1 else None


def _extract_sql_and_reasoning(result):
    if isinstance(result, dict):
        return result.get("sql"), result.get("reasoning", "")
    return getattr(result, "sql", None), getattr(result, "reasoning", "")


def _extract_rewrite(result, fallback_question: str):
    if isinstance(result, dict):
        return result.get("standalone_question", fallback_question), result.get("was_rewritten", False)
    return (
        getattr(result, "standalone_question", fallback_question),
        getattr(result, "was_rewritten", False)
    )


def references_real_schema(query: str, target_db: SQLDatabase) -> bool:
    statement = parse_sql_statement(query)
    if statement is None:
        return False

    real_tables = {table.lower() for table in target_db.get_usable_table_names()}
    referenced_tables = {table.name.lower() for table in statement.find_all(exp.Table)}
    return bool(real_tables & referenced_tables)


def get_query_type(sql: str) -> str:
    """Classifies a parsed SQL statement by its AST node type."""
    statement = parse_sql_statement(sql)
    if statement is None:
        return "UNKNOWN"
    if isinstance(statement, exp.Delete):
        return "DELETE"
    if isinstance(statement, exp.Update):
        return "UPDATE"
    if isinstance(statement, exp.Insert):
        return "INSERT"
    if isinstance(statement, exp.Query):
        return "READ"
    return "UNKNOWN"


def has_where_clause(sql: str) -> bool:
    statement = parse_sql_statement(sql)
    return statement is not None and statement.args.get("where") is not None


def is_forbidden_structural(sql: str) -> bool:
    statement = parse_sql_statement(sql)
    return isinstance(statement, (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable))


def is_safe_write(sql: str, query_type: str):
    if query_type in ("DELETE", "UPDATE") and not has_where_clause(sql):
        return False, f"{query_type} with no WHERE clause would affect the ENTIRE table — blocked."
    return True, ""


def describe_write(sql: str, query_type: str) -> str:
    prompt = f"""In one short, plain sentence, describe what this SQL query will do.
Be specific about which rows are affected (mention actual values/conditions from the WHERE clause if present).
SQL: {sql}"""
    try:
        return summarizer_llm.invoke(prompt).content
    except Exception:
        return f"This will run a {query_type.lower()} statement."


def rewrite_question(question: str, conversation_history: str):
    if not conversation_history or conversation_history.strip() == "(no prior questions this session)":
        return question, False

    prompt = ChatPromptTemplate.from_template(REWRITE_PROMPT_TEMPLATE)
    rewriter = llm.with_structured_output(RewrittenQuestion)
    chain = prompt | rewriter

    try:
        result = chain.invoke({"question": question, "conversation_history": conversation_history})
    except Exception:
        return question, False

    return _extract_rewrite(result, question)


def generate_sql(question: str):
    try:
        result = sql_chain.invoke({"question": question})
    except Exception as e:
        return None, None, f"LLM call failed: {e}"

    if not result:
        return None, None, "Model did not return SQL."

    raw_sql, reasoning = _extract_sql_and_reasoning(result)
    if not raw_sql:
        return None, None, "Model returned no SQL."

    sql = clean_sql(raw_sql)
    if sql is None:
        return None, None, "Model declined to generate valid SQL for this question."

    if is_forbidden_structural(sql):
        return sql, None, "That would alter the database structure — not allowed."

    if not references_real_schema(sql, db):
        return sql, None, "Generated query didn't reference real data — blocked."

    query_type = get_query_type(sql)
    if query_type == "UNKNOWN":
        return sql, None, "Generated query type is not allowed."

    return sql, query_type, None


def execute_read_with_retry(question: str, conversation_history: str = "", max_retries: int = 2):
    standalone_question, was_rewritten = rewrite_question(question, conversation_history)
    current_question = standalone_question
    last_sql = None
    last_error = None

    for attempt in range(max_retries + 1):
        sql, query_type, block_reason = generate_sql(current_question)
        last_sql = sql

        if block_reason:
            return {"status": "blocked", "sql": sql, "reason": block_reason}

        if query_type != "READ":
            return {"status": "not_read", "sql": sql, "query_type": query_type}

        try:
            columns, rows = run_query_with_columns(sql)
            return {
                "status": "success", "sql": sql, "columns": columns,
                "rows": rows, "attempts": attempt + 1,
                "rewritten_question": standalone_question if was_rewritten else None
            }
        except Exception as e:
            last_error = str(e)
            print(f"Attempt {attempt + 1} failed: {last_error}. Retrying with error feedback...")
            current_question = (
                f"{current_question}\n\n"
                f"(A previous attempt generated this SQL, which failed:\n{sql}\n"
                f"Database error: {last_error}\nPlease generate a corrected query that fixes this.)"
            )

    return {
        "status": "failed", "sql": last_sql,
        "reason": f"Failed after {max_retries + 1} attempts. Last error: {last_error}"
    }


# ---------------- Intent detection (deterministic keyword checks) ----------------

def is_create_table_request(text: str) -> bool:
    text_lower = text.lower()
    triggers = ["create a table", "create table", "new table", "add a table", "make a table"]
    return any(trigger in text_lower for trigger in triggers)


def is_insert_request(text: str) -> bool:
    text_lower = text.lower()
    triggers = [
        "add data", "insert data", "add a row", "insert a row",
        "add an entry", "insert an entry", "add a record", "insert a record",
        "add data to", "insert into"
    ]
    return any(trigger in text_lower for trigger in triggers)


def is_update_request(text: str) -> bool:
    text_lower = text.lower()
    triggers = [
        "update ", "edit ", "modify ", "change the", "change a", "update the", "update a"
    ]
    return any(trigger in text_lower for trigger in triggers)


def is_add_column_request(text: str) -> bool:
    text_lower = text.lower()
    triggers = ["add a column", "add column", "new column", "add a field", "add field"]
    return any(trigger in text_lower for trigger in triggers)


# ---------------- Identifier / value validation ----------------

def is_valid_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def cast_value_for_column(raw_value: str, col_type: str):
    """Converts a form's raw text input into the right Python type for the
    column, based on its declared SQLite type — so numbers are inserted as
    real numbers, not strings."""
    if raw_value == "":
        return None
    col_type_upper = col_type.upper()
    try:
        if "INT" in col_type_upper:
            return int(raw_value)
        if any(t in col_type_upper for t in ("REAL", "FLOAT", "NUMERIC")):
            return float(raw_value)
        return raw_value
    except ValueError:
        raise ValueError(f"'{raw_value}' isn't a valid value for a {col_type} column.")


# ---------------- Table creation ----------------

def build_create_table_sql(table_name: str, columns: list) -> str:
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
    global db, sql_chain
    db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")
    sql_chain = build_sql_chain(db)


# ---------------- Insert (parameterized — values never string-interpolated) ----------------

def build_insert_sql_and_params(table_name: str, column_values: dict):
    if not is_valid_identifier(table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    for col in column_values:
        if not is_valid_identifier(col):
            raise ValueError(f"Invalid column name: {col}")

    columns = list(column_values.keys())
    col_names = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["?"] * len(columns))

    sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders});'
    params = tuple(column_values.values())

    preview_values = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in params)
    preview_sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({preview_values});'

    return sql, params, preview_sql


def execute_insert(sql: str, params: tuple):
    conn = get_connection()
    conn.execute(sql, params)
    conn.commit()
    conn.close()


# ---------------- Update (parameterized) ----------------

def build_update_sql_and_params(table_name: str, pk_column: str, pk_value, column_values: dict):
    """Builds a parameterized UPDATE ... SET ... WHERE <pk> = ?. Only the
    columns explicitly provided are updated — never a bare UPDATE with no
    WHERE, since pk_value is always required."""
    if not is_valid_identifier(table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    if not is_valid_identifier(pk_column):
        raise ValueError(f"Invalid primary key column: {pk_column}")
    for col in column_values:
        if not is_valid_identifier(col):
            raise ValueError(f"Invalid column name: {col}")
    if not column_values:
        raise ValueError("No fields to update.")

    set_clause = ", ".join(f'"{c}" = ?' for c in column_values)
    sql = f'UPDATE "{table_name}" SET {set_clause} WHERE "{pk_column}" = ?;'
    params = tuple(column_values.values()) + (pk_value,)

    set_preview = ", ".join(
        f'"{c}" = {repr(v) if isinstance(v, str) else v}' for c, v in column_values.items()
    )
    preview_sql = f'UPDATE "{table_name}" SET {set_preview} WHERE "{pk_column}" = {pk_value!r};'

    return sql, params, preview_sql


def execute_update(sql: str, params: tuple):
    conn = get_connection()
    conn.execute(sql, params)
    conn.commit()
    conn.close()


# ---------------- Add column (form-driven, never via LLM) ----------------

def build_add_column_sql(table_name: str, column_name: str, column_type: str) -> str:
    """ALTER TABLE ADD COLUMN only — never rename/drop/type-change, which
    are riskier and can affect existing data or other queries."""
    if not is_valid_identifier(table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    if not is_valid_identifier(column_name):
        raise ValueError(f"Invalid column name: {column_name}")
    if column_type not in VALID_TYPES:
        raise ValueError(f"Invalid type: {column_type}")

    return f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_type};'


def execute_add_column(sql: str):
    conn = get_connection()
    conn.execute(sql)
    conn.commit()
    conn.close()
    refresh_schema()


# ---------------- Schema introspection ----------------

def get_schema_details():
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


def get_primary_key_column(table_name: str):
    """Returns the name of the first PRIMARY KEY column, or None if the
    table has none (composite/no-PK tables aren't supported by the
    update/insert forms — a known, documented scope limit)."""
    info = get_schema_details().get(table_name, {})
    for name, col_type, is_pk in info.get("columns", []):
        if is_pk:
            return name
    return None


def get_foreign_key_map(table_name: str) -> dict:
    """{column_name: (ref_table, ref_column)} — used by the insert/update
    forms to decide which fields should be dropdowns of real existing
    values instead of free-text input."""
    info = get_schema_details().get(table_name, {})
    return {from_col: (to_table, to_col) for from_col, to_table, to_col in info.get("foreign_keys", [])}


def get_column_values_for_dropdown(table_name: str, column: str, limit: int = 200):
    """Real existing values for a column — used to populate FK dropdowns
    so an invalid reference can't be typed in the first place."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(f'SELECT DISTINCT "{column}" FROM "{table_name}" LIMIT {limit}')
    values = [row[0] for row in cursor.fetchall()]
    conn.close()
    return values


def get_table_rows(table_name: str, limit: int = 200):
    """Returns (columns, rows) for a table — used by the update form to let
    the user pick a real, existing row rather than typing a PK value blind."""
    return run_query_with_columns(f'SELECT * FROM "{table_name}" LIMIT {limit};')


def get_row_by_pk(table_name: str, pk_column: str, pk_value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(f'SELECT * FROM "{table_name}" WHERE "{pk_column}" = ?', (pk_value,))
    columns = [desc[0] for desc in cursor.description]
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(columns, row))


# ---------------- Result fetching with real column names ----------------

def run_query_with_columns(sql: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        conn.commit()
        return columns, rows
    finally:
        conn.close()


# ---------------- Headless usage (scripts / eval_set.py) ----------------

def ask_question(question: str, retries: int = 2):
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
