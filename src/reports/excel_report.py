"""
excel_report.py — Excel reconciliation report generator.

Produces a multi-sheet Excel workbook using xlsxwriter:
  Sheet 1 — Summary:              key statistics and exception breakdown
  Sheet 2 — Matched Transactions: all bank/ledger pairs with match details
  Sheet 3 — Exceptions:           all unmatched items with exception categories
  Sheet 4 — All Transactions:     full bank transaction list with recon status

Usage:
    from src.reports.excel_report import generate_excel_report
    report_path = generate_excel_report(
        recon=recon_dict,
        matched_rows=matched_rows,
        exception_rows=exception_rows,
        all_bank_txns=all_bank_txns,
        output_path=Path("data/reports/recon_1_report.xlsx"),
    )
"""

import logging
from datetime import datetime
from pathlib import Path

import xlsxwriter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette — consistent throughout the workbook
# ---------------------------------------------------------------------------

COLOUR_HEADER_BG   = "#1F4E79"   # Dark blue for column headers
COLOUR_HEADER_TEXT = "#FFFFFF"   # White text on dark headers
COLOUR_TITLE_TEXT  = "#1F4E79"   # Dark blue for the report title
COLOUR_ALT_ROW     = "#EEF4FB"   # Light blue alternating row background
COLOUR_MATCHED_ROW = "#E2EFDA"   # Light green for matched transaction rows
COLOUR_BORDER      = "#BDD7EE"   # Light blue border colour


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_excel_report(
    recon: dict,
    matched_rows: list[dict],
    exception_rows: list[dict],
    all_bank_txns: list[dict],
    output_path: Path,
) -> Path:
    """
    Generate the full Excel reconciliation report.

    Args:
        recon:          Reconciliation run dict from the database.
        matched_rows:   Matched pair dicts from list_match_details_for_reconciliation.
        exception_rows: Exception dicts from list_exceptions_for_reconciliation.
        all_bank_txns:  All bank transaction dicts for the period.
        output_path:    Where to write the .xlsx file.

    Returns:
        The output_path that was written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    workbook = xlsxwriter.Workbook(str(output_path))
    formats  = _build_formats(workbook)

    _write_summary_sheet(workbook, formats, recon, exception_rows)
    _write_matched_sheet(workbook, formats, matched_rows)
    _write_exceptions_sheet(workbook, formats, exception_rows)
    _write_all_transactions_sheet(workbook, formats, all_bank_txns)

    workbook.close()
    logger.info("Excel report written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Format definitions
# ---------------------------------------------------------------------------

def _build_formats(workbook: xlsxwriter.Workbook) -> dict:
    """Create and register all reusable cell formats for the workbook."""

    title_fmt = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": COLOUR_TITLE_TEXT,
        "bottom": 2,
        "bottom_color": COLOUR_TITLE_TEXT,
    })

    label_fmt = workbook.add_format({
        "bold": True,
        "font_size": 11,
        "font_color": "#333333",
    })

    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": COLOUR_HEADER_TEXT,
        "bg_color": COLOUR_HEADER_BG,
        "border": 1,
        "border_color": COLOUR_BORDER,
        "align": "center",
        "text_wrap": True,
    })

    cell_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
    })

    alt_cell_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "bg_color": COLOUR_ALT_ROW,
    })

    matched_cell_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "bg_color": COLOUR_MATCHED_ROW,
    })

    # Number / amount — right-aligned, two decimal places
    amount_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "num_format": "#,##0.00",
        "align": "right",
    })

    alt_amount_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "bg_color": COLOUR_ALT_ROW,
        "num_format": "#,##0.00",
        "align": "right",
    })

    matched_amount_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "bg_color": COLOUR_MATCHED_ROW,
        "num_format": "#,##0.00",
        "align": "right",
    })

    # Percentage — shown as 0.00% (pass a fraction, e.g. 0.75 → "75.00%")
    pct_fmt = workbook.add_format({
        "border": 1,
        "border_color": COLOUR_BORDER,
        "num_format": "0.00%",
        "align": "right",
    })

    return {
        "title":          title_fmt,
        "label":          label_fmt,
        "header":         header_fmt,
        "cell":           cell_fmt,
        "alt_cell":       alt_cell_fmt,
        "matched_cell":   matched_cell_fmt,
        "amount":         amount_fmt,
        "alt_amount":     alt_amount_fmt,
        "matched_amount": matched_amount_fmt,
        "pct":            pct_fmt,
    }


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------

def _write_summary_sheet(
    workbook: xlsxwriter.Workbook,
    formats: dict,
    recon: dict,
    exception_rows: list[dict],
) -> None:
    """Write the Summary sheet — run metadata, key stats, exception breakdown."""
    sheet = workbook.add_worksheet("Summary")
    sheet.set_column("A:A", 30)
    sheet.set_column("B:B", 28)

    row = 0

    # Report title spanning two columns
    sheet.merge_range(row, 0, row, 1, "Reconciliation Report", formats["title"])
    row += 2

    # --- Run metadata -------------------------------------------------------
    sheet.write(row, 0, "Run Details", formats["label"])
    row += 1

    meta_fields = [
        ("Bank",           recon.get("bank_name") or "—"),
        ("Account Number", recon.get("account_number") or "—"),
        ("Period Start",   str(recon.get("period_start") or "—")),
        ("Period End",     str(recon.get("period_end") or "—")),
        ("Run Date",       str(recon.get("run_date") or "—")),
        ("Status",         recon.get("status") or "—"),
    ]
    for field_label, field_value in meta_fields:
        sheet.write(row, 0, field_label,  formats["cell"])
        sheet.write(row, 1, field_value,  formats["cell"])
        row += 1

    row += 1

    # --- Key statistics -----------------------------------------------------
    sheet.write(row, 0, "Statistics", formats["label"])
    row += 1

    total_bank   = recon.get("total_bank_txns", 0)
    total_ledger = recon.get("total_ledger_entries", 0)
    matched      = recon.get("matched_count", 0)
    # Pass the fraction directly — the pct format multiplies by 100 for display
    match_rate_fraction = (matched / total_bank) if total_bank > 0 else 0.0
    unmatched_bank    = recon.get("unmatched_bank", 0)
    unmatched_ledger  = recon.get("unmatched_ledger", 0)
    total_exceptions  = recon.get("exceptions", 0)

    stats = [
        ("Total Bank Transactions",  total_bank,          "cell"),
        ("Total Ledger Entries",     total_ledger,        "cell"),
        ("Matched Pairs",            matched,             "cell"),
        ("Match Rate",               match_rate_fraction, "pct"),
        ("Unmatched Bank Items",     unmatched_bank,      "cell"),
        ("Unmatched Ledger Items",   unmatched_ledger,    "cell"),
        ("Total Exceptions",         total_exceptions,    "cell"),
    ]
    for stat_label, stat_value, fmt_key in stats:
        sheet.write(row, 0, stat_label,  formats["cell"])
        sheet.write(row, 1, stat_value,  formats[fmt_key])
        row += 1

    row += 1

    # --- Exception breakdown ------------------------------------------------
    if exception_rows:
        sheet.write(row, 0, "Exception Breakdown", formats["label"])
        row += 1

        sheet.write(row, 0, "Exception Type", formats["header"])
        sheet.write(row, 1, "Count",           formats["header"])
        row += 1

        # Count occurrences of each exception type
        type_counts: dict[str, int] = {}
        for exc_row in exception_rows:
            exc_type = exc_row.get("exception_type") or "UNKNOWN"
            type_counts[exc_type] = type_counts.get(exc_type, 0) + 1

        for exc_type, count in sorted(type_counts.items()):
            sheet.write(row, 0, exc_type, formats["cell"])
            sheet.write(row, 1, count,    formats["cell"])
            row += 1

    # Timestamp at the bottom so the reader knows when this was produced
    row += 1
    sheet.write(
        row, 0,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        formats["label"],
    )


def _write_matched_sheet(
    workbook: xlsxwriter.Workbook,
    formats: dict,
    matched_rows: list[dict],
) -> None:
    """Write the Matched Transactions sheet — one row per bank/ledger pair."""
    sheet = workbook.add_worksheet("Matched Transactions")

    sheet.set_column("A:A", 14)   # Bank Date
    sheet.set_column("B:B", 36)   # Bank Description
    sheet.set_column("C:C", 14)   # Debit
    sheet.set_column("D:D", 14)   # Credit
    sheet.set_column("E:E", 14)   # Ledger Date
    sheet.set_column("F:F", 36)   # Ledger Description
    sheet.set_column("G:G", 16)   # Ledger Amount
    sheet.set_column("H:H", 14)   # Match Type
    sheet.set_column("I:I", 12)   # Confidence

    headers = [
        "Bank Date", "Bank Description", "Debit (RM)", "Credit (RM)",
        "Ledger Date", "Ledger Description", "Ledger Amount (RM)",
        "Match Type", "Confidence",
    ]
    for col_idx, header_text in enumerate(headers):
        sheet.write(0, col_idx, header_text, formats["header"])

    for row_idx, match in enumerate(matched_rows, start=1):
        # Alternate between matched-green and alt-blue for readability
        use_alt = row_idx % 2 == 0
        cell_fmt   = formats["alt_cell"]   if use_alt else formats["matched_cell"]
        amount_fmt = formats["alt_amount"] if use_alt else formats["matched_amount"]

        sheet.write(row_idx, 0, str(match.get("bank_date") or ""),          cell_fmt)
        sheet.write(row_idx, 1, match.get("bank_description") or "",        cell_fmt)
        sheet.write(row_idx, 2, match.get("debit_amount") or 0,             amount_fmt)
        sheet.write(row_idx, 3, match.get("credit_amount") or 0,            amount_fmt)
        sheet.write(row_idx, 4, str(match.get("ledger_date") or ""),        cell_fmt)
        sheet.write(row_idx, 5, match.get("ledger_description") or "",      cell_fmt)
        sheet.write(row_idx, 6, match.get("ledger_amount") or 0,            amount_fmt)
        sheet.write(row_idx, 7, match.get("match_type") or "",              cell_fmt)
        sheet.write(row_idx, 8, match.get("confidence_score") or 0,        amount_fmt)


def _write_exceptions_sheet(
    workbook: xlsxwriter.Workbook,
    formats: dict,
    exception_rows: list[dict],
) -> None:
    """Write the Exceptions sheet — one row per unmatched item."""
    sheet = workbook.add_worksheet("Exceptions")

    sheet.set_column("A:A", 12)   # Source
    sheet.set_column("B:B", 18)   # Exception Type
    sheet.set_column("C:C", 14)   # Date
    sheet.set_column("D:D", 42)   # Description
    sheet.set_column("E:E", 16)   # Amount
    sheet.set_column("F:F", 24)   # Reference

    headers = ["Source", "Exception Type", "Date", "Description", "Amount (RM)", "Reference"]
    for col_idx, header_text in enumerate(headers):
        sheet.write(0, col_idx, header_text, formats["header"])

    for row_idx, exc in enumerate(exception_rows, start=1):
        use_alt    = row_idx % 2 == 0
        cell_fmt   = formats["alt_cell"]   if use_alt else formats["cell"]
        amount_fmt = formats["alt_amount"] if use_alt else formats["amount"]

        sheet.write(row_idx, 0, exc.get("source") or "—",         cell_fmt)
        sheet.write(row_idx, 1, exc.get("exception_type") or "—", cell_fmt)
        sheet.write(row_idx, 2, str(exc.get("txn_date") or ""),   cell_fmt)
        sheet.write(row_idx, 3, exc.get("description") or "—",    cell_fmt)
        sheet.write(row_idx, 4, exc.get("amount") or 0,           amount_fmt)
        sheet.write(row_idx, 5, exc.get("reference") or "—",      cell_fmt)


def _write_all_transactions_sheet(
    workbook: xlsxwriter.Workbook,
    formats: dict,
    all_bank_txns: list[dict],
) -> None:
    """Write the All Transactions sheet — every bank transaction with its status."""
    sheet = workbook.add_worksheet("All Transactions")

    sheet.set_column("A:A", 14)   # Date
    sheet.set_column("B:B", 42)   # Description
    sheet.set_column("C:C", 14)   # Debit
    sheet.set_column("D:D", 14)   # Credit
    sheet.set_column("E:E", 24)   # Reference
    sheet.set_column("F:F", 18)   # Recon Status
    sheet.set_column("G:G", 12)   # Bank

    headers = [
        "Date", "Description", "Debit (RM)", "Credit (RM)",
        "Reference", "Recon Status", "Bank",
    ]
    for col_idx, header_text in enumerate(headers):
        sheet.write(0, col_idx, header_text, formats["header"])

    for row_idx, txn in enumerate(all_bank_txns, start=1):
        use_alt    = row_idx % 2 == 0
        cell_fmt   = formats["alt_cell"]   if use_alt else formats["cell"]
        amount_fmt = formats["alt_amount"] if use_alt else formats["amount"]

        sheet.write(row_idx, 0, str(txn.get("transaction_date") or ""), cell_fmt)
        sheet.write(row_idx, 1, txn.get("description") or "—",          cell_fmt)
        sheet.write(row_idx, 2, txn.get("debit_amount") or 0,           amount_fmt)
        sheet.write(row_idx, 3, txn.get("credit_amount") or 0,          amount_fmt)
        sheet.write(row_idx, 4, txn.get("reference") or "—",            cell_fmt)
        sheet.write(row_idx, 5, txn.get("recon_status") or "—",         cell_fmt)
        sheet.write(row_idx, 6, txn.get("bank_name") or "—",            cell_fmt)