"""
cimb_parser.py — CIMB Bank statement parser (PDF and CSV).

CIMB statement characteristics:
  PDF: table with columns — Date, Description/Particulars, Debit (RM), Credit (RM), Balance (RM)
       Account number is 14 digits.
       Period appears as "Statement Date: DD/MM/YYYY" or "From DD/MM/YYYY To DD/MM/YYYY"
  CSV: exported from CIMB Clicks — columns are Date, Description, Debit, Credit, Balance
       with an account number in the first few metadata rows.

Both parsers inherit from the generic parser and only override what is
specific to CIMB's format — column name aliases and metadata extraction.

Usage:
    parser = CIMBParser(file_path="cimb_statement.pdf", bank_name="CIMB")
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
# CIMB-specific column name variants
#
# CIMB uses "(RM)" suffixed column headers and sometimes splits the date
# into "Posting Date" and "Transaction Date".
# ---------------------------------------------------------------------------

CIMB_DATE_COLUMNS = [
    "date", "transaction date", "posting date", "txn date",
    "trans. date", "trans date",
]

CIMB_DESCRIPTION_COLUMNS = [
    "description", "particulars", "transaction description",
    "details", "txn description", "narration",
]

CIMB_DEBIT_COLUMNS = [
    "debit (rm)", "debit", "withdrawal (rm)", "withdrawal",
    "dr (rm)", "dr", "debit amount",
]

CIMB_CREDIT_COLUMNS = [
    "credit (rm)", "credit", "deposit (rm)", "deposit",
    "cr (rm)", "cr", "credit amount",
]

CIMB_BALANCE_COLUMNS = [
    "balance (rm)", "balance", "running balance", "closing balance",
]

CIMB_REFERENCE_COLUMNS = [
    "cheque no.", "cheque no", "reference", "ref no", "ref",
]

# CIMB account numbers are 14 digits
CIMB_ACCOUNT_PATTERN = re.compile(r"\b(\d{14})\b")

# CIMB statement period patterns
CIMB_PERIOD_PATTERN = re.compile(
    r"(?:from|period|statement date)[:\s]+"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"
    r"\s+(?:to|–|-)\s+"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    re.IGNORECASE,
)

# Credit keywords common in CIMB descriptions
CIMB_CREDIT_KEYWORDS = {
    "salary", "credit", "deposit", "receive", "refund",
    "rebate", "interest", "bonus", "cashback", "incoming",
    "transfer in", "giro cr", "fpx cr", "ibft cr",
}


class CIMBPDFParser(PDFParser):
    """
    Parser for CIMB bank statement PDFs.

    Extends the generic PDFParser with CIMB-specific column aliases
    and account number / statement period extraction.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="CIMB")

    def extract_account_number(self) -> Optional[str]:
        """Extract CIMB's 14-digit account number from the statement header."""
        text = self._get_full_text(max_pages=2)
        if not text:
            return None

        match = CIMB_ACCOUNT_PATTERN.search(text)
        return match.group(1) if match else None

    def extract_statement_period(self) -> tuple[date, date]:
        """Extract the statement period from CIMB-specific header text."""
        text = self._get_full_text(max_pages=2)
        if text:
            match = CIMB_PERIOD_PATTERN.search(text)
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
        Override the generic heuristic with CIMB-specific credit keywords.

        CIMB descriptions often include "CR" or "DR" as a suffix in
        text-mode PDFs. Check that first, then fall back to keywords.
        """
        from src.utils.normaliser import parse_amount

        amount = parse_amount(amount_str)
        upper = amount_str.upper()

        if upper.endswith("CR") or " CR " in upper:
            return 0.0, amount
        if upper.endswith("DR") or " DR " in upper:
            return amount, 0.0

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in CIMB_CREDIT_KEYWORDS):
            return 0.0, amount

        return amount, 0.0  # Default to debit

    def _detect_table_columns(self, header: list[str]) -> dict[str, Optional[int]]:
        """Use CIMB-specific column name lists for table column detection."""

        def find_index(candidate_names: list[str]) -> Optional[int]:
            candidate_set = {name.lower().strip() for name in candidate_names}
            for index, cell in enumerate(header):
                if cell.lower().strip() in candidate_set:
                    return index
            return None

        return {
            "transaction_date": find_index(CIMB_DATE_COLUMNS),
            "description":      find_index(CIMB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_index(CIMB_DEBIT_COLUMNS),
            "credit_amount":    find_index(CIMB_CREDIT_COLUMNS),
            "amount":           None,  # CIMB always uses split columns
            "balance":          find_index(CIMB_BALANCE_COLUMNS),
            "reference":        find_index(CIMB_REFERENCE_COLUMNS),
        }


class CIMBCSVParser(CSVParser):
    """
    Parser for CIMB bank statement CSVs (exported from CIMB Clicks).

    Extends the generic CSVParser with CIMB-specific column name aliases.
    The generic header-row auto-detection handles CIMB's metadata rows
    at the top of the file automatically.
    """

    def __init__(self, file_path: str):
        super().__init__(file_path=file_path, bank_name="CIMB")

    def extract_account_number(self) -> Optional[str]:
        """Extract CIMB's 14-digit account number from the CSV metadata rows."""
        try:
            raw_text = self.file_path.read_text(encoding="utf-8", errors="replace")
            match = CIMB_ACCOUNT_PATTERN.search(raw_text[:500])  # Only scan header area
            return match.group(1) if match else None
        except Exception as e:
            logger.debug("Could not read CSV for account number: %s", e)
            return None

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """Use CIMB-specific column name lists."""
        from src.parsers.csv_parser import find_matching_column

        return {
            "transaction_date": find_matching_column(columns, CIMB_DATE_COLUMNS),
            "value_date":       None,
            "description":      find_matching_column(columns, CIMB_DESCRIPTION_COLUMNS),
            "debit_amount":     find_matching_column(columns, CIMB_DEBIT_COLUMNS),
            "credit_amount":    find_matching_column(columns, CIMB_CREDIT_COLUMNS),
            "amount":           None,
            "balance":          find_matching_column(columns, CIMB_BALANCE_COLUMNS),
            "reference":        find_matching_column(columns, CIMB_REFERENCE_COLUMNS),
        }


class CIMBParser:
    """
    Entry point for CIMB statement parsing.

    Automatically selects CIMBPDFParser or CIMBCSVParser based on
    the file extension. Use this class in the CLI and Streamlit UI.

    Usage:
        parser = CIMBParser(file_path="statement.pdf")
        transactions = parser.parse()
    """

    def __new__(cls, file_path: str):
        from pathlib import Path
        extension = Path(file_path).suffix.lower()

        if extension == ".pdf":
            return CIMBPDFParser(file_path=file_path)
        elif extension == ".csv":
            return CIMBCSVParser(file_path=file_path)
        else:
            raise ValueError(
                f"CIMB parser supports .pdf and .csv files. Got: {extension}"
            )
