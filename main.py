"""
main.py — CLI entry point for the Bank Statement Parser & Reconciliation tool.

Run any command with:
    python main.py <command> [options]

Run this file with --help to see all available commands.
"""

import logging
import click

from src.utils.logger import setup_logging
from src.database.connection import get_db

logger = logging.getLogger(__name__)


@click.group()
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable verbose debug logging.",
)
def cli(debug: bool) -> None:
    """Bank Statement Parser & Reconciliation Automation."""
    log_level = "DEBUG" if debug else "INFO"
    setup_logging(level=log_level)


# ---------------------------------------------------------------------------
# Placeholder commands — these will be filled in during later phases
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--file",    required=True,  help="Path to the bank statement file.")
@click.option("--bank",    required=True,  help="Bank name: CIMB, HLB, MAYBANK, PUBLIC_BANK.")
@click.option("--account", required=False, default=None, help="Account number (optional override).")
def parse(file: str, bank: str, account: str) -> None:
    """Parse a bank statement file and store transactions in the database."""
    from src.parsers.factory import get_parser
    from src.database.connection import get_db
    from src.database.models import BankTransaction
    from src.database.queries import insert_bank_transaction, insert_audit_log
    from src.database.models import AuditLog

    # Get the right parser for this bank and file type
    parser = get_parser(bank_name=bank, file_path=file)

    # Extract metadata from the statement
    account_number = account or parser.extract_account_number()
    period_start, period_end = parser.extract_statement_period()

    click.echo(f"Parsing {file}  [{bank}]  Account: {account_number or 'unknown'}")
    click.echo(f"Statement period: {period_start} to {period_end}")

    # Parse all transactions
    parsed_transactions = parser.parse()
    click.echo(f"Found {len(parsed_transactions)} transactions in file.")

    # Save to database
    new_count = 0
    duplicate_count = 0

    with get_db() as db:
        conn = db.get_connection()

        for txn in parsed_transactions:
            bank_txn = BankTransaction(
                bank_name=bank.upper(),
                account_number=account_number,
                transaction_date=txn.transaction_date,
                value_date=txn.value_date,
                description=txn.description,
                reference=txn.reference,
                debit_amount=txn.debit_amount,
                credit_amount=txn.credit_amount,
                balance=txn.balance,
                raw_description=txn.raw_description,
                source_file=file,
                hash=txn.compute_hash(),
            )

            row_id = insert_bank_transaction(conn, bank_txn)
            if row_id == -1:
                duplicate_count += 1
            else:
                new_count += 1

        # Write an audit log entry for this parse run
        insert_audit_log(conn, AuditLog(
            action="PARSE_FILE",
            entity="bank_transactions",
            details={
                "file": file,
                "bank": bank,
                "found": len(parsed_transactions),
                "inserted": new_count,
                "duplicates": duplicate_count,
            },
        ))

    click.echo(f"Saved: {new_count} new  |  Skipped: {duplicate_count} duplicates")


@cli.command("import-ledger")
@click.option("--file",   required=True, help="Path to the ledger CSV file.")
@click.option("--period", required=True, help="Accounting period e.g. 2026-03.")
def import_ledger(file: str, period: str) -> None:
    """Import internal ledger entries from a CSV file."""
    import pandas as pd
    from src.database.connection import get_db
    from src.database.models import LedgerEntry, AuditLog
    from src.database.queries import insert_ledger_entry, insert_audit_log
    from src.utils.normaliser import parse_date, parse_amount, clean_description

    df = pd.read_csv(file, dtype=str, skip_blank_lines=True)
    df.columns = [col.strip().lower() for col in df.columns]

    new_count = 0
    skipped_count = 0

    with get_db() as db:
        conn = db.get_connection()

        for _, row in df.iterrows():
            # Required fields
            raw_date   = str(row.get("entry_date", "")).strip()
            raw_amount = str(row.get("amount", "")).strip()
            description = clean_description(str(row.get("description", "")))
            entry_type  = str(row.get("entry_type", "")).strip().upper()

            entry_date = parse_date(raw_date)
            amount = parse_amount(raw_amount)

            if not entry_date or not description or not entry_type:
                skipped_count += 1
                continue

            ledger_entry = LedgerEntry(
                entry_date=entry_date,
                description=description,
                reference=clean_description(str(row.get("reference", ""))) or None,
                amount=amount,
                entry_type=entry_type,
                account_code=str(row.get("account_code", "")).strip() or None,
                counterparty=str(row.get("counterparty", "")).strip() or None,
                source=file,
            )

            insert_ledger_entry(conn, ledger_entry)
            new_count += 1

        insert_audit_log(conn, AuditLog(
            action="IMPORT_LEDGER",
            entity="ledger_entries",
            details={"file": file, "period": period, "inserted": new_count, "skipped": skipped_count},
        ))

    click.echo(f"Imported: {new_count} ledger entries  |  Skipped: {skipped_count} invalid rows")


