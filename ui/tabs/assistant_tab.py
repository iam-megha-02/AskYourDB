import streamlit as st
import pandas as pd
import sqlite3
import html as html_lib

import core.text_to_sql as tsql
from core.text_to_sql import (
    is_safe_write, describe_write, build_create_table_sql, refresh_schema,
    get_schema_details, VALID_TYPES,
    build_insert_sql_and_params, execute_insert, cast_value_for_column,
    build_update_sql_and_params, execute_update,
    build_add_column_sql, execute_add_column,
    get_primary_key_column, get_foreign_key_map, get_column_values_for_dropdown,
    get_table_rows, get_row_by_pk
)
from core.conversation_store import save_exchange
from ui.sql_render import highlight_sql, render_dark_table
from ui.state import PANEL_HEIGHT, blank_column, process_question


def render_assistant_tab():
    left_col, right_col = st.columns([1, 1])

    with left_col:
        st.markdown('<div class="panel-header chat-header" style="border-radius:10px 10px 0 0;">💬 Ask a question</div>', unsafe_allow_html=True)

        with st.container(border=True, height=PANEL_HEIGHT, key="chat_scroll"):
            for entry in st.session_state.chat_history:
                with st.chat_message("user"):
                    st.write(entry["question"])
                with st.chat_message("assistant"):
                    st.write(entry["summary"])

            if st.session_state.pending_question:
                q = st.session_state.pending_question
                with st.chat_message("user"):
                    st.write(q)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        entry = process_question(q)
                st.session_state.chat_history.append(entry)
                save_exchange(st.session_state.active_db_name, entry["question"], entry["sql"], entry["summary"])
                st.session_state.pending_question = None
                st.rerun()

        col_input, col_clear = st.columns([5, 1])
        with col_input:
            user_question = st.chat_input(
                "Ask a question about your store's data",
                disabled=bool(st.session_state.pending_question)
            )
        with col_clear:
            from core.conversation_store import clear_history
            if st.button("Clear"):
                clear_history(st.session_state.active_db_name)
                st.session_state.chat_history = []
                st.rerun()

        if user_question:
            st.session_state.pending_question = user_question
            st.rerun()

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

            if st.session_state.pending_add_column:
                _render_add_column_form()
            elif st.session_state.pending_insert:
                _render_insert_form()
            elif st.session_state.pending_update:
                _render_update_form()
            elif st.session_state.pending_table_creation:
                _render_table_creation_form()
            elif st.session_state.pending_write:
                _render_write_confirmation()
            elif st.session_state.chat_history:
                _render_latest_result()
            else:
                st.info("Ask a question on the left to see the generated SQL and raw results here.")


def _render_table_creation_form():
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


def _fk_aware_input(table_name, col_name, col_type, fk_map, key, current_value=None):
    """Renders a dropdown of real existing values if the column is a foreign
    key, otherwise a plain text input — so an invalid reference can't be
    typed in the first place."""
    if col_name in fk_map:
        ref_table, ref_column = fk_map[col_name]
        options = get_column_values_for_dropdown(ref_table, ref_column)
        options = [""] + [str(v) for v in options]
        default_index = 0
        if current_value is not None and str(current_value) in options:
            default_index = options.index(str(current_value))
        return st.selectbox(f"{col_name} → {ref_table}.{ref_column}", options, index=default_index, key=key)
    else:
        default = "" if current_value is None else str(current_value)
        return st.text_input(f"{col_name} ({col_type})", value=default, key=key)


