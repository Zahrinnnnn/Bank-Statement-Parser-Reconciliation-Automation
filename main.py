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
    click.echo(f"[Phase 2] import-ledger command — file: {file}, period: {period}")


@cli.command()
@click.option("--bank",    required=True,  help="Bank name.")
@click.option("--account", required=True,  help="Account number.")
@click.option("--period",  required=True,  help="Accounting period e.g. 2026-03.")
def reconcile(bank: str, account: str, period: str) -> None:
    """Run automated reconciliation for a given period and account."""
    click.echo(f"[Phase 5] reconcile command — bank: {bank}, account: {account}, period: {period}")


@cli.command()
@click.option("--recon-id", required=True, type=int, help="Reconciliation run ID.")
@click.option("--format",   required=True, type=click.Choice(["excel", "pdf"]), help="Report format.")
def report(recon_id: int, format: str) -> None:
    """Generate an Excel or PDF reconciliation report."""
    click.echo(f"[Phase 7] report command — recon_id: {recon_id}, format: {format}")


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
    click.echo(f"[Phase 6] exceptions command — recon_id: {recon_id}")


@cli.command()
@click.option("--bank-txn-id", required=True, type=int, help="Bank transaction ID.")
@click.option("--ledger-id",   required=True, type=int, help="Ledger entry ID.")
@click.option("--note",        required=False, help="Reason for manual match.")
def match(bank_txn_id: int, ledger_id: int, note: str) -> None:
    """Manually match a bank transaction to a ledger entry."""
    click.echo(f"[Phase 5] match command — bank_txn_id: {bank_txn_id}, ledger_id: {ledger_id}")


@cli.command()
@click.option("--period", required=True, help="Accounting period e.g. 2026-03.")
@click.option("--output", required=True, help="Output CSV file path.")
def export(period: str, output: str) -> None:
    """Export all transactions for a period to a CSV file."""
    click.echo(f"[Phase 8] export command — period: {period}, output: {output}")


@cli.command("init-db")
def init_db() -> None:
    """Initialise the SQLite database and create all tables."""
    with get_db() as db:
        click.echo(f"Database ready: {db.db_path}")


if __name__ == "__main__":
    cli()
