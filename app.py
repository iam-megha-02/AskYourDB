import streamlit as st
import pandas as pd
import sqlite3
import html as html_lib
import tempfile

import text_to_sql as tsql
from text_to_sql import (
    clean_sql, references_real_schema,
    is_safe_write, describe_write, summarizer_llm,
    is_create_table_request, build_create_table_sql, refresh_schema,
    get_schema_details, VALID_TYPES,
    load_database, is_valid_sqlite_file, execute_read_with_retry
)
from conversation_store import (
    init_history_db, save_exchange, load_recent_history, format_history_for_prompt, clear_history
)
from styles import CUSTOM_CSS
from sql_render import highlight_sql, render_dark_table

st.set_page_config(page_title="AskYourDB", page_icon="assets/AYD_logo.png", layout="wide")

init_history_db()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("AskYourDB: Chat with your database")
st.caption("Ask questions about your database in plain English, and see the generated SQL and results.")

# ---------------- Session state ----------------
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
if "new_columns" not in st.session_state:
    st.session_state.new_columns = [{"name": "", "type": "TEXT", "is_pk": False, "fk_table": None, "fk_column": None}]


def blank_column():
    return {"name": "", "type": "TEXT", "is_pk": False, "fk_table": None, "fk_column": None}


def switch_database(db_name: str):
    """Called on upload/reset — loads that database's persisted history
    instead of blanking it, so conversation memory survives across sessions."""
    st.session_state.active_db_name = db_name
    persisted = load_recent_history(db_name, limit=10)
    st.session_state.chat_history = [
        {"question": q, "sql": s, "result": None, "columns": None, "summary": summary}
        for q, s, summary in persisted
    ]
    st.session_state.pending_write = None
    st.session_state.pending_table_creation = False


PANEL_HEIGHT = 460

tab_assistant, tab_schema, tab_upload = st.tabs(["Assistant", "Schema", "Upload DB"])

