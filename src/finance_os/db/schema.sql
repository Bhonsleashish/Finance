-- =============================================================================
-- Finance OS database schema (SQLite)
-- Every table lives in one local file: database/finance.db
-- =============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- documents: every source file ever ingested (payslip, statement, receipt...)
-- Content hash prevents re-importing the same file twice.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type        TEXT NOT NULL CHECK (doc_type IN (
                        'payslip', 'bank_statement', 'csv_export', 'receipt',
                        'invoice', 'insurance', 'tax', 'screenshot', 'manual'
                    )),
    source_path     TEXT NOT NULL,
    content_hash    TEXT NOT NULL UNIQUE,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    period_month    TEXT,                    -- 'YYYY-MM' when applicable
    extraction_method TEXT,                  -- 'native_text' | 'ocr' | 'csv' | 'manual'
    raw_text        TEXT,                    -- full extracted text, for audit/debug
    status          TEXT NOT NULL DEFAULT 'processed'
                        CHECK (status IN ('processed', 'needs_review', 'failed')),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_period ON documents(period_month);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);

-- ---------------------------------------------------------------------------
-- salary_slips: one row per German payslip, fully itemized.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS salary_slips (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id             INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    period_month            TEXT NOT NULL,        -- 'YYYY-MM'
    employer                TEXT,
    gross_salary            REAL,
    net_salary              REAL,
    income_tax              REAL,                  -- Lohnsteuer
    solidarity_surcharge    REAL,                  -- Solidaritätszuschlag
    church_tax              REAL,                  -- Kirchensteuer
    health_insurance        REAL,                  -- Krankenversicherung
    pension_insurance       REAL,                  -- Rentenversicherung
    unemployment_insurance  REAL,                  -- Arbeitslosenversicherung
    nursing_care_insurance  REAL,                  -- Pflegeversicherung
    overtime_pay             REAL,
    bonus                    REAL,
    reimbursements           REAL,
    other_deductions         REAL,
    other_earnings           REAL,
    currency                 TEXT NOT NULL DEFAULT 'EUR',
    UNIQUE (period_month, employer)
);

CREATE INDEX IF NOT EXISTS idx_salary_period ON salary_slips(period_month);

-- ---------------------------------------------------------------------------
-- accounts: bank accounts / cards discovered from statements
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,     -- e.g. "N26 Girokonto", "Sparkasse Sparkonto"
    institution     TEXT,
    account_type    TEXT DEFAULT 'checking'   -- checking | savings | credit_card | investment | cash
                        CHECK (account_type IN ('checking','savings','credit_card','investment','cash')),
    currency        TEXT NOT NULL DEFAULT 'EUR',
    opening_balance REAL DEFAULT 0,
    opening_date    TEXT
);

-- ---------------------------------------------------------------------------
-- categories: canonical category list (seeded from config/categories.yaml,
-- editable at runtime so users can add custom categories).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    "group"         TEXT NOT NULL DEFAULT 'wants' CHECK ("group" IN ('needs','wants','savings')),
    is_custom       INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- merchants: canonical merchant list (seeded from config/merchants.yaml,
-- plus merchants learned automatically from user corrections).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS merchants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    default_category_id INTEGER REFERENCES categories(id),
    is_learned      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS merchant_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    pattern         TEXT NOT NULL,             -- lower-cased substring/regex fragment
    UNIQUE (merchant_id, pattern)
);

-- ---------------------------------------------------------------------------
-- transactions: the core ledger. Every expense/income line lands here,
-- whatever its source (bank statement, receipt, manual entry).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id         INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    account_id          INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    txn_date            TEXT NOT NULL,          -- 'YYYY-MM-DD'
    period_month        TEXT NOT NULL,          -- 'YYYY-MM', derived from txn_date
    description_raw     TEXT NOT NULL,
    merchant_id         INTEGER REFERENCES merchants(id),
    category_id         INTEGER REFERENCES categories(id),
    amount              REAL NOT NULL,          -- negative = expense, positive = income
    currency            TEXT NOT NULL DEFAULT 'EUR',
    direction            TEXT NOT NULL CHECK (direction IN ('income','expense','transfer')),
    is_manual_entry      INTEGER NOT NULL DEFAULT 0,
    is_corrected          INTEGER NOT NULL DEFAULT 0,  -- category set/overridden by user
    dedup_hash            TEXT NOT NULL,                -- hash(date+amount+description+account) to avoid duplicate imports
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (dedup_hash)
);

