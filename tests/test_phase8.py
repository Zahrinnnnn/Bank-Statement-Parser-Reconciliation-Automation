"""
test_phase8.py — Tests for the Phase 8 CLI commands: match and export.

Tests exercise the underlying database logic directly (not through the CLI
runner) so they work with in-memory SQLite without needing to mock get_db().

Run with:
    python -m pytest tests/test_phase8.py -v
"""

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.database.connection import DatabaseConnection
from src.database.models import AuditLog, BankTransaction, LedgerEntry
from src.database.queries import (
    get_bank_transaction,
    get_ledger_entry,
    insert_bank_transaction,
    insert_ledger_entry,
    list_audit_log,
    list_bank_transactions,
    update_bank_transaction_recon_status,
    update_ledger_entry_recon_status,
    insert_audit_log,
)


# ---------------------------------------------------------------------------
# Shared test database setup
# ---------------------------------------------------------------------------

class PhaseEightTestBase:
    """Sets up a fresh in-memory database with a handful of known records."""

    def setup_method(self):
        self.db = DatabaseConnection(db_path=Path(":memory:"))
        self.db.connect()
        self.db.initialise_schema()
        self.conn = self.db.get_connection()
        self._load_sample_data()

    def teardown_method(self):
        self.db.close()

    def _load_sample_data(self):
        """Insert bank transactions and ledger entries used across all Phase 8 tests."""
        bank_txns = [
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 5),
                description="FPX SHOPEE PAYMENT", reference="FPX2026001",
                debit_amount=250.0, credit_amount=0.0,
                source_file="test.csv", hash="p8_hash_shopee",
            ),
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 10),
                description="IBG TRANSFER OUT", reference="IBG20260310",
                debit_amount=1500.0, credit_amount=0.0,
                source_file="test.csv", hash="p8_hash_ibg",
            ),
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 3, 15),
                description="SALARY CREDIT ACME SDN BHD", reference=None,
                debit_amount=0.0, credit_amount=5000.0,
                source_file="test.csv", hash="p8_hash_salary",
            ),
            # April transaction — should NOT appear in March export
            BankTransaction(
                bank_name="CIMB", account_number="1234567890",
                transaction_date=date(2026, 4, 1),
                description="APRIL PAYMENT", reference=None,
                debit_amount=100.0, credit_amount=0.0,
                source_file="test.csv", hash="p8_hash_april",
            ),
        ]
        self.bank_ids = []
        for txn in bank_txns:
            row_id = insert_bank_transaction(self.conn, txn)
            self.bank_ids.append(row_id)

        ledger_entries = [
            LedgerEntry(
                entry_date=date(2026, 3, 5), description="Shopee Payment March",
                reference="FPX2026001", amount=250.0, entry_type="DEBIT",
            ),
            LedgerEntry(
                entry_date=date(2026, 3, 10), description="Transfer to Ahmad Ali",
                reference="IBG20260310", amount=1500.0, entry_type="DEBIT",
            ),
        ]
        self.ledger_ids = []
        for entry in ledger_entries:
            row_id = insert_ledger_entry(self.conn, entry)
            self.ledger_ids.append(row_id)


# ===========================================================================
# Manual match — underlying query logic
# ===========================================================================

class TestManualMatchLogic(PhaseEightTestBase):
    """
    Tests for the core operations that the match CLI command performs.
    We test the query logic directly rather than going through the Click runner.
    """

    def _do_manual_match(self, bank_txn_id: int, ledger_entry_id: int, note: str = None):
        """Replicate exactly what the match CLI command does internally."""
        update_bank_transaction_recon_status(self.conn, bank_txn_id, "MATCHED")
        update_ledger_entry_recon_status(self.conn, ledger_entry_id, "MATCHED")

        audit_details = {
            "bank_txn_id":     bank_txn_id,
            "ledger_entry_id": ledger_entry_id,
        }
        if note:
            audit_details["note"] = note

        insert_audit_log(self.conn, AuditLog(
            action="MANUAL_MATCH",
            entity="bank_transactions",
            entity_id=bank_txn_id,
            details=audit_details,
        ))

    def test_bank_txn_status_becomes_matched(self):
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        self._do_manual_match(bank_id, ledger_id)
        txn = get_bank_transaction(self.conn, bank_id)
        assert txn["recon_status"] == "MATCHED"

    def test_ledger_entry_status_becomes_matched(self):
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        self._do_manual_match(bank_id, ledger_id)
        entry = get_ledger_entry(self.conn, ledger_id)
        assert entry["recon_status"] == "MATCHED"

    def test_other_bank_txns_are_not_affected(self):
        """Matching one transaction must not change other transactions' statuses."""
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        self._do_manual_match(bank_id, ledger_id)

        # The second bank transaction should still be UNMATCHED
        other_txn = get_bank_transaction(self.conn, self.bank_ids[1])
        assert other_txn["recon_status"] == "UNMATCHED"

    def test_audit_log_entry_written(self):
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        self._do_manual_match(bank_id, ledger_id, note="Approved by finance team")

        log_entries = list_audit_log(self.conn, entity="bank_transactions", entity_id=bank_id)
        assert len(log_entries) >= 1
        assert log_entries[0]["action"] == "MANUAL_MATCH"

    def test_note_is_stored_in_audit_details(self):
        import json
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        test_note = "Confirmed with Ahmad Ali"
        self._do_manual_match(bank_id, ledger_id, note=test_note)

        log_entries = list_audit_log(self.conn, entity="bank_transactions", entity_id=bank_id)
        details = json.loads(log_entries[0]["details"])
        assert details.get("note") == test_note

    def test_match_without_note_does_not_crash(self):
        bank_id   = self.bank_ids[1]
        ledger_id = self.ledger_ids[1]
        # Should complete without raising any exception
        self._do_manual_match(bank_id, ledger_id)
        txn = get_bank_transaction(self.conn, bank_id)
        assert txn["recon_status"] == "MATCHED"

    def test_nonexistent_bank_txn_returns_none(self):
        """get_bank_transaction should return None for an ID that doesn't exist."""
        missing = get_bank_transaction(self.conn, 99999)
        assert missing is None

    def test_nonexistent_ledger_entry_returns_none(self):
        """get_ledger_entry should return None for an ID that doesn't exist."""
        missing = get_ledger_entry(self.conn, 99999)
        assert missing is None

    def test_match_can_be_applied_twice_without_error(self):
        """Re-matching an already-matched row must not raise — it stays MATCHED."""
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        self._do_manual_match(bank_id, ledger_id)
        self._do_manual_match(bank_id, ledger_id)  # second call should not crash
        txn = get_bank_transaction(self.conn, bank_id)
        assert txn["recon_status"] == "MATCHED"


