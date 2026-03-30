"""
create_maybank_public_bank_fixtures.py — Generate sample PDF fixtures
for Maybank and Public Bank parsers using reportlab.

Run from the project root:
    python tests/fixtures/create_maybank_public_bank_fixtures.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors


OUTPUT_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Maybank PDF fixture
# ---------------------------------------------------------------------------

def create_maybank_pdf() -> None:
    output_path = OUTPUT_DIR / "sample_maybank.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("MALAYAN BANKING BERHAD", styles["Title"]))
    story.append(Paragraph("Current Account Statement", styles["Heading2"]))
    story.append(Paragraph("Account Number: 564312345678", styles["Normal"]))
    story.append(Paragraph("Account Name: AHMAD BIN ALI", styles["Normal"]))
    story.append(Paragraph("From 01/03/2026 to 31/03/2026", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    table_data = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["03/03/2026", "FPX SHOPEE PAYMENT FPX2026001",    "250.00", "",        "4,750.00"],
        ["05/03/2026", "SALARY CREDIT ACME SDN BHD",       "",       "3,500.00","8,250.00"],
        ["08/03/2026", "IBG TRANSFER OUT IBG20260308",      "1,000.00","",       "7,250.00"],
        ["12/03/2026", "MAYBANK2U BILL PAYMENT TNB",        "156.30", "",        "7,093.70"],
        ["15/03/2026", "ATM CASH WITHDRAWAL",               "500.00", "",        "6,593.70"],
        ["20/03/2026", "INTERBANK GIRO RECEIVED",           "",       "800.00",  "7,393.70"],
        ["25/03/2026", "CREDIT CARD PAYMENT",               "2,000.00","",       "5,393.70"],
    ]

    table = Table(table_data, colWidths=[2.5*cm, 7*cm, 2.5*cm, 2.5*cm, 2.5*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#1F4E79")),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF4FB")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(table)
    doc.build(story)
    print(f"Created: {output_path}")


# ---------------------------------------------------------------------------
# Public Bank PDF fixture
# ---------------------------------------------------------------------------

def create_public_bank_pdf() -> None:
    output_path = OUTPUT_DIR / "sample_public_bank.pdf"
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("PUBLIC BANK BERHAD", styles["Title"]))
    story.append(Paragraph("Savings Account Statement", styles["Heading2"]))
    story.append(Paragraph("Account Number: 1234567890", styles["Normal"]))
    story.append(Paragraph("Account Name: SITI BINTI HASSAN", styles["Normal"]))
    story.append(Paragraph("Statement Date: 01/03/2026 to 31/03/2026", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    table_data = [
        ["Date", "Transaction Description", "Withdrawal", "Deposit", "Balance"],
        ["02/03/2026", "INTERBANK TRANSFER IN",             "",        "2,500.00","7,500.00"],
        ["06/03/2026", "CHEQUE WITHDRAWAL 001234",          "800.00",  "",        "6,700.00"],
        ["10/03/2026", "FPX PAYMENT RECEIVED FPX2026005",   "",        "650.00",  "7,350.00"],
        ["14/03/2026", "ATM CASH WITHDRAWAL",               "300.00",  "",        "7,050.00"],
        ["18/03/2026", "DEBIT CARD PURCHASE GIANT",         "125.50",  "",        "6,924.50"],
        ["22/03/2026", "SALARY CREDIT",                     "",        "4,500.00","11,424.50"],
        ["28/03/2026", "BILL PAYMENT TELEKOM",              "88.00",   "",        "11,336.50"],
    ]

    table = Table(table_data, colWidths=[2.5*cm, 7*cm, 2.5*cm, 2.5*cm, 2.5*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#C00000")),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF0F0")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(table)
    doc.build(story)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    create_maybank_pdf()
    create_public_bank_pdf()
    print("Done.")