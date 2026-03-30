"""
base_parser.py — Abstract base class that all bank parsers must implement.

Every bank parser (CIMB, HLB, Maybank, etc.) inherits from BaseParser
and implements three methods:
  - parse()                  → extract all transactions from the file
  - extract_account_number() → pull the account number from the statement
  - extract_statement_period() → find the start and end date of the statement

The ParsedTransaction dataclass is the common format that every parser
returns. The database layer then converts these into BankTransaction rows.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from src.utils.normaliser import generate_transaction_hash

logger = logging.getLogger(__name__)


@dataclass
class ParsedTransaction:
    """
    One transaction extracted from a bank statement, in normalised form.

    This is the intermediate format between raw file data and the database.
    All amounts are plain floats in MYR. Dates are Python date objects.
    """

    transaction_date: date
    description: str
    debit_amount: float
    credit_amount: float

    value_date: Optional[date] = None
    reference: Optional[str] = None
    balance: Optional[float] = None
    raw_description: str = ""   # The original unmodified description text

    def compute_hash(self) -> str:
        """Generate a deduplication hash for this transaction."""
        return generate_transaction_hash(
            self.transaction_date,
            self.description,
            self.debit_amount,
            self.credit_amount,
        )

    def is_debit(self) -> bool:
        """Return True if money left the account."""
        return self.debit_amount > 0

    def is_credit(self) -> bool:
        """Return True if money entered the account."""
        return self.credit_amount > 0

    def net_amount(self) -> float:
        """Credit minus debit — positive means money in, negative means money out."""
        return self.credit_amount - self.debit_amount

    def __str__(self) -> str:
        direction = "DR" if self.is_debit() else "CR"
        amount = self.debit_amount if self.is_debit() else self.credit_amount
        return f"{self.transaction_date}  {direction} {amount:>12.2f}  {self.description[:50]}"


class BaseParser(ABC):
    """
    Abstract base class for all bank statement parsers.

    Subclasses must implement parse(), extract_account_number(),
    and extract_statement_period(). Everything else is provided here.

    Usage:
        parser = CIMBParser(file_path="/path/to/statement.pdf", bank_name="CIMB")
        transactions = parser.parse()
        account = parser.extract_account_number()
        start, end = parser.extract_statement_period()
    """

    def __init__(self, file_path: str, bank_name: str):
        self.file_path = Path(file_path)
        self.bank_name = bank_name

        if not self.file_path.exists():
            raise FileNotFoundError(f"Statement file not found: {file_path}")

        logger.info(
            "Initialised %s parser for: %s",
            self.__class__.__name__,
            self.file_path.name,
        )

    @abstractmethod
    def parse(self) -> list[ParsedTransaction]:
        """
        Parse the bank statement file and return all transactions found.

        Must return an empty list (not raise) if no transactions are found.
        Each transaction must have its description cleaned and hash computed.
        """

    @abstractmethod
    def extract_account_number(self) -> Optional[str]:
        """
        Extract the bank account number from the statement.

        Returns None if the account number cannot be found.
        """

    @abstractmethod
    def extract_statement_period(self) -> tuple[date, date]:
        """
        Extract the statement period as (start_date, end_date).

        If the period cannot be determined, return the date range
        of the parsed transactions as a fallback.
        """

    # ------------------------------------------------------------------
    # Shared helpers available to all subclasses
    # ------------------------------------------------------------------

    def log_parse_result(self, transactions: list[ParsedTransaction]) -> None:
        """Log a summary after parsing completes."""
        total_debits = sum(t.debit_amount for t in transactions)
        total_credits = sum(t.credit_amount for t in transactions)
        logger.info(
            "Parsed %d transactions from %s  |  Debits: %.2f  Credits: %.2f",
            len(transactions),
            self.file_path.name,
            total_debits,
            total_credits,
        )

    def get_date_range_from_transactions(
        self, transactions: list[ParsedTransaction]
    ) -> tuple[date, date]:
        """
        Derive the statement period from the earliest and latest transaction dates.

        Useful as a fallback in extract_statement_period() when the header
        section of the statement does not contain explicit period dates.
        """
        if not transactions:
            today = date.today()
            return today, today

        dates = [t.transaction_date for t in transactions]
        return min(dates), max(dates)