# ===========================================================================
# Export — CSV output logic
# ===========================================================================

class TestExportLogic(PhaseEightTestBase):
    """
    Tests for the core operations that the export CLI command performs.
    We generate CSVs using the same logic as the CLI but with an in-memory DB.
    """

    # Columns we expect in every export CSV
    EXPECTED_COLUMNS = [
        "id", "bank_name", "account_number", "transaction_date",
        "description", "debit_amount", "credit_amount",
        "recon_status", "source_file",
    ]

    def _do_export(self, period_start: date, period_end: date, output_path: Path):
        """Replicate the export command's logic using the test connection."""
        transactions = list_bank_transactions(
            self.conn,
            period_start=period_start,
            period_end=period_end,
        )

        export_columns = [
            "id", "bank_name", "account_number", "transaction_date",
            "value_date", "description", "reference", "debit_amount",
            "credit_amount", "balance", "currency", "recon_status",
            "recon_id", "source_file",
        ]

        dataframe = pd.DataFrame(transactions)
        available_columns = [col for col in export_columns if col in dataframe.columns]
        dataframe = dataframe[available_columns]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(output_path, index=False)
        return transactions

    def test_csv_file_is_created(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            assert output_path.exists()

    def test_csv_contains_correct_row_count(self):
        """March export should have 3 rows (4th transaction is in April)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            assert len(df) == 3

    def test_april_transaction_excluded_from_march_export(self):
        """The April transaction must not appear in a March export."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "march.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            assert "APRIL PAYMENT" not in df["description"].values

    def test_april_transaction_in_april_export(self):
        """The April transaction should appear when we export April."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "april.csv"
            self._do_export(date(2026, 4, 1), date(2026, 4, 30), output_path)
            df = pd.read_csv(output_path)
            assert len(df) == 1
            assert df.iloc[0]["description"] == "APRIL PAYMENT"

    def test_expected_columns_present(self):
        """All expected columns must appear in the exported CSV."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            for col in self.EXPECTED_COLUMNS:
                assert col in df.columns, f"Missing column: {col}"

    def test_amounts_are_correct(self):
        """Shopee debit row must export with debit_amount=250 and credit_amount=0."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            shopee_row = df[df["description"].str.contains("SHOPEE")]
            assert len(shopee_row) == 1
            assert shopee_row.iloc[0]["debit_amount"] == pytest.approx(250.0)
            assert shopee_row.iloc[0]["credit_amount"] == pytest.approx(0.0)

    def test_recon_status_column_present_and_populated(self):
        """Every exported row should have a recon_status value."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            assert df["recon_status"].notna().all()

    def test_export_after_manual_match_shows_matched_status(self):
        """A manually matched transaction must export with recon_status MATCHED."""
        bank_id   = self.bank_ids[0]
        ledger_id = self.ledger_ids[0]
        update_bank_transaction_recon_status(self.conn, bank_id, "MATCHED")
        update_ledger_entry_recon_status(self.conn, ledger_id, "MATCHED")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), output_path)
            df = pd.read_csv(output_path)
            shopee_row = df[df["description"].str.contains("SHOPEE")]
            assert shopee_row.iloc[0]["recon_status"] == "MATCHED"

    def test_empty_period_returns_no_rows(self):
        """A period with no transactions should produce an empty CSV."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "export.csv"
            transactions = self._do_export(
                date(2025, 1, 1), date(2025, 1, 31), output_path
            )
            assert transactions == []

    def test_output_parent_directory_created_if_missing(self):
        """Export should create any missing directories in the output path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested_path = Path(tmp_dir) / "new_dir" / "sub" / "export.csv"
            self._do_export(date(2026, 3, 1), date(2026, 3, 31), nested_path)
            assert nested_path.exists()