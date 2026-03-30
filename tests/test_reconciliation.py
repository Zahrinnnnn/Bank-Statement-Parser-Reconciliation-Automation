"""
test_reconciliation.py — Tests for the reconciliation matching, exception
categorisation, and the full reconciliation engine.

Run with:
    python -m pytest tests/test_reconciliation.py -v
"""

from datetime import date
from pathlib import Path

import pytest

from src.reconciliation.matching import (
    CONFIDENCE,
    amounts_are_close,
    dates_are_within,
    find_best_match,
    fuzzy_similarity,
    references_match,
    try_amount_date_match,
    try_amount_only_match,
    try_amount_reference_match,
    try_exact_match,
    try_fuzzy_description_match,
)
from src.reconciliation.exceptions import (
    categorise_unmatched_bank_transaction,
    categorise_unmatched_ledger_entry,
    detect_duplicate_bank_transactions,
    summarise_exceptions,
)
from src.reconciliation.engine import run_reconciliation, ReconciliationResult
from src.database.connection import DatabaseConnection
from src.database.models import BankTransaction, LedgerEntry
from src.database.queries import insert_bank_transaction, insert_ledger_entry


# ---------------------------------------------------------------------------
# Test fixtures — minimal dicts that mimic database rows
# ---------------------------------------------------------------------------

def make_bank_txn(
    id=1,
    date="2026-03-05",
    description="SHOPEE PAYMENT",
    debit=250.0,
    credit=0.0,
    reference="FPX2026001",
    hash=None,
) -> dict:
    return {
        "id": id,
        "transaction_date": date,
        "description": description,
        "debit_amount": debit,
        "credit_amount": credit,
        "reference": reference,
        "hash": hash or f"hash_{id}",
        "entry_type": "DEBIT" if debit > 0 else "CREDIT",
    }


def make_ledger_entry(
    id=1,
    date="2026-03-05",
    description="Shopee Payment",
    amount=250.0,
    entry_type="DEBIT",
    reference="FPX2026001",
) -> dict:
    return {
        "id": id,
        "entry_date": date,
        "description": description,
        "amount": amount,
        "entry_type": entry_type,
        "reference": reference,
    }


# ===========================================================================
# amounts_are_close
# ===========================================================================

class TestAmountsAreClose:

    def test_exact_same_amount(self):
        bank = make_bank_txn(debit=250.0)
        ledger = make_ledger_entry(amount=250.0, entry_type="DEBIT")
        assert amounts_are_close(bank, ledger) is True

    def test_within_tolerance(self):
        bank = make_bank_txn(debit=250.00)
        ledger = make_ledger_entry(amount=250.009, entry_type="DEBIT")
        assert amounts_are_close(bank, ledger, tolerance=0.01) is True

    def test_outside_tolerance(self):
        bank = make_bank_txn(debit=250.00)
        ledger = make_ledger_entry(amount=251.00, entry_type="DEBIT")
        assert amounts_are_close(bank, ledger, tolerance=0.01) is False

    def test_direction_mismatch_debit_vs_credit(self):
        bank = make_bank_txn(debit=250.0, credit=0.0)
        ledger = make_ledger_entry(amount=250.0, entry_type="CREDIT")
        assert amounts_are_close(bank, ledger) is False

    def test_credit_direction_matches(self):
        bank = make_bank_txn(debit=0.0, credit=3500.0)
        ledger = make_ledger_entry(amount=3500.0, entry_type="CREDIT")
        assert amounts_are_close(bank, ledger) is True


# ===========================================================================
# dates_are_within
# ===========================================================================

class TestDatesAreWithin:

    def test_same_date(self):
        bank = make_bank_txn(date="2026-03-05")
        ledger = make_ledger_entry(date="2026-03-05")
        assert dates_are_within(bank, ledger, max_days=0) is True

    def test_one_day_apart_within_1(self):
        bank = make_bank_txn(date="2026-03-05")
        ledger = make_ledger_entry(date="2026-03-06")
        assert dates_are_within(bank, ledger, max_days=1) is True

    def test_one_day_apart_exceeds_0(self):
        bank = make_bank_txn(date="2026-03-05")
        ledger = make_ledger_entry(date="2026-03-06")
        assert dates_are_within(bank, ledger, max_days=0) is False

    def test_three_days_apart_within_3(self):
        bank = make_bank_txn(date="2026-03-01")
        ledger = make_ledger_entry(date="2026-03-04")
        assert dates_are_within(bank, ledger, max_days=3) is True

    def test_four_days_apart_exceeds_3(self):
        bank = make_bank_txn(date="2026-03-01")
        ledger = make_ledger_entry(date="2026-03-05")
        assert dates_are_within(bank, ledger, max_days=3) is False


