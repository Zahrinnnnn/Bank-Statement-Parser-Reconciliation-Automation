"""
upload.py — Upload page for the Streamlit UI.

Lets the user upload a bank statement file (PDF, CSV, or Excel), select
the bank, optionally enter an account number, and trigger parsing.
Parsed transactions are saved to SQLite with duplicate detection.

The page shows a results summary after each successful parse.
"""

import tempfile
from pathlib import Path

import streamlit as st

from src.database.connection import get_db
from src.database.models import AuditLog, BankTransaction
from src.database.queries import insert_audit_log, insert_bank_transaction
from src.parsers.factory import get_parser


# Banks listed in the drop-down — "Generic" covers any CSV/Excel without
# a bank-specific parser.
SUPPORTED_BANKS = ["CIMB", "HLB", "MAYBANK", "PUBLIC_BANK", "GENERIC"]

# File types the upload widget will accept
ACCEPTED_EXTENSIONS = ["pdf", "csv", "xlsx", "xls"]


def render() -> None:
    """Render the Upload page."""
    st.header("📤 Upload Bank Statement")
    st.caption(
        "Upload a bank statement file, select the bank, and click Parse "
        "to import transactions into the database."
    )

    st.divider()

    # --- Upload form --------------------------------------------------------

    col_left, col_right = st.columns([2, 1])

    with col_left:
        uploaded_file = st.file_uploader(
            "Choose a bank statement file",
            type=ACCEPTED_EXTENSIONS,
            help="Supported formats: PDF, CSV, Excel (.xlsx, .xls)",
        )

    with col_right:
        bank_name = st.selectbox(
            "Bank",
            options=SUPPORTED_BANKS,
            help="Select the bank that issued this statement.",
        )
        account_number = st.text_input(
            "Account Number (optional)",
            placeholder="e.g. 80012345678901",
            help="Leave blank to auto-detect from the file.",
        )

    if not uploaded_file:
        st.info("Upload a file above to get started.")
        return

    # Show file details before parsing
    file_size_kb = len(uploaded_file.getvalue()) / 1024
    st.write(
        f"**File:** {uploaded_file.name}  |  "
        f"**Size:** {file_size_kb:.1f} KB  |  "
        f"**Bank:** {bank_name}"
    )

    st.divider()

    # --- Parse button -------------------------------------------------------

    if st.button("🚀 Parse & Import", type="primary", use_container_width=True):
        _parse_and_import(
            uploaded_file=uploaded_file,
            bank_name=bank_name,
            account_number=account_number.strip() or None,
        )


def _parse_and_import(uploaded_file, bank_name: str, account_number: str | None) -> None:
    """
    Save the uploaded file to a temp location, run the parser, and store
    results in the database.  Shows a progress spinner while working.
    """
    with st.spinner(f"Parsing {uploaded_file.name} ..."):
        # Write the uploaded bytes to a temp file so parsers can open it by path
        suffix = Path(uploaded_file.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            parser = get_parser(bank_name=bank_name, file_path=tmp_path)

            detected_account = account_number or parser.extract_account_number()
            period_start, period_end = parser.extract_statement_period()

            parsed_transactions = parser.parse()
        except Exception as parse_error:
            st.error(f"Parsing failed: {parse_error}")
            return
        finally:
            # Always remove the temp file even if parsing raised an exception
            Path(tmp_path).unlink(missing_ok=True)

    # --- Save to database ---------------------------------------------------

    new_count       = 0
    duplicate_count = 0

    with get_db() as db:
        conn = db.get_connection()

        for txn in parsed_transactions:
            bank_txn = BankTransaction(
                bank_name=bank_name.upper(),
                account_number=detected_account,
                transaction_date=txn.transaction_date,
                value_date=txn.value_date,
                description=txn.description,
                reference=txn.reference,
                debit_amount=txn.debit_amount,
                credit_amount=txn.credit_amount,
                balance=txn.balance,
                raw_description=txn.raw_description,
                source_file=uploaded_file.name,
                hash=txn.compute_hash(),
            )
            row_id = insert_bank_transaction(conn, bank_txn)
            if row_id == -1:
                duplicate_count += 1
            else:
                new_count += 1

        insert_audit_log(conn, AuditLog(
            action="PARSE_FILE",
            entity="bank_transactions",
            details={
                "file":       uploaded_file.name,
                "bank":       bank_name,
                "found":      len(parsed_transactions),
                "inserted":   new_count,
                "duplicates": duplicate_count,
            },
        ))

    # --- Results summary ----------------------------------------------------

    st.success("Import complete!")

    result_col1, result_col2, result_col3, result_col4 = st.columns(4)
    result_col1.metric("Found in file",   len(parsed_transactions))
    result_col2.metric("New imported",    new_count)
    result_col3.metric("Duplicates skipped", duplicate_count)
    result_col4.metric("Account",         detected_account or "—")

    if period_start or period_end:
        st.caption(
            f"Statement period: {period_start or '?'} to {period_end or '?'}"
        )

    if duplicate_count > 0:
        st.warning(
            f"{duplicate_count} duplicate transaction(s) were skipped — "
            "they are already in the database."
        )