"""
app.py — Streamlit web UI entry point.

Run with:
    streamlit run app.py

Phase 9 will fill in the individual pages. For now this just confirms
the app starts and the database is accessible.
"""

import streamlit as st
from src.utils.logger import setup_logging
from src.database.connection import get_db

setup_logging()

st.set_page_config(
    page_title="Bank Statement Reconciliation",
    page_icon="🏦",
    layout="wide",
)

st.title("Bank Statement Parser & Reconciliation")
st.caption("Phase 1 — Database layer ready. UI pages coming in Phase 9.")

# Quick health check — show the database path and table list
with get_db() as db:
    conn = db.get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [row["name"] for row in tables]

st.success(f"Database connected. Tables: {', '.join(table_names)}")
