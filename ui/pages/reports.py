"""
reports.py — Report generation page for the Streamlit UI.

Lists past reconciliation runs and lets the user generate and download
Excel or PDF reports for any completed run.
"""

from datetime import date
from pathlib import Path

import streamlit as st

from src.database.connection import get_db
from src.database.queries import (
    get_reconciliation,
    list_exceptions_for_reconciliation,
    list_match_details_for_reconciliation,
    list_reconciliations,
    list_bank_transactions,
    update_reconciliation_report_path,
)
from src.reports.excel_report import generate_excel_report
from src.reports.pdf_report import generate_pdf_report


def render() -> None:
    """Render the Reports page."""
    st.header("📊 Reports")
    st.caption(
        "Generate and download Excel or PDF reconciliation reports "
        "for any completed reconciliation run."
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

    # Build a human-readable label for each run to show in the drop-down
    def run_label(recon: dict) -> str:
        return (
            f"#{recon['id']}  {recon['bank_name']}  "
            f"{recon['period_start']} to {recon['period_end']}  "
            f"({recon['matched_count']} matched, {recon['exceptions']} exceptions)"
        )

    selected_label = st.selectbox(
        "Select reconciliation run",
        options=[run_label(r) for r in history],
        help="Choose the reconciliation run you want to generate a report for.",
    )

    # Map the selected label back to its recon dict
    selected_recon = history[[run_label(r) for r in history].index(selected_label)]

    recon_id = selected_recon["id"]

    # --- Summary of selected run --------------------------------------------

    st.subheader(f"Run #{recon_id} Summary")

    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)

    total_bank   = selected_recon.get("total_bank_txns", 0)
    matched      = selected_recon.get("matched_count", 0)
    match_rate   = (matched / total_bank * 100) if total_bank > 0 else 0.0

    metric_col1.metric("Bank transactions", total_bank)
    metric_col2.metric("Ledger entries",    selected_recon.get("total_ledger_entries", 0))
    metric_col3.metric("Matched",           matched)
    metric_col4.metric("Match rate",        f"{match_rate:.1f}%")
    metric_col5.metric("Exceptions",        selected_recon.get("exceptions", 0))

    st.divider()

    # --- Generate report ----------------------------------------------------

    format_choice = st.radio(
        "Report format",
        options=["Excel (.xlsx)", "PDF (.pdf)"],
        horizontal=True,
    )
    is_excel = format_choice.startswith("Excel")

    if st.button("📥 Generate Report", type="primary", use_container_width=True):
        _generate_and_offer_download(recon_id=recon_id, is_excel=is_excel)


def _generate_and_offer_download(recon_id: int, is_excel: bool) -> None:
    """Generate the report file and present a download button."""
    with st.spinner("Generating report ..."):
        try:
            with get_db() as db:
                conn = db.get_connection()

                recon        = dict(get_reconciliation(conn, recon_id))
                matched_rows = list_match_details_for_reconciliation(conn, recon_id)
                exc_rows     = list_exceptions_for_reconciliation(conn, recon_id)

                # Resolve period dates so the bank transaction query works
                period_start = recon["period_start"]
                period_end   = recon["period_end"]
                if isinstance(period_start, str):
                    period_start = date.fromisoformat(period_start)
                if isinstance(period_end, str):
                    period_end = date.fromisoformat(period_end)

                all_bank_txns = list_bank_transactions(
                    conn,
                    bank_name=recon["bank_name"],
                    account_number=recon.get("account_number"),
                    period_start=period_start,
                    period_end=period_end,
                )

                extension   = "xlsx" if is_excel else "pdf"
                output_path = Path("data/reports") / f"recon_{recon_id}_report.{extension}"

                if is_excel:
                    report_path = generate_excel_report(
                        recon=recon,
                        matched_rows=matched_rows,
                        exception_rows=exc_rows,
                        all_bank_txns=all_bank_txns,
                        output_path=output_path,
                    )
                else:
                    report_path = generate_pdf_report(
                        recon=recon,
                        matched_rows=matched_rows,
                        exception_rows=exc_rows,
                        output_path=output_path,
                    )

                update_reconciliation_report_path(conn, recon_id, str(report_path))

        except Exception as error:
            st.error(f"Report generation failed: {error}")
            return

    # Read the file back and offer it as a download
    report_bytes = report_path.read_bytes()
    mime_type    = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if is_excel
        else "application/pdf"
    )

    st.success(f"Report generated: {report_path.name}")
    st.download_button(
        label=f"⬇️ Download {report_path.name}",
        data=report_bytes,
        file_name=report_path.name,
        mime=mime_type,
        use_container_width=True,
    )