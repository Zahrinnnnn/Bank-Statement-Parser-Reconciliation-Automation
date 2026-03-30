# Bank Statement Parser & Reconciliation Automation

A Python CLI and Streamlit web app that parses Malaysian bank statements (PDF, CSV, Excel), normalises transactions into a unified schema, stores them in SQLite, and runs automated reconciliation against internal ledger data. Produces downloadable Excel and PDF reports.

**Author:** Zahrin Bin Jasni
**Stack:** Python 3.13 · SQLite · Streamlit · Click · pdfplumber · pandas · rapidfuzz · reportlab · xlsxwriter

---

## Supported Banks

| Bank | Formats |
|---|---|
| CIMB | PDF, CSV |
| Hong Leong Bank (HLB) | PDF, Excel (.xlsx) |
| Maybank | PDF, CSV |
| Public Bank | PDF, CSV |
| Generic | CSV, Excel (auto-detect columns) |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Zahrinnnnn/Bank-Statement-Parser-Reconciliation-Automation.git
cd Bank-Statement-Parser-Reconciliation-Automation
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Initialise the database

```bash
python main.py init-db
```

This creates `data/database.db` with all five tables.

---

## CLI Usage

All commands are accessed through `python main.py`. Run `python main.py --help` to see the full list.

### Parse a bank statement

```bash
python main.py parse --file statement.pdf --bank CIMB
python main.py parse --file maybank_march.csv --bank MAYBANK --account 564312345678
```

Supported banks: `CIMB`, `HLB`, `MAYBANK`, `PUBLIC_BANK`, `GENERIC`

### Import ledger entries

Prepare a CSV with columns: `entry_date, description, amount, entry_type, reference, account_code, counterparty`

```bash
python main.py import-ledger --file ledger.csv --period 2026-03
```

### Run reconciliation

```bash
python main.py reconcile --bank CIMB --account 80012345678901 --period 2026-03
```

Optional flags:
- `--tolerance 0.01` — amount match tolerance in RM (default: 0.01)
- `--fuzzy 0.80` — fuzzy description similarity threshold (default: 0.80)

### Generate a report

```bash
python main.py report --recon-id 1 --format excel
python main.py report --recon-id 1 --format pdf
```

Reports are saved to `data/reports/`.

### View exceptions

```bash
python main.py exceptions --recon-id 1
```

Displays a colour-coded table of all unmatched and flagged items.

### Manually match a transaction

```bash
python main.py match --bank-txn-id 42 --ledger-id 87 --note "Confirmed by finance team"
```

### Export transactions to CSV

```bash
python main.py export --period 2026-03 --output march_transactions.csv
```

### View reconciliation history

```bash
python main.py history --bank CIMB --limit 10
```

---

## Web UI

