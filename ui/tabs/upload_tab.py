import os

import streamlit as st
import tempfile

from core.text_to_sql import load_database, is_valid_sqlite_file
from ui.state import switch_database


def render_upload_tab():
    st.subheader("📤 Upload DB")
    st.caption(f"Currently connected to: **{st.session_state.active_db_name}**")

    if "previous_temp_db_path" not in st.session_state:
        st.session_state.previous_temp_db_path = None

    MAX_UPLOAD_MB = 50

    uploaded = st.file_uploader(
        "Upload a SQLite (.db) file — max 50MB",
        type=["db", "sqlite", "sqlite3"]
    )
    st.caption("Privacy: uploaded database schema and query results are sent to Groq to generate SQL and answer summaries.")

    if uploaded is not None and uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"File too large ({uploaded.size / 1024 / 1024:.1f}MB) — max {MAX_UPLOAD_MB}MB.")
        uploaded = None

    col_a, col_b = st.columns([2, 1])
    with col_a:
        if uploaded is not None:
            if st.button(f"📤 Load '{uploaded.name}'"):
                temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
                with open(temp_path, "wb") as f:
                    f.write(uploaded.getbuffer())

                if is_valid_sqlite_file(temp_path):
                    try:
                        load_database(temp_path)
                        if st.session_state.previous_temp_db_path:
                            try:
                                os.remove(st.session_state.previous_temp_db_path)
                            except Exception:
                                pass
                        st.session_state.previous_temp_db_path = temp_path
                        switch_database(uploaded.name)
                        st.success(f"Now chatting with '{uploaded.name}'")
                        st.rerun()
                    except Exception as e:
                        os.remove(temp_path)
                        st.error(f"Failed to load database: {e}")
                else:
                    os.remove(temp_path)
                    st.error("That doesn't look like a valid SQLite database file.")
    with col_b:
        if st.button("↩️ Reset to sample DB"):
            load_database("data/ecommerce.db")
            if st.session_state.previous_temp_db_path:
                try:
                    os.remove(st.session_state.previous_temp_db_path)
                except Exception:
                    pass
                st.session_state.previous_temp_db_path = None
            switch_database("ecommerce.db (sample)")
            st.rerun()
