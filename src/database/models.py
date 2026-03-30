"""
models.py — Data classes that mirror each SQLite table.

Each class represents one row in a table. Using dataclasses keeps
the field definitions in one place and makes passing data around
the codebase explicit and readable.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class BankTransaction:
    """One transaction row from a parsed bank statement."""

    bank_name: str
    transaction_date: date
    description: str
    source_file: str

    # Optional fields that not all banks provide
    account_number: Optional[str] = None
    value_date: Optional[date] = None
    reference: Optional[str] = None
    debit_amount: float = 0.0
    credit_amount: float = 0.0
    balance: Optional[float] = None
    currency: str = "MYR"
    raw_description: str = ""

    # Set by the database layer, not the parser
    id: Optional[int] = None
    parsed_at: Optional[datetime] = None
    recon_status: str = "UNMATCHED"
    recon_id: Optional[int] = None
    hash: Optional[str] = None


@dataclass
class LedgerEntry:
    """One entry from the internal accounting ledger."""

    entry_date: date
    description: str
    amount: float
    entry_type: str  # DEBIT or CREDIT

    reference: Optional[str] = None
    account_code: Optional[str] = None
    counterparty: Optional[str] = None
    source: Optional[str] = None

    # Set by the database layer
    id: Optional[int] = None
    recon_status: str = "UNMATCHED"
    recon_id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class Reconciliation:
    """One reconciliation run record."""

    period_start: date
    period_end: date
    bank_name: str

    account_number: Optional[str] = None
    total_bank_txns: int = 0
    total_ledger_entries: int = 0
    matched_count: int = 0
    unmatched_bank: int = 0
    unmatched_ledger: int = 0
    exceptions: int = 0
    status: str = "COMPLETED"
    report_path: Optional[str] = None

    # Set by the database layer
    id: Optional[int] = None
    run_date: Optional[datetime] = None


@dataclass
class ReconciliationMatch:
    """One matched pair from a reconciliation run."""

    recon_id: int
    match_type: str  # EXACT, AMOUNT_DATE, AMOUNT_REF, FUZZY, AMOUNT_ONLY

    bank_txn_id: Optional[int] = None
    ledger_entry_id: Optional[int] = None
    confidence_score: float = 0.0
    matched_by: str = "AUTO"
    notes: Optional[str] = None

    # Set by the database layer
    id: Optional[int] = None
    matched_at: Optional[datetime] = None


@dataclass
class AuditLog:
    """One audit trail entry recording a system or user action."""

    action: str  # e.g. PARSE_FILE, RUN_RECONCILIATION, MANUAL_MATCH

    entity: Optional[str] = None       # Table name the action affected
    entity_id: Optional[int] = None    # Row ID the action affected
    details: Optional[str] = None      # Free-text details or JSON
    user: str = "SYSTEM"

    # Set by the database layer
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
