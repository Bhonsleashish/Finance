# Finance OS

A completely local-first personal finance operating system. It ingests your
payslips, bank statements, receipts and CSVs; categorizes and analyzes your
spending; and generates budgets, forecasts and reviews — all on your own
machine, with nothing ever sent anywhere else.

**Privacy guarantee:** everything lives in one file, `database/finance.db`.
There are no cloud services, no telemetry, no analytics, and no external API
calls anywhere in this codebase (including Streamlit's own usage-stats ping,
which is disabled in `.streamlit/config.toml`). You can `strace`/firewall the
process and confirm it never opens a socket to anything but `localhost`.

## What it does

- **Ingests** PDF salary slips, PDF/CSV bank statements, receipts and
  screenshots (via OCR), extracting structured data automatically.
- **Parses German payslips** (Gehaltsabrechnung) into gross/net salary,
  income tax, solidarity surcharge, church tax, health/pension/unemployment/
  nursing-care insurance, overtime, bonuses and reimbursements — and
  highlights month-over-month changes.
- **Categorizes expenses automatically**, recognizing common German merchants
  (REWE, EDEKA, Lidl, Aldi, DM, Amazon, Miles Mobility, DB, BVG, N26, ...),
  and **learns from your manual corrections** so it gets more accurate the
  more you use it.
- **Builds an adaptive monthly budget** from your actual income and spending
  patterns rather than a fixed template.
- **Tracks goals** (emergency fund, debt payoff, vacation, custom) with
  estimated completion dates.
- **Advises on purchases**: tell it what you want to buy, and it evaluates
  affordability, goal delay and opportunity cost, then recommends
  Buy now / Wait / Avoid — with the math shown.
- **Detects subscriptions** automatically and flags stale or duplicate ones
  for cancellation.
- **Estimates income for the current month** — confirmed amounts already
  received plus a projected remainder, based on parsed payslips or your
  transaction history.
- **Tracks investments** (stocks, ETFs, crypto, funds): cost basis, manually
  updated current value (this app never calls a live market-data API),
  unrealized gain/loss and allocation. Add a purchase via the dashboard/CLI,
  or drop a broker screenshot in `data/investments/` for a best-effort draft
  entry you confirm afterward.
- **Coaches you on money management**: a priority-ranked list of suggestions
  (starter emergency fund -> high-interest debt -> full emergency fund ->
  investing -> savings rate -> subscriptions -> lifestyle inflation) applied
  to your actual numbers, with the reasoning shown.
- **Forecasts** your balance, savings, net worth and debt payoff over
  1/3/6/12/60-month horizons.
- **Generates weekly and monthly reviews**, plus CSV/Excel/PDF exports and an
  interactive local dashboard.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Install local OCR support (required for scanned PDFs, receipts, screenshots)
#   Debian/Ubuntu: sudo apt-get install tesseract-ocr tesseract-ocr-deu
#   macOS:         brew install tesseract tesseract-lang

finance init                       # create the local database
finance ingest data/salary_slips   # drop PDFs/CSVs into data/* first
finance ingest data/bank_statements
finance report monthly             # generate this month's review
finance dashboard                  # launch the local Streamlit UI
```

Everything works fully offline after `pip install`. See `ARCHITECTURE.md` for
how the pieces fit together and where to extend the system (new merchants,
new payslip layouts, new categories, custom rules).

## Folder layout

```
finance/
  data/
    salary_slips/      # drop payslip PDFs here
    bank_statements/    # drop bank statement PDFs here
    receipts/            # drop receipt/invoice photos & PDFs here
    investments/           # drop broker purchase screenshots here (draft entries, needs review)
    invoices/, insurance/, tax/, manual/, inbox/
    exports/              # CSV/Excel exports land here
  database/
    finance.db             # the entire system's data, one local file
  config/
    config.yaml             # thresholds, budgeting rules, emergency fund target
    categories.yaml          # category definitions + keyword rules
    merchants.yaml            # German merchant recognition patterns
  reports/
    weekly/, monthly/          # generated PDF reviews
  src/finance_os/               # the application (see ARCHITECTURE.md)
  tests/                          # pytest suite
```

## CLI reference

```bash
finance init                                  # initialize the database
finance ingest <file-or-folder>               # import documents (safe to re-run)
finance uncategorized                         # list transactions needing a category
finance categorize <txn_id> <category>        # correct a category (learns from it)
finance budget generate --month YYYY-MM       # (re)generate the adaptive budget
finance budget status --month YYYY-MM         # budget vs. actual
finance goals add <name> --goal-type ... --target-amount ...
finance goals list
finance goals delete <name>
finance expense add "<description>" --amount <±EUR> --date YYYY-MM-DD
finance expense list --month YYYY-MM
finance expense delete <transaction_id>
finance investment add <name> --amount <EUR> --date YYYY-MM-DD [--asset-type etf|stock|crypto|...]
finance investment list                       # holdings, cost basis, current value, gain/loss
finance investment update-value <id> <current_value>
finance investment delete <id>
finance income --month YYYY-MM                # estimated income: received so far + projected remainder
finance advise "<item>" <cost>                # should I buy this?
finance tips                                  # priority-ranked money-management suggestions
finance forecast --balance <current-balance>  # 1/3/6/12/60-month projections
finance report weekly
finance report monthly --month YYYY-MM --export-pdf
finance report export --fmt csv|excel
finance dashboard                             # launch the Streamlit UI
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## Extending

- **New merchant**: add an entry to `config/merchants.yaml` (name, category,
  matching substrings). No code change needed.
- **New category**: add it to `config/categories.yaml` with a `group`
  (needs/wants/savings) and keyword list.
- **A payslip that doesn't parse well**: add the missing German label to
  `FIELD_PATTERNS` in `src/finance_os/ingest/payslip_parser.py` — payslip
  layouts vary by provider (DATEV, SAP, Personio, ...) and this table is the
  intended extension point.
- **A bank whose CSV export doesn't auto-detect**: pass an explicit
  `column_map` to `finance_os.ingest.csv_importer.parse_csv`.
