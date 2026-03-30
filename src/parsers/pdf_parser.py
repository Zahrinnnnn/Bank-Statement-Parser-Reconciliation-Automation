"""
pdf_parser.py — Generic PDF bank statement parser.

Uses pdfplumber to extract transaction tables from PDF statements.
Works in two modes depending on how the PDF was produced:

  1. Table mode  — the PDF has actual embedded tables (most bank PDFs).
                   pdfplumber extracts rows and columns directly.

  2. Text mode   — the PDF has no structured tables, just raw text lines.
                   The parser reads lines and tries to reconstruct rows
                   by matching date patterns at the start of each line.

Bank-specific parsers (CIMBParser, HLBParser, etc.) inherit from this
class and override the methods that need bank-specific column names or
text patterns. For many banks, this generic parser works as-is.

Usage:
    parser = PDFParser(file_path="statement.pdf", bank_name="CIMB")
    transactions = parser.parse()
"""

import logging
import re
from datetime import date
from typing import Optional

import pdfplumber

from src.parsers.base_parser import BaseParser, ParsedTransaction
from src.parsers.csv_parser import (
    AMOUNT_COLUMN_NAMES,
    BALANCE_COLUMN_NAMES,
    CREDIT_COLUMN_NAMES,
    DATE_COLUMN_NAMES,
    DEBIT_COLUMN_NAMES,
    DESCRIPTION_COLUMN_NAMES,
    REFERENCE_COLUMN_NAMES,
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

# ---------------------------------------------------------------------------
# Regex patterns for text-mode parsing
# ---------------------------------------------------------------------------

# Matches a line that starts with a date — used to identify transaction rows
# in raw text when there's no structured table.
# Covers: DD/MM/YYYY, DD-MM-YYYY, DD MMM YYYY, DD/MM/YY
DATE_AT_LINE_START = re.compile(
    r"^(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"   # DD/MM/YYYY or DD-MM-YYYY
    r"|\d{1,2}\s+[A-Za-z]{3}\s+\d{4})"        # DD MMM YYYY
)

# Matches a money amount anywhere in a line — used to split amounts from description
MONEY_PATTERN = re.compile(
    r"[\d,]+\.\d{2}"   # e.g. 1,234.56 or 250.00
)

# Matches an account number (10-16 consecutive digits)
ACCOUNT_NUMBER_PATTERN = re.compile(r"\b(\d{10,16})\b")

# Matches a statement period like "01/03/2026 to 31/03/2026" or "01-03-2026 - 31-03-2026"
PERIOD_PATTERN = re.compile(
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"   # start date
    r"\s+(?:to|TO|\-|–)\s+"                    # separator
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"   # end date
)


class PDFParser(BaseParser):
    """
    Generic PDF parser — works for most Malaysian bank statement PDFs.

    Tries table extraction first. If pdfplumber finds no tables, falls
    back to line-by-line text parsing.

    Bank-specific subclasses can override:
      - _column_names_for_table()  to add bank-specific header synonyms
      - _parse_text_line()         to handle unusual line formats
      - extract_account_number()   to use a bank-specific regex
      - extract_statement_period() to find a bank-specific date header
    """

    def __init__(self, file_path: str, bank_name: str):
        super().__init__(file_path, bank_name)
        self._all_page_text: Optional[str] = None   # cached full-document text

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self) -> list[ParsedTransaction]:
        """
        Parse the PDF and return all transactions found.

        Tries table extraction on each page first. If a page has no
        tables, runs text-mode parsing on that page instead.
        """
        transactions = []

        with pdfplumber.open(str(self.file_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_transactions = self._parse_page(page, page_number)
                transactions.extend(page_transactions)

        self.log_parse_result(transactions)
        return transactions

    def extract_account_number(self) -> Optional[str]:
        """
        Search the first two pages of the PDF for an account number.

        Returns the first 10-16 digit sequence found outside of a date
        or amount context, or None if nothing is found.
        """
        text = self._get_full_text(max_pages=2)
        if not text:
            return None

        for match in ACCOUNT_NUMBER_PATTERN.finditer(text):
            candidate = match.group(1)
            # Skip sequences that look like dates (8 digits) or years (4 digits)
            if len(candidate) in (4, 8):
                continue
            return candidate

        return None

    def extract_statement_period(self) -> tuple[date, date]:
        """
        Search the first two pages for a date range like "01/03/2026 to 31/03/2026".

        Falls back to the date range of parsed transactions if not found.
        """
        text = self._get_full_text(max_pages=2)
        if text:
            match = PERIOD_PATTERN.search(text)
            if match:
                start = parse_date(match.group(1))
                end   = parse_date(match.group(2))
                if start and end:
                    return start, end

        # Fallback — derive the period from the parsed transactions
        transactions = self.parse()
        return self.get_date_range_from_transactions(transactions)

    # ------------------------------------------------------------------
    # Private — page-level parsing
    # ------------------------------------------------------------------

    def _parse_page(
        self, page: pdfplumber.page.Page, page_number: int
    ) -> list[ParsedTransaction]:
        """
        Try table extraction first. If the page has no tables, use text mode.
        """
        tables = page.extract_tables()

        if tables:
            logger.debug("Page %d: found %d table(s) — using table mode", page_number, len(tables))
            return self._parse_tables(tables)

        logger.debug("Page %d: no tables found — using text mode", page_number)
        text = page.extract_text() or ""
        return self._parse_text(text)

    # ------------------------------------------------------------------
    # Private — table mode
    # ------------------------------------------------------------------

    def _parse_tables(self, tables: list[list]) -> list[ParsedTransaction]:
        """
        Parse all tables from one page.

        Each table is a list of rows; each row is a list of cell strings.
        The first row that looks like a header row is used to detect columns.
        """
        transactions = []

        for table in tables:
            if not table or len(table) < 2:
                continue  # Skip empty or single-row tables

            # Find the header row within this table
            header_row_index = self._find_table_header_row(table)
            header = [str(cell).strip() if cell else "" for cell in table[header_row_index]]

            column_map = self._detect_table_columns(header)

            # Process all rows after the header
            for row in table[header_row_index + 1:]:
                txn = self._parse_table_row(row, header, column_map)
                if txn is not None:
                    transactions.append(txn)

        return transactions

    def _find_table_header_row(self, table: list[list]) -> int:
        """
        Find the index of the row within a table that contains column headers.
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

        for row_index, row in enumerate(table[:5]):  # Only check first 5 rows
            cells = [str(cell).lower().strip() for cell in row if cell]
            matches = sum(1 for cell in cells if cell in known_headers_set)
            if matches >= 2:
                return row_index

        return 0

    def _detect_table_columns(self, header: list[str]) -> dict[str, Optional[int]]:
        """
        Map internal field names to column indices in the table header.

        Returns a dict like {"transaction_date": 0, "description": 1, ...}
        Values are integer column indices (not column names).
        """
        def find_index(candidate_names: list[str]) -> Optional[int]:
            """Find the first header cell that matches any candidate name."""
            candidate_set = {name.lower().strip() for name in candidate_names}
            for index, cell in enumerate(header):
                if cell.lower().strip() in candidate_set:
                    return index
            return None

        return {
            "transaction_date": find_index(DATE_COLUMN_NAMES),
            "description":      find_index(DESCRIPTION_COLUMN_NAMES),
            "debit_amount":     find_index(DEBIT_COLUMN_NAMES),
            "credit_amount":    find_index(CREDIT_COLUMN_NAMES),
            "amount":           find_index(AMOUNT_COLUMN_NAMES),
            "balance":          find_index(BALANCE_COLUMN_NAMES),
            "reference":        find_index(REFERENCE_COLUMN_NAMES),
        }

    def _parse_table_row(
        self,
        row: list,
        header: list[str],
        column_map: dict[str, Optional[int]],
    ) -> Optional[ParsedTransaction]:
        """
        Convert one table row into a ParsedTransaction.

        Returns None if the row has no valid date or is a summary/total row.
        """
        def get_cell(field_name: str) -> str:
            """Safely get a cell value by field name."""
            index = column_map.get(field_name)
            if index is None or index >= len(row):
                return ""
            return str(row[index]).strip() if row[index] else ""

        # --- Date (required) ---
        raw_date = get_cell("transaction_date")
        if not raw_date:
            return None

        transaction_date = parse_date(raw_date)
        if transaction_date is None:
            return None

        # --- Description (required) ---
        raw_description = get_cell("description")
        description = clean_description(raw_description)
        if not description:
            return None

        # --- Amounts ---
        debit_amount, credit_amount = self._extract_table_amounts(get_cell, column_map)

        if debit_amount == 0.0 and credit_amount == 0.0:
            return None

        # --- Balance ---
        balance = None
        raw_balance = get_cell("balance")
        if raw_balance:
            balance = parse_amount(raw_balance)

        # --- Reference ---
        raw_reference = get_cell("reference")
        reference = clean_description(raw_reference) or extract_reference(description)

        return ParsedTransaction(
            transaction_date=transaction_date,
            description=description,
            raw_description=raw_description,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            balance=balance,
            reference=reference,
        )

    def _extract_table_amounts(
        self, get_cell, column_map: dict[str, Optional[int]]
    ) -> tuple[float, float]:
        """Extract debit and credit amounts from a table row."""
        debit_col  = column_map.get("debit_amount")
        credit_col = column_map.get("credit_amount")
        amount_col = column_map.get("amount")

        if debit_col is not None and credit_col is not None:
            return parse_amount(get_cell("debit_amount")), parse_amount(get_cell("credit_amount"))

        if amount_col is not None:
            return split_debit_credit(get_cell("amount"))

        return 0.0, 0.0

    # ------------------------------------------------------------------
    # Private — text mode
    # ------------------------------------------------------------------

    def _parse_text(self, text: str) -> list[ParsedTransaction]:
        """
        Parse raw page text when no tables were found.

        Scans line by line. Lines starting with a date are treated as
        new transactions. Subsequent lines without a date are treated as
        continuation of the previous transaction's description.
        """
        transactions = []
        current_lines: list[str] = []  # Lines belonging to the current transaction

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if DATE_AT_LINE_START.match(stripped):
                # This line starts a new transaction — process the previous one first
                if current_lines:
                    txn = self._parse_text_line(" ".join(current_lines))
                    if txn is not None:
                        transactions.append(txn)
                current_lines = [stripped]
            else:
                # Continuation line — belongs to the current transaction
                current_lines.append(stripped)

        # Don't forget the last transaction
        if current_lines:
            txn = self._parse_text_line(" ".join(current_lines))
            if txn is not None:
                transactions.append(txn)

        return transactions

    def _parse_text_line(self, line: str) -> Optional[ParsedTransaction]:
        """
        Parse one logical transaction line from raw PDF text.

        A typical line looks like:
          03/03/2026  FPX SHOPEE PAYMENT  250.00  4,750.00
          05/03/2026  SALARY CREDIT ACME  3,500.00  8,250.00

        Strategy:
          1. Extract the date from the start of the line
          2. Find all money amounts in the line (right-most is usually balance)
          3. Everything between the date and the amounts is the description
        """
        line = line.strip()
        if not line:
            return None

        # --- Extract date from start of line ---
        date_match = DATE_AT_LINE_START.match(line)
        if not date_match:
            return None

        raw_date = date_match.group(0)
        transaction_date = parse_date(raw_date)
        if transaction_date is None:
            return None

        # Remove the date from the line so we can parse the rest
        remainder = line[date_match.end():].strip()

        # --- Find all money amounts in the remainder ---
        amount_matches = list(MONEY_PATTERN.finditer(remainder))

        if not amount_matches:
            return None  # No amounts — not a transaction line

        # The last amount is usually the running balance
        # The second-to-last (if it exists) is the transaction amount
        if len(amount_matches) >= 2:
            balance_str = amount_matches[-1].group(0)
            txn_amount_str = amount_matches[-2].group(0)
            # Description is the text before the first amount
            description_end = amount_matches[-2].start()
        else:
            balance_str = None
            txn_amount_str = amount_matches[-1].group(0)
            description_end = amount_matches[-1].start()

        # --- Description ---
        raw_description = remainder[:description_end].strip()
        description = clean_description(raw_description)

        if not description:
            return None

        # --- Determine debit vs credit from context ---
        # In many bank PDFs, debits and credits appear in separate columns
        # but collapse into one stream in text mode. We use a heuristic:
        # check if the description contains Dr/Cr keywords or common patterns.
        debit_amount, credit_amount = self._classify_text_amount(txn_amount_str, description)

        if debit_amount == 0.0 and credit_amount == 0.0:
            return None

        # --- Balance ---
        balance = parse_amount(balance_str) if balance_str else None

        # --- Reference ---
        reference = extract_reference(description)

        return ParsedTransaction(
            transaction_date=transaction_date,
            description=description,
            raw_description=raw_description,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            balance=balance,
            reference=reference,
        )

    def _classify_text_amount(
        self, amount_str: str, description: str
    ) -> tuple[float, float]:
        """
        Decide whether a text-mode amount is a debit or credit.

        In text-mode PDFs, the two columns collapse and we lose the
        column position. We use these heuristics in order:

        1. If the amount string has a Dr/Cr suffix — use it directly.
        2. If the description contains credit keywords (SALARY, DEPOSIT,
           RECEIVE, CREDIT, REFUND) — treat as credit.
        3. Default — treat as debit (most transactions are outflows).

        Bank-specific parsers can override this method for better accuracy.
        """
        amount = parse_amount(amount_str)

        # Heuristic 1 — explicit Dr/Cr suffix in the amount string
        upper_amount = amount_str.upper()
        if upper_amount.endswith("CR") or upper_amount.endswith(" CR"):
            return 0.0, amount
        if upper_amount.endswith("DR") or upper_amount.endswith(" DR"):
            return amount, 0.0

        # Heuristic 2 — keywords in the description that suggest a credit
        credit_keywords = {
            "SALARY", "CREDIT", "DEPOSIT", "RECEIVE", "REFUND",
            "REBATE", "TRANSFER IN", "INCOMING", "INTEREST", "BONUS",
        }
        description_upper = description.upper()
        if any(keyword in description_upper for keyword in credit_keywords):
            return 0.0, amount

        # Default — debit
        return amount, 0.0

    # ------------------------------------------------------------------
    # Private — utility
    # ------------------------------------------------------------------

    def _get_full_text(self, max_pages: int = 2) -> str:
        """
        Extract and cache the raw text from the first N pages.

        Used by extract_account_number() and extract_statement_period()
        to scan for metadata without re-parsing all transactions.
        """
        if self._all_page_text is not None:
            return self._all_page_text

        pages_text = []
        try:
            with pdfplumber.open(str(self.file_path)) as pdf:
                for page in pdf.pages[:max_pages]:
                    text = page.extract_text() or ""
                    pages_text.append(text)
        except Exception as e:
            logger.error("Failed to read PDF text from %s: %s", self.file_path.name, e)

        self._all_page_text = "\n".join(pages_text)
        return self._all_page_text
