"""
matching.py — Individual match strategy functions for the reconciliation engine.

Each function takes one bank transaction and one ledger entry and decides
whether they are a match under a specific strategy.

The engine in engine.py calls these in priority order and stops at the
first match found for each bank transaction.

Match types (highest to lowest confidence):
  EXACT         — same date, same amount, same reference          100%
  AMOUNT_DATE   — same amount, date within 1 day                   95%
  AMOUNT_REF    — same amount, reference substring match           90%
  FUZZY         — same amount, description similarity > threshold  75%
  AMOUNT_ONLY   — same amount, date within 3 days                  60%
"""

import logging
from datetime import date, timedelta
from typing import Optional

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Confidence scores for each match type — matches the PRD exactly
CONFIDENCE = {
    "EXACT":       1.00,
    "AMOUNT_DATE": 0.95,
    "AMOUNT_REF":  0.90,
    "FUZZY":       0.75,
    "AMOUNT_ONLY": 0.60,
}


# ---------------------------------------------------------------------------
# Amount helpers
# ---------------------------------------------------------------------------

def get_bank_amount(bank_txn: dict) -> float:
    """
    Return the transaction's net amount as a positive float.

    A debit (money out) returns the debit_amount.
    A credit (money in) returns the credit_amount.
    """
    if bank_txn["debit_amount"] > 0:
        return bank_txn["debit_amount"]
    return bank_txn["credit_amount"]


def get_ledger_amount(ledger_entry: dict) -> float:
    """Return the ledger entry amount as a positive float."""
    return abs(ledger_entry["amount"])


def amounts_are_close(
    bank_txn: dict,
    ledger_entry: dict,
    tolerance: float = 0.01,
) -> bool:
    """
    Return True if the bank and ledger amounts are within tolerance of each other.

    Also checks that the direction matches — a bank debit should match a
    ledger DEBIT entry, and a bank credit should match a ledger CREDIT entry.
    """
    # Direction check — don't match a payment against a receipt
    bank_is_debit   = bank_txn["debit_amount"] > 0
    ledger_is_debit = ledger_entry["entry_type"].upper() == "DEBIT"

    if bank_is_debit != ledger_is_debit:
        return False

    bank_amount   = get_bank_amount(bank_txn)
    ledger_amount = get_ledger_amount(ledger_entry)

    return abs(bank_amount - ledger_amount) <= tolerance


def dates_are_within(
    bank_txn: dict,
    ledger_entry: dict,
    max_days: int,
) -> bool:
    """Return True if the two dates are no more than max_days apart."""
    bank_date   = _as_date(bank_txn["transaction_date"])
    ledger_date = _as_date(ledger_entry["entry_date"])
    return abs((bank_date - ledger_date).days) <= max_days


def _as_date(value) -> date:
    """Convert a string or date-like value to a Python date object."""
    if isinstance(value, date):
        return value
    # SQLite returns dates as strings in ISO format
    from datetime import datetime
    return datetime.fromisoformat(str(value)).date()


# ---------------------------------------------------------------------------
# Reference helpers
# ---------------------------------------------------------------------------

def references_match(ref_a: Optional[str], ref_b: Optional[str]) -> bool:
    """
    Return True if two reference strings are considered a match.

    A match means one reference is a substring of the other (case-insensitive).
    Returns False if either reference is missing.
    """
    if not ref_a or not ref_b:
        return False

    a = ref_a.upper().strip()
    b = ref_b.upper().strip()

    return a in b or b in a


# ---------------------------------------------------------------------------
# Description fuzzy match
# ---------------------------------------------------------------------------

def fuzzy_similarity(description_a: str, description_b: str) -> float:
    """
    Return a similarity score between 0.0 and 1.0 for two descriptions.

    Uses rapidfuzz token_sort_ratio which handles word-order differences
    well (e.g. "ACME SALARY MARCH" vs "MARCH SALARY ACME").
    """
    if not description_a or not description_b:
        return 0.0

    score = fuzz.token_sort_ratio(
        description_a.lower().strip(),
        description_b.lower().strip(),
    )
    # rapidfuzz returns 0-100, convert to 0.0-1.0
    return score / 100.0