@cli.command()
@click.option("--bank",      required=True,  help="Bank name: CIMB, HLB, MAYBANK, PUBLIC_BANK.")
@click.option("--account",   required=False, default=None, help="Account number filter (optional).")
@click.option("--period",    required=True,  help="Accounting period e.g. 2026-03.")
@click.option("--tolerance", default=0.01,   help="Amount match tolerance in RM (default 0.01).")
@click.option("--fuzzy",     default=0.80,   help="Fuzzy match threshold 0-1 (default 0.80).")
def reconcile(bank: str, account: str, period: str, tolerance: float, fuzzy: float) -> None:
    """Run automated reconciliation for a given period and account."""
    from datetime import date
    from src.database.connection import get_db
    from src.reconciliation.engine import run_reconciliation

    # Parse "2026-03" → first and last day of that month
    try:
        year, month = int(period.split("-")[0]), int(period.split("-")[1])
    except (ValueError, IndexError):
        click.echo(f"Invalid period format: {period!r}. Use YYYY-MM e.g. 2026-03")
        return

    import calendar
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    click.echo(f"Reconciling {bank}  {period_start} to {period_end} ...")

    with get_db() as db:
        result = run_reconciliation(
            conn=db.get_connection(),
            period_start=period_start,
            period_end=period_end,
            bank_name=bank,
            account_number=account,
            amount_tolerance=tolerance,
            fuzzy_threshold=fuzzy,
        )

    click.echo(result.summary())


@cli.command()
@click.option("--recon-id", required=True, type=int, help="Reconciliation run ID.")
@click.option("--format",   required=True, type=click.Choice(["excel", "pdf"]), help="Report format.")
def report(recon_id: int, format: str) -> None:
    """Generate an Excel or PDF reconciliation report."""
    from pathlib import Path
    from datetime import date as date_type
    from rich.console import Console
    from src.database.queries import (
        get_reconciliation,
        list_match_details_for_reconciliation,
        list_exceptions_for_reconciliation,
        list_bank_transactions,
        update_reconciliation_report_path,
    )

    console = Console()

    with get_db() as db:
        conn = db.get_connection()
        recon = get_reconciliation(conn, recon_id)

        if not recon:
            console.print(f"[red]Reconciliation run #{recon_id} not found.[/red]")
            return

        # Fetch all the data the report generators need
        matched_rows   = list_match_details_for_reconciliation(conn, recon_id)
        exception_rows = list_exceptions_for_reconciliation(conn, recon_id)

        # Get the full bank transaction list for this run's period
        period_start = recon["period_start"]
        period_end   = recon["period_end"]
        if isinstance(period_start, str):
            period_start = date_type.fromisoformat(period_start)
        if isinstance(period_end, str):
            period_end = date_type.fromisoformat(period_end)

        all_bank_txns = list_bank_transactions(
            conn,
            bank_name=recon["bank_name"],
            account_number=recon.get("account_number"),
            period_start=period_start,
            period_end=period_end,
        )

        output_path = Path("data/reports") / f"recon_{recon_id}_report.{format}"

        if format == "excel":
            from src.reports.excel_report import generate_excel_report
            report_path = generate_excel_report(
                recon=dict(recon),
                matched_rows=matched_rows,
                exception_rows=exception_rows,
                all_bank_txns=all_bank_txns,
                output_path=output_path,
            )
        else:
            from src.reports.pdf_report import generate_pdf_report
            report_path = generate_pdf_report(
                recon=dict(recon),
                matched_rows=matched_rows,
                exception_rows=exception_rows,
                output_path=output_path,
            )

        # Record the report file path on the reconciliation run so it can be found later
        update_reconciliation_report_path(conn, recon_id, str(report_path))

    console.print(f"[green]Report saved:[/green] {report_path}")