def _render_insert_form():
    st.markdown("##### Add a row")

    tables = list(get_schema_details().keys())
    selected_table = st.selectbox("Table", ["Select a table..."] + tables, key="insert_table_select")

    if selected_table == "Select a table...":
        if st.button("Cancel"):
            st.session_state.pending_insert = False
            st.rerun()
        return

    columns_info = get_schema_details()[selected_table]["columns"]
    fk_map = get_foreign_key_map(selected_table)

    if not st.session_state.insert_previewing:
        st.markdown(f"**Values for `{selected_table}`:**")
        raw_values = {}
        for col_name, col_type, is_pk in columns_info:
            key = f"insert_{selected_table}_{col_name}"
            if is_pk:
                st.caption(f"{col_name} — leave blank to auto-assign")
            raw_values[col_name] = _fk_aware_input(selected_table, col_name, col_type, fk_map, key)

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Cancel", key="insert_cancel"):
                st.session_state.pending_insert = False
                st.rerun()
        with b2:
            if st.button("Preview", key="insert_preview"):
                try:
                    column_values = {}
                    for col_name, col_type, is_pk in columns_info:
                        raw = raw_values[col_name]
                        if raw == "" or raw is None:
                            continue
                        column_values[col_name] = cast_value_for_column(str(raw), col_type)

                    if not column_values:
                        st.error("Enter at least one value.")
                    else:
                        sql, params, preview_sql = build_insert_sql_and_params(selected_table, column_values)
                        st.session_state.insert_pending_sql = sql
                        st.session_state.insert_pending_params = params
                        st.session_state.insert_preview_display = preview_sql
                        st.session_state.insert_table_for_history = selected_table
                        st.session_state.insert_previewing = True
                        st.rerun()
                except ValueError as e:
                    st.error(str(e))

    else:
        st.markdown("**Preview:**")
        st.code(st.session_state.insert_preview_display, language="sql")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Confirm and insert"):
                try:
                    execute_insert(st.session_state.insert_pending_sql, st.session_state.insert_pending_params)
                    table_name = st.session_state.insert_table_for_history
                    preview_sql = st.session_state.insert_preview_display
                    summary = f"Row added to '{table_name}'."

                    st.session_state.chat_history.append({
                        "question": "", "sql": preview_sql, "result": None, "columns": None,
                        "summary": summary
                    })
                    save_exchange(st.session_state.active_db_name, "", preview_sql, summary)

                    st.session_state.pending_insert = False
                    st.session_state.insert_previewing = False
                    st.success(summary)
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add row: {e}")
        with c2:
            if st.button("❌ Back"):
                st.session_state.insert_previewing = False
                st.rerun()


def _render_update_form():
    st.markdown("##### Update a row")

    tables = list(get_schema_details().keys())

    if st.session_state.update_stage == "pick_table":
        selected_table = st.selectbox("Table", ["Select a table..."] + tables, key="update_table_select")
        if selected_table == "Select a table...":
            if st.button("Cancel", key="update_cancel_1"):
                st.session_state.pending_update = False
                st.rerun()
            return

        pk_col = get_primary_key_column(selected_table)
        if not pk_col:
            st.error(f"'{selected_table}' has no primary key — row-level update isn't supported for it.")
            if st.button("Back", key="update_back_1"):
                st.session_state.pending_update = False
                st.rerun()
            return

        st.session_state.update_table_name = selected_table
        st.session_state.update_pk_column = pk_col

        columns, rows = get_table_rows(selected_table)
        st.session_state.update_row_options = {str(row[columns.index(pk_col)]): row for row in rows}
        st.session_state.update_row_columns = columns
        st.session_state.update_stage = "pick_row"
        st.rerun()

    elif st.session_state.update_stage == "pick_row":
        table_name = st.session_state.update_table_name
        pk_col = st.session_state.update_pk_column
        options = list(st.session_state.update_row_options.keys())

        st.caption(f"Table: `{table_name}` — pick a row by `{pk_col}`")
        selected_pk = st.selectbox(f"{pk_col}", ["Select a row..."] + options, key="update_row_select")

        if st.button("Back", key="update_back_2"):
            st.session_state.update_stage = "pick_table"
            st.rerun()

        if selected_pk != "Select a row...":
            if st.button("Next", key="update_next"):
                st.session_state.update_pk_value = selected_pk
                st.session_state.update_stage = "edit"
                st.rerun()

    elif st.session_state.update_stage == "edit":
        table_name = st.session_state.update_table_name
        pk_col = st.session_state.update_pk_column
        pk_value_raw = st.session_state.update_pk_value

        current_row = get_row_by_pk(table_name, pk_col, pk_value_raw)
        if current_row is None:
            st.error("That row no longer exists.")
            if st.button("Back", key="update_back_3"):
                st.session_state.update_stage = "pick_table"
                st.rerun()
            return

        columns_info = get_schema_details()[table_name]["columns"]
        fk_map = get_foreign_key_map(table_name)

        st.markdown(f"**Editing `{table_name}` where `{pk_col}` = {pk_value_raw}:**")
        raw_values = {}
        for col_name, col_type, is_pk in columns_info:
            if is_pk:
                continue  # don't let the primary key itself be edited here
            key = f"update_{table_name}_{col_name}"
            raw_values[col_name] = _fk_aware_input(
                table_name, col_name, col_type, fk_map, key, current_value=current_row.get(col_name)
            )

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Back", key="update_back_4"):
                st.session_state.update_stage = "pick_row"
                st.rerun()
        with b2:
            if st.button("Preview", key="update_preview"):
                try:
                    column_values = {}
                    for col_name, col_type, is_pk in columns_info:
                        if is_pk:
                            continue
                        raw = raw_values[col_name]
                        current = current_row.get(col_name)
                        if raw == "" or raw is None:
                            continue
                        if str(raw) == str(current):
                            continue  # unchanged — don't include in the UPDATE
                        column_values[col_name] = cast_value_for_column(str(raw), col_type)

                    if not column_values:
                        st.error("No changes made.")
                    else:
                        pk_type = next(t for n, t, _ in columns_info if n == pk_col)
                        pk_value = cast_value_for_column(str(pk_value_raw), pk_type)
                        sql, params, preview_sql = build_update_sql_and_params(
                            table_name, pk_col, pk_value, column_values
                        )
                        st.session_state.update_pending_sql = sql
                        st.session_state.update_pending_params = params
                        st.session_state.update_preview_display = preview_sql
                        st.session_state.update_stage = "preview"
                        st.rerun()
                except ValueError as e:
                    st.error(str(e))

    elif st.session_state.update_stage == "preview":
        st.markdown("**Preview:**")
        st.code(st.session_state.update_preview_display, language="sql")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Confirm and update"):
                try:
                    execute_update(st.session_state.update_pending_sql, st.session_state.update_pending_params)
                    preview_sql = st.session_state.update_preview_display
                    summary = f"Row updated in '{st.session_state.update_table_name}'."

                    st.session_state.chat_history.append({
                        "question": "", "sql": preview_sql, "result": None, "columns": None,
                        "summary": summary
                    })
                    save_exchange(st.session_state.active_db_name, "", preview_sql, summary)

                    st.session_state.pending_update = False
                    st.session_state.update_stage = "pick_table"
                    st.success(summary)
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update row: {e}")
        with c2:
            if st.button("❌ Back", key="update_back_5"):
                st.session_state.update_stage = "edit"
                st.rerun()


