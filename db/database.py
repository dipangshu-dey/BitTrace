"""
BitTrace v2 - SQLite database layer.

Thin, dependency-free wrapper around sqlite3. Every other module talks to
the database exclusively through this file so schema changes only need to
happen in one place.

Schema notes (migration v2):
  * investigation_transactions links each investigation to the transactions it analysed
    (many-to-many; the transactions table itself stays shared and de-duplicated by txid).
  * Investigation IDs come from SQLite AUTOINCREMENT. _sync_investigation_sequence() additionally
    guarantees a new ID can never equal an ID still referenced by child tables, even if the
    sqlite_sequence counter was lost or reset (e.g. by a database editor).
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


def init_db(db_path: Path = None, schema_path: Path = None) -> None:
    """Create/migrate the SQLite database and repair duplicate child rows.

    Older BitTrace builds could insert the same tx input/output or attribution
    more than once when an investigation was repeated. The migration below
    removes those historical duplicates once, then adds unique indexes so the
    problem cannot return. Transaction rows themselves remain shared across
    investigations because they are keyed by txid.
    """
    if db_path is None:
        db_path = config.DB_PATH
    if schema_path is None:
        schema_path = config.SCHEMA_PATH
    conn = sqlite3.connect(db_path)
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        # Repair duplicate rows created by older versions before creating the
        # uniqueness constraints. Keep the earliest row for each logical item.
        conn.executescript(
            """
            DELETE FROM tx_inputs
            WHERE id NOT IN (
                SELECT MIN(id) FROM tx_inputs GROUP BY txid, vin_index
            );
            DELETE FROM tx_outputs
            WHERE id NOT IN (
                SELECT MIN(id) FROM tx_outputs GROUP BY txid, vout_index
            );
            DELETE FROM threat_matches
            WHERE id NOT IN (
                SELECT MIN(id) FROM threat_matches
                GROUP BY address, list_name, entity_label, source
            );
            DELETE FROM entity_attributions
            WHERE id NOT IN (
                SELECT MIN(id) FROM entity_attributions
                GROUP BY address, entity_type, confidence, method, detail
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tx_inputs_position
                ON tx_inputs(txid, vin_index);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_tx_outputs_position
                ON tx_outputs(txid, vout_index);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_threat_match
                ON threat_matches(address, list_name, entity_label, source);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_attribution
                ON entity_attributions(address, entity_type, confidence, method, detail);
            """
        )
        conn.commit()
        _ensure_link_schema(conn)
        _sync_investigation_sequence(conn)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration v2: investigation <-> transaction links, ID safety
# ---------------------------------------------------------------------------
_LINK_TABLE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS investigation_transactions (
        investigation_id INTEGER NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
        txid             TEXT    NOT NULL REFERENCES transactions(txid),
        hop              INTEGER,
        discovered_via   TEXT,
        linked_at        TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (investigation_id, txid)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_invtx_txid ON investigation_transactions(txid)",
)

# tables whose investigation_id column must never point at a reused ID
_ID_REFERENCING_TABLES = ("risk_scores", "patterns", "clusters", "investigation_transactions")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _ensure_link_schema(conn) -> None:
    """Create the investigation_transactions table/index if missing. Safe to run any number of
    times, never touches existing data, and is all-or-nothing (one transaction).

    Also called from get_conn() so a database created by an older BitTrace is upgraded the first
    time any page reads it, not only when the next investigation is run."""
    if not _table_exists(conn, "investigations") or not _table_exists(conn, "transactions"):
        return
    has_table = _table_exists(conn, "investigation_transactions")
    has_index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_invtx_txid'"
    ).fetchone() is not None
    if has_table and has_index:
        return
    try:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        for ddl in _LINK_TABLE_DDL:
            conn.execute(ddl)
        conn.commit()
    except sqlite3.OperationalError:
        # e.g. read-only database file: reading still works, linking simply isn't available
        conn.rollback()


def _sync_investigation_sequence(conn) -> int:
    """Keep the investigation ID counter consistent. Returns the counter value afterwards.

    * Table EMPTY: nothing can collide, so the AUTOINCREMENT counter is reset and the next
      investigation gets ID 1. Child rows that still point at deleted investigations (orphans left
      by deletions made outside BitTrace) are removed first, otherwise a reused ID 1 would inherit
      them. Shared transactions/addresses are never touched.
    * Table NOT empty: the counter is raised to at least the largest ID that exists or is still
      referenced by a child table, so a new ID can never collide. It is never lowered, so deleting
      individual investigations does not change or reuse IDs.
    """
    if not _table_exists(conn, "investigations"):
        return 0
    count = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
    if count == 0:
        if _table_exists(conn, "clusters"):
            if _table_exists(conn, "cluster_addresses"):
                conn.execute("DELETE FROM cluster_addresses WHERE cluster_id IN "
                             "(SELECT id FROM clusters WHERE investigation_id IS NOT NULL)")
            conn.execute("DELETE FROM clusters WHERE investigation_id IS NOT NULL")
        for table in ("risk_scores", "patterns", "investigation_transactions"):
            if _table_exists(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE investigation_id IS NOT NULL")
        if _table_exists(conn, "sqlite_sequence"):
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'investigations'")
        return 0
    floor = conn.execute("SELECT COALESCE(MAX(id), 0) FROM investigations").fetchone()[0]
    for table in _ID_REFERENCING_TABLES:
        if _table_exists(conn, table):
            m = conn.execute(f"SELECT COALESCE(MAX(investigation_id), 0) FROM {table}").fetchone()[0]
            floor = max(floor, m or 0)
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'investigations'").fetchone()
    if row is None:
        if floor:
            conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('investigations', ?)", (floor,))
        return floor
    if row[0] < floor:
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'investigations'", (floor,))
        return floor
    return row[0]


@contextmanager
def get_conn(db_path: Path = None):
    if db_path is None:
        db_path = config.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_link_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------
def create_investigation(root_address: str, max_hops: int, notes: str = "") -> int:
    with get_conn() as conn:
        _sync_investigation_sequence(conn)   # never hand out an ID that old child rows still point at
        cur = conn.execute(
            "INSERT INTO investigations (root_address, max_hops, notes) VALUES (?, ?, ?)",
            (root_address, max_hops, notes),
        )
        return cur.lastrowid


def get_investigation(investigation_id: int) -> Optional[sqlite3.Row]:
    if investigation_id is None:
        return None
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM investigations WHERE id = ?", (investigation_id,)
        ).fetchone()


def list_investigations() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM investigations ORDER BY created_at DESC, id DESC"
        ).fetchall()


def delete_investigation(investigation_id: int) -> bool:
    """Delete one investigation and only its investigation-scoped records.

    Shared blockchain transactions/addresses are intentionally retained because
    they may be reused by another investigation; only this investigation's links to
    them are removed. The deleted ID is never reused (AUTOINCREMENT + sequence sync).
    """
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM investigations WHERE id = ?", (investigation_id,)
        ).fetchone()
        if not exists:
            return False
        conn.execute("DELETE FROM cluster_addresses WHERE cluster_id IN (SELECT id FROM clusters WHERE investigation_id = ?)", (investigation_id,))
        conn.execute("DELETE FROM clusters WHERE investigation_id = ?", (investigation_id,))
        conn.execute("DELETE FROM patterns WHERE investigation_id = ?", (investigation_id,))
        conn.execute("DELETE FROM investigation_transactions WHERE investigation_id = ?", (investigation_id,))
        conn.execute("DELETE FROM risk_scores WHERE investigation_id = ?", (investigation_id,))
        conn.execute("DELETE FROM investigations WHERE id = ?", (investigation_id,))
        _sync_investigation_sequence(conn)   # table now empty -> counter resets so the next ID is 1
        return True


def get_statistics() -> dict:
    """Return aggregate statistics with a small number of SQL queries.

    This replaces the old N+1 pattern where the Statistics page opened a new
    SQLite connection for every investigation and fetched every row.
    """
    with get_conn() as conn:
        investigations = conn.execute("SELECT COUNT(*) AS n FROM investigations").fetchone()["n"]
        addresses_scored = conn.execute("SELECT COUNT(*) AS n FROM risk_scores").fetchone()["n"]
        bands = conn.execute(
            "SELECT band, COUNT(*) AS n FROM risk_scores GROUP BY band"
        ).fetchall()
        patterns = conn.execute(
            "SELECT pattern_type, COUNT(*) AS n FROM patterns GROUP BY pattern_type"
        ).fetchall()
        scores = conn.execute(
            "SELECT score FROM risk_scores ORDER BY score"
        ).fetchall()
    return {
        "investigations": int(investigations),
        "addresses_scored": int(addresses_scored),
        "bands": {r["band"]: int(r["n"]) for r in bands},
        "patterns": {r["pattern_type"]: int(r["n"]) for r in patterns},
        "scores": [float(r["score"]) for r in scores],
    }


def get_investigation_summaries() -> list:
    """One row per investigation with the aggregates the History and Statistics
    pages need, computed in a single query (read-only; no schema change).

    - n_scored / n_high / n_medium / n_low / max_score come from risk_scores
    - n_clusters / n_patterns come from clusters / patterns
    - stored_root_txs is the number of transactions stored in the shared
      transactions tables that involve the investigated address. It is a property
      of the address, not the exact set analysed in that run.
    - n_linked_txs is the number of transactions recorded as analysed BY this
      investigation (investigation_transactions). 0 means a legacy investigation
      saved before links existed: its transaction set is unknown.
    """
    sql = """
    SELECT i.id, i.root_address, i.max_hops, i.created_at, i.notes,
           COALESCE(r.n, 0)      AS n_scored,
           COALESCE(r.high, 0)   AS n_high,
           COALESCE(r.medium, 0) AS n_medium,
           COALESCE(r.low, 0)    AS n_low,
           r.max_score           AS max_score,
           COALESCE(c.n, 0)      AS n_clusters,
           COALESCE(p.n, 0)      AS n_patterns,
           (SELECT COUNT(*) FROM (
                SELECT txid FROM tx_inputs  WHERE address = i.root_address
                UNION
                SELECT txid FROM tx_outputs WHERE address = i.root_address
           )) AS stored_root_txs,
           (SELECT COUNT(*) FROM investigation_transactions t
             WHERE t.investigation_id = i.id) AS n_linked_txs
    FROM investigations i
    LEFT JOIN (SELECT investigation_id, COUNT(*) AS n,
                      SUM(band = 'high') AS high, SUM(band = 'medium') AS medium,
                      SUM(band = 'low') AS low, MAX(score) AS max_score
               FROM risk_scores GROUP BY investigation_id) r ON r.investigation_id = i.id
    LEFT JOIN (SELECT investigation_id, COUNT(*) AS n FROM clusters
               GROUP BY investigation_id) c ON c.investigation_id = i.id
    LEFT JOIN (SELECT investigation_id, COUNT(*) AS n FROM patterns
               GROUP BY investigation_id) p ON p.investigation_id = i.id
    ORDER BY i.created_at DESC, i.id DESC
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_pattern_counts() -> list:
    """(investigation_id, pattern_type, n) rows - lets the Statistics page scope
    pattern counts to one investigation or the latest run per address."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT investigation_id, pattern_type, COUNT(*) AS n FROM patterns "
            "GROUP BY investigation_id, pattern_type"
        ).fetchall()]


def get_score_rows() -> list:
    """(investigation_id, score, band) for every stored risk score."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT investigation_id, score, band FROM risk_scores"
        ).fetchall()]