@cli.command()
@click.option("--bank",  required=False, help="Filter by bank name.")
@click.option("--limit", default=10,     help="Maximum number of records to show.")
def history(bank: str, limit: int) -> None:
    """Show reconciliation history."""
    with get_db() as db:
        conn = db.get_connection()
        from src.database.queries import list_reconciliations
        records = list_reconciliations(conn, bank_name=bank, limit=limit)

    if not records:
        click.echo("No reconciliation history found.")
        return

    for record in records:
        click.echo(
            f"  ID {record['id']}  {record['bank_name']}  "
            f"{record['period_start']} to {record['period_end']}  "
            f"Status: {record['status']}"
        )


@cli.command()
@click.option("--recon-id", required=True, type=int, help="Reconciliation run ID.")
def exceptions(recon_id: int) -> None:
    """View exception items from a reconciliation run."""
    from rich.console import Console
    from rich.table import Table
    from src.database.queries import (
        get_reconciliation,
        list_exceptions_for_reconciliation,
    )

    console = Console()

    with get_db() as db:
        conn = db.get_connection()
        recon = get_reconciliation(conn, recon_id)

        if not recon:
            console.print(f"[red]Reconciliation run #{recon_id} not found.[/red]")
            return

        exception_rows = list_exceptions_for_reconciliation(conn, recon_id)

    if not exception_rows:
        console.print(f"[green]No exceptions for reconciliation #{recon_id}.[/green]")
        return

    # Build a colour-coded table so each exception type stands out at a glance
    EXCEPTION_TYPE_COLOURS = {
        "BANK_ONLY":       "yellow",
        "LEDGER_ONLY":     "cyan",
        "LARGE_UNMATCHED": "red",
        "DUPLICATE_BANK":  "magenta",
        "AMOUNT_MISMATCH": "orange3",
        "DATE_MISMATCH":   "blue",
    }

    table = Table(
        title=(
            f"Exceptions — Reconciliation #{recon_id}  "
            f"({recon['bank_name']}  "
            f"{recon['period_start']} to {recon['period_end']})"
        ),
        show_lines=True,
    )
    table.add_column("Type",        style="bold",   no_wrap=True)
    table.add_column("Source",      no_wrap=True)
    table.add_column("Date",        no_wrap=True)
    table.add_column("Description", min_width=30)
    table.add_column("Amount (RM)", justify="right")
    table.add_column("Reference")

    for row in exception_rows:
        exception_type = row["exception_type"] or "UNKNOWN"
        colour         = EXCEPTION_TYPE_COLOURS.get(exception_type, "white")
        amount_display = f"{row['amount']:,.2f}" if row["amount"] else "—"

        table.add_row(
            f"[{colour}]{exception_type}[/{colour}]",
            row["source"],
            str(row["txn_date"]),
            row["description"] or "—",
            amount_display,
            row["reference"] or "—",
        )

    console.print(table)
    console.print(f"\nTotal exceptions: [bold]{len(exception_rows)}[/bold]")