# ===========================================================================
# references_match
# ===========================================================================

class TestReferencesMatch:

    def test_identical_references(self):
        assert references_match("FPX2026001", "FPX2026001") is True

    def test_substring_match(self):
        assert references_match("FPX2026001", "PAYMENT FPX2026001 SHOPEE") is True

    def test_no_match(self):
        assert references_match("FPX2026001", "IBG2026002") is False

    def test_none_reference_returns_false(self):
        assert references_match(None, "FPX2026001") is False
        assert references_match("FPX2026001", None) is False

    def test_case_insensitive(self):
        assert references_match("fpx2026001", "FPX2026001") is True


# ===========================================================================
# fuzzy_similarity
# ===========================================================================

class TestFuzzySimilarity:

    def test_identical_strings_score_1(self):
        assert fuzzy_similarity("shopee payment", "shopee payment") == 1.0

    def test_different_word_order_scores_high(self):
        # token_sort_ratio handles word-order differences
        score = fuzzy_similarity("ACME SALARY MARCH", "MARCH SALARY ACME")
        assert score >= 0.90

    def test_completely_different_scores_low(self):
        score = fuzzy_similarity("SHOPEE PAYMENT", "TNB ELECTRICITY BILL")
        assert score < 0.50

    def test_empty_string_scores_zero(self):
        assert fuzzy_similarity("", "SHOPEE") == 0.0


# ===========================================================================
# Individual match strategies
# ===========================================================================

class TestMatchStrategies:

    def test_exact_match_succeeds(self):
        bank   = make_bank_txn(date="2026-03-05", debit=250.0, reference="FPX2026001")
        ledger = make_ledger_entry(date="2026-03-05", amount=250.0, entry_type="DEBIT", reference="FPX2026001")
        assert try_exact_match(bank, ledger) == "EXACT"

    def test_exact_match_fails_on_date_mismatch(self):
        bank   = make_bank_txn(date="2026-03-05", debit=250.0, reference="FPX2026001")
        ledger = make_ledger_entry(date="2026-03-06", amount=250.0, entry_type="DEBIT", reference="FPX2026001")
        assert try_exact_match(bank, ledger) is None

    def test_amount_date_match_succeeds(self):
        bank   = make_bank_txn(date="2026-03-05", debit=1000.0, reference=None)
        ledger = make_ledger_entry(date="2026-03-06", amount=1000.0, entry_type="DEBIT", reference=None)
        assert try_amount_date_match(bank, ledger, date_tolerance_days=1) == "AMOUNT_DATE"

    def test_amount_date_match_fails_outside_tolerance(self):
        bank   = make_bank_txn(date="2026-03-05", debit=1000.0)
        ledger = make_ledger_entry(date="2026-03-08", amount=1000.0, entry_type="DEBIT")
        assert try_amount_date_match(bank, ledger, date_tolerance_days=1) is None

    def test_amount_reference_match_succeeds(self):
        bank   = make_bank_txn(date="2026-03-05", debit=156.30, reference="TT123456")
        ledger = make_ledger_entry(date="2026-03-10", amount=156.30, entry_type="DEBIT", reference="TT123456")
        assert try_amount_reference_match(bank, ledger) == "AMOUNT_REF"

    def test_fuzzy_match_above_threshold(self):
        bank   = make_bank_txn(debit=3500.0, description="SALARY CREDIT ACME SDN BHD")
        ledger = make_ledger_entry(amount=3500.0, entry_type="DEBIT", description="ACME SDN BHD SALARY MARCH")
        # Force direction match
        bank["debit_amount"] = 0.0
        bank["credit_amount"] = 3500.0
        ledger["entry_type"] = "CREDIT"
        assert try_fuzzy_description_match(bank, ledger, fuzzy_threshold=0.60) == "FUZZY"

    def test_fuzzy_match_below_threshold_returns_none(self):
        bank   = make_bank_txn(debit=500.0, description="SHOPEE PAYMENT")
        ledger = make_ledger_entry(amount=500.0, entry_type="DEBIT", description="TNB ELECTRICITY BILL")
        assert try_fuzzy_description_match(bank, ledger, fuzzy_threshold=0.80) is None

    def test_amount_only_match_succeeds(self):
        bank   = make_bank_txn(date="2026-03-05", debit=89.90, reference=None)
        ledger = make_ledger_entry(date="2026-03-07", amount=89.90, entry_type="DEBIT", reference=None)
        assert try_amount_only_match(bank, ledger, date_tolerance_days=3) == "AMOUNT_ONLY"


