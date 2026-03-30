"""
hlb_parser.py — Hong Leong Bank (HLB) statement parser (PDF and Excel).

HLB statement characteristics:
  PDF: table with columns — Date, Transaction Description,
       Withdrawal (DR), Deposit (CR), Balance
       Account number is 10-12 digits.
       Period appears as "Statement Period: DD/MM/YYYY - DD/MM/YYYY"

  Excel: exported from HLB Connect — same column structure as PDF but
         in .xlsx format. Often has merged cells in the header section
         containing account details before the transaction table.

Both parsers inherit from the generic parser and only override what is
specific to HLB's format.

Usage:
    parser = HLBParser(file_path="hlb_statement.pdf")
    transactions = parser.parse()
"""

import logging
import re
from datetime import date
from typing import Optional

from src.parsers.excel_parser import ExcelParser
from src.parsers.pdf_parser import PDFParser
from src.utils.normaliser import parse_date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HLB-specific column name variants
# ---------------------------------------------------------------------------

HLB_DATE_COLUMNS = [
    "date", "transaction date", "txn date", "trans date",
    "value date", "posting date",
]

HLB_DESCRIPTION_COLUMNS = [
    "transaction description", "description", "particulars",
    "details", "narration", "remarks",
]

HLB_DEBIT_COLUMNS = [
    "withdrawal (dr)", "withdrawal(dr)", "withdrawal",
    "debit", "dr", "debit (rm)", "debit amount",
]

HLB_CREDIT_COLUMNS = [
    "deposit (cr)", "deposit(cr)", "deposit",
    "credit", "cr", "credit (rm)", "credit amount",
]

HLB_BALANCE_COLUMNS = [
    "balance", "running balance", "available balance",
    "closing balance", "balance (rm)",
]

HLB_REFERENCE_COLUMNS = [
    "reference", "ref", "cheque no", "cheque number",
    "txn ref", "transaction ref",
]

# HLB account numbers are 10-12 digits
HLB_ACCOUNT_PATTERN = re.compile(r"\b(\d{10,12})\b")

# HLB period pattern: "Statement Period: 01/03/2026 - 31/03/2026"
HLB_PERIOD_PATTERN = re.compile(
    r"(?:statement period|period)[:\s]+"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"
    r"\s*(?:to|–|-)\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    re.IGNORECASE,
)

# Credit keywords common in HLB descriptions
HLB_CREDIT_KEYWORDS = {
    "salary", "credit", "deposit cr", "incoming", "receive",
    "refund", "interest", "dividend", "bonus", "cashback",
    "transfer in", "ibft in", "fpx payment received",
}


class HLBPDFParser(PDFParser):
    """
    Parser for Hong Leong Bank statement PDFs.

    Extends the generic PDFParser with HLB-specific column aliases
    and metadata extraction.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="HLB")

    def extract_account_number(self) -> Optional[str]:
        """Extract HLB's 10-12 digit account number from the statement header."""
        text = self._get_full_text(max_pages=2)
        if not text:
            return None

        match = HLB_ACCOUNT_PATTERN.search(text)
        return match.group(1) if match else None

    def extract_statement_period(self) -> tuple[date, date]:
        """Extract the statement period from HLB-specific header text."""
        text = self._get_full_text(max_pages=2)
        if text:
            match = HLB_PERIOD_PATTERN.search(text)
            if match:
                start = parse_date(match.group(1))
                end   = parse_date(match.group(2))
                if start and end:
                    return start, end

        transactions = self.parse()
        return self.get_date_range_from_transactions(transactions)

    def _classify_text_amount(
        self, amount_str: str, description: str
    ) -> tuple[float, float]:
        """
        HLB-specific debit/credit classification for text-mode PDFs.

        HLB uses "DR" and "CR" suffixes on amounts in some PDF exports.
        """
        from src.utils.normaliser import parse_amount

        amount = parse_amount(amount_str)
        upper = amount_str.upper()

        if upper.endswith("CR") or " CR" in upper:
            return 0.0, amount
        if upper.endswith("DR") or " DR" in upper:
            return amount, 0.0

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in HLB_CREDIT_KEYWORDS):
            return 0.0, amount

        return amount, 0.0

    def _detect_table_columns(self, header: list[str]) -> dict[str, Optional[int]]:
        """Use HLB-specific column name lists for table column detection."""

        def find_index(candidate_names: list[str]) -> Optional[int]:
            candidate_set = {name.lower().strip() for name in candidate_names}
            for index, cell in enumerate(header):
                if cell.lower().strip() in candidate_set:
                    return index
            return None

        return {
            "transaction_date": find_index(HLB_DATE_COLUMNS),
            "description":      find_index(HLB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_index(HLB_DEBIT_COLUMNS),
            "credit_amount":    find_index(HLB_CREDIT_COLUMNS),
            "amount":           None,
            "balance":          find_index(HLB_BALANCE_COLUMNS),
            "reference":        find_index(HLB_REFERENCE_COLUMNS),
        }


class HLBExcelParser(ExcelParser):
    """
    Parser for Hong Leong Bank statement Excel files (.xlsx).

    Extends the generic ExcelParser with HLB-specific column name aliases.
    The generic header-row auto-detection handles merged cells and metadata
    rows above the transaction table.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="HLB")

    def extract_account_number(self) -> Optional[str]:
        """Extract HLB's 10-12 digit account number from the Excel metadata rows."""
        import pandas as pd

        try:
            raw_df = pd.read_excel(
                self.file_path,
                header=None,
                dtype=str,
                sheet_name=self.sheet_index,
                engine=self._pick_engine(),
            )
            for row_index in range(min(20, len(raw_df))):
                for cell_value in raw_df.iloc[row_index].values:
                    if pd.isna(cell_value):
                        continue
                    match = HLB_ACCOUNT_PATTERN.search(str(cell_value))
                    if match:
                        return match.group(1)
        except Exception as e:
            logger.debug("Could not extract HLB account number: %s", e)

        return None

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """Use HLB-specific column name lists."""
        from src.parsers.csv_parser import find_matching_column

        return {
            "transaction_date": find_matching_column(columns, HLB_DATE_COLUMNS),
            "value_date":       None,
            "description":      find_matching_column(columns, HLB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_matching_column(columns, HLB_DEBIT_COLUMNS),
            "credit_amount":    find_matching_column(columns, HLB_CREDIT_COLUMNS),
            "amount":           None,
            "balance":          find_matching_column(columns, HLB_BALANCE_COLUMNS),
            "reference":        find_matching_column(columns, HLB_REFERENCE_COLUMNS),
        }


class HLBParser:
    """
    Entry point for HLB statement parsing.

    Automatically selects HLBPDFParser or HLBExcelParser based on
    the file extension.

    Usage:
        parser = HLBParser(file_path="hlb_statement.xlsx")
        transactions = parser.parse()
    """

    def __new__(cls, file_path: str):
        from pathlib import Path
        extension = Path(file_path).suffix.lower()

        if extension == ".pdf":
            return HLBPDFParser(file_path=file_path)
        elif extension in (".xlsx", ".xls"):
            return HLBExcelParser(file_path=file_path)
        else:
            raise ValueError(
                f"HLB parser supports .pdf, .xlsx, and .xls files. Got: {extension}"
            )