def get_latest_investigation_id() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS id FROM investigations").fetchone()
        return int(row["id"])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
def upsert_address(address: str, first_seen: str = None, last_seen: str = None,
                    total_received: float = 0, total_sent: float = 0, tx_count: int = 0) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO addresses (address, first_seen, last_seen, total_received, total_sent, tx_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                last_seen = excluded.last_seen,
                total_received = excluded.total_received,
                total_sent = excluded.total_sent,
                tx_count = excluded.tx_count
            """,
            (address, first_seen, last_seen, total_received, total_sent, tx_count),
        )


def get_address(address: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM addresses WHERE address = ?", (address,)).fetchone()


# ---------------------------------------------------------------------------
# Transactions / inputs / outputs
# ---------------------------------------------------------------------------
def upsert_transaction(txid: str, block_height: Optional[int], block_time: Optional[str],
                        fee_sats: Optional[int], raw_json: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO transactions (txid, block_height, block_time, fee_sats, raw_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(txid) DO UPDATE SET
                block_height = excluded.block_height,
                block_time = excluded.block_time,
                fee_sats = excluded.fee_sats,
                raw_json = excluded.raw_json
            """,
            (txid, block_height, block_time, fee_sats, json.dumps(raw_json)),
        )


def insert_inputs(txid: str, inputs: Iterable[dict]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO tx_inputs (txid, vin_index, prev_txid, prev_vout, address, value_btc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (txid, i.get("vin_index", idx), i.get("prev_txid"), i.get("prev_vout"),
                 i.get("address"), i.get("value_btc"))
                for idx, i in enumerate(inputs)
            ],
        )


