import streamlit as st

from ui.styles import CUSTOM_CSS
from ui.state import init_session_state
from ui.tabs.assistant_tab import render_assistant_tab
from ui.tabs.schema_tab import render_schema_tab
from ui.tabs.upload_tab import render_upload_tab

import core.conversation_store as conversation_store

st.set_page_config(page_title="AskYourDB", page_icon="assets/AYD_logo.png", layout="wide")

conversation_store.init_history_db()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title("AskYourDB: Chat with your database")
st.caption("Ask questions about your database in plain English, and see the generated SQL and results.")

init_session_state()

tab_assistant, tab_schema, tab_upload = st.tabs(["Assistant", "Schema", "Upload DB"])

with tab_assistant:
    render_assistant_tab()

with tab_schema:
    render_schema_tab()

with tab_upload:
    render_upload_tab()