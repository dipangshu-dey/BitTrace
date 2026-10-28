"""PDF investigation report: generation, optional-data handling and database summaries."""
import io

import pytest
from pypdf import PdfReader

import config
from core import report_generator as rg
from core.demo_data import build_demo_transactions
from core.pipeline import run_investigation
from db import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "report_test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    database.init_db()
    return path


@pytest.fixture
def demo_result(temp_db):
    return run_investigation("DEMO_ROOT", synthetic_txs=build_demo_transactions("DEMO_ROOT"),
                             notes="Case 7 <b>& analyst</b> caf\u00e9")


def _text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return reader, "\n".join(p.extract_text() for p in reader.pages)


def test_pdf_builds_and_has_expected_content(demo_result):
    data = rg.build_pdf_report(demo_result)
    assert data.startswith(b"%PDF")
    reader, text = _text(data)
    assert len(reader.pages) >= 2
    for expected in ("BitTrace Investigation Report", f"Investigation #{demo_result['investigation_id']}", "DEMO_ROOT",
                     "Synthetic demo data", "Summary of findings", "Risk assessment", "High-risk addresses",
                     "Graph analysis", "Transaction details", "Method and limitations"):
        assert expected in text, expected
    assert "caf\u00e9" in text and "analyst" in text          # notes shown, special characters survive
    assert f"Page 1 of {len(reader.pages)}" in reader.pages[0].extract_text()
    assert reader.metadata.title.startswith("BitTrace investigation report")


def test_pdf_does_not_invent_block_times(demo_result):
    # demo transactions carry no block time; the report must say so rather than show dates
    _, text = _text(rg.build_pdf_report(demo_result))
    assert "has a block time" in text and "not blockchain chronology" in text
    assert "Block time (UTC)" in text and "n/a" in text


def test_pdf_with_real_block_times_draws_time_chart(temp_db):
    txs = [{"txid": f"tx{i}", "block_time": 1_600_000_000 + i * 86400,
            "inputs": [{"address": "R", "value_btc": 1.0}], "outputs": [{"address": f"O{i}", "value_btc": 0.9}]}
           for i in range(4)]
    res = run_investigation("R", synthetic_txs=txs)
    res["meta"]["synthetic"] = False
    _, text = _text(rg.build_pdf_report(res))
    assert "Live blockchain data" in text and "2020-09-13" in text      # 1_600_000_000 = 2020-09-13 UTC


@pytest.mark.parametrize("result", [
    {},
    {"investigation_id": 5, "root_address": "1Abc"},
    {"investigation_id": 5, "root_address": "1Abc", "addresses": [], "txs": [], "clusters": [], "patterns": {},
     "risk_scores": {}, "entity_map": {}, "analytics": {}, "meta": {}},
])
def test_pdf_generates_with_missing_or_empty_data(result):
    data = rg.build_pdf_report(result)
    reader, text = _text(data)
    assert data.startswith(b"%PDF") and len(reader.pages) >= 1
    assert "BitTrace Investigation Report" in text
    assert "could not be generated" not in text            # nothing silently failed


def test_pdf_low_risk_only_says_so(temp_db):
    txs = [{"txid": "t1", "inputs": [{"address": "A", "value_btc": 1.0}],
            "outputs": [{"address": "B", "value_btc": 0.6}, {"address": "C", "value_btc": 0.39}]}]
    res = run_investigation("A", synthetic_txs=txs)
    _, text = _text(rg.build_pdf_report(res))
    assert "No address scored in the High band" in text


def test_export_pdf_still_writes_a_file(demo_result, tmp_path):
    out = rg.export_pdf(demo_result, out_path=tmp_path / "r.pdf")
    assert out.exists() and out.read_bytes().startswith(b"%PDF")


def test_report_from_stored_records(demo_result):
    stored = rg.result_from_database(demo_result["investigation_id"])
    assert stored["stored_only"] and stored["txs"] == [] and stored["graph"] is None
    assert len(stored["risk_scores"]) == len(demo_result["risk_scores"])
    _, text = _text(rg.build_pdf_report(stored))
    assert "rebuilt from stored" in text and "Transaction-level data is not stored" in text
    assert "DEMO_ROOT" in text
    assert rg.result_from_database(987654) is None


def test_investigation_summaries_report_completed_and_incomplete(demo_result):
    incomplete_id = database.create_investigation("NEVER_FINISHED", 2, notes="stopped early")
    rows = {r["id"]: r for r in database.get_investigation_summaries()}
    done, broken = rows[demo_result["investigation_id"]], rows[incomplete_id]
    assert done["n_scored"] == len(demo_result["risk_scores"]) and done["n_high"] >= 1
    assert done["n_high"] + done["n_medium"] + done["n_low"] == done["n_scored"]
    assert done["n_clusters"] == len(demo_result["clusters"])
    assert broken["n_scored"] == 0 and broken["max_score"] is None and broken["n_clusters"] == 0
    assert sum(r["n"] for r in database.get_pattern_counts() if r["investigation_id"] == done["id"]) == done["n_patterns"]
    assert len(database.get_score_rows()) == done["n_scored"]