Start the Streamlit app:

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501` and has five pages:

| Page | Description |
|---|---|
| **Upload** | Upload a bank statement file and trigger parsing |
| **Transactions** | Browse all stored transactions with filters |
| **Reconcile** | Run automated reconciliation and see results |
| **Reports** | Generate and download Excel or PDF reports |
| **Exceptions** | View and investigate exception items |

---

## Reconciliation Matching

The engine tries matches in priority order and stops at the first hit:

| Priority | Strategy | Confidence |
|---|---|---|
| 1 | Exact — same date, amount, and reference | 100% |
| 2 | Amount + Date — same amount, date within 1 day | 95% |
| 3 | Amount + Reference — same amount, reference substring match | 90% |
| 4 | Amount + Fuzzy Description — same amount, description similarity > 80% | 75% |
| 5 | Amount Only — same amount, date within 3 days | 60% |
| — | No match | flagged as exception |

Fuzzy matching uses `rapidfuzz.fuzz.token_sort_ratio`.

---

## Exception Types

| Type | Meaning |
|---|---|
| `BANK_ONLY` | In bank statement, not in ledger |
| `LEDGER_ONLY` | In ledger, not in bank statement |
| `AMOUNT_MISMATCH` | Matched by reference but amounts differ |
| `DATE_MISMATCH` | Matched by amount/description but dates differ > 3 days |
| `DUPLICATE_BANK` | Same transaction hash appears twice in bank statement |
| `LARGE_UNMATCHED` | Unmatched transaction above RM 5,000 threshold |

---

## Project Structure

```
bank-statement-parser/
├── main.py                 # CLI entry point (Click)
├── app.py                  # Streamlit web UI entry point
├── requirements.txt
├── data/
│   ├── database.db         # SQLite database (created on first run)
│   ├── uploads/            # Raw uploaded statement files
│   └── reports/            # Generated Excel and PDF reports
├── src/
│   ├── parsers/
│   │   ├── base_parser.py          # Abstract BaseParser + ParsedTransaction
│   │   ├── cimb_parser.py          # CIMB PDF and CSV parser
│   │   ├── hlb_parser.py           # Hong Leong Bank PDF and Excel parser
│   │   ├── maybank_parser.py       # Maybank PDF and CSV parser
│   │   ├── public_bank_parser.py   # Public Bank PDF and CSV parser
│   │   ├── csv_parser.py           # Generic CSV parser
│   │   ├── excel_parser.py         # Generic Excel parser
│   │   ├── pdf_parser.py           # Generic PDF parser
│   │   └── factory.py              # Parser factory
│   ├── database/
│   │   ├── connection.py           # SQLite connection and schema
│   │   ├── models.py               # Dataclasses for all 5 tables
│   │   └── queries.py              # All SQL queries as named functions
│   ├── reconciliation/
│   │   ├── engine.py               # Main reconciliation runner
│   │   ├── matching.py             # 5 match strategies
│   │   └── exceptions.py           # Exception categorisation
│   ├── reports/
│   │   ├── excel_report.py         # 4-sheet Excel workbook generator
│   │   └── pdf_report.py           # PDF executive summary generator
│   └── utils/
│       ├── normaliser.py           # Date/amount/description normalisation
│       ├── validators.py           # Input validation helpers
│       └── logger.py               # Rotating file + console logger
├── tests/
│   ├── test_parsers.py
│   ├── test_pdf_parser.py
│   ├── test_bank_parsers.py
│   ├── test_reconciliation.py
│   ├── test_reports.py
│   ├── test_phase8.py
│   ├── test_maybank_public_bank.py
│   └── fixtures/                   # Sample bank statement files
└── ui/
    ├── pages/
    │   ├── upload.py
    │   ├── transactions.py
    │   ├── reconcile.py
    │   ├── reports.py
    │   └── exceptions.py
    └── components/
        ├── sidebar.py
        └── table.py
```

---

## Database Schema

Five SQLite tables:

| Table | Purpose |
|---|---|
| `bank_transactions` | All parsed bank statement rows |
| `ledger_entries` | Internal ledger / AP / AR records |
| `reconciliations` | One row per reconciliation run |
| `reconciliation_matches` | Individual matched pairs per run |
| `audit_log` | Full audit trail of every system action |

Duplicate transactions are prevented by a SHA-256 hash of `date + description + debit + credit` stored in `bank_transactions.hash` with a UNIQUE constraint.

---

## Running Tests

```bash
python -m pytest
```

Run a specific test file:

```bash
python -m pytest tests/test_reconciliation.py -v
```

Current test count: **247 passing**.

---

## Ledger CSV Format

The `import-ledger` command accepts a CSV with these columns:

| Column | Required | Example |
|---|---|---|
| `entry_date` | Yes | `05/03/2026` |
| `description` | Yes | `Shopee Payment March` |
| `amount` | Yes | `250.00` |
| `entry_type` | Yes | `DEBIT` or `CREDIT` |
| `reference` | No | `FPX2026001` |
| `account_code` | No | `5000` |
| `counterparty` | No | `Shopee` |

See `tests/fixtures/sample_ledger.csv` for a working example.