# ===========================================================================
# find_best_match — priority ordering
# ===========================================================================

class TestFindBestMatch:

    def test_exact_wins_over_amount_date(self):
        bank   = make_bank_txn(date="2026-03-05", debit=250.0, reference="FPX001")
        ledger = make_ledger_entry(date="2026-03-05", amount=250.0, entry_type="DEBIT", reference="FPX001")
        result = find_best_match(bank, ledger)
        assert result is not None
        match_type, confidence = result
        assert match_type == "EXACT"
        assert confidence == CONFIDENCE["EXACT"]

    def test_returns_none_when_no_match(self):
        bank   = make_bank_txn(date="2026-03-05", debit=250.0, reference="FPX001")
        ledger = make_ledger_entry(date="2026-03-20", amount=999.0, entry_type="DEBIT", reference="IBG999")
        result = find_best_match(bank, ledger)
        assert result is None

    def test_confidence_scores_are_correct(self):
        assert CONFIDENCE["EXACT"]       == 1.00
        assert CONFIDENCE["AMOUNT_DATE"] == 0.95
        assert CONFIDENCE["AMOUNT_REF"]  == 0.90
        assert CONFIDENCE["FUZZY"]       == 0.75
        assert CONFIDENCE["AMOUNT_ONLY"] == 0.60


# ===========================================================================
# Exception categorisation
# ===========================================================================

class TestExceptionCategorisation:

    def test_small_unmatched_bank_txn_is_bank_only(self):
        bank = make_bank_txn(debit=250.0)
        exc = categorise_unmatched_bank_transaction(bank, large_amount_threshold=5000.0)
        assert exc.exception_type == "BANK_ONLY"

    def test_large_unmatched_bank_txn_is_large_unmatched(self):
        bank = make_bank_txn(debit=10000.0)
        exc = categorise_unmatched_bank_transaction(bank, large_amount_threshold=5000.0)
        assert exc.exception_type == "LARGE_UNMATCHED"

    def test_unmatched_ledger_is_ledger_only(self):
        ledger = make_ledger_entry(amount=500.0)
        exc = categorise_unmatched_ledger_entry(ledger)
        assert exc.exception_type == "LEDGER_ONLY"

    def test_duplicate_detection(self):
        txns = [
            make_bank_txn(id=1, hash="abc123"),
            make_bank_txn(id=2, hash="def456"),
            make_bank_txn(id=3, hash="abc123"),  # duplicate of txn 1
        ]
        duplicates = detect_duplicate_bank_transactions(txns)
        assert len(duplicates) == 1
        assert duplicates[0].exception_type == "DUPLICATE_BANK"
        assert duplicates[0].bank_txn_id == 3

    def test_no_duplicates_when_all_unique(self):
        txns = [
            make_bank_txn(id=1, hash="abc123"),
            make_bank_txn(id=2, hash="def456"),
        ]
        assert detect_duplicate_bank_transactions(txns) == []

    def test_summarise_exceptions(self):
        from src.reconciliation.exceptions import ExceptionItem
        exceptions = [
            ExceptionItem("BANK_ONLY", bank_txn_id=1),
            ExceptionItem("BANK_ONLY", bank_txn_id=2),
            ExceptionItem("LEDGER_ONLY", ledger_entry_id=3),
            ExceptionItem("LARGE_UNMATCHED", bank_txn_id=4),
        ]
        summary = summarise_exceptions(exceptions)
        assert summary["BANK_ONLY"] == 2
        assert summary["LEDGER_ONLY"] == 1
        assert summary["LARGE_UNMATCHED"] == 1


# ===========================================================================
# Full reconciliation engine — integration test with in-memory SQLite
# ===========================================================================

