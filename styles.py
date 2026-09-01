CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}
h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    letter-spacing: -0.01em;
}

.block-container {
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
}
h1 {
    margin-bottom: 0.2rem !important;
}
[data-testid="stCaptionContainer"] {
    margin-bottom: 0.5rem !important;
}
header[data-testid="stHeader"] {
    height: 2rem;
}

.panel-header {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 1.05rem;
    color: white;
    padding: 14px 18px;
}
.chat-header { background-color: #0B6E76; }

[data-testid="stAlert"] {
    border-radius: 8px;
    border-left: 4px solid #D9932E;
}
.stButton button {
    border-radius: 6px;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 500;
}
[data-testid="stChatInputSubmitButton"] {
    background-color: #0B6E76 !important;
}

:root {
    --chrome: #17181D;
    --surface: #1E1E1E;
    --border: #2C2D33;
    --text: #E6E6E6;
    --text-muted: #8A8F98;
}

.st-key-inspector_box {
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}
.sticky-tab {
    background-color: var(--chrome);
    padding: 10px 18px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid var(--border);
    margin: -1rem -1rem 0.75rem -1rem;
    border-radius: 10px 10px 0 0;
}
.query-code {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem;
    color: var(--text);
    white-space: pre-wrap;
    word-break: break-word;
}
.result-header {
    color: white;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 1.0rem;
    margin: 14px 0 8px;
}
table.dark-table { width: 100%; border-collapse: collapse; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: var(--text); }
table.dark-table th { background-color: var(--chrome); text-align: left; padding: 8px 10px; border: 1px solid var(--border); color: #9CDCFE; }
table.dark-table td { padding: 8px 10px; border: 1px solid var(--border); }

[data-testid="stExpander"] {
    font-size: 0.95rem !important;
}
[data-testid="stExpander"] p, [data-testid="stExpander"] li {
    font-size: 0.95rem !important;
}
.schema-card-body {
    height: 220px;
    overflow-y: auto;
    padding-right: 6px;
}
.schema-card-body ul {
    margin: 0;
    padding-left: 20px;
}
.schema-card-body li {
    margin-bottom: 4px;
}
</style>
"""