"""
excel_parser.py — Generic Excel bank statement parser.

Works with .xlsx and .xls files. Auto-detects which row contains
the column headers and which columns hold dates, descriptions,
and amounts — using the same column-name matching logic as the CSV parser.

Some bank Excel exports have metadata in the first few rows
(bank name, account number, report period) before the actual
transaction table starts. This parser handles that gracefully.

Usage:
    parser = ExcelParser(file_path="statement.xlsx", bank_name="HLB")
    transactions = parser.parse()
"""

import logging
import re
from datetime import date, datetime
from typing import Optional

import openpyxl
import pandas as pd

from src.parsers.base_parser import BaseParser, ParsedTransaction
from src.parsers.csv_parser import (
    AMOUNT_COLUMN_NAMES,
    BALANCE_COLUMN_NAMES,
    CREDIT_COLUMN_NAMES,
    DATE_COLUMN_NAMES,
    DEBIT_COLUMN_NAMES,
    DESCRIPTION_COLUMN_NAMES,
    REFERENCE_COLUMN_NAMES,
    VALUE_DATE_COLUMN_NAMES,
    find_matching_column,
)
from src.utils.normaliser import (
    clean_description,
    extract_reference,
    parse_amount,
    parse_date,
    split_debit_credit,
)

logger = logging.getLogger(__name__)