def insert_outputs(txid: str, outputs: Iterable[dict]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO tx_outputs (txid, vout_index, address, value_btc, script_type, is_change, change_signals)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (txid, o.get("vout_index", idx), o.get("address"), o.get("value_btc"),
                 o.get("script_type"), int(o.get("is_change", 0)), o.get("change_signals", 0))
                for idx, o in enumerate(outputs)
            ],
        )


def get_transaction(txid: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM transactions WHERE txid = ?", (txid,)).fetchone()


def get_inputs(txid: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tx_inputs WHERE txid = ? ORDER BY vin_index", (txid,)
        ).fetchall()


def get_outputs(txid: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tx_outputs WHERE txid = ? ORDER BY vout_index", (txid,)
        ).fetchall()


def get_txs_for_address(address: str, investigation_id: Optional[int] = None) -> list:
    """All txids where this address appears as an input or output.

    With investigation_id, only transactions recorded as analysed by that investigation."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT txid FROM (
                SELECT txid FROM tx_inputs WHERE address = ?
                UNION
                SELECT txid FROM tx_outputs WHERE address = ?
            )
            """,
            (address, address),
        ).fetchall()
        txids = [r["txid"] for r in rows]
        if investigation_id is None:
            return txids
        linked = {r["txid"] for r in conn.execute(
            "SELECT txid FROM investigation_transactions WHERE investigation_id = ?", (investigation_id,))}
        return [t for t in txids if t in linked]


