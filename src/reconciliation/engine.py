"""
engine.py — The reconciliation engine.

Orchestrates a full reconciliation run:
  1. Load bank transactions for the period
  2. Load ledger entries for the period
  3. Match transactions using strategies from matching.py (priority order)
  4. Categorise unmatched items as exceptions using exceptions.py
  5. Persist results to the database (reconciliation_matches, audit_log)
  6. Update recon_status on matched bank_transactions and ledger_entries
  7. Return a ReconciliationResult with all the details

Usage:
    with get_db() as db:
        result = run_reconciliation(
            conn=db.get_connection(),
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            bank_name="CIMB",
            account_number="80012345678901",
        )
    print(result.summary())
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import sqlite3

from src.database.models import AuditLog, ReconciliationMatch, Reconciliation
from src.database.queries import (
    insert_audit_log,
    insert_reconciliation,
    insert_reconciliation_match,
    list_bank_transactions,
    list_ledger_entries,
    update_bank_transaction_recon_status,
    update_ledger_entry_recon_status,
)
from src.reconciliation.exceptions import (
    ExceptionItem,
    categorise_unmatched_bank_transaction,
    categorise_unmatched_ledger_entry,
    detect_duplicate_bank_transactions,
    summarise_exceptions,
)
from src.reconciliation.matching import CONFIDENCE, find_best_match

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationResult:
    """
    Full result of one reconciliation run.

    Contains summary statistics, all matched pairs, all exceptions,
    and the lists of unmatched items for report generation.
    """

    recon_id: int
    period_start: date
    period_end: date
    bank_name: str
    account_number: Optional[str]

    total_bank_txns: int = 0
    total_ledger_entries: int = 0
    matched_count: int = 0
    unmatched_bank_count: int = 0
    unmatched_ledger_count: int = 0
    exception_count: int = 0

    # Detailed lists for report generation
    matched_pairs: list[dict] = field(default_factory=list)
    unmatched_bank_txns: list[dict] = field(default_factory=list)
    unmatched_ledger_entries: list[dict] = field(default_factory=list)
    exceptions: list[ExceptionItem] = field(default_factory=list)

    def match_rate(self) -> float:
        """Percentage of bank transactions that were matched."""
        if self.total_bank_txns == 0:
            return 0.0
        return self.matched_count / self.total_bank_txns * 100

    def exact_match_count(self) -> int:
        return sum(1 for p in self.matched_pairs if p["match_type"] == "EXACT")

    def fuzzy_match_count(self) -> int:
        return sum(1 for p in self.matched_pairs if p["match_type"] == "FUZZY")

    def exception_summary(self) -> dict[str, int]:
        return summarise_exceptions(self.exceptions)

    def summary(self) -> str:
        """Return a plain-text summary of the reconciliation result."""
        lines = [
            f"Reconciliation #{self.recon_id}",
            f"Period: {self.period_start} to {self.period_end}",
            f"Bank: {self.bank_name}  Account: {self.account_number or 'N/A'}",
            f"",
            f"Bank transactions:   {self.total_bank_txns}",
            f"Ledger entries:      {self.total_ledger_entries}",
            f"Matched:             {self.matched_count} ({self.match_rate():.1f}%)",
            f"  - Exact matches:   {self.exact_match_count()}",
            f"  - Fuzzy matches:   {self.fuzzy_match_count()}",
            f"Unmatched (bank):    {self.unmatched_bank_count}",
            f"Unmatched (ledger):  {self.unmatched_ledger_count}",
            f"Exceptions:          {self.exception_count}",
        ]
        if self.exceptions:
            lines.append("")
            lines.append("Exception breakdown:")
            for exc_type, count in self.exception_summary().items():
                lines.append(f"  {exc_type}: {count}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main reconciliation function
# ---------------------------------------------------------------------------

def run_reconciliation(
    conn: sqlite3.Connection,
    period_start: date,
    period_end: date,
    bank_name: str,
    account_number: Optional[str] = None,
    amount_tolerance: float = 0.01,
    date_tolerance_days: int = 3,
    fuzzy_threshold: float = 0.80,
    large_amount_threshold: float = 5000.00,
) -> ReconciliationResult:
    """
    Run a full reconciliation for the given period and bank account.

    Args:
        conn:                 Active SQLite connection.
        period_start:         First date of the reconciliation period.
        period_end:           Last date of the reconciliation period.
        bank_name:            Bank name to filter bank transactions.
        account_number:       Account number to filter (optional).
        amount_tolerance:     Max RM difference to still consider amounts equal.
        date_tolerance_days:  Max days difference for date-based strategies.
        fuzzy_threshold:      Min similarity score (0-1) for fuzzy matching.
        large_amount_threshold: Flag unmatched items above this RM value.

    Returns:
        ReconciliationResult with full details.
    """
    logger.info(
        "Starting reconciliation — %s  %s to %s",
        bank_name, period_start, period_end,
    )

    # --- Step 1: Load data ---------------------------------------------------

    bank_txns = list_bank_transactions(
        conn,
        bank_name=bank_name,
        account_number=account_number,
        period_start=period_start,
        period_end=period_end,
    )

    ledger_entries = list_ledger_entries(
        conn,
        period_start=period_start,
        period_end=period_end,
    )

    logger.info(
        "Loaded %d bank transactions and %d ledger entries",
        len(bank_txns), len(ledger_entries),
    )

    # --- Step 2: Check for duplicate bank transactions -----------------------

    duplicate_exceptions = detect_duplicate_bank_transactions(bank_txns)
    if duplicate_exceptions:
        logger.warning(
            "Found %d duplicate bank transactions — flagging as exceptions",
            len(duplicate_exceptions),
        )

    # --- Step 3: Run matching ------------------------------------------------

    # Track which ledger entries have already been matched so we don't
    # assign the same ledger entry to two bank transactions.
    matched_ledger_ids: set[int] = set()
    matched_pairs: list[dict] = []
    unmatched_bank_txns: list[dict] = []

    for bank_txn in bank_txns:
        best_match = _find_match_for_transaction(
            bank_txn=bank_txn,
            ledger_entries=ledger_entries,
            matched_ledger_ids=matched_ledger_ids,
            amount_tolerance=amount_tolerance,
            date_tolerance_days=date_tolerance_days,
            fuzzy_threshold=fuzzy_threshold,
        )

        if best_match:
            ledger_entry, match_type, confidence = best_match
            matched_ledger_ids.add(ledger_entry["id"])
            matched_pairs.append({
                "bank_txn": bank_txn,
                "ledger_entry": ledger_entry,
                "match_type": match_type,
                "confidence_score": confidence,
            })
        else:
            unmatched_bank_txns.append(bank_txn)

    # Ledger entries that were never matched
    unmatched_ledger_entries = [
        e for e in ledger_entries if e["id"] not in matched_ledger_ids
    ]

    # --- Step 4: Categorise exceptions ---------------------------------------

    all_exceptions: list[ExceptionItem] = list(duplicate_exceptions)

    for bank_txn in unmatched_bank_txns:
        exc = categorise_unmatched_bank_transaction(bank_txn, large_amount_threshold)
        all_exceptions.append(exc)

    for ledger_entry in unmatched_ledger_entries:
        exc = categorise_unmatched_ledger_entry(ledger_entry)
        all_exceptions.append(exc)

    # --- Step 5: Persist reconciliation run record ---------------------------

    recon_record = Reconciliation(
        period_start=period_start,
        period_end=period_end,
        bank_name=bank_name,
        account_number=account_number,
        total_bank_txns=len(bank_txns),
        total_ledger_entries=len(ledger_entries),
        matched_count=len(matched_pairs),
        unmatched_bank=len(unmatched_bank_txns),
        unmatched_ledger=len(unmatched_ledger_entries),
        exceptions=len(all_exceptions),
        status="COMPLETED",
    )
    recon_id = insert_reconciliation(conn, recon_record)

    # --- Step 6: Persist matched pairs and update statuses ------------------

    for pair in matched_pairs:
        bank_txn     = pair["bank_txn"]
        ledger_entry = pair["ledger_entry"]
        match_type   = pair["match_type"]
        confidence   = pair["confidence_score"]

        insert_reconciliation_match(conn, ReconciliationMatch(
            recon_id=recon_id,
            bank_txn_id=bank_txn["id"],
            ledger_entry_id=ledger_entry["id"],
            match_type=match_type,
            confidence_score=confidence,
        ))

        update_bank_transaction_recon_status(conn, bank_txn["id"], "MATCHED", recon_id)
        update_ledger_entry_recon_status(conn, ledger_entry["id"], "MATCHED", recon_id)

    # Build a lookup so each unmatched bank transaction gets the right exception
    # category (BANK_ONLY vs LARGE_UNMATCHED) stored on its recon_status field.
    # We exclude DUPLICATE_BANK here because duplicates are handled separately below.
    bank_exception_by_txn_id: dict[int, str] = {
        exc.bank_txn_id: exc.exception_type
        for exc in all_exceptions
        if exc.bank_txn_id is not None and exc.exception_type != "DUPLICATE_BANK"
    }

    for bank_txn in unmatched_bank_txns:
        exception_type = bank_exception_by_txn_id.get(bank_txn["id"], "BANK_ONLY")
        update_bank_transaction_recon_status(conn, bank_txn["id"], exception_type, recon_id)

    for ledger_entry in unmatched_ledger_entries:
        update_ledger_entry_recon_status(conn, ledger_entry["id"], "LEDGER_ONLY", recon_id)

    # Mark duplicate bank transactions with their own category so they can be
    # distinguished from regular unmatched items in the exceptions view.
    for exc in duplicate_exceptions:
        if exc.bank_txn_id is not None:
            update_bank_transaction_recon_status(conn, exc.bank_txn_id, "DUPLICATE_BANK", recon_id)

    # --- Step 7: Audit log entry --------------------------------------------

    insert_audit_log(conn, AuditLog(
        action="RUN_RECONCILIATION",
        entity="reconciliations",
        entity_id=recon_id,
        details={
            "bank": bank_name,
            "period": f"{period_start} to {period_end}",
            "matched": len(matched_pairs),
            "unmatched_bank": len(unmatched_bank_txns),
            "unmatched_ledger": len(unmatched_ledger_entries),
            "exceptions": len(all_exceptions),
        },
    ))

    logger.info(
        "Reconciliation #%d complete — %d matched, %d unmatched bank, %d unmatched ledger, %d exceptions",
        recon_id, len(matched_pairs), len(unmatched_bank_txns),
        len(unmatched_ledger_entries), len(all_exceptions),
    )

    return ReconciliationResult(
        recon_id=recon_id,
        period_start=period_start,
        period_end=period_end,
        bank_name=bank_name,
        account_number=account_number,
        total_bank_txns=len(bank_txns),
        total_ledger_entries=len(ledger_entries),
        matched_count=len(matched_pairs),
        unmatched_bank_count=len(unmatched_bank_txns),
        unmatched_ledger_count=len(unmatched_ledger_entries),
        exception_count=len(all_exceptions),
        matched_pairs=matched_pairs,
        unmatched_bank_txns=unmatched_bank_txns,
        unmatched_ledger_entries=unmatched_ledger_entries,
        exceptions=all_exceptions,
    )


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _find_match_for_transaction(
    bank_txn: dict,
    ledger_entries: list[dict],
    matched_ledger_ids: set[int],
    amount_tolerance: float,
    date_tolerance_days: int,
    fuzzy_threshold: float,
) -> Optional[tuple[dict, str, float]]:
    """
    Find the best available ledger entry match for one bank transaction.

    Tries all ledger entries that haven't already been matched.
    Among the candidates that match, picks the one with the highest
    confidence score. If two candidates tie, picks the one with the
    closest date to break the tie.

    Returns (ledger_entry, match_type, confidence) or None.
    """
    best: Optional[tuple[dict, str, float]] = None
    best_date_diff = float("inf")

    for ledger_entry in ledger_entries:
        # Skip entries already matched to another bank transaction
        if ledger_entry["id"] in matched_ledger_ids:
            continue

        result = find_best_match(
            bank_txn=bank_txn,
            ledger_entry=ledger_entry,
            amount_tolerance=amount_tolerance,
            date_tolerance_days=date_tolerance_days,
            fuzzy_threshold=fuzzy_threshold,
        )

        if result is None:
            continue

        match_type, confidence = result

        # Calculate date difference for tie-breaking
        from src.reconciliation.matching import _as_date
        bank_date   = _as_date(bank_txn["transaction_date"])
        ledger_date = _as_date(ledger_entry["entry_date"])
        date_diff   = abs((bank_date - ledger_date).days)

        # Keep this candidate if it's better than what we have so far
        is_better_confidence = best is None or confidence > best[2]
        is_same_confidence_closer_date = (
            best is not None
            and confidence == best[2]
            and date_diff < best_date_diff
        )

        if is_better_confidence or is_same_confidence_closer_date:
            best = (ledger_entry, match_type, confidence)
            best_date_diff = date_diff

    return best