class ExcelParser(BaseParser):
    """
    Generic Excel parser that auto-detects header rows and column layout.

    Reads the first sheet by default. Handles both .xlsx and .xls formats
    via openpyxl (xlsx) and pandas xlrd fallback (xls).
    """

    def __init__(self, file_path: str, bank_name: str, sheet_index: int = 0):
        super().__init__(file_path, bank_name)
        self.sheet_index = sheet_index
        self._dataframe: Optional[pd.DataFrame] = None
        self._raw_workbook: Optional[openpyxl.Workbook] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self) -> list[ParsedTransaction]:
        """Load the Excel file and convert every data row into a ParsedTransaction."""
        self._dataframe = self._load_excel()

        if self._dataframe is None or self._dataframe.empty:
            logger.warning("No data found in Excel file: %s", self.file_path.name)
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
        Scan the first 20 rows of the Excel file for an account number.

        Account numbers are typically in the metadata rows above the
        transaction table — formatted as long digit strings.
        """
        try:
            # Load raw with no header so we can read metadata rows
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
                    match = re.search(r"\b(\d{10,16})\b", str(cell_value))
                    if match:
                        return match.group(1)

        except Exception as e:
            logger.debug("Could not extract account number from Excel: %s", e)

        return None

    def extract_statement_period(self) -> tuple[date, date]:
        """Return the date range covered by the parsed transactions."""
        if self._dataframe is None:
            self._dataframe = self._load_excel()

        if self._dataframe is None or self._dataframe.empty:
            today = date.today()
            return today, today

        column_map = self._detect_columns(self._dataframe.columns.tolist())
        date_col = column_map.get("transaction_date")

        if date_col and date_col in self._dataframe.columns:
            parsed_dates = [
                self._parse_cell_date(v)
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

    def _pick_engine(self) -> str:
        """Choose the right pandas Excel engine based on file extension."""
        suffix = self.file_path.suffix.lower()
        if suffix == ".xls":
            return "xlrd"
        return "openpyxl"  # Default for .xlsx and others

    def _load_excel(self) -> Optional[pd.DataFrame]:
        """
        Load the Excel sheet into a DataFrame.

        Scans the first 20 rows to find where the header row is,
        then reloads with that row as the column names.
        """
        try:
            engine = self._pick_engine()

            # First pass — load with no header to inspect all rows
            raw_df = pd.read_excel(
                self.file_path,
                header=None,
                dtype=str,
                sheet_name=self.sheet_index,
                engine=engine,
            )

            header_row_index = self._find_header_row(raw_df)
            logger.debug("Header row found at index: %d", header_row_index)

            # Second pass — reload using the correct header row
            df = pd.read_excel(
                self.file_path,
                header=header_row_index,
                dtype=str,
                sheet_name=self.sheet_index,
                engine=engine,
            )

            # Strip whitespace from column names
            df.columns = [str(col).strip() for col in df.columns]

            return df

        except Exception as e:
            logger.error("Failed to load Excel file %s: %s", self.file_path.name, e)
            return None

    def _find_header_row(self, raw_df: pd.DataFrame) -> int:
        """
        Find the row index that contains column headers by looking for
        recognisable header keywords (date, description, debit, etc.).
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

        for row_index in range(min(20, len(raw_df))):
            row_values = [
                str(val).lower().strip()
                for val in raw_df.iloc[row_index].values
                if pd.notna(val)
            ]
            matches = sum(1 for val in row_values if val in known_headers_set)
            if matches >= 2:
                return row_index

        return 0

    def _detect_columns(self, columns: list[str]) -> dict[str, Optional[str]]:
        """Map internal field names to actual Excel column names."""
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

    def _parse_cell_date(self, cell_value) -> Optional[date]:
        """
        Parse a date from an Excel cell value.

        Excel sometimes gives us a Python datetime directly (when the cell
        was formatted as a date in Excel), or a string. Handle both.
        """
        if isinstance(cell_value, (datetime, date)):
            return cell_value.date() if isinstance(cell_value, datetime) else cell_value

        if pd.isna(cell_value):
            return None

        return parse_date(str(cell_value))

    def _parse_row(
        self,
        row: pd.Series,
        column_map: dict[str, Optional[str]],
        row_index: int,
    ) -> Optional[ParsedTransaction]:
        """
        Convert one Excel row into a ParsedTransaction.

        Returns None if the row has no valid date or no description
        (e.g. totals rows, blank rows, sub-header rows).
        """
        # --- Date (required) ---
        date_col = column_map.get("transaction_date")
        if not date_col or pd.isna(row.get(date_col)):
            return None

        transaction_date = self._parse_cell_date(row[date_col])
        if transaction_date is None:
            return None

        # --- Value date (optional) ---
        value_date = None
        value_date_col = column_map.get("value_date")
        if value_date_col and not pd.isna(row.get(value_date_col, None)):
            value_date = self._parse_cell_date(row[value_date_col])

        # --- Description (required) ---
        desc_col = column_map.get("description")
        if not desc_col or pd.isna(row.get(desc_col)):
            return None

        raw_description = str(row[desc_col])
        description = clean_description(raw_description)

        if not description:
            return None

        # --- Amounts ---
        debit_amount, credit_amount = self._extract_amounts(row, column_map)

        if debit_amount == 0.0 and credit_amount == 0.0:
            logger.debug("Row %d skipped — zero amounts: %s", row_index, description[:40])
            return None

        # --- Balance (optional) ---
        balance = None
        balance_col = column_map.get("balance")
        if balance_col and not pd.isna(row.get(balance_col, None)):
            balance = parse_amount(str(row[balance_col]))

        # --- Reference ---
        reference = None
        ref_col = column_map.get("reference")
        if ref_col and not pd.isna(row.get(ref_col, None)):
            reference = clean_description(str(row[ref_col])) or None

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
        Extract debit and credit from a row.

        Prefers split Debit/Credit columns; falls back to a single
        Amount column with Dr/Cr detection.
        """
        debit_col  = column_map.get("debit_amount")
        credit_col = column_map.get("credit_amount")
        amount_col = column_map.get("amount")

        # Split columns
        if debit_col and credit_col:
            raw_debit  = str(row.get(debit_col, ""))  if not pd.isna(row.get(debit_col, None))  else ""
            raw_credit = str(row.get(credit_col, "")) if not pd.isna(row.get(credit_col, None)) else ""
            return parse_amount(raw_debit), parse_amount(raw_credit)

        # Single amount column
        if amount_col and not pd.isna(row.get(amount_col, None)):
            return split_debit_credit(str(row[amount_col]))

        return 0.0, 0.0
