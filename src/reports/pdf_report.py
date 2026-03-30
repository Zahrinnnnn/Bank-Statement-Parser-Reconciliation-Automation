"""
pdf_report.py — PDF executive summary report generator.

Produces a single PDF document using ReportLab with:
  - Report header: bank name, period, and run ID
  - Key statistics table
  - Match breakdown by strategy
  - Exception summary table
  - Exception detail rows (up to 20)
  - Footer with generation timestamp

Usage:
    from src.reports.pdf_report import generate_pdf_report
    report_path = generate_pdf_report(
        recon=recon_dict,
        matched_rows=matched_rows,
        exception_rows=exception_rows,
        output_path=Path("data/reports/recon_1_report.pdf"),
    )
"""

import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour constants — match the Excel report palette
# ---------------------------------------------------------------------------

COLOUR_DARK_BLUE  = colors.HexColor("#1F4E79")
COLOUR_MID_BLUE   = colors.HexColor("#2E75B6")
COLOUR_LIGHT_BLUE = colors.HexColor("#DDEBF7")
COLOUR_ALT_ROW    = colors.HexColor("#EEF4FB")
COLOUR_GREEN_ROW  = colors.HexColor("#E2EFDA")
COLOUR_WHITE      = colors.white
COLOUR_BLACK      = colors.black
COLOUR_GREY       = colors.HexColor("#666666")
COLOUR_LIGHT_GREY = colors.HexColor("#CCCCCC")

