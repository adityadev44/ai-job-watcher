import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# A job that passes all 3 gates:
#   Gate 1: "manager" in title
#   Gate 3: no excluded term
#   Gate 2: GE90 (engine_specific) + MRO + maintenance + overhaul (domain)
MATCHING_JOB = {
    "title": "Engine Overhaul Manager",
    "url": "https://careers.safran-group.com/job/job-engine-overhaul-manager_100001.aspx",
    "location": "Hyderabad, India",
    "date": "6/10/2026",
    "contract": "Permanent",
    "ref": "Ref. : 2026-100001",
    "company": "",
    "source": "safran",
}

MATCHING_DESCRIPTION = (
    "Oversee GE90 and CFM56 engine overhaul shop operations. "
    "Responsible for Part 145 compliance and workscope planning. "
    "Coordinate MRO quality team. Ensure maintenance and airworthiness. "
    "Manage shop visit scheduling and EASA compliance. "
    "Lead a team of 30 engineers across the MRO facility."
)

# A job that fails Gate 1 (no title-family term):
NON_MATCHING_JOB = {
    "title": "Warehouse Associate",
    "url": "https://careers.safran-group.com/job/job-warehouse-associate_100099.aspx",
    "location": "Rochester, NH",
    "date": "6/9/2026",
    "contract": "Permanent",
    "ref": "Ref. : 2026-100099",
    "company": "",
    "source": "safran",
}


def _make_fetcher_module(jobs, description=MATCHING_DESCRIPTION):
    """Return a mock module that looks like safran_fetcher to the pipeline."""
    mod = MagicMock()
    mod.fetch_jobs.return_value = jobs

    class RateLimitError(Exception):
        pass

    mod.RateLimitError = RateLimitError
    mod.fetch_job_description.return_value = description
    return mod


def _load(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test 1: new matching job → alert fired, URL saved to seen_jobs
# ---------------------------------------------------------------------------

def test_new_match_triggers_alert_and_saves(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    seen.write_text("[]")
    near.write_text("[]")

    fake_fetcher = _make_fetcher_module([MATCHING_JOB])

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier") as mock_notifier:

        from src.run_safran import run_pipeline
        result = run_pipeline(seen_path=seen, near_miss_path=near)

    assert result["alert_sent"] is True, "Alert should have been sent"
    assert len(result["new_matches"]) == 1
    assert result["new_matches"][0]["title"] == "Engine Overhaul Manager"

    saved = _load(seen)
    assert MATCHING_JOB["url"] in saved, "URL must be persisted to seen_jobs"

    mock_notifier.notify_matches.assert_called_once()
    called_jobs = mock_notifier.notify_matches.call_args[0][0]
    assert called_jobs[0]["title"] == "Engine Overhaul Manager"


# ---------------------------------------------------------------------------
# Test 2: second run with same job → no alert, seen_jobs unchanged
# ---------------------------------------------------------------------------

def test_second_run_sends_no_alert(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    # Pre-populate seen with the matching job URL
    seen.write_text(json.dumps([MATCHING_JOB["url"]]))
    near.write_text("[]")

    fake_fetcher = _make_fetcher_module([MATCHING_JOB])

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier") as mock_notifier:

        from src.run_safran import run_pipeline
        result = run_pipeline(seen_path=seen, near_miss_path=near)

    assert result["alert_sent"] is False, "No alert should fire for already-seen job"
    assert result["new_matches"] == []
    mock_notifier.notify_matches.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: near-misses are written to near_misses file
# ---------------------------------------------------------------------------

def test_near_misses_are_persisted(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    seen.write_text("[]")
    near.write_text("[]")

    # NON_MATCHING_JOB fails Gate 1 → becomes a near-miss
    fake_fetcher = _make_fetcher_module([NON_MATCHING_JOB])

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier"):

        from src.run_safran import run_pipeline
        result = run_pipeline(seen_path=seen, near_miss_path=near)

    assert result["total_matched"] == 0
    nm_data = _load(near)
    assert len(nm_data) == 1
    assert nm_data[0]["title"] == "Warehouse Associate"
    assert nm_data[0]["gate_failed"] == "gate1"
    assert "run_timestamp" in nm_data[0]


# ---------------------------------------------------------------------------
# Test 4: near-misses accumulate across runs (append, not overwrite)
# ---------------------------------------------------------------------------

def test_near_misses_accumulate(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    seen.write_text("[]")
    near.write_text("[]")

    fake_fetcher = _make_fetcher_module([NON_MATCHING_JOB])

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier"):
        from src.run_safran import run_pipeline
        run_pipeline(seen_path=seen, near_miss_path=near)
        run_pipeline(seen_path=seen, near_miss_path=near)

    nm_data = _load(near)
    assert len(nm_data) == 2, "Two runs of the same near-miss should accumulate to 2 entries"


# ---------------------------------------------------------------------------
# Test 5: summary counters are correct
# ---------------------------------------------------------------------------

def test_summary_counters(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    seen.write_text("[]")
    near.write_text("[]")

    # Provide one matching + one non-matching job
    fake_fetcher = _make_fetcher_module([MATCHING_JOB, NON_MATCHING_JOB])

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier"):
        from src.run_safran import run_pipeline
        result = run_pipeline(seen_path=seen, near_miss_path=near)

    assert result["total_fetched"] == 2
    assert result["total_matched"] == 1    # only MATCHING_JOB passes all gates
    assert result["g1_pass"] == 1          # NON_MATCHING_JOB fails Gate 1
    assert len(result["near_misses"]) == 1


# ---------------------------------------------------------------------------
# Test 6: pipeline crash is contained (re-raises but doesn't silently swallow)
# ---------------------------------------------------------------------------

def test_pipeline_error_propagates(tmp_path):
    seen = tmp_path / "seen.json"
    near = tmp_path / "near.json"
    seen.write_text("[]")
    near.write_text("[]")

    fake_fetcher = MagicMock()
    fake_fetcher.fetch_jobs.side_effect = RuntimeError("network down")

    class RL(Exception):
        pass
    fake_fetcher.RateLimitError = RL

    with patch("src.run_safran.safran_fetcher", fake_fetcher), \
         patch("src.run_safran.notifier"):
        from src.run_safran import run_pipeline
        with pytest.raises(RuntimeError, match="network down"):
            run_pipeline(seen_path=seen, near_miss_path=near)
