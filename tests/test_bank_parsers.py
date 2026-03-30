"""
test_bank_parsers.py — Tests for CIMB, HLB parsers and the parser factory.

Run with:
    python -m pytest tests/test_bank_parsers.py -v
"""

from datetime import date
from pathlib import Path

import pytest

from src.parsers.cimb_parser import CIMBCSVParser, CIMBPDFParser, CIMBParser
from src.parsers.hlb_parser import HLBExcelParser, HLBPDFParser, HLBParser
from src.parsers.factory import get_parser, SUPPORTED_BANKS

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fixture(filename: str) -> str:
    path = FIXTURES / filename
    if not path.exists():
        pytest.skip(f"Fixture not found: {filename}")
    return str(path)


# ===========================================================================
# CIMB CSV Parser
# ===========================================================================

class TestCIMBCSVParser:

    def setup_method(self):
        self.parser = CIMBCSVParser(file_path=fixture("sample_cimb.csv"))

    def test_returns_correct_transaction_count(self):
        transactions = self.parser.parse()
        assert len(transactions) == 12

    def test_debit_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.debit_amount == 250.00
        assert shopee.credit_amount == 0.0

    def test_credit_parsed_correctly(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY CREDIT" in t.description and "BONUS" not in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0

    def test_account_number_extracted(self):
        account = self.parser.extract_account_number()
        assert account == "80012345678901"

    def test_statement_period(self):
        start, end = self.parser.extract_statement_period()
        assert start == date(2026, 3, 3)
        assert end == date(2026, 3, 31)

    def test_reference_extracted(self):
        transactions = self.parser.parse()
        tnb = next(t for t in transactions if "TNB" in t.description)
        assert tnb.reference == "TT123456"

    def test_no_duplicate_hashes(self):
        transactions = self.parser.parse()
        hashes = [t.compute_hash() for t in transactions]
        assert len(hashes) == len(set(hashes))


# ===========================================================================
# CIMB PDF Parser
# ===========================================================================

class TestCIMBPDFParser:

    def setup_method(self):
        self.parser = CIMBPDFParser(file_path=fixture("sample_cimb.pdf"))

    def test_returns_transactions(self):
        transactions = self.parser.parse()
        assert len(transactions) > 0

    def test_debit_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.debit_amount == 250.00
        assert shopee.credit_amount == 0.0

    def test_credit_parsed_correctly(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY" in t.description and "BONUS" not in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0

    def test_account_number_extracted(self):
        account = self.parser.extract_account_number()
        assert account == "80012345678901"

    def test_statement_period(self):
        start, end = self.parser.extract_statement_period()
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 31)

    def test_no_duplicate_hashes(self):
        transactions = self.parser.parse()
        hashes = [t.compute_hash() for t in transactions]
        assert len(hashes) == len(set(hashes))


# ===========================================================================
# CIMBParser factory dispatch
# ===========================================================================

class TestCIMBParserDispatch:

    def test_pdf_returns_cimb_pdf_parser(self):
        parser = CIMBParser(file_path=fixture("sample_cimb.pdf"))
        assert isinstance(parser, CIMBPDFParser)

    def test_csv_returns_cimb_csv_parser(self):
        parser = CIMBParser(file_path=fixture("sample_cimb.csv"))
        assert isinstance(parser, CIMBCSVParser)

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="CIMB"):
            CIMBParser(file_path=fixture("sample_hlb.xlsx"))


# ===========================================================================
# HLB PDF Parser
# ===========================================================================

class TestHLBPDFParser:

    def setup_method(self):
        self.parser = HLBPDFParser(file_path=fixture("sample_hlb.pdf"))

    def test_returns_transactions(self):
        transactions = self.parser.parse()
        assert len(transactions) > 0

    def test_debit_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.debit_amount == 250.00
        assert shopee.credit_amount == 0.0

    def test_credit_parsed_correctly(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY" in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0

    def test_account_number_extracted(self):
        account = self.parser.extract_account_number()
        assert account == "1234567890"

    def test_statement_period(self):
        start, end = self.parser.extract_statement_period()
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 31)

    def test_no_duplicate_hashes(self):
        transactions = self.parser.parse()
        hashes = [t.compute_hash() for t in transactions]
        assert len(hashes) == len(set(hashes))


