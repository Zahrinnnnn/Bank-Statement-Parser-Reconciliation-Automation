"""
app.py — Streamlit web UI entry point.

Run with:
    streamlit run app.py

Navigation is handled through the sidebar. Each page lives in ui/pages/
and exposes a single render() function that this file calls.
"""

import streamlit as st

from src.utils.logger import setup_logging
from ui.components.sidebar import render_sidebar

# Set up file + console logging before anything else runs
setup_logging()

st.set_page_config(
    page_title="Bank Statement Reconciliation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Render the sidebar and find out which page the user selected
active_page = render_sidebar()

# Route to the correct page module
if active_page == "Upload":
    from ui.pages.upload import render
    render()

elif active_page == "Transactions":
    from ui.pages.transactions import render
    render()

elif active_page == "Reconcile":
    from ui.pages.reconcile import render
    render()

elif active_page == "Reports":
    from ui.pages.reports import render
    render()

elif active_page == "Exceptions":
    from ui.pages.exceptions import render
    render()