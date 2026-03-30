"""
sidebar.py — Shared sidebar navigation component.

Renders the left-hand navigation menu and returns the name of the
currently selected page so app.py can route to it.

Usage:
    from ui.components.sidebar import render_sidebar
    page = render_sidebar()
"""

import streamlit as st


# Pages in the order they appear in the sidebar
PAGES = [
    ("Upload",       "📤"),
    ("Transactions", "📋"),
    ("Reconcile",    "🔄"),
    ("Reports",      "📊"),
    ("Exceptions",   "⚠️"),
]


def render_sidebar() -> str:
    """
    Render the sidebar navigation and return the selected page name.

    Returns:
        One of: "Upload", "Transactions", "Reconcile", "Reports", "Exceptions"
    """
    with st.sidebar:
        st.title("🏦 BankRecon")
        st.caption("Bank Statement Parser & Reconciliation")
        st.divider()

        # Build the navigation buttons — highlight the active page
        if "active_page" not in st.session_state:
            st.session_state.active_page = "Upload"

        for page_name, icon in PAGES:
            is_active = st.session_state.active_page == page_name
            button_type = "primary" if is_active else "secondary"

            if st.button(
                f"{icon}  {page_name}",
                key=f"nav_{page_name}",
                use_container_width=True,
                type=button_type,
            ):
                st.session_state.active_page = page_name

        st.divider()
        st.caption("Phase 9 — Streamlit UI")

    return st.session_state.active_page