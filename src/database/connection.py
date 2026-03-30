"""
connection.py — SQLite connection management and schema initialisation.

This module handles:
  - Opening and closing the database connection
  - Creating all tables on first run (if they don't exist yet)
  - Providing a single shared connection to the rest of the app

All SQL DDL lives here so the schema is defined in exactly one place.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default database location relative to the project root
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "database.db"


# --- Schema DDL -----------------------------------------------------------
# Each CREATE TABLE statement uses IF NOT EXISTS so running this on an
# existing database is always safe — it will never drop or overwrite data.

CREATE_BANK_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS bank_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name        TEXT    NOT NULL,
    account_number   TEXT,
    transaction_date DATE    NOT NULL,
    value_date       DATE,
    description      TEXT    NOT NULL,
    reference        TEXT,
    debit_amount     REAL    DEFAULT 0,
    credit_amount    REAL    DEFAULT 0,
    balance          REAL,
    currency         TEXT    DEFAULT 'MYR',
    raw_description  TEXT,
    source_file      TEXT    NOT NULL,
    parsed_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    recon_status     TEXT    DEFAULT 'UNMATCHED',
    recon_id         INTEGER,
    hash             TEXT    UNIQUE
);
"""

CREATE_LEDGER_ENTRIES = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date   DATE    NOT NULL,
    description  TEXT    NOT NULL,
    reference    TEXT,
    amount       REAL    NOT NULL,
    entry_type   TEXT    NOT NULL,
    account_code TEXT,
    counterparty TEXT,
    source       TEXT,
    recon_status TEXT    DEFAULT 'UNMATCHED',
    recon_id     INTEGER,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RECONCILIATIONS = """
CREATE TABLE IF NOT EXISTS reconciliations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date             DATETIME DEFAULT CURRENT_TIMESTAMP,
    period_start         DATE     NOT NULL,
    period_end           DATE     NOT NULL,
    bank_name            TEXT     NOT NULL,
    account_number       TEXT,
    total_bank_txns      INTEGER,
    total_ledger_entries INTEGER,
    matched_count        INTEGER,
    unmatched_bank       INTEGER,
    unmatched_ledger     INTEGER,
    exceptions           INTEGER,
    status               TEXT     DEFAULT 'COMPLETED',
    report_path          TEXT
);
"""

CREATE_RECONCILIATION_MATCHES = """
CREATE TABLE IF NOT EXISTS reconciliation_matches (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    recon_id         INTEGER  REFERENCES reconciliations(id),
    bank_txn_id      INTEGER  REFERENCES bank_transactions(id),
    ledger_entry_id  INTEGER  REFERENCES ledger_entries(id),
    match_type       TEXT     NOT NULL,
    confidence_score REAL,
    matched_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    matched_by       TEXT     DEFAULT 'AUTO',
    notes            TEXT
);
"""

CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    action    TEXT     NOT NULL,
    entity    TEXT,
    entity_id INTEGER,
    details   TEXT,
    user      TEXT     DEFAULT 'SYSTEM'
);
"""

# Collect all DDL in the order they should run
ALL_CREATE_STATEMENTS = [
    CREATE_BANK_TRANSACTIONS,
    CREATE_LEDGER_ENTRIES,
    CREATE_RECONCILIATIONS,
    CREATE_RECONCILIATION_MATCHES,
    CREATE_AUDIT_LOG,
]


# --- Connection class ------------------------------------------------------

class DatabaseConnection:
    """
    Wraps a sqlite3 connection for the application.

    Usage:
        db = DatabaseConnection()
        db.connect()
        db.initialise_schema()
        conn = db.get_connection()
        ...
        db.close()

    Or use as a context manager:
        with DatabaseConnection() as db:
            conn = db.get_connection()
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open the database file, creating it if it doesn't exist."""
        # Make sure the data/ directory exists before opening the file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )

        # Return rows as dict-like objects so callers can use column names
        self._connection.row_factory = sqlite3.Row

        # Enable foreign key enforcement — SQLite has it off by default
        self._connection.execute("PRAGMA foreign_keys = ON")

        logger.info("Connected to database: %s", self.db_path)

    def initialise_schema(self) -> None:
        """Create all tables if they don't already exist."""
        if self._connection is None:
            raise RuntimeError("Call connect() before initialise_schema().")

        cursor = self._connection.cursor()

        for statement in ALL_CREATE_STATEMENTS:
            cursor.execute(statement)

        self._connection.commit()
        logger.info("Database schema initialised.")

    def get_connection(self) -> sqlite3.Connection:
        """Return the active connection. Raises if not connected yet."""
        if self._connection is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._connection

    def close(self) -> None:
        """Commit any pending changes and close the connection."""
        if self._connection is not None:
            self._connection.commit()
            self._connection.close()
            self._connection = None
            logger.info("Database connection closed.")

    # --- Context manager support ---

    def __enter__(self):
        # Only connect if not already connected (handles the case where
        # get_db() already called connect() before the with-block runs)
        if self._connection is None:
            self.connect()
            self.initialise_schema()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If an exception occurred, rollback instead of committing
        if exc_type is not None and self._connection is not None:
            self._connection.rollback()
        self.close()
        # Return False so exceptions propagate normally
        return False


# --- Module-level convenience function ------------------------------------

def get_db(db_path: Path = DEFAULT_DB_PATH) -> DatabaseConnection:
    """
    Create, connect, and return a ready-to-use DatabaseConnection.

    Shorthand for the common case where you just need a connection
    without managing the lifecycle manually.
    """
    db = DatabaseConnection(db_path)
    db.connect()
    db.initialise_schema()
    return db
