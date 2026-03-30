"""
public_bank_parser.py — Public Bank Berhad statement parser (PDF and CSV).

Public Bank statement characteristics:
  PDF: table with columns — Date, Transaction Description,
       Withdrawal/Debit, Deposit/Credit, Balance
       Account number is 10-12 digits.
       Period appears as "Statement Date: DD/MM/YYYY to DD/MM/YYYY" or
       "Period: DD/MM/YYYY - DD/MM/YYYY"

  CSV: exported from PBe (Public Bank online) — columns are
       Transaction Date, Description, Debit, Credit, Balance.
       Account number appears in the first few metadata rows.

Both parsers inherit from the generic parser and only override what is
specific to Public Bank's format.

Usage:
    parser = PublicBankParser(file_path="publicbank_statement.pdf")
    transactions = parser.parse()
    account = parser.extract_account_number()
"""

import logging
import re
from datetime import date
from typing import Optional

from src.parsers.csv_parser import CSVParser
from src.parsers.pdf_parser import PDFParser
from src.utils.normaliser import parse_date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public Bank-specific column name variants
# ---------------------------------------------------------------------------

PBB_DATE_COLUMNS = [
    "date", "transaction date", "txn date", "trans. date",
    "trans date", "value date", "posting date",
]

PBB_DESCRIPTION_COLUMNS = [
    "transaction description", "description", "particulars",
    "details", "narration", "transaction details", "remarks",
]

PBB_DEBIT_COLUMNS = [
    "withdrawal", "debit", "withdrawal (rm)", "debit (rm)",
    "dr", "dr (rm)", "debit amount", "cheque/withdrawal",
]

PBB_CREDIT_COLUMNS = [
    "deposit", "credit", "deposit (rm)", "credit (rm)",
    "cr", "cr (rm)", "credit amount", "deposit/credit",
]

PBB_BALANCE_COLUMNS = [
    "balance", "running balance", "balance (rm)",
    "closing balance", "available balance",
]

PBB_REFERENCE_COLUMNS = [
    "reference", "ref", "cheque no", "cheque no.", "ref no",
    "transaction ref", "txn ref", "cheque/ref",
]

# Public Bank account numbers are 10-12 digits
PBB_ACCOUNT_PATTERN = re.compile(r"\b(\d{10,12})\b")

# Public Bank period patterns
PBB_PERIOD_PATTERN = re.compile(
    r"(?:statement date|period|from)[:\s]+"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"
    r"\s*(?:to|–|-)\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    re.IGNORECASE,
)

# Credit keywords common in Public Bank descriptions
PBB_CREDIT_KEYWORDS = {
    "salary", "credit", "deposit", "received", "receive",
    "refund", "interest", "dividend", "bonus", "cashback",
    "transfer in", "incoming", "ibft in", "fpx cr",
    "giro credit", "interbank transfer in",
}


class PublicBankPDFParser(PDFParser):
    """
    Parser for Public Bank statement PDFs.

    Extends the generic PDFParser with Public Bank-specific column aliases
    and account number / statement period extraction.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="PUBLIC_BANK")

    def extract_account_number(self) -> Optional[str]:
        """Extract Public Bank's 10-12 digit account number from the header."""
        text = self._get_full_text(max_pages=2)
        if not text:
            return None

        match = PBB_ACCOUNT_PATTERN.search(text)
        return match.group(1) if match else None

    def extract_statement_period(self) -> tuple[date, date]:
        """Extract the statement period from Public Bank-specific header text."""
        text = self._get_full_text(max_pages=2)
        if text:
            match = PBB_PERIOD_PATTERN.search(text)
            if match:
                start = parse_date(match.group(1))
                end   = parse_date(match.group(2))
                if start and end:
                    return start, end

        # Fallback to transaction date range
        transactions = self.parse()
        return self.get_date_range_from_transactions(transactions)

    def _classify_text_amount(
        self, amount_str: str, description: str
    ) -> tuple[float, float]:
        """
        Public Bank-specific debit/credit classification for text-mode PDFs.

        Public Bank sometimes appends "CR" or "DR" to the amount string.
        """
        from src.utils.normaliser import parse_amount

        amount = parse_amount(amount_str)
        upper  = amount_str.upper()

        if upper.endswith("CR") or " CR " in upper:
            return 0.0, amount
        if upper.endswith("DR") or " DR " in upper:
            return amount, 0.0

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in PBB_CREDIT_KEYWORDS):
            return 0.0, amount

        return amount, 0.0  # Default to debit

    def _detect_table_columns(self, header: list[str]) -> dict[str, Optional[int]]:
        """Use Public Bank-specific column name lists for table column detection."""

        def find_index(candidate_names: list[str]) -> Optional[int]:
            candidate_set = {name.lower().strip() for name in candidate_names}
            for index, cell in enumerate(header):
                if cell.lower().strip() in candidate_set:
                    return index
            return None

        return {
            "transaction_date": find_index(PBB_DATE_COLUMNS),
            "description":      find_index(PBB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_index(PBB_DEBIT_COLUMNS),
            "credit_amount":    find_index(PBB_CREDIT_COLUMNS),
            "amount":           None,  # Public Bank uses split debit/credit columns
            "balance":          find_index(PBB_BALANCE_COLUMNS),
            "reference":        find_index(PBB_REFERENCE_COLUMNS),
        }


class PublicBankCSVParser(CSVParser):
    """
    Parser for Public Bank statement CSVs (exported from PBe online banking).

    Extends the generic CSVParser with Public Bank-specific column name aliases.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="PUBLIC_BANK")

    def extract_account_number(self) -> Optional[str]:
        """Extract Public Bank's account number from the CSV metadata rows."""
        try:
            raw_text = self.file_path.read_text(encoding="utf-8", errors="replace")
            match    = PBB_ACCOUNT_PATTERN.search(raw_text[:500])
            return match.group(1) if match else None
        except Exception as e:
            logger.debug("Could not read CSV for Public Bank account number: %s", e)
            return None

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """Use Public Bank-specific column name lists."""
        from src.parsers.csv_parser import find_matching_column

        return {
            "transaction_date": find_matching_column(columns, PBB_DATE_COLUMNS),
            "value_date":       None,
            "description":      find_matching_column(columns, PBB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_matching_column(columns, PBB_DEBIT_COLUMNS),
            "credit_amount":    find_matching_column(columns, PBB_CREDIT_COLUMNS),
            "amount":           None,
            "balance":          find_matching_column(columns, PBB_BALANCE_COLUMNS),
            "reference":        find_matching_column(columns, PBB_REFERENCE_COLUMNS),
        }


class PublicBankParser:
    """
    Entry point for Public Bank statement parsing.

    Automatically selects PublicBankPDFParser or PublicBankCSVParser based on
    the file extension.

    Usage:
        parser = PublicBankParser(file_path="publicbank_statement.pdf")
        transactions = parser.parse()
    """

    def __new__(cls, file_path: str):
        from pathlib import Path
        extension = Path(file_path).suffix.lower()

        if extension == ".pdf":
            return PublicBankPDFParser(file_path=file_path)
        elif extension == ".csv":
            return PublicBankCSVParser(file_path=file_path)
        else:
            raise ValueError(
                f"Public Bank parser supports .pdf and .csv files. Got: {extension}"
            )