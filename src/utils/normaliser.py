"""
normaliser.py — Cleans and standardises raw data from bank statements.

Every bank formats dates, amounts, and descriptions differently.
This module converts everything into one consistent format before
it touches the database.

Rules applied:
  - Dates: try multiple formats, always return a date object
  - Amounts: strip currency symbols, commas, whitespace; handle Dr/Cr suffix
  - Descriptions: collapse whitespace, strip control characters
  - References: extract common Malaysian payment reference formats
  - Hashes: SHA256 of date + description + amounts for duplicate detection
"""

import hashlib
import logging
import re
from datetime import date
from typing import Optional

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

# Formats tried in order before falling back to dateutil's flexible parser.
# Most Malaysian bank statements use DD/MM/YYYY or DD-MM-YYYY.
DATE_FORMATS_TO_TRY = [
    "%d/%m/%Y",   # 31/03/2026  ← most common in Malaysian banks
    "%d-%m-%Y",   # 31-03-2026
    "%Y-%m-%d",   # 2026-03-31  ← ISO format
    "%d %b %Y",   # 31 Mar 2026
    "%d %B %Y",   # 31 March 2026
    "%d/%m/%y",   # 31/03/26   ← two-digit year
    "%d-%m-%y",   # 31-03-26
]


def parse_date(raw_date: str) -> Optional[date]:
    """
    Convert a raw date string into a Python date object.

    Tries a list of known formats first for speed, then falls back
    to dateutil's flexible parser which handles almost anything.
    Returns None if the string cannot be parsed.
    """
    if not raw_date or not raw_date.strip():
        return None

    cleaned = raw_date.strip()

    # Try each known format before reaching for the heavy parser
    from datetime import datetime
    for fmt in DATE_FORMATS_TO_TRY:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Last resort — dateutil handles most remaining edge cases
    try:
        return dateutil_parser.parse(cleaned, dayfirst=True).date()
    except Exception:
        logger.warning("Could not parse date: %r", raw_date)
        return None


# ---------------------------------------------------------------------------
# Amount normalisation
# ---------------------------------------------------------------------------

# Matches trailing Dr/Cr indicators that some banks append to amounts
DR_CR_PATTERN = re.compile(r"\s*(DR|CR|Dr|Cr|dr|cr)\s*$")


def parse_amount(raw_amount: str) -> float:
    """
    Convert a raw amount string into a plain float.

    Handles:
      - Currency symbols:  RM1,234.56  →  1234.56
      - Commas:            1,234.56    →  1234.56
      - Trailing Dr/Cr:   1234.56 DR  →  1234.56  (sign handled separately)
      - Parentheses:       (1234.56)   →  1234.56  (some banks use for debits)
      - Empty / dash:      -  or  ""  →  0.0
    """
    if not raw_amount or not str(raw_amount).strip():
        return 0.0

    text = str(raw_amount).strip()

    # Dash or placeholder means zero
    if text in ("-", "–", "—", "N/A", "nil", "NIL"):
        return 0.0

    # Remove Dr/Cr suffix before numeric parsing
    text = DR_CR_PATTERN.sub("", text)

    # Parentheses mean negative in accounting notation — strip them
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")

    # Remove currency symbols and thousand separators.
    # Replace commas and spaces used as thousand separators,
    # but only after stripping the currency prefix — otherwise
    # "1 234.56" (space-separated thousands) becomes "123456".
    text = text.replace("RM", "").replace(",", "")

    # Remove spaces only if they are acting as thousand separators
    # (i.e. digits on both sides). A leading/trailing space is already gone.
    import re as _re
    text = _re.sub(r"(\d)\s(\d)", r"\1\2", text).strip()

    try:
        amount = float(text)
        return -amount if is_negative else amount
    except ValueError:
        logger.warning("Could not parse amount: %r", raw_amount)
        return 0.0


def split_debit_credit(raw_amount: str) -> tuple[float, float]:
    """
    Some banks use a single amount column with a Dr/Cr suffix to indicate
    direction (e.g. "1,234.56 DR"). Split that into separate debit/credit.

    Returns (debit_amount, credit_amount) — one of which will always be 0.
    """
    if not raw_amount or not str(raw_amount).strip():
        return 0.0, 0.0

    text = str(raw_amount).strip()
    match = DR_CR_PATTERN.search(text)

    amount = parse_amount(text)

    if match:
        indicator = match.group(1).upper()
        if indicator == "DR":
            return amount, 0.0   # debit
        else:
            return 0.0, amount   # credit

    # No suffix — assume positive values are credits (common default)
    if amount >= 0:
        return 0.0, amount
    else:
        return abs(amount), 0.0


# ---------------------------------------------------------------------------
# Description normalisation
# ---------------------------------------------------------------------------

# Collapse multiple spaces, tabs, newlines into a single space
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_description(raw_description: str) -> str:
    """
    Normalise a transaction description.

    - Strips leading/trailing whitespace
    - Collapses internal runs of whitespace to a single space
    - Removes non-printable control characters
    """
    if not raw_description:
        return ""

    # Remove control characters (ASCII 0-31 except newline/tab which collapse)
    printable = "".join(ch for ch in str(raw_description) if ch.isprintable() or ch in "\t\n")

    # Collapse all whitespace runs into a single space
    collapsed = WHITESPACE_PATTERN.sub(" ", printable)

    return collapsed.strip()


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------

# Common Malaysian payment reference patterns
REFERENCE_PATTERNS = [
    re.compile(r"\b(TT\d+)\b", re.IGNORECASE),          # Telegraphic transfer
    re.compile(r"\b(FPX\w+)\b", re.IGNORECASE),         # FPX online payment
    re.compile(r"\b(IBG\w+)\b", re.IGNORECASE),         # Interbank GIRO
    re.compile(r"\b(IBFT\w+)\b", re.IGNORECASE),        # Interbank fund transfer
    re.compile(r"\b(CHEQ?\s*\w+)\b", re.IGNORECASE),   # Cheque number
    re.compile(r"\b([A-Z]{2,4}\d{6,})\b"),              # Generic alphanumeric ref
]


def extract_reference(description: str) -> Optional[str]:
    """
    Try to extract a payment reference from a transaction description.

    Returns the first recognisable reference found, or None.
    """
    if not description:
        return None

    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(description)
        if match:
            return match.group(1).upper().replace(" ", "")

    return None


# ---------------------------------------------------------------------------
# Duplicate detection hash
# ---------------------------------------------------------------------------

def generate_transaction_hash(
    transaction_date: date,
    description: str,
    debit_amount: float,
    credit_amount: float,
) -> str:
    """
    Generate a SHA256 hash that uniquely identifies a transaction.

    The hash is stored in the database with a UNIQUE constraint so
    importing the same file twice never creates duplicate rows.

    The key is: date + cleaned description + debit + credit
    Amounts are rounded to 2 decimal places before hashing to avoid
    floating-point representation differences causing false duplicates.
    """
    key = (
        f"{transaction_date.isoformat()}"
        f"|{clean_description(description).lower()}"
        f"|{round(debit_amount, 2)}"
        f"|{round(credit_amount, 2)}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
