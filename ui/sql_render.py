import re
import html as html_lib

SQL_KEYWORDS = (
    r"SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP BY|ORDER BY|AS|"
    r"AND|OR|NOT|LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|"
    r"PRIMARY KEY|FOREIGN KEY|REFERENCES|DISTINCT|HAVING|CASE|WHEN|THEN|ELSE|END|"
    r"LIKE|IN|BETWEEN|IS|NULL|DESC|ASC|COUNT|SUM|AVG|MIN|MAX|COALESCE|WITH"
)

TOKEN_PATTERN = re.compile(
    r"(?P<string>'[^']*')"
    r"|(?P<qident>\"[^\"]*\")"
    r"|(?P<number>\b\d+\.?\d*\b)"
    rf"|(?P<keyword>\b(?:{SQL_KEYWORDS})\b)",
    re.IGNORECASE,
)

COLORS = {"string": "#CE9178", "qident": "#9CDCFE", "number": "#B5CEA8", "keyword": "#569CD6"}


def highlight_sql(sql: str) -> str:
    out, last_end = [], 0
    for match in TOKEN_PATTERN.finditer(sql):
        out.append(html_lib.escape(sql[last_end:match.start()]))
        token_type = match.lastgroup
        color = COLORS[token_type]
        weight = "600" if token_type == "keyword" else "400"
        out.append(f'<span style="color:{color};font-weight:{weight}">{html_lib.escape(match.group())}</span>')
        last_end = match.end()
    out.append(html_lib.escape(sql[last_end:]))
    return "".join(out)


def render_dark_table(df) -> str:
    header = "".join(f"<th>{html_lib.escape(str(c))}</th>" for c in df.columns)
    rows = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{html_lib.escape(str(v))}</td>" for v in row)
        rows += f"<tr>{cells}</tr>"
    return f'<table class="dark-table"><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>'