"""
test_maybank_public_bank.py — Tests for the Maybank and Public Bank parsers.

Run with:
    python -m pytest tests/test_maybank_public_bank.py -v
"""

from pathlib import Path

import pytest

from src.parsers.maybank_parser import MaybankCSVParser, MaybankPDFParser, MaybankParser
from src.parsers.public_bank_parser import (
    PublicBankCSVParser,
    PublicBankPDFParser,
    PublicBankParser,
)
from src.parsers.factory import get_parser

FIXTURES = Path(__file__).parent / "fixtures"

MAYBANK_CSV  = FIXTURES / "sample_maybank.csv"
MAYBANK_PDF  = FIXTURES / "sample_maybank.pdf"
PBB_CSV      = FIXTURES / "sample_public_bank.csv"
PBB_PDF      = FIXTURES / "sample_public_bank.pdf"


# ===========================================================================
# Maybank CSV parser
# ===========================================================================

class TestMaybankCSVParser:

    def test_returns_correct_number_of_transactions(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        txns = parser.parse()
        assert len(txns) == 7

    def test_account_number_extracted(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        account = parser.extract_account_number()
        assert account == "564312345678"

    def test_statement_period_extracted(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        start, end = parser.extract_statement_period()
        assert start.month == 3
        assert end.month == 3
        assert start.year == 2026

    def test_debit_amounts_parsed_correctly(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        txns = parser.parse()
        # First transaction is a debit: FPX SHOPEE PAYMENT 250.00
        shopee = next(t for t in txns if "SHOPEE" in t.description)
        assert shopee.debit_amount == pytest.approx(250.0)
        assert shopee.credit_amount == pytest.approx(0.0)

    def test_credit_amounts_parsed_correctly(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        txns = parser.parse()
        # Salary is a credit
        salary = next(t for t in txns if "SALARY" in t.description)
        assert salary.credit_amount == pytest.approx(3500.0)
        assert salary.debit_amount == pytest.approx(0.0)

    def test_descriptions_are_non_empty(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        for txn in parser.parse():
            assert txn.description.strip() != ""

    def test_transaction_dates_are_in_march_2026(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        for txn in parser.parse():
            assert txn.transaction_date.year == 2026
            assert txn.transaction_date.month == 3

    def test_each_transaction_has_a_hash(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        for txn in parser.parse():
            assert txn.compute_hash() is not None
            assert len(txn.compute_hash()) == 64  # SHA-256 hex digest

    def test_bank_name_is_maybank(self):
        parser = MaybankCSVParser(file_path=str(MAYBANK_CSV))
        assert parser.bank_name == "MAYBANK"


# ===========================================================================
# Maybank PDF parser
# ===========================================================================

class TestMaybankPDFParser:

    def test_returns_transactions(self):
        parser = MaybankPDFParser(file_path=str(MAYBANK_PDF))
        txns = parser.parse()
        assert len(txns) > 0

    def test_account_number_extracted(self):
        parser = MaybankPDFParser(file_path=str(MAYBANK_PDF))
        account = parser.extract_account_number()
        assert account == "564312345678"

    def test_all_transactions_have_dates(self):
        parser = MaybankPDFParser(file_path=str(MAYBANK_PDF))
        for txn in parser.parse():
            assert txn.transaction_date is not None

    def test_debit_or_credit_is_non_zero(self):
        parser = MaybankPDFParser(file_path=str(MAYBANK_PDF))
        for txn in parser.parse():
            assert txn.debit_amount > 0 or txn.credit_amount > 0


# ===========================================================================
# Maybank factory dispatch
# ===========================================================================

class TestMaybankFactory:

    def test_factory_returns_csv_parser_for_csv_file(self):
        parser = get_parser(bank_name="MAYBANK", file_path=str(MAYBANK_CSV))
        assert isinstance(parser, MaybankCSVParser)

    def test_factory_returns_pdf_parser_for_pdf_file(self):
        parser = get_parser(bank_name="MAYBANK", file_path=str(MAYBANK_PDF))
        assert isinstance(parser, MaybankPDFParser)

    def test_maybank_parser_class_dispatches_to_csv(self):
        parser = MaybankParser(file_path=str(MAYBANK_CSV))
        assert isinstance(parser, MaybankCSVParser)

    def test_maybank_parser_class_dispatches_to_pdf(self):
        parser = MaybankParser(file_path=str(MAYBANK_PDF))
        assert isinstance(parser, MaybankPDFParser)

    def test_maybank_parser_raises_for_unsupported_extension(self):
        with pytest.raises(ValueError, match="Maybank"):
            MaybankParser(file_path="statement.xlsx")

    def test_factory_case_insensitive_bank_name(self):
        parser = get_parser(bank_name="maybank", file_path=str(MAYBANK_CSV))
        assert isinstance(parser, MaybankCSVParser)


# ===========================================================================
# Public Bank CSV parser
# ===========================================================================

class TestPublicBankCSVParser:

    def test_returns_correct_number_of_transactions(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        txns = parser.parse()
        assert len(txns) == 7

    def test_account_number_extracted(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        account = parser.extract_account_number()
        assert account == "1234567890"

    def test_statement_period_extracted(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        start, end = parser.extract_statement_period()
        assert start.month == 3
        assert end.month == 3
        assert start.year == 2026

    def test_withdrawal_column_maps_to_debit(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        txns = parser.parse()
        # Cheque withdrawal should be debit
        cheque = next(t for t in txns if "CHEQUE" in t.description)
        assert cheque.debit_amount == pytest.approx(800.0)
        assert cheque.credit_amount == pytest.approx(0.0)

    def test_deposit_column_maps_to_credit(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        txns = parser.parse()
        # Salary credit should be credit
        salary = next(t for t in txns if "SALARY" in t.description)
        assert salary.credit_amount == pytest.approx(4500.0)
        assert salary.debit_amount == pytest.approx(0.0)

    def test_descriptions_are_non_empty(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        for txn in parser.parse():
            assert txn.description.strip() != ""

    def test_transaction_dates_are_in_march_2026(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        for txn in parser.parse():
            assert txn.transaction_date.year == 2026
            assert txn.transaction_date.month == 3

    def test_bank_name_is_public_bank(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        assert parser.bank_name == "PUBLIC_BANK"

    def test_each_transaction_has_a_hash(self):
        parser = PublicBankCSVParser(file_path=str(PBB_CSV))
        for txn in parser.parse():
            assert txn.compute_hash() is not None


# ===========================================================================
# Public Bank PDF parser
# ===========================================================================

class TestPublicBankPDFParser:

    def test_returns_transactions(self):
        parser = PublicBankPDFParser(file_path=str(PBB_PDF))
        txns = parser.parse()
        assert len(txns) > 0

    def test_account_number_extracted(self):
        parser = PublicBankPDFParser(file_path=str(PBB_PDF))
        account = parser.extract_account_number()
        assert account == "1234567890"

    def test_all_transactions_have_dates(self):
        parser = PublicBankPDFParser(file_path=str(PBB_PDF))
        for txn in parser.parse():
            assert txn.transaction_date is not None

    def test_debit_or_credit_is_non_zero(self):
        parser = PublicBankPDFParser(file_path=str(PBB_PDF))
        for txn in parser.parse():
            assert txn.debit_amount > 0 or txn.credit_amount > 0


# ===========================================================================
# Public Bank factory dispatch
# ===========================================================================

class TestPublicBankFactory:

    def test_factory_returns_csv_parser_for_csv_file(self):
        parser = get_parser(bank_name="PUBLIC_BANK", file_path=str(PBB_CSV))
        assert isinstance(parser, PublicBankCSVParser)

    def test_factory_returns_pdf_parser_for_pdf_file(self):
        parser = get_parser(bank_name="PUBLIC_BANK", file_path=str(PBB_PDF))
        assert isinstance(parser, PublicBankPDFParser)

    def test_public_bank_parser_class_dispatches_to_csv(self):
        parser = PublicBankParser(file_path=str(PBB_CSV))
        assert isinstance(parser, PublicBankCSVParser)

    def test_public_bank_parser_class_dispatches_to_pdf(self):
        parser = PublicBankParser(file_path=str(PBB_PDF))
        assert isinstance(parser, PublicBankPDFParser)

    def test_public_bank_parser_raises_for_unsupported_extension(self):
        with pytest.raises(ValueError, match="Public Bank"):
            PublicBankParser(file_path="statement.xlsx")

    def test_factory_case_insensitive_bank_name(self):
        parser = get_parser(bank_name="public_bank", file_path=str(PBB_CSV))
        assert isinstance(parser, PublicBankCSVParser)