# ---------------------------------------------------------------------------
# Investigation <-> transaction links
# ---------------------------------------------------------------------------
def _chunks(items: list, n: int = 400):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def link_transactions(investigation_id: int, txids: Iterable, hop: Optional[int] = None,
                      discovered_via: Optional[str] = None) -> int:
    """Record that an investigation analysed these transactions. Idempotent: linking the same
    (investigation, txid) again changes nothing. Returns the number of NEW links.

    `txids` items are txid strings, or dicts {"txid", "hop", "discovered_via"} to give per-item
    hop information (hop / discovered_via are optional and stay NULL when unknown).
    The transactions must already be stored (upsert_transaction) and the investigation must exist,
    otherwise nothing is linked and sqlite3.IntegrityError is raised (all-or-nothing)."""
    rows = []
    for item in txids:
        if isinstance(item, dict):
            rows.append((investigation_id, item["txid"], item.get("hop", hop),
                         item.get("discovered_via", discovered_via)))
        else:
            rows.append((investigation_id, item, hop, discovered_via))
    with get_conn() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO investigation_transactions "
            "(investigation_id, txid, hop, discovered_via) VALUES (?, ?, ?, ?)", rows)
        return conn.total_changes - before


def has_transaction_links(investigation_id: int) -> bool:
    """True if this investigation has recorded transactions. False for legacy investigations
    (saved before links existed), whose analysed transaction set cannot be known."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM investigation_transactions WHERE investigation_id = ? LIMIT 1",
            (investigation_id,)).fetchone() is not None


def get_investigation_txids(investigation_id: int) -> list:
    with get_conn() as conn:
        return [r["txid"] for r in conn.execute(
            "SELECT txid FROM investigation_transactions WHERE investigation_id = ? ORDER BY txid",
            (investigation_id,))]


def get_investigation_transactions(investigation_id: int) -> list:
    """The investigation's OWN transactions in the normalised shape the pipeline produces
    (txid, block_height, block_time, fee_sats, inputs[], outputs[]) plus hop / discovered_via.
    Returns [] for an unknown or legacy investigation. Never includes another investigation's rows."""
    with get_conn() as conn:
        links = conn.execute(
            "SELECT l.txid, l.hop, l.discovered_via, t.block_height, t.block_time, t.fee_sats "
            "FROM investigation_transactions l JOIN transactions t ON t.txid = l.txid "
            "WHERE l.investigation_id = ? ORDER BY l.txid", (investigation_id,)).fetchall()
        txs = {r["txid"]: {"txid": r["txid"], "block_height": r["block_height"],
                           "block_time": r["block_time"], "fee_sats": r["fee_sats"],
                           "hop": r["hop"], "discovered_via": r["discovered_via"],
                           "inputs": [], "outputs": []} for r in links}
        for ch in _chunks(list(txs)):
            q = ",".join("?" * len(ch))
            for r in conn.execute(
                    f"SELECT txid, vin_index, prev_txid, prev_vout, address, value_btc FROM tx_inputs "
                    f"WHERE txid IN ({q}) ORDER BY txid, vin_index", ch):
                txs[r["txid"]]["inputs"].append({
                    "vin_index": r["vin_index"], "prev_txid": r["prev_txid"], "prev_vout": r["prev_vout"],
                    "address": r["address"], "value_btc": r["value_btc"]})
            for r in conn.execute(
                    f"SELECT txid, vout_index, address, value_btc, script_type, is_change, change_signals "
                    f"FROM tx_outputs WHERE txid IN ({q}) ORDER BY txid, vout_index", ch):
                txs[r["txid"]]["outputs"].append({
                    "vout_index": r["vout_index"], "address": r["address"], "value_btc": r["value_btc"],
                    "script_type": r["script_type"], "is_change": bool(r["is_change"]),
                    "change_signals": r["change_signals"]})
        return list(txs.values())


