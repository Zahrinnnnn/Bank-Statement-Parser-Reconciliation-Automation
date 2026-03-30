"""
exceptions.py — Exception categorisation for unmatched reconciliation items.

After the matching engine runs, any bank transactions or ledger entries
that remain unmatched are passed here to be categorised into exception types.

Exception categories (from the PRD):
  BANK_ONLY       — Transaction in bank statement, not in ledger
  LEDGER_ONLY     — Entry in ledger, not in bank statement
  AMOUNT_MISMATCH — Matched by reference but amounts differ
  DATE_MISMATCH   — Matched by amount/desc but dates differ > 3 days
  DUPLICATE_BANK  — Same transaction appears twice in bank statement
  LARGE_UNMATCHED — Unmatched transaction above the RM threshold
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Default threshold above which an unmatched transaction is flagged
# as LARGE_UNMATCHED (in addition to BANK_ONLY or LEDGER_ONLY)
DEFAULT_LARGE_AMOUNT_THRESHOLD = 5000.00


@dataclass
class ExceptionItem:
    """One reconciliation exception record."""

    exception_type: str     # One of the exception category strings above
    bank_txn_id: Optional[int] = None
    ledger_entry_id: Optional[int] = None
    amount: float = 0.0
    description: str = ""
    notes: str = ""


def categorise_unmatched_bank_transaction(
    bank_txn: dict,
    large_amount_threshold: float = DEFAULT_LARGE_AMOUNT_THRESHOLD,
) -> ExceptionItem:
    """
    Categorise a bank transaction that found no ledger match.

    Returns LARGE_UNMATCHED if the amount is above the threshold,
    otherwise BANK_ONLY.
    """
    from src.reconciliation.matching import get_bank_amount

    amount = get_bank_amount(bank_txn)

    if amount >= large_amount_threshold:
        exception_type = "LARGE_UNMATCHED"
        notes = f"Unmatched transaction of RM {amount:,.2f} — above threshold of RM {large_amount_threshold:,.2f}"
    else:
        exception_type = "BANK_ONLY"
        notes = "Transaction in bank statement with no matching ledger entry"

    return ExceptionItem(
        exception_type=exception_type,
        bank_txn_id=bank_txn.get("id"),
        amount=amount,
        description=bank_txn.get("description", ""),
        notes=notes,
    )


def categorise_unmatched_ledger_entry(ledger_entry: dict) -> ExceptionItem:
    """
    Categorise a ledger entry that found no bank transaction match.

    Returns LEDGER_ONLY.
    """
    return ExceptionItem(
        exception_type="LEDGER_ONLY",
        ledger_entry_id=ledger_entry.get("id"),
        amount=abs(ledger_entry.get("amount", 0.0)),
        description=ledger_entry.get("description", ""),
        notes="Ledger entry with no matching bank transaction",
    )


def detect_duplicate_bank_transactions(bank_txns: list[dict]) -> list[ExceptionItem]:
    """
    Scan the bank transaction list for duplicates — same hash appearing twice.

    This should not normally happen because the database UNIQUE constraint on
    the hash column prevents duplicate imports. This function is a safety net
    for cases where the hash was not stored (e.g. legacy records).

    Returns a list of DUPLICATE_BANK exception items.
    """
    seen_hashes: dict[str, int] = {}   # hash → first txn id
    duplicates: list[ExceptionItem] = []

    for txn in bank_txns:
        txn_hash = txn.get("hash")
        txn_id   = txn.get("id")

        if not txn_hash:
            continue  # Can't detect duplicates without a hash

        if txn_hash in seen_hashes:
            duplicates.append(ExceptionItem(
                exception_type="DUPLICATE_BANK",
                bank_txn_id=txn_id,
                amount=txn.get("debit_amount", 0) or txn.get("credit_amount", 0),
                description=txn.get("description", ""),
                notes=f"Duplicate of bank_txn_id {seen_hashes[txn_hash]}",
            ))
        else:
            seen_hashes[txn_hash] = txn_id

    return duplicates


def detect_amount_mismatch(
    bank_txn: dict,
    ledger_entry: dict,
) -> Optional[ExceptionItem]:
    """
    Create an AMOUNT_MISMATCH exception when two items were linked by reference
    but their amounts differ enough to be worth flagging.

    This is used when the matching engine finds a reference match but the
    amounts are outside the normal tolerance (caller checks this condition).
    """
    from src.reconciliation.matching import get_bank_amount, get_ledger_amount

    bank_amount   = get_bank_amount(bank_txn)
    ledger_amount = get_ledger_amount(ledger_entry)
    difference    = abs(bank_amount - ledger_amount)

    return ExceptionItem(
        exception_type="AMOUNT_MISMATCH",
        bank_txn_id=bank_txn.get("id"),
        ledger_entry_id=ledger_entry.get("id"),
        amount=difference,
        description=bank_txn.get("description", ""),
        notes=(
            f"Reference matched but amounts differ: "
            f"Bank RM {bank_amount:,.2f} vs Ledger RM {ledger_amount:,.2f} "
            f"(difference: RM {difference:,.2f})"
        ),
    )


def summarise_exceptions(exception_items: list[ExceptionItem]) -> dict[str, int]:
    """
    Count exceptions by category.

    Returns a dict like:
        {"BANK_ONLY": 4, "LEDGER_ONLY": 2, "LARGE_UNMATCHED": 1, ...}
    """
    counts: dict[str, int] = {}
    for item in exception_items:
        counts[item.exception_type] = counts.get(item.exception_type, 0) + 1
    return counts
