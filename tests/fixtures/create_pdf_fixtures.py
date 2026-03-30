"""
create_pdf_fixtures.py — Generates sample PDF fixtures for parser tests.

Run once to create the PDF files used by test_pdf_parser.py:
    python tests/fixtures/create_pdf_fixtures.py

Creates:
  - sample_table_pdf.pdf  — PDF with an embedded table (table-mode parsing)
  - sample_text_pdf.pdf   — PDF with plain text lines (text-mode parsing)
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm

OUTPUT_DIR = Path(__file__).parent


def create_table_pdf() -> None:
    """Create a PDF that contains an actual embedded table."""
    output_path = OUTPUT_DIR / "sample_table_pdf.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Metadata header (like a real bank statement header)
    elements.append(Paragraph("GENERIC TEST BANK BERHAD", styles["Title"]))
    elements.append(Paragraph("Account Number: 1234567890", styles["Normal"]))
    elements.append(Paragraph("Statement Period: 01/03/2026 to 31/03/2026", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    # Transaction table
    table_data = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["03/03/2026", "FPX SHOPEE PAYMENT", "250.00", "", "4750.00"],
        ["05/03/2026", "SALARY CREDIT ACME SDN BHD", "", "3500.00", "8250.00"],
        ["08/03/2026", "IBG TRANSFER TO AHMAD BIN ALI", "1000.00", "", "7250.00"],
        ["15/03/2026", "IBFT RECEIVE FROM SITI HASSAN", "", "500.00", "7750.00"],
        ["18/03/2026", "TT123456 UTILITY BILL TNB", "156.30", "", "7593.70"],
        ["20/03/2026", "CHEQ 000123 RENT PAYMENT", "1500.00", "", "6093.70"],
        ["25/03/2026", "SALARY BONUS ACME SDN BHD", "", "800.00", "6893.70"],
        ["31/03/2026", "BANK CHARGES", "10.00", "", "6883.70"],
    ]

    table = Table(table_data, colWidths=[30*mm, 80*mm, 30*mm, 30*mm, 30*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ]))

    elements.append(table)
    doc.build(elements)
    print(f"Created: {output_path}")


def create_text_pdf() -> None:
    """Create a PDF with plain text lines — no embedded tables."""
    output_path = OUTPUT_DIR / "sample_text_pdf.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("GENERIC TEST BANK BERHAD", styles["Title"]))
    elements.append(Paragraph("Account Number: 9876543210", styles["Normal"]))
    elements.append(Paragraph("Statement Period: 01/03/2026 to 31/03/2026", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph("Date        Description                          Amount      Balance", styles["Code"]))
    elements.append(Spacer(1, 3 * mm))

    # Plain text lines — no table structure
    lines = [
        "03/03/2026  FPX SHOPEE PAYMENT                   250.00      4750.00",
        "05/03/2026  SALARY CREDIT ACME SDN BHD           3500.00     8250.00",
        "08/03/2026  IBG TRANSFER OUT TO AHMAD ALI         1000.00     7250.00",
        "18/03/2026  TT123456 UTILITY BILL TNB             156.30      7093.70",
        "20/03/2026  CHEQ000123 RENT PAYMENT               1500.00     5593.70",
    ]
    for line in lines:
        elements.append(Paragraph(line, styles["Code"]))
        elements.append(Spacer(1, 2 * mm))

    doc.build(elements)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    create_table_pdf()
    create_text_pdf()
    print("Done.")