@cli.command()
@click.option("--bank-txn-id", required=True, type=int, help="Bank transaction ID.")
@click.option("--ledger-id",   required=True, type=int, help="Ledger entry ID.")
@click.option("--note",        required=False, default=None, help="Reason for manual match.")
def match(bank_txn_id: int, ledger_id: int, note: str) -> None:
    """Manually match a bank transaction to a ledger entry."""
    from rich.console import Console
    from src.database.models import AuditLog
    from src.database.queries import (
        get_bank_transaction,
        get_ledger_entry,
        update_bank_transaction_recon_status,
        update_ledger_entry_recon_status,
        insert_audit_log,
    )

    console = Console()

    with get_db() as db:
        conn = db.get_connection()

        # Verify both records exist before doing anything
        bank_txn     = get_bank_transaction(conn, bank_txn_id)
        ledger_entry = get_ledger_entry(conn, ledger_id)

        if not bank_txn:
            console.print(f"[red]Bank transaction #{bank_txn_id} not found.[/red]")
            return

        if not ledger_entry:
            console.print(f"[red]Ledger entry #{ledger_id} not found.[/red]")
            return

        # Warn if either record is already matched — the operator may have the wrong IDs
        if bank_txn["recon_status"] == "MATCHED":
            console.print(
                f"[yellow]Warning: bank transaction #{bank_txn_id} is already MATCHED.[/yellow]"
            )
        if ledger_entry["recon_status"] == "MATCHED":
            console.print(
                f"[yellow]Warning: ledger entry #{ledger_id} is already MATCHED.[/yellow]"
            )

        # Mark both records as manually matched
        update_bank_transaction_recon_status(conn, bank_txn_id, "MATCHED")
        update_ledger_entry_recon_status(conn, ledger_id, "MATCHED")

        # Capture the full context in the audit log so this action is traceable
        audit_details = {
            "bank_txn_id":        bank_txn_id,
            "ledger_entry_id":    ledger_id,
            "bank_description":   bank_txn["description"],
            "ledger_description": ledger_entry["description"],
        }
        if note:
            audit_details["note"] = note

        insert_audit_log(conn, AuditLog(
            action="MANUAL_MATCH",
            entity="bank_transactions",
            entity_id=bank_txn_id,
            details=audit_details,
        ))

    # Truncate long descriptions so the output line stays readable
    bank_desc   = (bank_txn["description"] or "")[:45]
    ledger_desc = (ledger_entry["description"] or "")[:45]

    console.print(
        f"[green]Matched:[/green] "
        f"Bank #{bank_txn_id} ({bank_desc}) "
        f"→ Ledger #{ledger_id} ({ledger_desc})"
    )


@cli.command()
@click.option("--period", required=True, help="Accounting period e.g. 2026-03.")
@click.option("--output", required=True, help="Output CSV file path.")
def export(period: str, output: str) -> None:
    """Export all transactions for a period to a CSV file."""
    import calendar
    from datetime import date
    from pathlib import Path

    import pandas as pd
    from rich.console import Console
    from src.database.queries import list_bank_transactions

    console = Console()

    # Parse "2026-03" → first and last day of that month
    try:
        year, month = int(period.split("-")[0]), int(period.split("-")[1])
    except (ValueError, IndexError):
        console.print(
            f"[red]Invalid period format: {period!r}. Use YYYY-MM e.g. 2026-03[/red]"
        )
        return

    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    with get_db() as db:
        transactions = list_bank_transactions(
            db.get_connection(),
            period_start=period_start,
            period_end=period_end,
        )

    if not transactions:
        console.print(f"[yellow]No transactions found for period {period}.[/yellow]")
        return

    # These are the columns we include in the export — internal DB fields like
    # 'hash', 'raw_description', and 'parsed_at' are omitted as they're not
    # meaningful to the end user.
    export_columns = [
        "id",
        "bank_name",
        "account_number",
        "transaction_date",
        "value_date",
        "description",
        "reference",
        "debit_amount",
        "credit_amount",
        "balance",
        "currency",
        "recon_status",
        "recon_id",
        "source_file",
    ]

    dataframe = pd.DataFrame(transactions)
    # Keep only columns that exist in the result (guards against schema variations)
    available_columns = [col for col in export_columns if col in dataframe.columns]
    dataframe = dataframe[available_columns]

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)

    console.print(
        f"[green]Exported {len(transactions)} transactions to[/green] {output_path}"
    )


@cli.command("init-db")
def init_db() -> None:
    """Initialise the SQLite database and create all tables."""
    with get_db() as db:
        click.echo(f"Database ready: {db.db_path}")


if __name__ == "__main__":
    cli()
