"""Tests for the pure helpers behind the Timeline, History and Statistics pages."""
from datetime import timezone

import pandas as pd
import pytest

import config
from core import dashboard_data as dd


# ---------------------------------------------------------------- timeline
def _tx(txid, inputs, outputs, block_time=None):
    return {"txid": txid, "block_time": block_time,
            "inputs": [{"address": a, "value_btc": v} for a, v in inputs],
            "outputs": [{"address": a, "value_btc": v} for a, v in outputs]}


def test_classify_tx_relations():
    root = "ROOT"
    assert dd.classify_tx(_tx("a", [("ROOT", 1)], [("X", 1)]), root) == "Outgoing"
    assert dd.classify_tx(_tx("b", [("X", 1)], [("ROOT", 1)]), root) == "Incoming"
    assert dd.classify_tx(_tx("c", [("X", 1)], [("Y", 1)]), root) == "Related"
    # root spends and receives change back: it still spent funds -> Outgoing
    assert dd.classify_tx(_tx("d", [("ROOT", 2)], [("X", 1), ("ROOT", 0.9)]), root) == "Outgoing"
    assert dd.classify_tx({}, root) == "Related"  # missing keys must not raise


def test_parse_block_time_never_invents_a_time():
    assert dd.parse_block_time(1_500_000_000).tzinfo == timezone.utc
    assert dd.parse_block_time("1500000000") == dd.parse_block_time(1_500_000_000)
    assert dd.parse_block_time("2021-03-04T05:06:07Z").year == 2021
    for missing in (None, "", "not a time", True, float("nan"), object()):
        assert dd.parse_block_time(missing) is None


def test_timeline_frame_keeps_order_and_missing_times():
    result = {"root_address": "R", "txs": [
        _tx("t1", [("R", 1)], [("X", 0.5), ("R", 0.4)], block_time=1_600_000_000),
        _tx("t2", [("X", 1)], [("R", 1)]),                       # no block time
        _tx("t3", [("A", 1)], [("B", 1)], block_time="garbage"),  # unparseable time
    ]}
    df = dd.timeline_frame(result)
    assert list(df["order"]) == [1, 2, 3]
    assert list(df["has_time"]) == [True, False, False]
    assert pd.isna(df.loc[1, "time"]) and pd.isna(df.loc[2, "time"])
    assert list(df["relation"]) == ["Outgoing", "Incoming", "Related"]
    assert df.loc[0, "value_btc"] == pytest.approx(0.9)
    assert df.loc[0, "n_inputs"] == 1 and df.loc[0, "n_outputs"] == 2


def test_timeline_frame_empty_and_missing_keys():
    assert dd.timeline_frame({}).empty
    assert list(dd.timeline_frame({"txs": []}).columns)[:3] == ["order", "txid", "short_txid"]
    df = dd.timeline_frame({"root_address": "R", "txs": [{"txid": "only-an-id"}]})
    assert len(df) == 1 and df.loc[0, "value_btc"] == 0


def test_short_id():
    assert dd.short_id(None) == "-"
    assert dd.short_id("abc") == "abc"
    long = "a" * 64
    assert dd.short_id(long) == "aaaaaaaa...aaaaaa" and len(dd.short_id(long)) < 20


# ---------------------------------------------------------------- history
def _row(**kw):
    base = {"id": 1, "root_address": "A", "created_at": "2026-01-01 10:00:00", "n_scored": 0, "n_high": 0,
            "n_medium": 0, "n_low": 0, "max_score": None, "n_clusters": 0, "n_patterns": 0, "stored_root_txs": 0,
            "max_hops": 1, "notes": None}
    base.update(kw)
    return base


def test_status_and_summary_text():
    done = _row(n_scored=10, n_high=2, n_medium=1, n_low=7, max_score=70)
    clean = _row(id=2, n_scored=5, n_low=5, max_score=8)
    broken = _row(id=3)
    assert dd.investigation_status(done) == "Completed" and dd.investigation_status(broken) == "Incomplete"
    assert dd.risk_summary(done) == "2 high, 1 medium"
    assert dd.risk_summary(clean) == "No high or medium risk addresses"
    assert dd.risk_summary(broken) == "No results saved"
    assert dd.top_band(done) == "High risk" and dd.top_band(clean) == "Low risk" and dd.top_band(broken) == "-"


