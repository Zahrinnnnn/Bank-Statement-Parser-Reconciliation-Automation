"""
csv_parser.py — Generic CSV bank statement parser.

Works with any CSV that has recognisable column headers.
Auto-detects which columns hold dates, descriptions, amounts,
and balances by matching headers against known name variants.

Handles two common amount layouts:
  1. Split columns  — separate Debit and Credit columns
  2. Single column  — one Amount column with Dr/Cr suffix or sign

Usage:
    parser = CSVParser(file_path="statement.csv", bank_name="CIMB")
    transactions = parser.parse()
"""

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base_parser import BaseParser, ParsedTransaction
from src.utils.normaliser import (
    clean_description,
    extract_reference,
    parse_amount,
    parse_date,
    split_debit_credit,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column name mappings
#
# Each key is the internal field name. The list contains all the header
# variants that different banks use for that field. Matching is
# case-insensitive and strips surrounding whitespace.
# ---------------------------------------------------------------------------

DATE_COLUMN_NAMES = [
    "date", "transaction date", "txn date", "trans date",
    "posting date", "value date", "tarikh",
]

VALUE_DATE_COLUMN_NAMES = [
    "value date", "val date", "value_date",
]

DESCRIPTION_COLUMN_NAMES = [
    "description", "particulars", "details", "narration",
    "transaction description", "txn description", "keterangan",
    "remarks", "reference description",
]

DEBIT_COLUMN_NAMES = [
    "debit", "withdrawal", "dr", "debit amount",
    "withdrawal amount", "debit (dr)",
]

CREDIT_COLUMN_NAMES = [
    "credit", "deposit", "cr", "credit amount",
    "deposit amount", "credit (cr)",
]

# Single-column amount layouts — used when there's no separate debit/credit
AMOUNT_COLUMN_NAMES = [
    "amount", "transaction amount", "txn amount",
]

BALANCE_COLUMN_NAMES = [
    "balance", "running balance", "closing balance",
    "baki", "available balance",
]

REFERENCE_COLUMN_NAMES = [
    "reference", "ref", "cheque no", "cheque number",
    "transaction ref", "txn ref", "reference no",
]


def find_matching_column(
    dataframe_columns: list[str], candidate_names: list[str]
) -> Optional[str]:
    """
    Find the first column in the dataframe whose name (lowercased, stripped)
    matches any of the candidate names.

    Returns the actual column name as it appears in the dataframe, or None.
    """
    normalised_candidates = {name.lower().strip() for name in candidate_names}

    for col in dataframe_columns:
        if col.lower().strip() in normalised_candidates:
            return col

    return None


class CSVParser(BaseParser):
    """
    Generic CSV parser that auto-detects column layout.

    Tries to find the header row automatically if the CSV has
    non-data rows at the top (e.g. bank name, account number lines).
    """

    def __init__(self, file_path: str, bank_name: str, encoding: str = "utf-8"):
        super().__init__(file_path, bank_name)
        self.encoding = encoding
        self._dataframe: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self) -> list[ParsedTransaction]:
        """Load the CSV and convert every data row into a ParsedTransaction."""
        self._dataframe = self._load_csv()

        if self._dataframe is None or self._dataframe.empty:
            logger.warning("No data found in CSV: %s", self.file_path.name)
            return []

        column_map = self._detect_columns(self._dataframe.columns.tolist())
        logger.debug("Detected column mapping: %s", column_map)

        transactions = []

        for row_index, row in self._dataframe.iterrows():
            transaction = self._parse_row(row, column_map, row_index)
            if transaction is not None:
                transactions.append(transaction)

        self.log_parse_result(transactions)
        return transactions

    def extract_account_number(self) -> Optional[str]:
        """
        Look for an account number in the first few rows of the raw file
        before the header row. Most banks put it there as metadata.
        """
        try:
            # Read the raw file to look at pre-header rows
            raw_lines = self.file_path.read_text(encoding=self.encoding, errors="replace")
            for line in raw_lines.splitlines()[:20]:
                # Account numbers are typically 10-16 digits
                import re
                match = re.search(r"\b(\d{10,16})\b", line)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug("Could not extract account number: %s", e)

        return None

    def extract_statement_period(self) -> tuple[date, date]:
        """Return the date range covered by the parsed transactions."""
        if self._dataframe is None:
            self._dataframe = self._load_csv()

        # Try to get the period from the parsed transactions
        column_map = self._detect_columns(self._dataframe.columns.tolist())
        date_col = column_map.get("transaction_date")

        if date_col and date_col in self._dataframe.columns:
            parsed_dates = [
                parse_date(str(v))
                for v in self._dataframe[date_col].dropna()
            ]
            valid_dates = [d for d in parsed_dates if d is not None]
            if valid_dates:
                return min(valid_dates), max(valid_dates)

        today = date.today()
        return today, today

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_csv(self) -> Optional[pd.DataFrame]:
        """
        Load the CSV file into a DataFrame.

        Tries a few common encodings. Reads the raw text first to locate
        the header row, then loads pandas starting from that row.
        This avoids the "unexpected number of columns" error that happens
        when metadata rows above the header have fewer columns than the data.
        """
        encodings_to_try = [self.encoding, "utf-8-sig", "latin-1", "cp1252"]

        for encoding in encodings_to_try:
            try:
                raw_text = self.file_path.read_text(encoding=encoding, errors="replace")
                header_row_index = self._find_header_row_in_text(raw_text)
                logger.debug("Header row found at index: %d", header_row_index)

                df = pd.read_csv(
                    self.file_path,
                    encoding=encoding,
                    dtype=str,
                    header=0,
                    skiprows=range(header_row_index),   # skip metadata rows above header
                    skip_blank_lines=True,
                )

                # Strip whitespace from all column names
                df.columns = [str(col).strip() for col in df.columns]
                return df

            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error("Failed to load CSV %s: %s", self.file_path.name, e)
                return None

        logger.error("Could not decode CSV with any known encoding: %s", self.file_path.name)
        return None

    def _find_header_row_in_text(self, raw_text: str) -> int:
        """
        Scan the first 20 lines of the raw file text to find the header row.

        Looks for a line containing at least two recognisable column-name
        keywords (date, description, debit, credit, amount, etc.).
        Returns 0 if no better row is found.
        """
        all_known_headers = (
            DATE_COLUMN_NAMES
            + DESCRIPTION_COLUMN_NAMES
            + DEBIT_COLUMN_NAMES
            + CREDIT_COLUMN_NAMES
            + AMOUNT_COLUMN_NAMES
        )
        known_headers_set = {name.lower().strip() for name in all_known_headers}

        lines = raw_text.splitlines()
        for line_index, line in enumerate(lines[:20]):
            # Split on comma to get individual cell values from this line
            cells = [cell.lower().strip() for cell in line.split(",")]
            matches = sum(1 for cell in cells if cell in known_headers_set)
            if matches >= 2:
                return line_index

        return 0  # Default to first row

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """
        Build a mapping from internal field names to actual column names.

        Returns a dict like:
            {
                "transaction_date": "Date",
                "description":      "Particulars",
                "debit_amount":     "Debit",
                "credit_amount":    "Credit",
                "balance":          "Balance",
                ...
            }
        """
        return {
            "transaction_date": find_matching_column(columns, DATE_COLUMN_NAMES),
            "value_date":       find_matching_column(columns, VALUE_DATE_COLUMN_NAMES),
            "description":      find_matching_column(columns, DESCRIPTION_COLUMN_NAMES),
            "debit_amount":     find_matching_column(columns, DEBIT_COLUMN_NAMES),
            "credit_amount":    find_matching_column(columns, CREDIT_COLUMN_NAMES),
            "amount":           find_matching_column(columns, AMOUNT_COLUMN_NAMES),
            "balance":          find_matching_column(columns, BALANCE_COLUMN_NAMES),
            "reference":        find_matching_column(columns, REFERENCE_COLUMN_NAMES),
        }

    def _parse_row(
        self,
        row: pd.Series,
        column_map: dict[str, Optional[str]],
        row_index: int,
    ) -> Optional[ParsedTransaction]:
        """
        Convert one CSV row into a ParsedTransaction.

        Returns None if the row is a summary/total row or has no valid date.
        """
        # --- Date (required) ---
        date_col = column_map.get("transaction_date")
        if not date_col or pd.isna(row.get(date_col)):
            return None  # Skip rows without a date (e.g. totals rows)

        transaction_date = parse_date(str(row[date_col]))
        if transaction_date is None:
            return None  # Could not parse the date — skip

        # --- Value date (optional) ---
        value_date = None
        value_date_col = column_map.get("value_date")
        if value_date_col and not pd.isna(row.get(value_date_col, None)):
            value_date = parse_date(str(row[value_date_col]))

        # --- Description (required) ---
        desc_col = column_map.get("description")
        if not desc_col or pd.isna(row.get(desc_col)):
            return None

        raw_description = str(row[desc_col])
        description = clean_description(raw_description)

        if not description:
            return None  # Skip blank-description rows

        # --- Amounts ---
        debit_amount, credit_amount = self._extract_amounts(row, column_map)

        # Skip rows where both amounts are zero (usually running-balance rows)
        if debit_amount == 0.0 and credit_amount == 0.0:
            logger.debug("Row %d skipped — zero amounts: %s", row_index, description[:40])
            return None

        # --- Balance (optional) ---
        balance = None
        balance_col = column_map.get("balance")
        if balance_col and not pd.isna(row.get(balance_col, None)):
            balance = parse_amount(str(row[balance_col]))

        # --- Reference (from dedicated column or extracted from description) ---
        reference = None
        ref_col = column_map.get("reference")
        if ref_col and not pd.isna(row.get(ref_col, None)):
            reference = clean_description(str(row[ref_col])) or None

        # If no dedicated reference column, try to extract one from description
        if not reference:
            reference = extract_reference(description)

        return ParsedTransaction(
            transaction_date=transaction_date,
            value_date=value_date,
            description=description,
            raw_description=raw_description,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            balance=balance,
            reference=reference,
        )

    def _extract_amounts(
        self, row: pd.Series, column_map: dict[str, Optional[str]]
    ) -> tuple[float, float]:
        """
        Extract debit and credit amounts from a row.

        Handles two layouts:
          - Split: separate Debit and Credit columns
          - Single: one Amount column (with optional Dr/Cr suffix)
        """
        debit_col  = column_map.get("debit_amount")
        credit_col = column_map.get("credit_amount")
        amount_col = column_map.get("amount")

        # Layout 1: separate Debit / Credit columns
        if debit_col and credit_col:
            raw_debit  = str(row.get(debit_col, "")) if not pd.isna(row.get(debit_col, None)) else ""
            raw_credit = str(row.get(credit_col, "")) if not pd.isna(row.get(credit_col, None)) else ""
            return parse_amount(raw_debit), parse_amount(raw_credit)

        # Layout 2: single amount column with Dr/Cr suffix
        if amount_col and not pd.isna(row.get(amount_col, None)):
            return split_debit_credit(str(row[amount_col]))

        return 0.0, 0.0