def _render_add_column_form():
    st.markdown("##### Add a column")

    tables = list(get_schema_details().keys())
    selected_table = st.selectbox("Table", ["Select a table..."] + tables, key="addcol_table_select")

    if selected_table == "Select a table...":
        if st.button("Cancel", key="addcol_cancel_1"):
            st.session_state.pending_add_column = False
            st.rerun()
        return

    if not st.session_state.add_column_previewing:
        new_col_name = st.text_input("New column name", key="addcol_name")
        new_col_type = st.selectbox("Type", VALID_TYPES, key="addcol_type")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Cancel", key="addcol_cancel_2"):
                st.session_state.pending_add_column = False
                st.rerun()
        with b2:
            if new_col_name and st.button("Preview", key="addcol_preview"):
                try:
                    preview_sql = build_add_column_sql(selected_table, new_col_name, new_col_type)
                    st.session_state.addcol_pending_sql = preview_sql
                    st.session_state.addcol_table_for_history = selected_table
                    st.session_state.add_column_previewing = True
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    else:
        st.markdown("**Preview:**")
        st.code(st.session_state.addcol_pending_sql, language="sql")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Confirm and add column"):
                try:
                    execute_add_column(st.session_state.addcol_pending_sql)
                    table_name = st.session_state.addcol_table_for_history
                    sql = st.session_state.addcol_pending_sql
                    summary = f"Column added to '{table_name}'."

                    st.session_state.chat_history.append({
                        "question": "", "sql": sql, "result": None, "columns": None,
                        "summary": summary
                    })
                    save_exchange(st.session_state.active_db_name, "", sql, summary)

                    st.session_state.pending_add_column = False
                    st.session_state.add_column_previewing = False
                    st.success(summary)
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add column: {e}")
        with c2:
            if st.button("❌ Back", key="addcol_back"):
                st.session_state.add_column_previewing = False
                st.rerun()


def _render_write_confirmation():
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
                conn = tsql.get_connection()
                try:
                    conn.execute(pw["sql"])
                    conn.commit()
                finally:
                    conn.close()
                st.success(f"{pw['query_type']} executed successfully.")
            except Exception as e:
                st.error(f"Execution failed: {e}")
            st.session_state.pending_write = None
            st.rerun()
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.pending_write = None
            st.rerun()


def _render_latest_result():
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
