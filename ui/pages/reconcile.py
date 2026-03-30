"""
reconcile.py — Reconciliation runner page for the Streamlit UI.

Lets the user select a bank, account, and period, then runs automated
reconciliation. Displays summary statistics and the full matched-pairs
table when the run completes.
"""

import calendar
from datetime import date

import streamlit as st

from src.database.connection import get_db
from src.reconciliation.engine import run_reconciliation
from ui.components.table import amount_column, date_column, render_table


def render() -> None:
    """Render the Reconcile page."""
    st.header("🔄 Reconcile")
    st.caption(
        "Run automated reconciliation for a bank account and period. "
        "The engine tries exact, amount+date, amount+reference, fuzzy, "
        "and amount-only matching in priority order."
    )

    st.divider()

    # --- Configuration form -------------------------------------------------

    form_col1, form_col2 = st.columns(2)

    with form_col1:
        bank_name = st.selectbox(
            "Bank",
            options=["CIMB", "HLB", "MAYBANK", "PUBLIC_BANK", "GENERIC"],
            help="Select the bank to reconcile.",
        )
        account_number = st.text_input(
            "Account Number (optional)",
            placeholder="e.g. 80012345678901",
            help="Leave blank to reconcile all accounts for this bank.",
        ).strip() or None

    with form_col2:
        current_year  = date.today().year
        current_month = date.today().month

        period_year = st.number_input(
            "Year", min_value=2000, max_value=2100, value=current_year, step=1,
        )
        period_month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            index=current_month - 1,
            format_func=lambda m: date(2000, m, 1).strftime("%B"),
        )

    with st.expander("Advanced matching options"):
        adv_col1, adv_col2 = st.columns(2)
        with adv_col1:
            amount_tolerance = st.number_input(
                "Amount tolerance (RM)",
                min_value=0.0, max_value=100.0, value=0.01, step=0.01,
                help="Max difference in RM to still consider amounts equal.",
            )
            fuzzy_threshold = st.slider(
                "Fuzzy match threshold",
                min_value=0.50, max_value=1.00, value=0.80, step=0.05,
                help="Minimum description similarity score (0–1) for a fuzzy match.",
            )
        with adv_col2:
            large_amount_threshold = st.number_input(
                "Large unmatched threshold (RM)",
                min_value=0.0, max_value=1_000_000.0, value=5000.0, step=500.0,
                help="Unmatched transactions above this amount are flagged as LARGE_UNMATCHED.",
            )

    st.divider()

    if st.button("▶️ Run Reconciliation", type="primary", use_container_width=True):
        _run_reconciliation(
            bank_name=bank_name,
            account_number=account_number,
            year=int(period_year),
            month=int(period_month),
            amount_tolerance=amount_tolerance,
            fuzzy_threshold=fuzzy_threshold,
            large_amount_threshold=large_amount_threshold,
        )


def _run_reconciliation(
    bank_name: str,
    account_number: str | None,
    year: int,
    month: int,
    amount_tolerance: float,
    fuzzy_threshold: float,
    large_amount_threshold: float,
) -> None:
    """Run reconciliation and display results."""
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    with st.spinner(f"Reconciling {bank_name} {year}-{month:02d} ..."):
        try:
            with get_db() as db:
                result = run_reconciliation(
                    conn=db.get_connection(),
                    period_start=period_start,
                    period_end=period_end,
                    bank_name=bank_name,
                    account_number=account_number,
                    amount_tolerance=amount_tolerance,
                    fuzzy_threshold=fuzzy_threshold,
                    large_amount_threshold=large_amount_threshold,
                )
        except Exception as error:
            st.error(f"Reconciliation failed: {error}")
            return

    # --- Summary metrics ----------------------------------------------------

    st.success(f"Reconciliation #{result.recon_id} complete.")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Bank transactions", result.total_bank_txns)
    col2.metric("Ledger entries",    result.total_ledger_entries)
    col3.metric("Matched",           result.matched_count)
    col4.metric("Match rate",        f"{result.match_rate():.1f}%")
    col5.metric("Exceptions",        result.exception_count)

    # Match strategy breakdown
    if result.matched_pairs:
        st.subheader("Match Breakdown")
        strategy_counts: dict[str, int] = {}
        for pair in result.matched_pairs:
            match_type = pair.get("match_type", "UNKNOWN")
            strategy_counts[match_type] = strategy_counts.get(match_type, 0) + 1

        breakdown_cols = st.columns(len(strategy_counts))
        for col, (match_type, count) in zip(breakdown_cols, strategy_counts.items()):
            col.metric(match_type, count)

    # --- Matched pairs table ------------------------------------------------

    if result.matched_pairs:
        st.subheader("Matched Pairs")

        matched_display = [
            {
                "bank_date":          str(pair["bank_txn"].get("transaction_date") or ""),
                "bank_description":   pair["bank_txn"].get("description") or "",
                "debit":              pair["bank_txn"].get("debit_amount") or 0,
                "credit":             pair["bank_txn"].get("credit_amount") or 0,
                "ledger_date":        str(pair["ledger_entry"].get("entry_date") or ""),
                "ledger_description": pair["ledger_entry"].get("description") or "",
                "ledger_amount":      pair["ledger_entry"].get("amount") or 0,
                "match_type":         pair.get("match_type") or "",
                "confidence":         pair.get("confidence_score") or 0,
            }
            for pair in result.matched_pairs
        ]

        render_table(
            matched_display,
            column_config={
                "bank_date":          st.column_config.TextColumn("Bank Date"),
                "bank_description":   st.column_config.TextColumn("Bank Description", width="medium"),
                "debit":              amount_column("Debit (RM)"),
                "credit":             amount_column("Credit (RM)"),
                "ledger_date":        st.column_config.TextColumn("Ledger Date"),
                "ledger_description": st.column_config.TextColumn("Ledger Description", width="medium"),
                "ledger_amount":      amount_column("Ledger Amt (RM)"),
                "match_type":         st.column_config.TextColumn("Match Type"),
                "confidence":         st.column_config.NumberColumn("Confidence", format="%.0f%%"),
            },
        )

    # --- Exceptions summary -------------------------------------------------

    if result.exceptions:
        st.subheader("Exceptions")
        exc_summary = result.exception_summary()
        exc_cols = st.columns(min(len(exc_summary), 4))
        for col, (exc_type, count) in zip(exc_cols, exc_summary.items()):
            col.metric(exc_type, count)

        st.info(
            f"Run `python main.py exceptions --recon-id {result.recon_id}` "
            f"in the CLI, or visit the Exceptions page to see the full list."
        )