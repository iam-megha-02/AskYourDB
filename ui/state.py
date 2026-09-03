import streamlit as st
from core.text_to_sql import (
    is_create_table_request, is_insert_request, is_update_request, is_add_column_request,
    execute_read_with_retry, is_safe_write, summarizer_llm
)
from core.conversation_store import load_recent_history, format_history_for_prompt, save_exchange

PANEL_HEIGHT = 460


def blank_column():
    return {"name": "", "type": "TEXT", "is_pk": False, "fk_table": None, "fk_column": None}


def init_session_state():
    if "active_db_name" not in st.session_state:
        st.session_state.active_db_name = "ecommerce.db (sample)"

    if "chat_history" not in st.session_state:
        persisted = load_recent_history(st.session_state.active_db_name, limit=10)
        st.session_state.chat_history = [
            {"question": q, "sql": s, "result": None, "columns": None, "summary": summary}
            for q, s, summary in persisted
        ]

    if "pending_write" not in st.session_state:
        st.session_state.pending_write = None
    if "pending_table_creation" not in st.session_state:
        st.session_state.pending_table_creation = False
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    if "new_columns" not in st.session_state:
        st.session_state.new_columns = [blank_column()]

    if "pending_insert" not in st.session_state:
        st.session_state.pending_insert = False
    if "insert_previewing" not in st.session_state:
        st.session_state.insert_previewing = False

    if "pending_update" not in st.session_state:
        st.session_state.pending_update = False
    if "update_stage" not in st.session_state:
        st.session_state.update_stage = "pick_table"  # pick_table -> pick_row -> edit -> preview

    if "pending_add_column" not in st.session_state:
        st.session_state.pending_add_column = False
    if "add_column_previewing" not in st.session_state:
        st.session_state.add_column_previewing = False


def switch_database(db_name: str):
    st.session_state.active_db_name = db_name
    persisted = load_recent_history(db_name, limit=10)
    st.session_state.chat_history = [
        {"question": q, "sql": s, "result": None, "columns": None, "summary": summary}
        for q, s, summary in persisted
    ]
    st.session_state.pending_write = None
    st.session_state.pending_table_creation = False
    st.session_state.pending_question = None
    st.session_state.pending_insert = False
    st.session_state.insert_previewing = False
    st.session_state.pending_update = False
    st.session_state.update_stage = "pick_table"
    st.session_state.pending_add_column = False
    st.session_state.add_column_previewing = False


def process_question(user_question):
    if is_create_table_request(user_question):
        summary = "Sure — fill in the table details in the panel on the right."
        st.session_state.pending_table_creation = True
        return {"question": user_question, "sql": "(form)", "result": None, "columns": None, "summary": summary}

    if is_add_column_request(user_question):
        summary = "Sure — pick the table and new column details in the panel on the right."
        st.session_state.pending_add_column = True
        return {"question": user_question, "sql": "(form)", "result": None, "columns": None, "summary": summary}

    if is_insert_request(user_question):
        summary = "Sure — pick the table and fill in the values in the panel on the right."
        st.session_state.pending_insert = True
        return {"question": user_question, "sql": "(form)", "result": None, "columns": None, "summary": summary}

    if is_update_request(user_question):
        summary = "Sure — pick the table and row to update in the panel on the right."
        st.session_state.pending_update = True
        st.session_state.update_stage = "pick_table"
        return {"question": user_question, "sql": "(form)", "result": None, "columns": None, "summary": summary}

    history_rows = load_recent_history(st.session_state.active_db_name, limit=5)
    conversation_history = format_history_for_prompt(history_rows)
    outcome = execute_read_with_retry(user_question, conversation_history)

    columns, result, sql_display = None, None, "(none)"

    if outcome["status"] == "success":
        columns = outcome["columns"]
        result = outcome["rows"]
        sql_display = outcome["sql"]
        try:
            summary = summarizer_llm.invoke(
                f"Question: {user_question}\nSQL: {sql_display}\nRaw result: {result}\n\n"
                "Answer in one or two plain, friendly sentences based only on the result. Don't mention SQL."
            ).content
        except Exception:
            summary = "The query ran successfully. The raw result is shown on the right."
        if outcome["attempts"] > 1:
            summary += f"  _(needed {outcome['attempts']} attempts — corrected a query error along the way)_"

    elif outcome["status"] == "blocked":
        summary = outcome["reason"]
        sql_display = outcome["sql"] or "(none)"

    elif outcome["status"] == "not_read":
        sql = outcome["sql"]
        query_type = outcome["query_type"]
        sql_display = sql
        safe, reason = is_safe_write(sql, query_type)
        if not safe:
            summary = f"Blocked: {reason}"
        else:
            st.session_state.pending_write = {"question": user_question, "sql": sql, "query_type": query_type}
            summary = f"This will run a {query_type} — check the panel on the right to review and confirm."

    else:
        summary = f"Couldn't get a working query: {outcome['reason']}"
        sql_display = outcome.get("sql") or "(none)"

    return {"question": user_question, "sql": sql_display, "result": result, "columns": columns, "summary": summary}
