"""
factory.py — Parser factory that returns the right parser for a given bank and file.

The CLI and Streamlit UI use this factory so they don't need to import
individual parser classes. Just pass the bank name and file path and
get back a parser ready to call .parse() on.

Supported banks:
    CIMB         — PDF, CSV
    HLB          — PDF, Excel (.xlsx, .xls)
    MAYBANK      — PDF, CSV
    PUBLIC_BANK  — PDF, CSV
    GENERIC      — any CSV, Excel, or PDF

Usage:
    parser = get_parser(bank_name="CIMB", file_path="statement.pdf")
    transactions = parser.parse()
"""

import logging
from pathlib import Path

from src.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

# Supported bank names — normalised to uppercase for matching
SUPPORTED_BANKS = ["CIMB", "HLB", "MAYBANK", "PUBLIC_BANK", "GENERIC"]


def get_parser(bank_name: str, file_path: str) -> BaseParser:
    """
    Return the appropriate parser for the given bank and file type.

    Args:
        bank_name:  One of CIMB, HLB, MAYBANK, PUBLIC_BANK, GENERIC.
                    Case-insensitive.
        file_path:  Path to the bank statement file.

    Returns:
        A parser instance with .parse(), .extract_account_number(),
        and .extract_statement_period() ready to call.

    Raises:
        ValueError: If the bank name or file type is not supported.
        FileNotFoundError: If the file does not exist.
    """
    bank = bank_name.upper().strip()
    extension = Path(file_path).suffix.lower()

    if bank == "CIMB":
        return _get_cimb_parser(file_path, extension)

    if bank == "HLB":
        return _get_hlb_parser(file_path, extension)

    if bank == "MAYBANK":
        return _get_maybank_parser(file_path, extension)

    if bank == "PUBLIC_BANK":
        return _get_public_bank_parser(file_path, extension)

    if bank == "GENERIC":
        return _get_generic_parser(file_path, extension, bank_name="GENERIC")

    raise ValueError(
        f"Unknown bank: {bank_name!r}. "
        f"Supported banks: {', '.join(SUPPORTED_BANKS)}"
    )


def _get_cimb_parser(file_path: str, extension: str) -> BaseParser:
    from src.parsers.cimb_parser import CIMBCSVParser, CIMBPDFParser

    if extension == ".pdf":
        return CIMBPDFParser(file_path=file_path)
    if extension == ".csv":
        return CIMBCSVParser(file_path=file_path)

    raise ValueError(f"CIMB supports .pdf and .csv files. Got: {extension}")


def _get_hlb_parser(file_path: str, extension: str) -> BaseParser:
    from src.parsers.hlb_parser import HLBExcelParser, HLBPDFParser

    if extension == ".pdf":
        return HLBPDFParser(file_path=file_path)
    if extension in (".xlsx", ".xls"):
        return HLBExcelParser(file_path=file_path)

    raise ValueError(f"HLB supports .pdf, .xlsx, and .xls files. Got: {extension}")


def _get_maybank_parser(file_path: str, extension: str) -> BaseParser:
    from src.parsers.maybank_parser import MaybankCSVParser, MaybankPDFParser

    if extension == ".pdf":
        return MaybankPDFParser(file_path=file_path)
    if extension == ".csv":
        return MaybankCSVParser(file_path=file_path)

    raise ValueError(f"Maybank supports .pdf and .csv files. Got: {extension}")


def _get_public_bank_parser(file_path: str, extension: str) -> BaseParser:
    from src.parsers.public_bank_parser import PublicBankCSVParser, PublicBankPDFParser

    if extension == ".pdf":
        return PublicBankPDFParser(file_path=file_path)
    if extension == ".csv":
        return PublicBankCSVParser(file_path=file_path)

    raise ValueError(f"Public Bank supports .pdf and .csv files. Got: {extension}")


def _get_generic_parser(
    file_path: str, extension: str, bank_name: str
) -> BaseParser:
    from src.parsers.csv_parser import CSVParser
    from src.parsers.excel_parser import ExcelParser
    from src.parsers.pdf_parser import PDFParser

    if extension == ".pdf":
        return PDFParser(file_path=file_path, bank_name=bank_name)
    if extension == ".csv":
        return CSVParser(file_path=file_path, bank_name=bank_name)
    if extension in (".xlsx", ".xls"):
        return ExcelParser(file_path=file_path, bank_name=bank_name)

    raise ValueError(
        f"Unsupported file type: {extension}. Supported: .pdf, .csv, .xlsx, .xls"
    )
