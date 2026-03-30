"""
queries.py — All database read and write operations.

Every SQL query in the application lives here as a named function.
This keeps SQL out of business logic and makes it easy to find,
read, and change queries without hunting through the codebase.

Functions follow a simple convention:
  - insert_*   → inserts a row, returns the new row ID
  - get_*      → fetches one row by ID, returns a dict or None
  - list_*     → fetches multiple rows, returns a list of dicts
  - update_*   → updates fields on an existing row
  - delete_*   → removes a row (used sparingly, prefer soft status updates)
"""

import json
import logging
import sqlite3
from datetime import date
from typing import Optional

from src.database.models import (
    AuditLog,
    BankTransaction,
    LedgerEntry,
    Reconciliation,
    ReconciliationMatch,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# bank_transactions
# ---------------------------------------------------------------------------

def insert_bank_transaction(conn: sqlite3.Connection, txn: BankTransaction) -> int:
    """
    Insert one bank transaction.

    Returns the new row ID, or -1 if the row was skipped because the
    hash already exists (i.e. it's a duplicate upload).
    """
    sql = """
        INSERT OR IGNORE INTO bank_transactions (
            bank_name, account_number, transaction_date, value_date,
            description, reference, debit_amount, credit_amount,
            balance, currency, raw_description, source_file,
            recon_status, hash
        ) VALUES (
            :bank_name, :account_number, :transaction_date, :value_date,
            :description, :reference, :debit_amount, :credit_amount,
            :balance, :currency, :raw_description, :source_file,
            :recon_status, :hash
        )
    """
    params = {
        "bank_name":        txn.bank_name,
        "account_number":   txn.account_number,
        "transaction_date": txn.transaction_date.isoformat(),
        "value_date":       txn.value_date.isoformat() if txn.value_date else None,
        "description":      txn.description,
        "reference":        txn.reference,
        "debit_amount":     txn.debit_amount,
        "credit_amount":    txn.credit_amount,
        "balance":          txn.balance,
        "currency":         txn.currency,
        "raw_description":  txn.raw_description,
        "source_file":      txn.source_file,
        "recon_status":     txn.recon_status,
        "hash":             txn.hash,
    }

    cursor = conn.execute(sql, params)
    conn.commit()

    # INSERT OR IGNORE sets lastrowid to 0 when the row is skipped
    if cursor.lastrowid == 0:
        logger.debug("Duplicate transaction skipped (hash: %s)", txn.hash)
        return -1

    return cursor.lastrowid


def get_bank_transaction(conn: sqlite3.Connection, txn_id: int) -> Optional[dict]:
    """Fetch one bank transaction by its primary key."""
    row = conn.execute(
        "SELECT * FROM bank_transactions WHERE id = ?", (txn_id,)
    ).fetchone()
    return dict(row) if row else None


def list_bank_transactions(
    conn: sqlite3.Connection,
    bank_name: Optional[str] = None,
    account_number: Optional[str] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    recon_status: Optional[str] = None,
) -> list[dict]:
    """
    Fetch bank transactions with optional filters.

    All filter arguments are optional — pass only the ones you need.
    """
    conditions = []
    params: dict = {}

    if bank_name:
        conditions.append("bank_name = :bank_name")
        params["bank_name"] = bank_name

    if account_number:
        conditions.append("account_number = :account_number")
        params["account_number"] = account_number

    if period_start:
        conditions.append("transaction_date >= :period_start")
        params["period_start"] = period_start.isoformat()

    if period_end:
        conditions.append("transaction_date <= :period_end")
        params["period_end"] = period_end.isoformat()

    if recon_status:
        conditions.append("recon_status = :recon_status")
        params["recon_status"] = recon_status

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM bank_transactions {where_clause} ORDER BY transaction_date"

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def update_bank_transaction_recon_status(
    conn: sqlite3.Connection,
    txn_id: int,
    recon_status: str,
    recon_id: Optional[int] = None,
) -> None:
    """Mark a bank transaction as MATCHED, UNMATCHED, or EXCEPTION."""
    conn.execute(
        "UPDATE bank_transactions SET recon_status = ?, recon_id = ? WHERE id = ?",
        (recon_status, recon_id, txn_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# ledger_entries
# ---------------------------------------------------------------------------

def insert_ledger_entry(conn: sqlite3.Connection, entry: LedgerEntry) -> int:
    """Insert one ledger entry and return its new row ID."""
    sql = """
        INSERT INTO ledger_entries (
            entry_date, description, reference, amount, entry_type,
            account_code, counterparty, source, recon_status
        ) VALUES (
            :entry_date, :description, :reference, :amount, :entry_type,
            :account_code, :counterparty, :source, :recon_status
        )
    """
    params = {
        "entry_date":   entry.entry_date.isoformat(),
        "description":  entry.description,
        "reference":    entry.reference,
        "amount":       entry.amount,
        "entry_type":   entry.entry_type,
        "account_code": entry.account_code,
        "counterparty": entry.counterparty,
        "source":       entry.source,
        "recon_status": entry.recon_status,
    }

    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def get_ledger_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[dict]:
    """Fetch one ledger entry by its primary key."""
    row = conn.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    return dict(row) if row else None


def list_ledger_entries(
    conn: sqlite3.Connection,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    recon_status: Optional[str] = None,
) -> list[dict]:
    """Fetch ledger entries with optional date range and status filters."""
    conditions = []
    params: dict = {}

    if period_start:
        conditions.append("entry_date >= :period_start")
        params["period_start"] = period_start.isoformat()

    if period_end:
        conditions.append("entry_date <= :period_end")
        params["period_end"] = period_end.isoformat()

    if recon_status:
        conditions.append("recon_status = :recon_status")
        params["recon_status"] = recon_status

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM ledger_entries {where_clause} ORDER BY entry_date"

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def update_ledger_entry_recon_status(
    conn: sqlite3.Connection,
    entry_id: int,
    recon_status: str,
    recon_id: Optional[int] = None,
) -> None:
    """Mark a ledger entry as MATCHED, UNMATCHED, or EXCEPTION."""
    conn.execute(
        "UPDATE ledger_entries SET recon_status = ?, recon_id = ? WHERE id = ?",
        (recon_status, recon_id, entry_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# reconciliations
# ---------------------------------------------------------------------------

def insert_reconciliation(conn: sqlite3.Connection, recon: Reconciliation) -> int:
    """Create a new reconciliation run record and return its ID."""
    sql = """
        INSERT INTO reconciliations (
            period_start, period_end, bank_name, account_number,
            total_bank_txns, total_ledger_entries, matched_count,
            unmatched_bank, unmatched_ledger, exceptions, status, report_path
        ) VALUES (
            :period_start, :period_end, :bank_name, :account_number,
            :total_bank_txns, :total_ledger_entries, :matched_count,
            :unmatched_bank, :unmatched_ledger, :exceptions, :status, :report_path
        )
    """
    params = {
        "period_start":         recon.period_start.isoformat(),
        "period_end":           recon.period_end.isoformat(),
        "bank_name":            recon.bank_name,
        "account_number":       recon.account_number,
        "total_bank_txns":      recon.total_bank_txns,
        "total_ledger_entries": recon.total_ledger_entries,
        "matched_count":        recon.matched_count,
        "unmatched_bank":       recon.unmatched_bank,
        "unmatched_ledger":     recon.unmatched_ledger,
        "exceptions":           recon.exceptions,
        "status":               recon.status,
        "report_path":          recon.report_path,
    }

    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def get_reconciliation(conn: sqlite3.Connection, recon_id: int) -> Optional[dict]:
    """Fetch one reconciliation run by its ID."""
    row = conn.execute(
        "SELECT * FROM reconciliations WHERE id = ?", (recon_id,)
    ).fetchone()
    return dict(row) if row else None


def list_reconciliations(
    conn: sqlite3.Connection,
    bank_name: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch recent reconciliation runs, newest first.

    Optionally filter by bank name and cap the number of results.
    """
    if bank_name:
        sql = """
            SELECT * FROM reconciliations
            WHERE bank_name = ?
            ORDER BY run_date DESC
            LIMIT ?
        """
        rows = conn.execute(sql, (bank_name, limit)).fetchall()
    else:
        sql = "SELECT * FROM reconciliations ORDER BY run_date DESC LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()

    return [dict(row) for row in rows]


def update_reconciliation_report_path(
    conn: sqlite3.Connection, recon_id: int, report_path: str
) -> None:
    """Store the file path of the generated report on a reconciliation run."""
    conn.execute(
        "UPDATE reconciliations SET report_path = ? WHERE id = ?",
        (report_path, recon_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# reconciliation_matches
# ---------------------------------------------------------------------------

def insert_reconciliation_match(
    conn: sqlite3.Connection, match: ReconciliationMatch
) -> int:
    """Record one matched pair from a reconciliation run."""
    sql = """
        INSERT INTO reconciliation_matches (
            recon_id, bank_txn_id, ledger_entry_id,
            match_type, confidence_score, matched_by, notes
        ) VALUES (
            :recon_id, :bank_txn_id, :ledger_entry_id,
            :match_type, :confidence_score, :matched_by, :notes
        )
    """
    params = {
        "recon_id":        match.recon_id,
        "bank_txn_id":     match.bank_txn_id,
        "ledger_entry_id": match.ledger_entry_id,
        "match_type":      match.match_type,
        "confidence_score": match.confidence_score,
        "matched_by":      match.matched_by,
        "notes":           match.notes,
    }

    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def list_matches_for_reconciliation(
    conn: sqlite3.Connection, recon_id: int
) -> list[dict]:
    """Fetch all match records for one reconciliation run."""
    rows = conn.execute(
        "SELECT * FROM reconciliation_matches WHERE recon_id = ? ORDER BY id",
        (recon_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# audit_log
# ---------------------------------------------------------------------------

def insert_audit_log(conn: sqlite3.Connection, log_entry: AuditLog) -> int:
    """Write one audit log entry and return its ID."""
    sql = """
        INSERT INTO audit_log (action, entity, entity_id, details, user)
        VALUES (:action, :entity, :entity_id, :details, :user)
    """
    params = {
        "action":    log_entry.action,
        "entity":    log_entry.entity,
        "entity_id": log_entry.entity_id,
        # Store extra details as JSON string if a dict was passed in
        "details":   json.dumps(log_entry.details)
                     if isinstance(log_entry.details, dict)
                     else log_entry.details,
        "user":      log_entry.user,
    }

    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def list_audit_log(
    conn: sqlite3.Connection,
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 100,
) -> list[dict]:
    """
    Fetch recent audit log entries, newest first.

    Filter by entity table name and/or entity row ID if needed.
    """
    conditions = []
    params: list = []

    if entity:
        conditions.append("entity = ?")
        params.append(entity)

    if entity_id is not None:
        conditions.append("entity_id = ?")
        params.append(entity_id)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    sql = f"SELECT * FROM audit_log {where_clause} ORDER BY timestamp DESC LIMIT ?"

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
