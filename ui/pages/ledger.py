"""
ledger.py — Ledger Import page for the Streamlit UI.

Lets the user upload a CSV file containing internal ledger entries,
preview the rows, and import them into the database for reconciliation.

Expected CSV columns:
    date, description, amount, entry_type (DEBIT or CREDIT), reference

Optional columns:
    account_code, counterparty
"""

import io
from datetime import date, datetime

import pandas as pd
import streamlit as st

from src.database.connection import get_db
from src.database.models import AuditLog, LedgerEntry
from src.database.queries import insert_audit_log, insert_ledger_entry


# Required columns that must be present in the uploaded CSV
REQUIRED_COLUMNS = {"date", "description", "amount", "entry_type"}

# Sample CSV content shown to the user as a format guide
SAMPLE_CSV = """date,description,amount,entry_type,reference,account_code,counterparty
2026-03-01,Payment to Vendor ABC,1500.00,DEBIT,INV-001,5000,ABC Sdn Bhd
2026-03-02,Customer Payment XYZ,3200.00,CREDIT,REC-045,4000,XYZ Trading
2026-03-05,Utility Bill TNB,450.00,DEBIT,BILL-012,6100,Tenaga Nasional
2026-03-10,Salary Payment,8000.00,DEBIT,SAL-MAR,6200,Staff
2026-03-15,Sales Collection,5500.00,CREDIT,SO-0089,4000,Customer A
"""


def render() -> None:
    """Render the Ledger Import page."""
    st.header("📒 Import Ledger")
    st.caption(
        "Upload your internal accounting ledger as a CSV file. "
        "The system will match these entries against your bank statement "
        "transactions during reconciliation."
    )

    st.divider()

    # --- Format guide -------------------------------------------------------

    with st.expander("📋 Required CSV format — click to see example", expanded=False):
        st.markdown(
            "Your CSV must have these columns: "
            "`date`, `description`, `amount`, `entry_type`\n\n"
            "Optional columns: `reference`, `account_code`, `counterparty`\n\n"
            "**entry_type** must be `DEBIT` or `CREDIT`  \n"
            "**date** format: `YYYY-MM-DD`"
        )
        st.code(SAMPLE_CSV, language="csv")

        # Download a ready-made sample the user can fill in
        st.download_button(
            label="⬇️ Download sample CSV template",
            data=SAMPLE_CSV,
            file_name="ledger_template.csv",
            mime="text/csv",
        )

    st.divider()

    # --- Upload form --------------------------------------------------------

    uploaded_file = st.file_uploader(
        "Choose a ledger CSV file",
        type=["csv"],
        help="Upload a CSV with your internal accounting entries.",
    )

    if not uploaded_file:
        st.info("Upload a CSV file above to get started.")
        return

    # --- Parse and preview --------------------------------------------------

    try:
        dataframe = pd.read_csv(io.BytesIO(uploaded_file.getvalue()))
    except Exception as read_error:
        st.error(f"Could not read CSV: {read_error}")
        return

    # Normalise column names to lowercase with no extra whitespace
    dataframe.columns = [col.strip().lower() for col in dataframe.columns]

    missing_columns = REQUIRED_COLUMNS - set(dataframe.columns)
    if missing_columns:
        st.error(
            f"Missing required column(s): **{', '.join(sorted(missing_columns))}**  \n"
            "Check the format guide above."
        )
        return

    st.success(f"File loaded — {len(dataframe)} rows found.")

    # Show a preview of the first 10 rows so the user can verify before importing
    st.subheader("Preview (first 10 rows)")
    st.dataframe(dataframe.head(10), use_container_width=True, hide_index=True)

    # Show entry type breakdown
    if "entry_type" in dataframe.columns:
        type_counts = dataframe["entry_type"].str.upper().value_counts()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total rows",  len(dataframe))
        col2.metric("DEBIT rows",  int(type_counts.get("DEBIT",  0)))
        col3.metric("CREDIT rows", int(type_counts.get("CREDIT", 0)))

    st.divider()

    # --- Period label (optional) for the audit log --------------------------

    period = st.text_input(
        "Period label (optional)",
        placeholder="e.g. 2026-03",
        help="Used for reference only — helps you identify this import later.",
    )

    # --- Import button ------------------------------------------------------

    if st.button("📥 Import Ledger Entries", type="primary", use_container_width=True):
        _import_ledger(dataframe, uploaded_file.name, period.strip() or None)


def _import_ledger(dataframe: pd.DataFrame, source_file: str, period: str | None) -> None:
    """
    Validate each row, build LedgerEntry objects, and insert them into
    the database.  Shows a progress bar and a results summary when done.
    """
    inserted_count = 0
    skipped_count  = 0
    error_rows      = []

    progress_bar = st.progress(0, text="Importing...")
    total_rows   = len(dataframe)

    with get_db() as db:
        conn = db.get_connection()

        for row_index, row in dataframe.iterrows():
            progress_bar.progress(
                (row_index + 1) / total_rows,
                text=f"Importing row {row_index + 1} of {total_rows}...",
            )

            # --- Validate and parse each row --------------------------------

            try:
                entry_date  = _parse_date(str(row["date"]).strip())
                description = str(row["description"]).strip()
                amount      = float(row["amount"])
                entry_type  = str(row["entry_type"]).strip().upper()

                if entry_type not in ("DEBIT", "CREDIT"):
                    raise ValueError(
                        f"entry_type must be DEBIT or CREDIT, got '{entry_type}'"
                    )

                reference    = _optional_str(row, "reference")
                account_code = _optional_str(row, "account_code")
                counterparty = _optional_str(row, "counterparty")

            except Exception as validation_error:
                error_rows.append((row_index + 1, str(validation_error)))
                skipped_count += 1
                continue

            # --- Insert into database ---------------------------------------

            ledger_entry = LedgerEntry(
                entry_date=entry_date,
                description=description,
                amount=amount,
                entry_type=entry_type,
                reference=reference,
                account_code=account_code,
                counterparty=counterparty,
                source=source_file,
            )

            insert_ledger_entry(conn, ledger_entry)
            inserted_count += 1

        # Write one audit log entry for the whole import
        insert_audit_log(conn, AuditLog(
            action="IMPORT_LEDGER",
            entity="ledger_entries",
            details={
                "file":     source_file,
                "period":   period or "unspecified",
                "inserted": inserted_count,
                "skipped":  skipped_count,
            },
        ))

    progress_bar.empty()

    # --- Results summary ----------------------------------------------------

    if inserted_count > 0:
        st.success(f"Import complete — {inserted_count} entries added.")
    else:
        st.warning("No entries were imported.")

    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Imported",   inserted_count)
    summary_col2.metric("Skipped",    skipped_count)
    summary_col3.metric("Period",     period or "—")

    # Show row-level errors if any rows failed validation
    if error_rows:
        st.error(f"{skipped_count} row(s) had errors and were skipped:")
        for row_number, error_message in error_rows:
            st.caption(f"Row {row_number}: {error_message}")


def _parse_date(date_string: str) -> date:
    """
    Parse a date string into a date object.
    Accepts YYYY-MM-DD and DD/MM/YYYY formats.
    """
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_string, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{date_string}' — use YYYY-MM-DD format")


def _optional_str(row: pd.Series, column_name: str) -> str | None:
    """Return the string value of a column if it exists and is not empty."""
    if column_name not in row.index:
        return None
    value = str(row[column_name]).strip()
    return value if value and value.lower() != "nan" else None
