"""
transactions.py — Transactions browser page for the Streamlit UI.

Shows all bank transactions stored in the database with filter controls
for bank, account, date range, and reconciliation status.
"""

import streamlit as st

from src.database.connection import get_db
from src.database.queries import list_bank_transactions
from ui.components.table import amount_column, date_column, render_table, status_column


# Reconciliation status options for the filter drop-down
RECON_STATUS_OPTIONS = ["All", "UNMATCHED", "MATCHED", "BANK_ONLY", "LEDGER_ONLY",
                        "LARGE_UNMATCHED", "DUPLICATE_BANK"]


def render() -> None:
    """Render the Transactions browser page."""
    st.header("📋 Transactions")
    st.caption("Browse and filter all bank transactions stored in the database.")

    st.divider()

    # --- Filters ------------------------------------------------------------

    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        bank_filter = st.text_input(
            "Bank",
            placeholder="e.g. CIMB",
            help="Filter by bank name. Leave blank to show all banks.",
        ).strip().upper() or None

        account_filter = st.text_input(
            "Account Number",
            placeholder="e.g. 80012345678901",
            help="Filter by account number. Leave blank to show all accounts.",
        ).strip() or None

    with filter_col2:
        date_from = st.date_input(
            "From date",
            value=None,
            help="Show transactions on or after this date.",
        )
        date_to = st.date_input(
            "To date",
            value=None,
            help="Show transactions on or before this date.",
        )

    with filter_col3:
        status_filter_label = st.selectbox(
            "Reconciliation Status",
            options=RECON_STATUS_OPTIONS,
            help="Filter by reconciliation status.",
        )
        # "All" means no status filter — pass None to the query
        status_filter = None if status_filter_label == "All" else status_filter_label

    st.divider()

    # --- Load and display ---------------------------------------------------

    with get_db() as db:
        rows = list_bank_transactions(
            db.get_connection(),
            bank_name=bank_filter,
            account_number=account_filter,
            period_start=date_from or None,
            period_end=date_to or None,
            recon_status=status_filter,
        )

    # Summary metrics above the table
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Total rows", len(rows))

    if rows:
        matched_count   = sum(1 for r in rows if r.get("recon_status") == "MATCHED")
        unmatched_count = sum(1 for r in rows if r.get("recon_status") not in ("MATCHED",))
        total_debit     = sum(r.get("debit_amount") or 0 for r in rows)
        total_credit    = sum(r.get("credit_amount") or 0 for r in rows)

        metric_col2.metric("Matched",   matched_count)
        metric_col3.metric("Unmatched", unmatched_count)
        metric_col4.metric("Net flow (RM)", f"{total_credit - total_debit:,.2f}")

    # Display columns — omit internal DB fields that aren't useful to the user
    display_columns = [
        "id", "bank_name", "account_number", "transaction_date",
        "description", "reference", "debit_amount", "credit_amount",
        "balance", "recon_status",
    ]
    display_rows = [
        {col: row.get(col) for col in display_columns if col in row}
        for row in rows
    ]

    render_table(
        display_rows,
        column_config={
            "id":               st.column_config.NumberColumn("ID", width="small"),
            "bank_name":        st.column_config.TextColumn("Bank"),
            "account_number":   st.column_config.TextColumn("Account"),
            "transaction_date": date_column("Date"),
            "description":      st.column_config.TextColumn("Description", width="large"),
            "reference":        st.column_config.TextColumn("Reference"),
            "debit_amount":     amount_column("Debit (RM)"),
            "credit_amount":    amount_column("Credit (RM)"),
            "balance":          amount_column("Balance (RM)"),
            "recon_status":     status_column("Status"),
        },
        height=500,
    )