# ==================== ASSISTANT TAB ====================
with tab_assistant:
    left_col, right_col = st.columns([1, 1])

    # ---------------- LEFT: chat ----------------
    with left_col:
        with st.container(border=True, height=PANEL_HEIGHT):
            st.markdown('<div class="panel-header chat-header sticky-tab" style="border-radius:10px 10px 0 0;">💬 Ask a question</div>', unsafe_allow_html=True)
            for entry in st.session_state.chat_history:
                with st.chat_message("user"):
                    st.write(entry["question"])
                with st.chat_message("assistant"):
                    st.write(entry["summary"])

        col_input, col_clear = st.columns([5, 1])
        with col_input:
            user_question = st.chat_input("Ask a question about your store's data")
        with col_clear:
            if st.button("🗑️ Clear memory"):
                clear_history(st.session_state.active_db_name)
                st.session_state.chat_history = []
                st.rerun()

        if user_question:
            if is_create_table_request(user_question):
                summary = "Sure — fill in the table details in the panel on the right."
                st.session_state.chat_history.append({
                    "question": user_question, "sql": "(form)", "result": None,
                    "columns": None, "summary": summary
                })
                save_exchange(st.session_state.active_db_name, user_question, "(form)", summary)
                st.session_state.pending_table_creation = True
                st.rerun()
            else:
                with st.spinner("Thinking..."):
                    history_rows = load_recent_history(st.session_state.active_db_name, limit=5)
                    conversation_history = format_history_for_prompt(history_rows)

                    outcome = execute_read_with_retry(user_question, conversation_history)

                    columns, result, sql_display = None, None, "(none)"

                    if outcome["status"] == "success":
                        columns = outcome["columns"]
                        result = outcome["rows"]
                        sql_display = outcome["sql"]
                        summary = summarizer_llm.invoke(
                            f"Question: {user_question}\nSQL: {sql_display}\nRaw result: {result}\n\n"
                            "Answer in one or two plain, friendly sentences based only on the result. Don't mention SQL."
                        ).content
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
                            st.session_state.pending_write = {
                                "question": user_question, "sql": sql, "query_type": query_type
                            }
                            summary = f"This will run a {query_type} — check the panel on the right to review and confirm."

                    else:  # failed after retries
                        summary = f"Couldn't get a working query: {outcome['reason']}"
                        sql_display = outcome.get("sql") or "(none)"

                entry = {
                    "question": user_question, "sql": sql_display, "result": result,
                    "columns": columns, "summary": summary
                }
                st.session_state.chat_history.append(entry)
                save_exchange(st.session_state.active_db_name, user_question, sql_display, summary)
                st.rerun()

    # ---------------- RIGHT: query inspector ----------------
    with right_col:
        with st.container(key="inspector_box", height=PANEL_HEIGHT):
            st.markdown("""
            <div class="sticky-tab">
                <span style="width:11px;height:11px;border-radius:50%;background:#FF5F56;display:inline-block;"></span>
                <span style="width:11px;height:11px;border-radius:50%;background:#FFBD2E;display:inline-block;"></span>
                <span style="width:11px;height:11px;border-radius:50%;background:#27C93F;display:inline-block;"></span>
                <span style="color:var(--text-muted);font-family:'IBM Plex Mono',monospace;font-size:0.85rem;margin-left:6px;">query.sql</span>
            </div>
            """, unsafe_allow_html=True)

            if st.session_state.pending_table_creation:
                st.markdown("##### Create a new table")
                new_table_name = st.text_input("Table name")

                existing_tables = list(get_schema_details().keys())

                for i, col in enumerate(st.session_state.new_columns):
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
                    col["name"] = c1.text_input("Column", value=col["name"], key=f"name_{i}")
                    col["type"] = c2.selectbox("Type", VALID_TYPES, index=VALID_TYPES.index(col["type"]), key=f"type_{i}")
                    col["is_pk"] = c3.checkbox("PK", value=col["is_pk"], key=f"pk_{i}")
                    ref = c4.selectbox("FK →", ["None"] + existing_tables, key=f"fk_{i}")
                    col["fk_table"] = None if ref == "None" else ref
                    if col["fk_table"]:
                        fk_cols = [c[0] for c in get_schema_details()[col["fk_table"]]["columns"]]
                        col["fk_column"] = st.selectbox(f"column in {ref}", fk_cols, key=f"fkcol_{i}")

                b1, b2 = st.columns(2)
                if b1.button("+ Add column"):
                    st.session_state.new_columns.append(blank_column())
                    st.rerun()
                if b2.button("Cancel"):
                    st.session_state.pending_table_creation = False
                    st.session_state.new_columns = [blank_column()]
                    st.rerun()

                if new_table_name and all(c["name"] for c in st.session_state.new_columns):
                    try:
                        preview_sql = build_create_table_sql(new_table_name, st.session_state.new_columns)
                        st.markdown("**Preview:**")
                        st.code(preview_sql, language="sql")
                        if st.button("✅ Create table"):
                            conn = sqlite3.connect(tsql.DB_PATH)
                            conn.execute(preview_sql)
                            conn.commit()
                            conn.close()
                            refresh_schema()
                            st.session_state.pending_table_creation = False
                            st.session_state.new_columns = [blank_column()]
                            summary = f"Table '{new_table_name}' created successfully."
                            st.session_state.chat_history.append({
                                "question": "", "sql": preview_sql, "result": None, "columns": None,
                                "summary": summary
                            })
                            save_exchange(st.session_state.active_db_name, "", preview_sql, summary)
                            st.success(f"Table '{new_table_name}' created.")
                            st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"Failed to create table: {e}")

            elif st.session_state.pending_write:
                pw = st.session_state.pending_write
                description = describe_write(pw["sql"], pw["query_type"])
                st.warning(f"⚠️ About to run a {pw['query_type']}")
                st.write(description)
                with st.expander("Show actual SQL"):
                    st.code(pw["sql"], language="sql")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Confirm and execute"):
                        try:
                            tsql.db.run(pw["sql"])
                            st.success(f"{pw['query_type']} executed successfully.")
                        except Exception as e:
                            st.error(f"Execution failed: {e}")
                        st.session_state.pending_write = None
                        st.rerun()
                with col2:
                    if st.button("❌ Cancel"):
                        st.session_state.pending_write = None
                        st.rerun()

            elif st.session_state.chat_history:
                latest = st.session_state.chat_history[-1]
                highlighted = highlight_sql(latest["sql"] or "")

                if latest.get("columns") and latest.get("result"):
                    df = pd.DataFrame(latest["result"], columns=latest["columns"])
                    table_html = render_dark_table(df)
                    row_note = f'{len(df)} row{"s" if len(df) != 1 else ""} returned'
                elif latest.get("result") is not None:
                    table_html = f'<div style="color:#D4D4D4;font-family:\'IBM Plex Mono\',monospace;">{html_lib.escape(str(latest["result"]))}</div>'
                    row_note = ""
                else:
                    table_html = '<div style="color:#888;">No result to display.</div>'
                    row_note = ""

                st.markdown(f"""
                <div class="query-code">{highlighted}</div>
                <div class="result-header">Result</div>
                {table_html}
                <div style="color:var(--text-muted);font-size:0.8rem;padding-top:8px;">{row_note}</div>
                """, unsafe_allow_html=True)
            else:
                st.info("Ask a question on the left to see the generated SQL and raw results here.")