# How many exception detail rows to show before truncating
MAX_EXCEPTION_DETAIL_ROWS = 20


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_pdf_report(
    recon: dict,
    matched_rows: list[dict],
    exception_rows: list[dict],
    output_path: Path,
) -> Path:
    """
    Generate the PDF executive summary report.

    Args:
        recon:          Reconciliation run dict from the database.
        matched_rows:   Matched pair dicts from list_match_details_for_reconciliation.
        exception_rows: Exception dicts from list_exceptions_for_reconciliation.
        output_path:    Where to write the .pdf file.

    Returns:
        The output_path that was written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = _build_styles()
    story  = _build_story(recon, matched_rows, exception_rows, styles)

    doc.build(story)
    logger.info("PDF report written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------

def _build_styles() -> dict:
    """Create custom paragraph styles for the report."""
    base   = getSampleStyleSheet()
    normal = base["Normal"]

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=normal,
        fontSize=20,
        textColor=COLOUR_DARK_BLUE,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )

    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=normal,
        fontSize=11,
        textColor=COLOUR_GREY,
        spaceAfter=2,
        fontName="Helvetica",
    )

    section_heading_style = ParagraphStyle(
        "SectionHeading",
        parent=normal,
        fontSize=13,
        textColor=COLOUR_DARK_BLUE,
        spaceBefore=14,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )

    body_style = ParagraphStyle(
        "Body",
        parent=normal,
        fontSize=10,
        textColor=COLOUR_BLACK,
        fontName="Helvetica",
    )

    footer_style = ParagraphStyle(
        "Footer",
        parent=normal,
        fontSize=8,
        textColor=COLOUR_GREY,
        fontName="Helvetica",
    )

    return {
        "title":   title_style,
        "subtitle": subtitle_style,
        "heading": section_heading_style,
        "body":    body_style,
        "footer":  footer_style,
    }


# ---------------------------------------------------------------------------
# Story builder — assembles all the flowable elements in order
# ---------------------------------------------------------------------------

def _build_story(
    recon: dict,
    matched_rows: list[dict],
    exception_rows: list[dict],
    styles: dict,
) -> list:
    """Return the list of ReportLab flowable elements that make up the PDF."""
    story = []

    # --- Page header --------------------------------------------------------

    bank_name    = recon.get("bank_name") or "—"
    period_start = str(recon.get("period_start") or "—")
    period_end   = str(recon.get("period_end") or "—")
    run_id       = recon.get("id") or "—"

    story.append(Paragraph("Reconciliation Report", styles["title"]))
    story.append(Paragraph(
        f"{bank_name}  |  {period_start} to {period_end}  |  Run #{run_id}",
        styles["subtitle"],
    ))
    story.append(HRFlowable(
        width="100%", thickness=2, color=COLOUR_DARK_BLUE, spaceAfter=10,
    ))

    # --- Key statistics table -----------------------------------------------

    story.append(Paragraph("Key Statistics", styles["heading"]))

    total_bank    = recon.get("total_bank_txns", 0)
    total_ledger  = recon.get("total_ledger_entries", 0)
    matched       = recon.get("matched_count", 0)
    match_rate    = (matched / total_bank * 100) if total_bank > 0 else 0.0
    unmatched_b   = recon.get("unmatched_bank", 0)
    unmatched_l   = recon.get("unmatched_ledger", 0)
    total_exc     = recon.get("exceptions", 0)
    account       = recon.get("account_number") or "—"
    run_date      = str(recon.get("run_date") or "—")

    stats_data = [
        ["Metric",                   "Value"],
        ["Bank",                     bank_name],
        ["Account Number",           account],
        ["Period",                   f"{period_start} to {period_end}"],
        ["Run Date",                 run_date],
        ["Total Bank Transactions",  str(total_bank)],
        ["Total Ledger Entries",     str(total_ledger)],
        ["Matched Pairs",            str(matched)],
        ["Match Rate",               f"{match_rate:.1f}%"],
        ["Unmatched Bank Items",     str(unmatched_b)],
        ["Unmatched Ledger Items",   str(unmatched_l)],
        ["Total Exceptions",         str(total_exc)],
    ]
    story.append(_two_column_table(stats_data))

    # --- Match breakdown by strategy ----------------------------------------

    if matched_rows:
        story.append(Paragraph("Match Breakdown by Strategy", styles["heading"]))

        strategy_counts: dict[str, int] = {}
        for match in matched_rows:
            match_type = match.get("match_type") or "UNKNOWN"
            strategy_counts[match_type] = strategy_counts.get(match_type, 0) + 1

        # Human-readable labels for each strategy code
        strategy_labels = {
            "EXACT":       "100% — Exact match (date + amount + reference)",
            "AMOUNT_DATE": "95%  — Amount + Date (within 1 day)",
            "AMOUNT_REF":  "90%  — Amount + Reference match",
            "FUZZY":       "75%  — Fuzzy description match",
            "AMOUNT_ONLY": "60%  — Amount only (within 3 days)",
        }

        match_data = [["Strategy", "Confidence Level", "Count"]]
        for match_type, count in sorted(strategy_counts.items(), key=lambda kv: -kv[1]):
            confidence_label = strategy_labels.get(match_type, "—")
            match_data.append([match_type, confidence_label, str(count)])

        story.append(_three_column_table(match_data))

    # --- Exception summary --------------------------------------------------

    if exception_rows:
        story.append(Paragraph("Exception Summary", styles["heading"]))

        type_counts: dict[str, int] = {}
        for exc in exception_rows:
            exc_type = exc.get("exception_type") or "UNKNOWN"
            type_counts[exc_type] = type_counts.get(exc_type, 0) + 1

        # Plain-English meaning for each exception code
        exception_meanings = {
            "BANK_ONLY":       "In bank statement but not in ledger",
            "LEDGER_ONLY":     "In ledger but not in bank statement",
            "LARGE_UNMATCHED": "Unmatched transaction above RM threshold",
            "DUPLICATE_BANK":  "Same transaction appears twice in bank statement",
            "AMOUNT_MISMATCH": "Matched by reference but amounts differ",
            "DATE_MISMATCH":   "Matched by amount/description but dates differ",
        }

        exc_summary_data = [["Exception Type", "Count", "Meaning"]]
        for exc_type, count in sorted(type_counts.items()):
            meaning = exception_meanings.get(exc_type, "—")
            exc_summary_data.append([exc_type, str(count), meaning])

        story.append(_three_column_table(exc_summary_data))

        # Detail rows — cap at MAX_EXCEPTION_DETAIL_ROWS to keep the PDF readable
        detail_rows = exception_rows[:MAX_EXCEPTION_DETAIL_ROWS]
        truncated   = len(exception_rows) > MAX_EXCEPTION_DETAIL_ROWS

        heading_text = (
            f"Exception Details (showing {len(detail_rows)} of {len(exception_rows)})"
            if truncated
            else "Exception Details"
        )
        story.append(Paragraph(heading_text, styles["heading"]))

        detail_data = [["Source", "Type", "Date", "Description", "Amount (RM)"]]
        for exc in detail_rows:
            raw_amount = exc.get("amount")
            amount_str = f"{raw_amount:,.2f}" if raw_amount is not None else "—"
            description = (exc.get("description") or "—")[:48]

            detail_data.append([
                exc.get("source") or "—",
                exc.get("exception_type") or "—",
                str(exc.get("txn_date") or "—"),
                description,
                amount_str,
            ])

        story.append(_exception_detail_table(detail_data))

    # --- Footer -------------------------------------------------------------

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOUR_LIGHT_GREY))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  "
        "Bank Statement Parser & Reconciliation Automation",
        styles["footer"],
    ))

    return story


# ---------------------------------------------------------------------------
# Table builders — shared styling helpers
# ---------------------------------------------------------------------------

def _two_column_table(data: list[list]) -> Table:
    """Styled two-column label/value table for the statistics section."""
    col_widths = [9 * cm, 8 * cm]
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0),  COLOUR_DARK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  COLOUR_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  10),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        # Body rows — alternating backgrounds
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOUR_WHITE, COLOUR_ALT_ROW]),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 10),
        # Bold label column
        ("FONTNAME",      (0, 1), (0, -1),  "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1, -1), 0.5, COLOUR_LIGHT_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    return table


def _three_column_table(data: list[list]) -> Table:
    """Styled three-column table for match breakdown and exception summary."""
    col_widths = [5 * cm, 7 * cm, 5 * cm]
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  COLOUR_DARK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  COLOUR_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  10),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOUR_WHITE, COLOUR_ALT_ROW]),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 10),
        ("GRID",          (0, 0), (-1, -1), 0.5, COLOUR_LIGHT_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    return table


def _exception_detail_table(data: list[list]) -> Table:
    """Compact five-column table for the exception detail rows."""
    col_widths = [2 * cm, 3.5 * cm, 2.8 * cm, 6.5 * cm, 2.7 * cm]
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  COLOUR_DARK_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  COLOUR_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COLOUR_WHITE, COLOUR_ALT_ROW]),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.5, COLOUR_LIGHT_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        # Right-align the amount column
        ("ALIGN",         (4, 1), (4, -1),  "RIGHT"),
    ]))
    return table