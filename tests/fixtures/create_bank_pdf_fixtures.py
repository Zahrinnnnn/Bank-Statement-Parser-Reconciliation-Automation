"""
create_bank_pdf_fixtures.py — Generates bank-specific PDF fixtures for tests.

Run once to create:
  - sample_cimb.pdf   — CIMB-style statement PDF
  - sample_hlb.pdf    — HLB-style statement PDF

    python tests/fixtures/create_bank_pdf_fixtures.py
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm

OUTPUT_DIR = Path(__file__).parent


def create_cimb_pdf() -> None:
    """CIMB-style PDF with 'Debit (RM)' and 'Credit (RM)' column headers."""
    output_path = OUTPUT_DIR / "sample_cimb.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("CIMB BANK BERHAD", styles["Title"]))
    elements.append(Paragraph("Account No.: 80012345678901", styles["Normal"]))
    elements.append(Paragraph("Account Name: ZAHRIN BIN JASNI", styles["Normal"]))
    elements.append(Paragraph("Statement Period: 01/03/2026 - 31/03/2026", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    table_data = [
        ["Date", "Description", "Debit (RM)", "Credit (RM)", "Balance (RM)"],
        ["03/03/2026", "FPX SHOPEE PAYMENT",              "250.00",  "",        "4750.00"],
        ["05/03/2026", "SALARY CREDIT ACME SDN BHD",      "",        "3500.00", "8250.00"],
        ["08/03/2026", "IBFT TRANSFER TO AHMAD BIN ALI",  "1000.00", "",        "7250.00"],
        ["12/03/2026", "FPX LAZADA ONLINE PURCHASE",      "89.90",   "",        "6960.10"],
        ["15/03/2026", "IBFT RECEIVE FROM SITI HASSAN",   "",        "500.00",  "7460.10"],
        ["18/03/2026", "TT123456 UTILITY BILL TNB",       "156.30",  "",        "7303.80"],
        ["20/03/2026", "CHEQ NO 000123 RENT PAYMENT",     "1500.00", "",        "5803.80"],
        ["25/03/2026", "SALARY BONUS CREDIT ACME",        "",        "800.00",  "6603.80"],
        ["31/03/2026", "BANK SERVICE CHARGES",            "10.00",   "",        "6593.80"],
    ]

    table = Table(table_data, colWidths=[28*mm, 80*mm, 28*mm, 28*mm, 28*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#c00000")),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff0f0")]),
    ]))

    elements.append(table)
    doc.build(elements)
    print(f"Created: {output_path}")


def create_hlb_pdf() -> None:
    """HLB-style PDF with 'Withdrawal (DR)' and 'Deposit (CR)' column headers."""
    output_path = OUTPUT_DIR / "sample_hlb.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("HONG LEONG BANK BERHAD", styles["Title"]))
    elements.append(Paragraph("Account Number: 1234567890", styles["Normal"]))
    elements.append(Paragraph("Account Holder: ZAHRIN BIN JASNI", styles["Normal"]))
    elements.append(Paragraph("Statement Period: 01/03/2026 - 31/03/2026", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    table_data = [
        ["Date", "Transaction Description", "Withdrawal (DR)", "Deposit (CR)", "Balance"],
        ["03/03/2026", "FPX SHOPEE PAYMENT",            "250.00",  "",        "4750.00"],
        ["05/03/2026", "SALARY CREDIT ACME SDN BHD",    "",        "3500.00", "8250.00"],
        ["08/03/2026", "IBG TRANSFER OUT AHMAD ALI",    "1000.00", "",        "7250.00"],
        ["15/03/2026", "IBFT IN FROM SITI HASSAN",      "",        "500.00",  "7750.00"],
        ["18/03/2026", "TT789012 UTILITY TNB PAYMENT",  "156.30",  "",        "7593.70"],
        ["20/03/2026", "CHEQ000456 RENT PAYMENT",       "1500.00", "",        "6093.70"],
        ["25/03/2026", "BONUS CREDIT ACME SDN BHD",     "",        "800.00",  "6893.70"],
        ["31/03/2026", "SERVICE CHARGE",                "10.00",   "",        "6883.70"],
    ]

    table = Table(table_data, colWidths=[28*mm, 80*mm, 30*mm, 28*mm, 26*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#003399")),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0ff")]),
    ]))

    elements.append(table)
    doc.build(elements)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    create_cimb_pdf()
    create_hlb_pdf()
    print("Done.")
