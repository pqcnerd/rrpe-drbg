"""
Integration tests for the full commit → reveal → extract workflow.
"""
import json
import os
from datetime import date, datetime, time
from unittest.mock import Mock

import pytest
import pytz

from src import commit_reveal, config, extractor


@pytest.fixture
def mock_full_workflow_setup(monkeypatch, temp_output_dir, test_salt_key, sample_trade_date):
    """set up all mocks needed for full workflow testing."""
    monkeypatch.setattr("src.datafeed.is_trading_day", lambda d: True)
    
    def mock_prev(d):
        if d == sample_trade_date:
            return date(2024, 1, 12)
        return date(2024, 1, 11)
    monkeypatch.setattr("src.datafeed.previous_trading_day", mock_prev)
    
    def mock_closes(symbol, end_date, lookback_trading_days=6):
        dates = [
            date(2024, 1, 8),
            date(2024, 1, 9),
            date(2024, 1, 10),
            date(2024, 1, 11),
            date(2024, 1, 12),
        ]
        prices = [450.0, 451.0, 452.0, 453.0, 454.0]
        return list(zip(dates, prices))
    monkeypatch.setattr("src.datafeed.get_recent_closes", mock_closes)
    
    et = pytz.timezone("America/New_York")
    bar_time = et.localize(datetime.combine(sample_trade_date, time(15, 55, 0)))
    
    def mock_bar(symbol, trade_date, target_et, tolerance_minutes=2):
        return 450.25, bar_time.isoformat()
    monkeypatch.setattr("src.datafeed.get_minute_bar_near_et", mock_bar)
    
    def mock_price(symbol, trade_date, bar_ts_et_iso, tolerance_minutes=2):
        return 450.25, bar_ts_et_iso
    monkeypatch.setattr("src.datafeed.get_price_at_bar_et", mock_price)
    
    def mock_closes_pair(symbol, trade_date):
        return 450.0, 451.0  # prev_close, today_close (up)
    monkeypatch.setattr("src.datafeed.get_prev_and_today_close", mock_closes_pair)
    
    def mock_now_commit():
        et = pytz.timezone("America/New_York")
        return et.localize(datetime.combine(sample_trade_date, time(15, 55))).replace(tzinfo=None)
    
    def mock_now_reveal():
        et = pytz.timezone("America/New_York")
        return et.localize(datetime.combine(sample_trade_date, time(16, 5))).replace(tzinfo=None)
    
    mock_response = Mock()
    mock_response.json.return_value = {
        "randomness": "a1b2c3d4e5f6789012345678901234567890123456789012345678901234567890",
    }
    mock_response.raise_for_status = Mock()
    
    def mock_get(url, timeout=None):
        return mock_response
    monkeypatch.setattr("requests.get", mock_get)
    
    return {
        "mock_now_commit": mock_now_commit,
        "mock_now_reveal": mock_now_reveal,
    }


def test_full_workflow_commit_reveal_extract(
    monkeypatch, mock_full_workflow_setup, temp_output_dir, test_salt_key, sample_trade_date
):
    """test the complete workflow: commit -> reveal -> extract."""
    monkeypatch.setattr("src.commit_reveal._now_et_wall", mock_full_workflow_setup["mock_now_commit"])
    
    result_commit = commit_reveal.perform_commit(sample_trade_date, enforce_window=False)
    assert result_commit is True
    
    commit_path = os.path.join(config.DAILY_DIR, f"{sample_trade_date.isoformat()}.json")
    assert os.path.exists(commit_path)
    
    with open(commit_path, "r", encoding="utf-8") as f:
        commit_doc = json.load(f)
        assert "symbols" in commit_doc
        assert len(commit_doc["symbols"]) > 0
        assert commit_doc["symbols"][0].get("commit") is not None
    
    monkeypatch.setattr("src.commit_reveal._now_et_wall", mock_full_workflow_setup["mock_now_reveal"])
    
    result_reveal = commit_reveal.perform_reveal(sample_trade_date, enforce_window=False)
    assert result_reveal is True
    
    with open(commit_path, "r", encoding="utf-8") as f:
        reveal_doc = json.load(f)
        symbol_rec = reveal_doc["symbols"][0]
        assert symbol_rec.get("revealed_at_utc") is not None
        assert symbol_rec.get("prediction") is not None
        assert symbol_rec.get("outcome") is not None
        assert symbol_rec.get("symbol_bits") is not None
        assert symbol_rec.get("symbol_bytes_hex") is not None
    
    assert os.path.exists(config.ENTROPY_LOG)
    
    result_extract = extractor.run_for_date(sample_trade_date, window=1, out_bits=256)
    assert result_extract is True
    
    with open(commit_path, "r", encoding="utf-8") as f:
        extract_doc = json.load(f)
        assert "extractor" in extract_doc
        assert "output_hex" in extract_doc["extractor"]
        assert len(extract_doc["extractor"]["output_hex"]) == 64  # 256 bits / 4


def test_reveal_detects_commit_mismatch(
    monkeypatch, mock_full_workflow_setup, temp_output_dir, test_salt_key, sample_trade_date
):
    """tamper with the commit file to ensure reveal detects mismatches."""
    monkeypatch.setattr("src.commit_reveal._now_et_wall", mock_full_workflow_setup["mock_now_commit"])
    assert commit_reveal.perform_commit(sample_trade_date, enforce_window=False) is True

    commit_path = os.path.join(config.DAILY_DIR, f"{sample_trade_date.isoformat()}.json")
    with open(commit_path, "r", encoding="utf-8") as f:
        commit_doc = json.load(f)
    original_inputs = commit_doc["symbols"][0]["commit_inputs"]
    commit_doc["symbols"][0]["commit"] = "not-the-original-commit"
    with open(commit_path, "w", encoding="utf-8") as f:
        json.dump(commit_doc, f)

    monkeypatch.setattr("src.commit_reveal._now_et_wall", mock_full_workflow_setup["mock_now_reveal"])
    monkeypatch.setattr(
        "src.commit_reveal._ensure_commit_inputs",
        lambda rec, sym, td, secret: original_inputs,
    )
    with pytest.raises(RuntimeError, match="Commit mismatch"):
        commit_reveal.perform_reveal(sample_trade_date, enforce_window=False)

