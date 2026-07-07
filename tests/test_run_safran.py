import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from unittest.mock import MagicMock

from src.pipeline_runner import PipelineSpec


MATCHING_JOB = {
    "title": "Engine Overhaul Manager",
    "url": "https://careers.safran-group.com/job/job-engine-overhaul-manager_100001.aspx",
    "location": "Hyderabad, India",
    "date": "6/10/2026",
    "company": "",
    "source": "safran",
}

MATCHING_DESCRIPTION = (
    "Oversee GE90 and CFM56 engine overhaul shop operations. "
    "Responsible for Part 145 compliance and workscope planning. "
    "Coordinate MRO quality team. Ensure maintenance and airworthiness."
)

NON_MATCHING_JOB = {
    "title": "Warehouse Associate",
    "url": "https://careers.safran-group.com/job/job-warehouse-associate_100099.aspx",
    "location": "Rochester, NH",
    "company": "",
    "source": "safran",
}


def _make_fetcher(jobs, description=MATCHING_DESCRIPTION):
    fetcher = MagicMock()
    fetcher.fetch_jobs.return_value = jobs

    class RateLimitError(Exception):
        pass

    fetcher.RateLimitError = RateLimitError
    fetcher.fetch_job_description.return_value = description
    fetcher.get_company.return_value = "Safran Aircraft Engines"
    return fetcher


def _make_spec(fetcher):
    return PipelineSpec(
        source="safran",
        display_name="Safran",
        fetcher=fetcher,
        seen_filename="seen_jobs_safran.json",
        populate_company=lambda job: job.update(company=fetcher.get_company(job["url"])),
    )


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_match_triggers_alert_and_saves(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text("[]", encoding="utf-8")
    health = tmp_path / "health.json"
    fake_fetcher = _make_fetcher([MATCHING_JOB])
    mock_notifier = MagicMock()

    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", health)
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)
    monkeypatch.setattr("src.run_safran.SPEC", _make_spec(fake_fetcher))

    from src.run_safran import run_pipeline
    result = run_pipeline(seen_path=seen)

    assert result["alert_sent"] is True
    assert len(result["new_matches"]) == 1
    assert MATCHING_JOB["url"] in _load(seen)
    assert result["new_matches"][0]["company"] == "Safran Aircraft Engines"
    mock_notifier.notify_matches.assert_called_once()


def test_second_run_sends_no_alert(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text(json.dumps([MATCHING_JOB["url"]]), encoding="utf-8")
    fake_fetcher = _make_fetcher([MATCHING_JOB])
    mock_notifier = MagicMock()

    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)
    monkeypatch.setattr("src.run_safran.SPEC", _make_spec(fake_fetcher))

    from src.run_safran import run_pipeline
    result = run_pipeline(seen_path=seen)

    assert result["alert_sent"] is False
    assert result["new_matches"] == []
    mock_notifier.notify_matches.assert_not_called()


def test_summary_counters_include_gate4(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text("[]", encoding="utf-8")
    fake_fetcher = _make_fetcher([MATCHING_JOB, NON_MATCHING_JOB])

    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr("src.pipeline_runner.notifier", MagicMock())
    monkeypatch.setattr("src.run_safran.SPEC", _make_spec(fake_fetcher))

    from src.run_safran import run_pipeline
    result = run_pipeline(seen_path=seen)

    assert result["total_fetched"] == 2
    assert result["g1_pass"] == 1
    assert result["g3_pass"] == 1
    assert result["g4_pass"] == 1
    assert result["total_matched"] == 1
