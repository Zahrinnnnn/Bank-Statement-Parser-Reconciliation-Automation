"""
exceptions.py — Exceptions viewer page for the Streamlit UI.

Lets the user select a reconciliation run and browse all exception items
(BANK_ONLY, LEDGER_ONLY, LARGE_UNMATCHED, DUPLICATE_BANK) with
colour-coded badges and filters.
"""

import streamlit as st

from src.database.connection import get_db
from src.database.queries import (
    list_exceptions_for_reconciliation,
    list_reconciliations,
)
from ui.components.table import render_table


# Colour styling for each exception type badge
EXCEPTION_BADGE_COLOURS = {
    "BANK_ONLY":       "🟡",
    "LEDGER_ONLY":     "🔵",
    "LARGE_UNMATCHED": "🔴",
    "DUPLICATE_BANK":  "🟣",
    "AMOUNT_MISMATCH": "🟠",
    "DATE_MISMATCH":   "🔵",
}


def render() -> None:
    """Render the Exceptions viewer page."""
    st.header("⚠️ Exceptions")
    st.caption(
        "View unmatched and flagged items from a reconciliation run. "
        "Use this page to investigate and resolve exceptions before closing the period."
    )

    st.divider()

    # --- Load reconciliation history ----------------------------------------

    with get_db() as db:
        history = list_reconciliations(db.get_connection(), limit=50)

    if not history:
        st.info(
            "No reconciliation runs found. "
            "Go to the Reconcile page to run your first reconciliation."
        )
        return

    # --- Select a run -------------------------------------------------------

    def run_label(recon: dict) -> str:
        return (
            f"#{recon['id']}  {recon['bank_name']}  "
            f"{recon['period_start']} to {recon['period_end']}  "
            f"({recon['exceptions']} exceptions)"
        )

    selected_label = st.selectbox(
        "Select reconciliation run",
        options=[run_label(r) for r in history],
    )
    selected_recon = history[[run_label(r) for r in history].index(selected_label)]
    recon_id = selected_recon["id"]

    # --- Load exceptions for this run ---------------------------------------

    with get_db() as db:
        exception_rows = list_exceptions_for_reconciliation(db.get_connection(), recon_id)

    if not exception_rows:
        st.success(f"No exceptions for reconciliation #{recon_id}. All items matched!")
        return

    # --- Summary badges -----------------------------------------------------

    type_counts: dict[str, int] = {}
    for row in exception_rows:
        exc_type = row.get("exception_type") or "UNKNOWN"
        type_counts[exc_type] = type_counts.get(exc_type, 0) + 1

    st.subheader(f"Run #{recon_id} — {len(exception_rows)} exceptions")

    badge_cols = st.columns(min(len(type_counts), 5))
    for col, (exc_type, count) in zip(badge_cols, type_counts.items()):
        icon = EXCEPTION_BADGE_COLOURS.get(exc_type, "⚪")
        col.metric(f"{icon} {exc_type}", count)

    st.divider()

    # --- Filter by exception type -------------------------------------------

    filter_options = ["All"] + sorted(type_counts.keys())
    type_filter = st.selectbox(
        "Filter by exception type",
        options=filter_options,
        help="Show only exceptions of this type.",
    )

    source_filter = st.radio(
        "Source",
        options=["All", "BANK", "LEDGER"],
        horizontal=True,
        help="Show only bank-side or ledger-side exceptions.",
    )

    # Apply filters
    filtered_rows = exception_rows

    if type_filter != "All":
        filtered_rows = [r for r in filtered_rows if r.get("exception_type") == type_filter]

    if source_filter != "All":
        filtered_rows = [r for r in filtered_rows if r.get("source") == source_filter]

    st.caption(f"Showing {len(filtered_rows)} of {len(exception_rows)} exceptions")

    # --- Exceptions table ---------------------------------------------------

    display_rows = [
        {
            "source":         row.get("source") or "—",
            "exception_type": row.get("exception_type") or "—",
            "date":           str(row.get("txn_date") or ""),
            "description":    row.get("description") or "—",
            "amount":         row.get("amount") or 0,
            "reference":      row.get("reference") or "—",
        }
        for row in filtered_rows
    ]

    render_table(
        display_rows,
        column_config={
            "source":         st.column_config.TextColumn("Source",   width="small"),
            "exception_type": st.column_config.TextColumn("Type",     width="medium"),
            "date":           st.column_config.TextColumn("Date",     width="small"),
            "description":    st.column_config.TextColumn("Description", width="large"),
            "amount":         st.column_config.NumberColumn(
                                  "Amount (RM)", format="RM %.2f",
                              ),
            "reference":      st.column_config.TextColumn("Reference"),
        },
        height=500,
    )

    # --- Exception type legend ----------------------------------------------

    with st.expander("Exception type reference"):
        st.markdown("""
| Type | Meaning |
|---|---|
| 🟡 BANK_ONLY | Transaction in bank statement but not in ledger |
| 🔵 LEDGER_ONLY | Entry in ledger but not in bank statement |
| 🔴 LARGE_UNMATCHED | Unmatched transaction above the RM threshold |
| 🟣 DUPLICATE_BANK | Same transaction appears twice in the bank statement |
| 🟠 AMOUNT_MISMATCH | Matched by reference but amounts differ |
| 🔵 DATE_MISMATCH | Matched by amount/description but dates differ |
        """)