def get_orphaned_investigation_ids() -> list:
    """Read-only diagnostic: investigation IDs that child tables still reference although the
    investigation row no longer exists (left by deletions made outside BitTrace). They are never
    deleted automatically and can no longer be reused or confused with a new investigation."""
    with get_conn() as conn:
        found = set()
        for table in _ID_REFERENCING_TABLES:
            if _table_exists(conn, table):
                found |= {r[0] for r in conn.execute(
                    f"SELECT DISTINCT investigation_id FROM {table} WHERE investigation_id IS NOT NULL "
                    f"AND investigation_id NOT IN (SELECT id FROM investigations)")}
        return sorted(found)


# ---------------------------------------------------------------------------
# Clusters (Objective 1)
# ---------------------------------------------------------------------------
def create_cluster(investigation_id: int, label: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO clusters (investigation_id, label) VALUES (?, ?)",
            (investigation_id, label),
        )
        return cur.lastrowid


def add_address_to_cluster(cluster_id: int, address: str, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO cluster_addresses (cluster_id, address, reason)
            VALUES (?, ?, ?)
            ON CONFLICT(cluster_id, address) DO UPDATE SET reason = excluded.reason
            """,
            (cluster_id, address, reason),
        )


def set_cluster_total_btc(cluster_id: int, total_btc: float) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE clusters SET total_btc = ? WHERE id = ?", (total_btc, cluster_id))


def get_cluster_addresses(cluster_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM cluster_addresses WHERE cluster_id = ?", (cluster_id,)
        ).fetchall()


def get_clusters_for_investigation(investigation_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM clusters WHERE investigation_id = ?", (investigation_id,)
        ).fetchall()


# ---------------------------------------------------------------------------
# Patterns (Objective 2)
# ---------------------------------------------------------------------------
def save_pattern(investigation_id: int, pattern_type: str, addresses: list, detail: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO patterns (investigation_id, pattern_type, addresses_json, detail_json)
            VALUES (?, ?, ?, ?)
            """,
            (investigation_id, pattern_type, json.dumps(addresses), json.dumps(detail)),
        )
        return cur.lastrowid


def get_patterns_for_investigation(investigation_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM patterns WHERE investigation_id = ?", (investigation_id,)
        ).fetchall()


# ---------------------------------------------------------------------------
# Threat intel & entity attribution (Objective 4)
# ---------------------------------------------------------------------------
def save_threat_match(address: str, list_name: str, entity_label: str, source: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO threat_matches (address, list_name, entity_label, source) VALUES (?, ?, ?, ?)",
            (address, list_name, entity_label, source),
        )


def get_threat_matches(address: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM threat_matches WHERE address = ?", (address,)
        ).fetchall()


def save_entity_attribution(address: str, entity_type: str, confidence: float,
                             method: str, detail: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO entity_attributions (address, entity_type, confidence, method, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (address, entity_type, confidence, method, detail),
        )


def get_entity_attributions(address: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM entity_attributions WHERE address = ?", (address,)
        ).fetchall()


# ---------------------------------------------------------------------------
# Risk scores (Objective 3)
# ---------------------------------------------------------------------------
def save_risk_score(investigation_id: int, address: str, score: float, band: str, explanation: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO risk_scores (investigation_id, address, score, band, explanation_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (investigation_id, address, score, band, json.dumps(explanation)),
        )
        return cur.lastrowid


def get_risk_scores_for_investigation(investigation_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM risk_scores WHERE investigation_id = ? ORDER BY score DESC",
            (investigation_id,),
        ).fetchall()


def get_latest_risk_score(address: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM risk_scores WHERE address = ? ORDER BY scored_at DESC LIMIT 1",
            (address,),
        ).fetchone()