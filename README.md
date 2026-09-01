<p align="center">
  <img src="AYD_logo.png" alt="AskYourDB logo" width="150"/>
</p>

# AskYourDB

Chat with your database in plain English. Ask a question, see the generated SQL, and get a clear answer; built with LangChain, Groq, and Streamlit.

**🔗 Live demo:** https://askyourdb-bjuekrtwwfgq5dtacgswyy.streamlit.app

## What it does

AskYourDB translates natural-language questions into SQL, runs them against a real SQLite database, and shows both the generated query and the result. Ships with a sample e-commerce database (customers, products, orders, order items) or upload your own `.db` file.

**Features:**
- Natural language => SQL, powered by Groq
- Query inspector: the exact generated SQL and result table for every question
- Read and write support (SELECT, DELETE, UPDATE, INSERT), writes require explicit confirmation before executing
- Table creation via a structured form, schema is defined by the user, not the LLM
- Schema browser: tables, columns, types, foreign keys
- Upload and query your own SQLite database

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

Create a `.env` file with a free [Groq](https://console.groq.com) API key:
```
GROQ_API_KEY=your_key_here
```

Run the app:
```bash
streamlit run app.py
```

(`ecommerce.db` is included pre-populated. To regenerate it: `python create_schema.py` then `python generate_data.py`.)

## Safety design

- **Structural changes (CREATE, DROP, ALTER, TRUNCATE) are blocked unconditionally** — no confirmation can override these. Table creation goes through a form instead, since schema design isn't something a single LLM-generated sentence should decide.
- **DELETE/UPDATE with no WHERE clause is blocked automatically** — the most common way to accidentally wipe a table.
- **All other writes require explicit confirmation** — the generated SQL is shown before anything executes.
- **Queries that don't reference a real table are blocked** — added after testing showed the model could generate a plausible, successfully-executing but fabricated query instead of failing visibly.
- Verified directly that destructive requests phrased conversationally, not just as obvious SQL keywords, are still caught by the deterministic check rather than relying on the model to refuse.

## Known limitations

- **No authentication.** Built for single-owner, local/personal use — not session-isolated for multiple concurrent users.
- **Ambiguous questions can resolve inconsistently.** E.g. "average items per order" was answered differently across runs depending on whether "items" meant line items or total quantity.
- **Some window-function and nested-aggregation questions are unreliable.** Targeted prompt instructions improved this but don't guarantee correctness on every similarly-structured question.
- **Exhaustive-list questions can be silently truncated** by a default LIMIT the SQL generator sometimes applies even when the question implies "show everything."

## Evaluation

`eval_set.py` runs test questions — lookups, joins, aggregations, ambiguous phrasing, and adversarial/out-of-scope questions — against the live pipeline, checked against independently-verified ground truth:
```bash
python eval_set.py
```

## Tech stack

Streamlit · LangChain · Groq · SQLite · Faker

## Project structure

```
├── app.py                # Streamlit app
├── text_to_sql.py         # SQL generation, validation, guardrails
├── eval_set.py             # Evaluation harness
├── check_ground_truth.py    # Independent SQL queries used to verify eval expectations
├── create_schema.py        # Regenerates the sample DB schema
├── generate_data.py        # Populates the sample DB
├── ecommerce.db             # Sample database (pre-populated)
├── requirements.txt
└── .streamlit/config.toml   # Theme config
```