# ==================== SCHEMA TAB ====================

with tab_schema:
    st.subheader("Database schema")

    schema = get_schema_details()
    tables = list(schema.items())

    for i in range(0, len(tables), 2):
        row_tables = tables[i:i + 2]
        cols = st.columns(2)

        for col, (table, info) in zip(cols, row_tables):
            with col:
                with st.expander(f"📋 {table}", expanded=True):
                    lines = []
                    for name, col_type, is_pk in info["columns"]:
                        pk_marker = " 🔑 primary key" if is_pk else ""
                        lines.append(f"<li><code>{name}</code> — <em>{col_type}</em>{pk_marker}</li>")

                    fk_html = ""
                    if info["foreign_keys"]:
                        fk_lines = "".join(
                            f"<li><code>{from_col}</code> → <code>{to_table}.{to_col}</code></li>"
                            for from_col, to_table, to_col in info["foreign_keys"]
                        )
                        fk_html = f"<p><strong>Relationships:</strong></p><ul>{fk_lines}</ul>"

                    card_html = f"""
                    <div class="schema-card-body">
                        <ul>{''.join(lines)}</ul>
                        {fk_html}
                    </div>
                    """
                    st.markdown(card_html, unsafe_allow_html=True)

# ==================== UPLOAD DB TAB ====================
with tab_upload:
    st.subheader("📤 Upload DB")
    st.caption(f"Currently connected to: **{st.session_state.active_db_name}**")

    uploaded = st.file_uploader("Upload a SQLite (.db) file", type=["db", "sqlite", "sqlite3"])

    col_a, col_b = st.columns([2, 1])
    with col_a:
        if uploaded is not None:
            if st.button(f"📤 Load '{uploaded.name}'"):
                temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
                with open(temp_path, "wb") as f:
                    f.write(uploaded.getbuffer())

                if is_valid_sqlite_file(temp_path):
                    load_database(temp_path)
                    switch_database(uploaded.name)
                    st.success(f"Now chatting with '{uploaded.name}'")
                    st.rerun()
                else:
                    st.error("That doesn't look like a valid SQLite database file.")
    with col_b:
        if st.button("↩️ Reset to sample DB"):
            load_database("ecommerce.db")
            switch_database("ecommerce.db (sample)")
            st.rerun()