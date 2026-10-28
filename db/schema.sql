-- BitTrace v2 database schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS investigations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    root_address    TEXT NOT NULL,
    max_hops        INTEGER NOT NULL DEFAULT 3,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS addresses (
    address         TEXT PRIMARY KEY,
    first_seen      TEXT,
    last_seen       TEXT,
    total_received  REAL DEFAULT 0,
    total_sent      REAL DEFAULT 0,
    tx_count        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    txid            TEXT PRIMARY KEY,
    block_height    INTEGER,
    block_time      TEXT,
    fee_sats        INTEGER,
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS tx_inputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    txid            TEXT NOT NULL REFERENCES transactions(txid),
    vin_index       INTEGER NOT NULL,
    prev_txid       TEXT,
    prev_vout       INTEGER,
    address         TEXT,
    value_btc       REAL
);

CREATE TABLE IF NOT EXISTS tx_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    txid            TEXT NOT NULL REFERENCES transactions(txid),
    vout_index      INTEGER NOT NULL,
    address         TEXT,
    value_btc       REAL,
    script_type     TEXT,
    is_change       INTEGER DEFAULT 0,
    change_signals  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clusters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id INTEGER REFERENCES investigations(id),
    label           TEXT,
    total_btc       REAL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cluster_addresses (
    cluster_id      INTEGER NOT NULL REFERENCES clusters(id),
    address         TEXT NOT NULL,
    reason          TEXT,
    PRIMARY KEY (cluster_id, address)
);

CREATE TABLE IF NOT EXISTS patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id INTEGER REFERENCES investigations(id),
    pattern_type    TEXT NOT NULL,
    addresses_json  TEXT NOT NULL,
    detail_json     TEXT,
    detected_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS threat_matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL,
    list_name       TEXT NOT NULL,
    entity_label    TEXT,
    source          TEXT,
    matched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entity_attributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL,
    entity_type     TEXT,
    confidence      REAL,
    method          TEXT,
    detail          TEXT
);

CREATE TABLE IF NOT EXISTS risk_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id INTEGER REFERENCES investigations(id),
    address         TEXT NOT NULL,
    score           REAL NOT NULL,
    band            TEXT NOT NULL,
    explanation_json TEXT NOT NULL,
    scored_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_inputs_txid ON tx_inputs(txid);
CREATE INDEX IF NOT EXISTS idx_tx_outputs_txid ON tx_outputs(txid);
CREATE INDEX IF NOT EXISTS idx_tx_inputs_address ON tx_inputs(address);
CREATE INDEX IF NOT EXISTS idx_tx_outputs_address ON tx_outputs(address);
CREATE INDEX IF NOT EXISTS idx_cluster_addresses_addr ON cluster_addresses(address);
CREATE INDEX IF NOT EXISTS idx_threat_matches_addr ON threat_matches(address);
CREATE INDEX IF NOT EXISTS idx_risk_scores_addr ON risk_scores(address);