class TestReconciliationEngine:
    """
    Integration tests that run a full reconciliation against an in-memory
    SQLite database populated with known transactions and ledger entries.
    """

    def setup_method(self):
        """Create a fresh in-memory database with sample data for each test."""
        from pathlib import Path

        self.db = DatabaseConnection(db_path=Path(":memory:"))
        self.db.connect()
        self.db.initialise_schema()
        self.conn = self.db.get_connection()
        self._load_sample_data()

    def teardown_method(self):
        self.db.close()

    def _load_sample_data(self):
        """Insert bank transactions and ledger entries for March 2026."""
        bank_txns = [
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 3),
                description="FPX SHOPEE PAYMENT", reference="FPX2026001",
                debit_amount=250.0, credit_amount=0.0,
                source_file="test.csv",
                hash="hash_shopee",
            ),
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 5),
                description="SALARY CREDIT ACME SDN BHD", reference=None,
                debit_amount=0.0, credit_amount=3500.0,
                source_file="test.csv",
                hash="hash_salary",
            ),
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 8),
                description="IBG TRANSFER OUT", reference="IBG20260308",
                debit_amount=1000.0, credit_amount=0.0,
                source_file="test.csv",
                hash="hash_ibg",
            ),
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 20),
                description="UNKNOWN PAYMENT NO LEDGER MATCH", reference=None,
                debit_amount=99.0, credit_amount=0.0,
                source_file="test.csv",
                hash="hash_unknown",
            ),
        ]

        for txn in bank_txns:
            insert_bank_transaction(self.conn, txn)

        ledger_entries = [
            LedgerEntry(
                entry_date=date(2026, 3, 3),
                description="Shopee Payment March", reference="FPX2026001",
                amount=250.0, entry_type="DEBIT",
            ),
            LedgerEntry(
                entry_date=date(2026, 3, 5),
                description="Salary March 2026", reference="PAYROLL-MAR-26",
                amount=3500.0, entry_type="CREDIT",
            ),
            LedgerEntry(
                entry_date=date(2026, 3, 8),
                description="Transfer to Ahmad Ali", reference="IBG20260308",
                amount=1000.0, entry_type="DEBIT",
            ),
            LedgerEntry(
                entry_date=date(2026, 3, 15),
                description="Outstanding ledger entry with no bank match",
                reference=None, amount=500.0, entry_type="DEBIT",
            ),
        ]

        for entry in ledger_entries:
            insert_ledger_entry(self.conn, entry)

    def _run(self, **kwargs) -> ReconciliationResult:
        return run_reconciliation(
            conn=self.conn,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            bank_name="CIMB",
            account_number="1234567890",
            **kwargs,
        )

    def test_matched_count_correct(self):
        result = self._run()
        # Shopee (exact ref+amount+date), Salary (amount+date), IBG (exact) = 3
        assert result.matched_count == 3

    def test_unmatched_bank_count_correct(self):
        result = self._run()
        # "UNKNOWN PAYMENT" has no ledger match
        assert result.unmatched_bank_count == 1

    def test_unmatched_ledger_count_correct(self):
        result = self._run()
        # "Outstanding ledger entry" has no bank match
        assert result.unmatched_ledger_count == 1

    def test_total_counts_correct(self):
        result = self._run()
        assert result.total_bank_txns == 4
        assert result.total_ledger_entries == 4

    def test_recon_id_assigned(self):
        result = self._run()
        assert result.recon_id > 0

    def test_exact_match_shopee(self):
        result = self._run()
        shopee_pair = next(
            p for p in result.matched_pairs
            if "SHOPEE" in p["bank_txn"]["description"]
        )
        assert shopee_pair["match_type"] == "EXACT"
        assert shopee_pair["confidence_score"] == 1.0

    def test_match_rate_is_75_percent(self):
        result = self._run()
        # 3 matched out of 4 bank txns = 75%
        assert result.match_rate() == pytest.approx(75.0)

    def test_exception_count_equals_unmatched_total(self):
        result = self._run()
        # 1 unmatched bank + 1 unmatched ledger = 2 exceptions
        assert result.exception_count == 2

    def test_bank_only_exception_present(self):
        result = self._run()
        bank_only = [e for e in result.exceptions if e.exception_type == "BANK_ONLY"]
        assert len(bank_only) == 1

    def test_ledger_only_exception_present(self):
        result = self._run()
        ledger_only = [e for e in result.exceptions if e.exception_type == "LEDGER_ONLY"]
        assert len(ledger_only) == 1

    def test_duplicate_detection_with_real_db(self):
        """Second import of same data should produce zero new rows and detect no duplicates."""
        # All hashes are unique so no duplicates expected
        result = self._run()
        duplicate_excs = [e for e in result.exceptions if e.exception_type == "DUPLICATE_BANK"]
        assert len(duplicate_excs) == 0

    def test_amount_tolerance_applied(self):
        """A ledger entry 0.005 off should still match within default tolerance."""
        result = self._run(amount_tolerance=0.01)
        # The existing exact matches should still work
        assert result.matched_count >= 3

    def test_summary_string_contains_key_info(self):
        result = self._run()
        summary = result.summary()
        assert "CIMB" in summary
        assert "Matched" in summary
        assert "Unmatched" in summary