# ===========================================================================
# HLB Excel Parser
# ===========================================================================

class TestHLBExcelParser:

    def setup_method(self):
        self.parser = HLBExcelParser(file_path=fixture("sample_hlb.xlsx"))

    def test_returns_correct_transaction_count(self):
        transactions = self.parser.parse()
        assert len(transactions) == 8

    def test_debit_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.debit_amount == 250.00
        assert shopee.credit_amount == 0.0

    def test_credit_parsed_correctly(self):
        transactions = self.parser.parse()
        salary = next(t for t in transactions if "SALARY" in t.description)
        assert salary.credit_amount == 3500.00
        assert salary.debit_amount == 0.0

    def test_account_number_extracted(self):
        account = self.parser.extract_account_number()
        assert account == "1234567890"

    def test_no_duplicate_hashes(self):
        transactions = self.parser.parse()
        hashes = [t.compute_hash() for t in transactions]
        assert len(hashes) == len(set(hashes))

    def test_balance_parsed_correctly(self):
        transactions = self.parser.parse()
        shopee = next(t for t in transactions if "SHOPEE" in t.description)
        assert shopee.balance == 4750.00


# ===========================================================================
# HLBParser factory dispatch
# ===========================================================================

class TestHLBParserDispatch:

    def test_pdf_returns_hlb_pdf_parser(self):
        parser = HLBParser(file_path=fixture("sample_hlb.pdf"))
        assert isinstance(parser, HLBPDFParser)

    def test_xlsx_returns_hlb_excel_parser(self):
        parser = HLBParser(file_path=fixture("sample_hlb.xlsx"))
        assert isinstance(parser, HLBExcelParser)

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="HLB"):
            HLBParser(file_path=fixture("sample_cimb.csv"))


# ===========================================================================
# Parser factory (get_parser)
# ===========================================================================

class TestParserFactory:

    def test_cimb_pdf(self):
        parser = get_parser(bank_name="CIMB", file_path=fixture("sample_cimb.pdf"))
        assert isinstance(parser, CIMBPDFParser)

    def test_cimb_csv(self):
        parser = get_parser(bank_name="CIMB", file_path=fixture("sample_cimb.csv"))
        assert isinstance(parser, CIMBCSVParser)

    def test_hlb_pdf(self):
        parser = get_parser(bank_name="HLB", file_path=fixture("sample_hlb.pdf"))
        assert isinstance(parser, HLBPDFParser)

    def test_hlb_excel(self):
        parser = get_parser(bank_name="HLB", file_path=fixture("sample_hlb.xlsx"))
        assert isinstance(parser, HLBExcelParser)

    def test_case_insensitive_bank_name(self):
        parser = get_parser(bank_name="cimb", file_path=fixture("sample_cimb.csv"))
        assert isinstance(parser, CIMBCSVParser)

    def test_unknown_bank_raises(self):
        with pytest.raises(ValueError, match="Unknown bank"):
            get_parser(bank_name="UNKNOWN_BANK", file_path=fixture("sample_cimb.csv"))

    def test_maybank_uses_generic_parser(self):
        from src.parsers.csv_parser import CSVParser
        parser = get_parser(bank_name="MAYBANK", file_path=fixture("sample_generic.csv"))
        assert isinstance(parser, CSVParser)

    def test_supported_banks_list(self):
        assert "CIMB" in SUPPORTED_BANKS
        assert "HLB" in SUPPORTED_BANKS
        assert "MAYBANK" in SUPPORTED_BANKS
        assert "PUBLIC_BANK" in SUPPORTED_BANKS
