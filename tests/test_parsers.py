"""
test_parsers.py — Tests for the base parser, CSV parser, Excel parser,
and the normaliser utilities.

Run with:
    python -m pytest tests/test_parsers.py -v
"""

from datetime import date
from pathlib import Path

import pytest

from src.parsers.base_parser import ParsedTransaction
from src.parsers.csv_parser import CSVParser, find_matching_column
from src.utils.normaliser import (
    clean_description,
    extract_reference,
    generate_transaction_hash,
    parse_amount,
    parse_date,
    split_debit_credit,
)

# Path to the fixtures directory
FIXTURES = Path(__file__).parent / "fixtures"


# ===========================================================================
# normaliser — parse_date
# ===========================================================================

class TestParseDate:

    def test_dd_mm_yyyy_slash(self):
        assert parse_date("31/03/2026") == date(2026, 3, 31)

    def test_dd_mm_yyyy_dash(self):
        assert parse_date("31-03-2026") == date(2026, 3, 31)

    def test_yyyy_mm_dd_iso(self):
        assert parse_date("2026-03-31") == date(2026, 3, 31)

    def test_dd_mon_yyyy(self):
        assert parse_date("31 Mar 2026") == date(2026, 3, 31)

    def test_dd_month_yyyy(self):
        assert parse_date("31 March 2026") == date(2026, 3, 31)

    def test_two_digit_year(self):
        assert parse_date("31/03/26") == date(2026, 3, 31)

    def test_empty_string_returns_none(self):
        assert parse_date("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_date("   ") is None

    def test_garbage_string_returns_none(self):
        assert parse_date("not-a-date") is None


# ===========================================================================
# normaliser — parse_amount
# ===========================================================================

class TestParseAmount:

    def test_plain_number(self):
        assert parse_amount("1234.56") == 1234.56

    def test_with_commas(self):
        assert parse_amount("1,234.56") == 1234.56

    def test_with_rm_prefix(self):
        assert parse_amount("RM1,234.56") == 1234.56

    def test_with_spaces(self):
        # "1 234.56" — space as thousand separator → 1234.56
        assert parse_amount("  1 234.56  ") == pytest.approx(1234.56, rel=1e-4)

    def test_parentheses_as_negative(self):
        # Parentheses are standard accounting notation for negative numbers
        assert parse_amount("(500.00)") == -500.00

    def test_dash_returns_zero(self):
        assert parse_amount("-") == 0.0

    def test_empty_returns_zero(self):
        assert parse_amount("") == 0.0

    def test_trailing_dr_stripped(self):
        assert parse_amount("1,000.00 DR") == 1000.00

    def test_trailing_cr_stripped(self):
        assert parse_amount("500.00 CR") == 500.00


# ===========================================================================
# normaliser — split_debit_credit
# ===========================================================================

class TestSplitDebitCredit:

    def test_dr_suffix_goes_to_debit(self):
        debit, credit = split_debit_credit("1,000.00 DR")
        assert debit == 1000.00
        assert credit == 0.0

    def test_cr_suffix_goes_to_credit(self):
        debit, credit = split_debit_credit("500.00 CR")
        assert debit == 0.0
        assert credit == 500.00

    def test_no_suffix_positive_is_credit(self):
        debit, credit = split_debit_credit("250.00")
        assert debit == 0.0
        assert credit == 250.00

    def test_empty_returns_zeros(self):
        debit, credit = split_debit_credit("")
        assert debit == 0.0
        assert credit == 0.0


# ===========================================================================
# normaliser — clean_description
# ===========================================================================

class TestCleanDescription:

    def test_strips_surrounding_whitespace(self):
        assert clean_description("  PAYMENT  ") == "PAYMENT"

    def test_collapses_internal_spaces(self):
        assert clean_description("SALARY   CREDIT   ACME") == "SALARY CREDIT ACME"

    def test_handles_tabs_and_newlines(self):
        assert clean_description("FPX\tSHOPEE\nPAYMENT") == "FPX SHOPEE PAYMENT"

    def test_empty_returns_empty(self):
        assert clean_description("") == ""


# ===========================================================================
# normaliser — extract_reference
# ===========================================================================

class TestExtractReference:

    def test_extracts_fpx(self):
        assert extract_reference("FPX2026030001 SHOPEE") == "FPX2026030001"

    def test_extracts_ibg(self):
        assert extract_reference("IBG20260308 TRANSFER OUT") == "IBG20260308"

    def test_extracts_ibft(self):
        assert extract_reference("IBFT20260315 RECEIVE") == "IBFT20260315"

    def test_extracts_tt(self):
        assert extract_reference("TT123456 UTILITY BILL") == "TT123456"

    def test_returns_none_when_no_match(self):
        assert extract_reference("BANK CHARGES") is None


# ===========================================================================
# normaliser — generate_transaction_hash
# ===========================================================================

class TestGenerateTransactionHash:

    def test_same_inputs_produce_same_hash(self):
        hash1 = generate_transaction_hash(date(2026, 3, 5), "SHOPEE PAYMENT", 250.0, 0.0)
        hash2 = generate_transaction_hash(date(2026, 3, 5), "SHOPEE PAYMENT", 250.0, 0.0)
        assert hash1 == hash2

    def test_different_amounts_produce_different_hash(self):
        hash1 = generate_transaction_hash(date(2026, 3, 5), "SHOPEE PAYMENT", 250.0, 0.0)
        hash2 = generate_transaction_hash(date(2026, 3, 5), "SHOPEE PAYMENT", 251.0, 0.0)
        assert hash1 != hash2

    def test_different_dates_produce_different_hash(self):
        hash1 = generate_transaction_hash(date(2026, 3, 5), "SHOPEE PAYMENT", 250.0, 0.0)
        hash2 = generate_transaction_hash(date(2026, 3, 6), "SHOPEE PAYMENT", 250.0, 0.0)
        assert hash1 != hash2

    def test_hash_is_64_characters(self):
        # SHA256 hex digest is always 64 characters
        h = generate_transaction_hash(date(2026, 3, 5), "TEST", 100.0, 0.0)
        assert len(h) == 64


# ===========================================================================
# ParsedTransaction
# ===========================================================================

class TestParsedTransaction:

    def _make_transaction(self, debit=0.0, credit=0.0):
        return ParsedTransaction(
            transaction_date=date(2026, 3, 5),
            description="Test transaction",
            debit_amount=debit,
            credit_amount=credit,
        )

    def test_is_debit(self):
        txn = self._make_transaction(debit=100.0)
        assert txn.is_debit() is True
        assert txn.is_credit() is False

    def test_is_credit(self):
        txn = self._make_transaction(credit=500.0)
        assert txn.is_credit() is True
        assert txn.is_debit() is False

    def test_net_amount_debit(self):
        txn = self._make_transaction(debit=250.0)
        assert txn.net_amount() == -250.0

    def test_net_amount_credit(self):
        txn = self._make_transaction(credit=3500.0)
        assert txn.net_amount() == 3500.0

    def test_compute_hash_is_consistent(self):
        txn = self._make_transaction(debit=250.0)
        assert txn.compute_hash() == txn.compute_hash()


# ===========================================================================
# find_matching_column
# ===========================================================================

class TestFindMatchingColumn:

    def test_finds_exact_match(self):
        columns = ["Date", "Description", "Debit", "Credit", "Balance"]
        assert find_matching_column(columns, ["date", "transaction date"]) == "Date"

    def test_case_insensitive(self):
        columns = ["TRANSACTION DATE", "PARTICULARS", "AMOUNT"]
        assert find_matching_column(columns, ["transaction date"]) == "TRANSACTION DATE"

    def test_returns_none_when_not_found(self):
        columns = ["Col1", "Col2", "Col3"]
        assert find_matching_column(columns, ["date", "description"]) is None

    def test_first_match_wins(self):
        # "debit" appears before "withdrawal" in the column list
        columns = ["Date", "Debit", "Withdrawal", "Credit"]
        result = find_matching_column(columns, ["debit", "withdrawal"])
        assert result == "Debit"


# ===========================================================================
# CSVParser — with fixture file
# ===========================================================================

class TestCSVParser:

    def setup_method(self):
        self.fixture_path = str(FIXTURES / "sample_generic.csv")
        self.parser = CSVParser(file_path=self.fixture_path, bank_name="GENERIC")

    def test_parse_returns_correct_transaction_count(self):
        # File has 13 rows: 1 opening balance row (zero amounts, skipped) + 12 real transactions
        transactions = self.parser.parse()
        assert len(transactions) == 12

    def test_first_transaction_is_debit(self):
        transactions = self.parser.parse()
        # First real transaction: FPX SHOPEE PAYMENT 250.00 debit
        first = transactions[0]
        assert first.debit_amount == 250.00
        assert first.credit_amount == 0.0

    def test_salary_credit_parsed_correctly(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY" in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0

    def test_dates_parsed_correctly(self):
        transactions = self.parser.parse()
        assert transactions[0].transaction_date == date(2026, 3, 3)

    def test_reference_extracted_from_description(self):
        transactions = self.parser.parse()
        tnb = next(t for t in transactions if "TNB" in t.description)
        assert tnb.reference == "TT123456"

    def test_balance_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = transactions[0]
        assert shopee.balance == 4750.00

    def test_account_number_extracted(self):
        account = self.parser.extract_account_number()
        assert account == "1234567890"

    def test_statement_period(self):
        start, end = self.parser.extract_statement_period()
        # Period spans all rows in the date column, including the
        # opening-balance row (01/03/2026) which has no amounts
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 31)

    def test_all_transactions_have_hashes(self):
        transactions = self.parser.parse()
        for txn in transactions:
            assert txn.compute_hash() is not None
            assert len(txn.compute_hash()) == 64

    def test_no_duplicate_hashes(self):
        transactions = self.parser.parse()
        hashes = [t.compute_hash() for t in transactions]
        assert len(hashes) == len(set(hashes)), "Duplicate hashes found — duplicate detection broken"


class TestCSVParserSingleAmountColumn:

    def setup_method(self):
        self.fixture_path = str(FIXTURES / "sample_single_amount.csv")
        self.parser = CSVParser(file_path=self.fixture_path, bank_name="GENERIC")

    def test_dr_suffix_goes_to_debit(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.debit_amount == 250.00
        assert shopee.credit_amount == 0.0

    def test_cr_suffix_goes_to_credit(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY" in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0
