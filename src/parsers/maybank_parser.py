"""
maybank_parser.py — Maybank (Malayan Banking Berhad) statement parser (PDF and CSV).

Maybank statement characteristics:
  PDF: table with columns — Date, Description, Debit, Credit, Balance
       Account number is 12 digits (e.g. 564312345678).
       Period appears as "From DD/MM/YYYY to DD/MM/YYYY" or
       "Statement Date: DD/MM/YYYY"

  CSV: exported from Maybank2u — columns are Transaction Date, Description,
       Debit, Credit, Balance.  Account number appears in the first few
       metadata rows.

Both parsers inherit from the generic parser and only override what is
specific to Maybank's format — column name aliases and metadata extraction.

Usage:
    parser = MaybankParser(file_path="maybank_statement.pdf")
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
# Maybank-specific column name variants
# ---------------------------------------------------------------------------

MAYBANK_DATE_COLUMNS = [
    "date", "transaction date", "txn date", "trans. date",
    "trans date", "value date",
]

MAYBANK_DESCRIPTION_COLUMNS = [
    "description", "particulars", "transaction description",
    "details", "narration", "transaction details",
]

MAYBANK_DEBIT_COLUMNS = [
    "debit", "withdrawal", "debit (rm)", "withdrawal (rm)",
    "dr", "dr (rm)", "debit amount",
]

MAYBANK_CREDIT_COLUMNS = [
    "credit", "deposit", "credit (rm)", "deposit (rm)",
    "cr", "cr (rm)", "credit amount",
]

MAYBANK_BALANCE_COLUMNS = [
    "balance", "running balance", "balance (rm)",
    "closing balance", "available balance",
]

MAYBANK_REFERENCE_COLUMNS = [
    "reference", "ref", "cheque no", "cheque no.", "ref no",
    "transaction ref", "txn ref",
]

# Maybank account numbers are 12 digits
MAYBANK_ACCOUNT_PATTERN = re.compile(r"\b(\d{12})\b")

# Maybank period patterns
MAYBANK_PERIOD_PATTERN = re.compile(
    r"(?:from|period|statement date|date)[:\s]+"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"
    r"\s*(?:to|–|-)\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    re.IGNORECASE,
)

# Credit keywords common in Maybank descriptions
MAYBANK_CREDIT_KEYWORDS = {
    "salary", "credit", "deposit", "received", "receive",
    "refund", "rebate", "interest", "bonus", "cashback",
    "transfer in", "incoming", "ibft in", "fpx cr",
    "giro cr", "maybank2u cr", "m2u cr",
}


class MaybankPDFParser(PDFParser):
    """
    Parser for Maybank statement PDFs.

    Extends the generic PDFParser with Maybank-specific column aliases
    and account number / statement period extraction.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="MAYBANK")

    def extract_account_number(self) -> Optional[str]:
        """Extract Maybank's 12-digit account number from the statement header."""
        text = self._get_full_text(max_pages=2)
        if not text:
            return None

        match = MAYBANK_ACCOUNT_PATTERN.search(text)
        return match.group(1) if match else None

    def extract_statement_period(self) -> tuple[date, date]:
        """Extract the statement period from Maybank-specific header text."""
        text = self._get_full_text(max_pages=2)
        if text:
            match = MAYBANK_PERIOD_PATTERN.search(text)
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
        Maybank-specific debit/credit classification for text-mode PDFs.

        Maybank sometimes appends "CR" or "DR" to the amount string.
        """
        from src.utils.normaliser import parse_amount

        amount = parse_amount(amount_str)
        upper  = amount_str.upper()

        if upper.endswith("CR") or " CR " in upper:
            return 0.0, amount
        if upper.endswith("DR") or " DR " in upper:
            return amount, 0.0

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in MAYBANK_CREDIT_KEYWORDS):
            return 0.0, amount

        return amount, 0.0  # Default to debit

    def _detect_table_columns(self, header: list[str]) -> dict[str, Optional[int]]:
        """Use Maybank-specific column name lists for table column detection."""

        def find_index(candidate_names: list[str]) -> Optional[int]:
            candidate_set = {name.lower().strip() for name in candidate_names}
            for index, cell in enumerate(header):
                if cell.lower().strip() in candidate_set:
                    return index
            return None

        return {
            "transaction_date": find_index(MAYBANK_DATE_COLUMNS),
            "description":      find_index(MAYBANK_DESCRIPTION_COLUMNS),
            "debit_amount":     find_index(MAYBANK_DEBIT_COLUMNS),
            "credit_amount":    find_index(MAYBANK_CREDIT_COLUMNS),
            "amount":           None,  # Maybank always uses split columns
            "balance":          find_index(MAYBANK_BALANCE_COLUMNS),
            "reference":        find_index(MAYBANK_REFERENCE_COLUMNS),
        }


class MaybankCSVParser(CSVParser):
    """
    Parser for Maybank statement CSVs (exported from Maybank2u).

    Extends the generic CSVParser with Maybank-specific column name aliases.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="MAYBANK")

    def extract_account_number(self) -> Optional[str]:
        """Extract Maybank's 12-digit account number from the CSV metadata rows."""
        try:
            raw_text = self.file_path.read_text(encoding="utf-8", errors="replace")
            match    = MAYBANK_ACCOUNT_PATTERN.search(raw_text[:500])
            return match.group(1) if match else None
        except Exception as e:
            logger.debug("Could not read CSV for Maybank account number: %s", e)
            return None

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """Use Maybank-specific column name lists."""
        from src.parsers.csv_parser import find_matching_column

        return {
            "transaction_date": find_matching_column(columns, MAYBANK_DATE_COLUMNS),
            "value_date":       None,
            "description":      find_matching_column(columns, MAYBANK_DESCRIPTION_COLUMNS),
            "debit_amount":     find_matching_column(columns, MAYBANK_DEBIT_COLUMNS),
            "credit_amount":    find_matching_column(columns, MAYBANK_CREDIT_COLUMNS),
            "amount":           None,
            "balance":          find_matching_column(columns, MAYBANK_BALANCE_COLUMNS),
            "reference":        find_matching_column(columns, MAYBANK_REFERENCE_COLUMNS),
        }


class MaybankParser:
    """
    Entry point for Maybank statement parsing.

    Automatically selects MaybankPDFParser or MaybankCSVParser based on
    the file extension.

    Usage:
        parser = MaybankParser(file_path="maybank_statement.pdf")
        transactions = parser.parse()
    """

    def __new__(cls, file_path: str):
        from pathlib import Path
        extension = Path(file_path).suffix.lower()

        if extension == ".pdf":
            return MaybankPDFParser(file_path=file_path)
        elif extension == ".csv":
            return MaybankCSVParser(file_path=file_path)
        else:
            raise ValueError(
                f"Maybank parser supports .pdf and .csv files. Got: {extension}"
            )