def test_history_frame_handles_missing_fields():
    df = dd.history_frame([_row(n_scored=3, n_low=3, max_score=5.0, notes="  case 1 "), _row(id=2, notes=None)])
    assert list(df["ID"]) == [1, 2]
    assert df.loc[0, "Notes"] == "case 1" and df.loc[1, "Notes"] == "-"
    assert pd.isna(df.loc[1, "Max score"]) or df.loc[1, "Max score"] is None
    assert dd.history_frame([]).empty


def test_investigation_label_distinguishes_repeat_runs():
    a = dd.investigation_label(_row(id=4, root_address="X" * 34, created_at="2026-02-01 09:15:00"))
    b = dd.investigation_label(_row(id=5, root_address="X" * 34, created_at="2026-02-02 09:15:00"))
    assert a != b and a.startswith("#4") and b.startswith("#5")


# ---------------------------------------------------------------- statistics
SUMMARIES = [
    _row(id=1, root_address="A", created_at="2026-01-01 10:00:00", n_scored=5),
    _row(id=2, root_address="A", created_at="2026-01-02 10:00:00", n_scored=7),
    _row(id=3, root_address="A", created_at="2026-01-03 10:00:00", n_scored=0),   # incomplete: never "latest"
    _row(id=4, root_address="B", created_at="2026-01-01 12:00:00", n_scored=2),
]


def test_scope_selection():
    assert dd.latest_run_ids(SUMMARIES) == [2, 4]
    assert dd.select_ids(SUMMARIES, "all") == [1, 2, 3, 4]
    assert dd.select_ids(SUMMARIES, "latest") == [2, 4]
    assert dd.select_ids(SUMMARIES, "single", 4) == [4] and dd.select_ids(SUMMARIES, "single") == []


def test_band_and_pattern_counts_include_zeros():
    rows = [{"investigation_id": 1, "score": 10, "band": "low"}, {"investigation_id": 1, "score": 70, "band": "high"},
            {"investigation_id": 2, "score": 40, "band": "medium"}]
    assert dd.band_counts(rows, [1]) == {"high": 1, "medium": 0, "low": 1}
    assert dd.band_counts(rows, []) == {"high": 0, "medium": 0, "low": 0}
    pats = [{"investigation_id": 1, "pattern_type": "fan_in", "n": 3}, {"investigation_id": 2, "pattern_type": "fan_out", "n": 9}]
    got = dd.pattern_counts(pats, [1])
    assert got["fan_in"] == 3 and got["fan_out"] == 0 and got["peel_chain"] == 0 and got["circular_flow"] == 0
    assert set(dd.PATTERN_ORDER) <= set(got)


def test_score_histogram_bins_follow_the_risk_bands():
    scores = [0, 4.9, 5, 34, 35, 59, 60, 99, 100, 100]
    rows = [{"investigation_id": 1, "score": s, "band": dd.band_for_score(s)} for s in scores]
    h = dd.score_histogram(rows, [1])
    assert len(h) == 20 and int(h["count"].sum()) == len(scores)       # every score counted exactly once
    by_label = dict(zip(h["label"], h["count"]))
    assert by_label["0-4"] == 2 and by_label["5-9"] == 1
    assert by_label["30-34"] == 1 and by_label["35-39"] == 1          # 34 is Low, 35 is Medium
    assert by_label["55-59"] == 1 and by_label["60-64"] == 1          # 59 is Medium, 60 is High
    assert by_label["95-100"] == 3                                    # 99, 100, 100: top bin includes 100
    for r in h.itertuples():                                          # each bin lies inside exactly one band
        assert dd.band_for_score(r.bin_start) == dd.band_for_score(r.bin_end - 1) == r.band
    assert dd.score_histogram([], [1])["count"].sum() == 0


def test_band_thresholds_match_config():
    assert dd.band_for_score(config.RISK_BAND_MEDIUM - 1) == "low"
    assert dd.band_for_score(config.RISK_BAND_MEDIUM) == "medium"
    assert dd.band_for_score(config.RISK_BAND_HIGH - 1) == "medium"
    assert dd.band_for_score(config.RISK_BAND_HIGH) == "high"
    assert "Low 0-34" in dd.band_ranges_text() and "High 60-100" in dd.band_ranges_text()