# ---------------------------------------------------------------------------
# Individual match strategy functions
# ---------------------------------------------------------------------------

def try_exact_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
) -> Optional[str]:
    """
    Strategy 1: Same date, same amount (within tolerance), same reference.

    Returns "EXACT" if matched, None otherwise.
    """
    if (
        amounts_are_close(bank_txn, ledger_entry, amount_tolerance)
        and dates_are_within(bank_txn, ledger_entry, max_days=0)
        and references_match(bank_txn.get("reference"), ledger_entry.get("reference"))
    ):
        return "EXACT"
    return None


def try_amount_date_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
    date_tolerance_days: int = 1,
) -> Optional[str]:
    """
    Strategy 2: Same amount, date within 1 day.

    Returns "AMOUNT_DATE" if matched, None otherwise.
    """
    if (
        amounts_are_close(bank_txn, ledger_entry, amount_tolerance)
        and dates_are_within(bank_txn, ledger_entry, max_days=date_tolerance_days)
    ):
        return "AMOUNT_DATE"
    return None


def try_amount_reference_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
) -> Optional[str]:
    """
    Strategy 3: Same amount, reference substring match.

    Date is not checked here — useful when transactions cross month-end
    and the reference is the reliable linking field.

    Returns "AMOUNT_REF" if matched, None otherwise.
    """
    if (
        amounts_are_close(bank_txn, ledger_entry, amount_tolerance)
        and references_match(bank_txn.get("reference"), ledger_entry.get("reference"))
    ):
        return "AMOUNT_REF"
    return None


def try_fuzzy_description_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
    fuzzy_threshold: float = 0.80,
) -> Optional[str]:
    """
    Strategy 4: Same amount, description similarity above threshold.

    Returns "FUZZY" if matched, None otherwise.
    """
    if not amounts_are_close(bank_txn, ledger_entry, amount_tolerance):
        return None

    similarity = fuzzy_similarity(
        bank_txn.get("description", ""),
        ledger_entry.get("description", ""),
    )

    if similarity >= fuzzy_threshold:
        return "FUZZY"
    return None


def try_amount_only_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
    date_tolerance_days: int = 3,
) -> Optional[str]:
    """
    Strategy 5: Same amount, date within 3 days — lowest confidence match.

    Returns "AMOUNT_ONLY" if matched, None otherwise.
    """
    if (
        amounts_are_close(bank_txn, ledger_entry, amount_tolerance)
        and dates_are_within(bank_txn, ledger_entry, max_days=date_tolerance_days)
    ):
        return "AMOUNT_ONLY"
    return None


# ---------------------------------------------------------------------------
# Run all strategies in priority order
# ---------------------------------------------------------------------------

def find_best_match(
    bank_txn: dict,
    ledger_entry: dict,
    amount_tolerance: float = 0.01,
    date_tolerance_days: int = 3,
    fuzzy_threshold: float = 0.80,
) -> Optional[tuple[str, float]]:
    """
    Try all match strategies in priority order against one bank/ledger pair.

    Returns (match_type, confidence_score) if any strategy succeeds,
    or None if no match is found.
    """
    # Strategy 1 — Exact
    result = try_exact_match(bank_txn, ledger_entry, amount_tolerance)
    if result:
        return result, CONFIDENCE[result]

    # Strategy 2 — Amount + Date (within 1 day)
    result = try_amount_date_match(bank_txn, ledger_entry, amount_tolerance, date_tolerance_days=1)
    if result:
        return result, CONFIDENCE[result]

    # Strategy 3 — Amount + Reference substring
    result = try_amount_reference_match(bank_txn, ledger_entry, amount_tolerance)
    if result:
        return result, CONFIDENCE[result]

    # Strategy 4 — Amount + Fuzzy description
    result = try_fuzzy_description_match(
        bank_txn, ledger_entry, amount_tolerance, fuzzy_threshold
    )
    if result:
        return result, CONFIDENCE[result]

    # Strategy 5 — Amount only, date within tolerance
    result = try_amount_only_match(bank_txn, ledger_entry, amount_tolerance, date_tolerance_days)
    if result:
        return result, CONFIDENCE[result]

    return None
