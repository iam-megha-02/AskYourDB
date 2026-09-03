import streamlit as st
from core.text_to_sql import get_schema_details


def render_schema_tab():
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