CREATE INDEX IF NOT EXISTS idx_txn_period ON transactions(period_month);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant_id);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);

-- ---------------------------------------------------------------------------
-- category_corrections: every time a user re-categorizes a transaction,
-- we log it here. The categorizer learns merchant -> category associations
-- from this table (see categorize/categorizer.py).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS category_corrections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    merchant_text   TEXT,                    -- raw description at time of correction
    old_category_id INTEGER REFERENCES categories(id),
    new_category_id INTEGER REFERENCES categories(id),
    corrected_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- net_worth_snapshots: point-in-time net worth (assets - liabilities).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL UNIQUE,     -- 'YYYY-MM-DD', typically last day of month
    assets_total    REAL NOT NULL DEFAULT 0,
    liabilities_total REAL NOT NULL DEFAULT 0,
    net_worth        REAL NOT NULL DEFAULT 0,
    notes             TEXT
);

-- ---------------------------------------------------------------------------
-- goals: emergency fund, debt payoff, vacation, custom, etc.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS goals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    goal_type            TEXT NOT NULL DEFAULT 'custom'
                            CHECK (goal_type IN (
                                'emergency_fund','debt_payoff','vacation','car',
                                'move_countries','investment','retirement','custom'
                            )),
    target_amount         REAL NOT NULL,
    current_amount         REAL NOT NULL DEFAULT 0,
    monthly_contribution    REAL DEFAULT 0,     -- planned/average monthly contribution
    target_date              TEXT,               -- optional user-set deadline 'YYYY-MM-DD'
    created_at                TEXT NOT NULL DEFAULT (datetime('now')),
    is_active                  INTEGER NOT NULL DEFAULT 1,
    notes                       TEXT
);

CREATE TABLE IF NOT EXISTS goal_contributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id         INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    transaction_id  INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    amount          REAL NOT NULL,
    contributed_on  TEXT NOT NULL,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- budgets: monthly budget per category, either user-set or engine-generated.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budgets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_month    TEXT NOT NULL,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    budgeted_amount REAL NOT NULL,
    source          TEXT NOT NULL DEFAULT 'engine' CHECK (source IN ('engine','manual')),
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (period_month, category_id)
);

-- ---------------------------------------------------------------------------
-- subscriptions: detected recurring charges.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id          INTEGER REFERENCES merchants(id),
    label                 TEXT NOT NULL,
    monthly_cost           REAL NOT NULL,
    interval_days           INTEGER NOT NULL DEFAULT 30,
    first_seen              TEXT,
    last_seen                TEXT,
    occurrences               INTEGER NOT NULL DEFAULT 0,
    status                     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','stale','cancelled')),
    recommend_cancel            INTEGER NOT NULL DEFAULT 0,
    UNIQUE (merchant_id, label)
);

-- ---------------------------------------------------------------------------
-- alerts: generated smart-alert log (so we don't repeat the same alert).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','critical')),
    period_month    TEXT,
    message         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged    INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- reviews: cached weekly/monthly review output (JSON) for fast dashboard load
-- and historical audit trail of what was reported when.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_type     TEXT NOT NULL CHECK (review_type IN ('weekly','monthly')),
    period_key      TEXT NOT NULL,     -- 'YYYY-MM' for monthly, 'YYYY-Www' for weekly (ISO week)
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    payload_json    TEXT NOT NULL,
    UNIQUE (review_type, period_key)
);

-- ---------------------------------------------------------------------------
-- schema_meta: single-row table tracking schema version for future migrations.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    version         INTEGER NOT NULL
);

INSERT OR IGNORE INTO schema_meta (id, version) VALUES (1, 1);
