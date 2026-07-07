import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from unittest.mock import MagicMock

from src.pipeline_runner import PipelineSpec, run_pipeline


GOOD_DESC = (
    "GE90 engine overhaul maintenance workscope shop visit Part 145 "
    "airworthiness MRO compliance planning."
)


class RateLimitError(Exception):
    pass


def _fetcher(jobs, desc=GOOD_DESC):
    fetcher = MagicMock()
    fetcher.fetch_jobs.return_value = jobs
    fetcher.fetch_job_description.return_value = desc
    fetcher.RateLimitError = RateLimitError
    return fetcher


def _job(title="Engine Overhaul Manager", url="https://example.test/job/1", id_="REQ-1"):
    return {
        "id": id_,
        "title": title,
        "url": url,
        "location": "Dubai, UAE",
        "company": "Example",
        "source": "example",
    }


def test_url_dedupe_persists_url(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    mock_notifier = MagicMock()
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)

    spec = PipelineSpec("example", "Example", _fetcher([_job()]), "seen.json")
    result = run_pipeline(spec, seen_path=seen)

    assert result["alert_sent"] is True
    assert json.loads(seen.read_text(encoding="utf-8")) == ["https://example.test/job/1"]


def test_id_dedupe_blocks_reposted_url(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text(json.dumps(["REQ-1"]), encoding="utf-8")
    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    mock_notifier = MagicMock()
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)

    repost = _job(url="https://example.test/job/new-posting", id_="REQ-1")
    spec = PipelineSpec("example", "Example", _fetcher([repost]), "seen.json", dedupe_key="id")
    result = run_pipeline(spec, seen_path=seen)

    assert result["alert_sent"] is False
    assert result["new_matches"] == []
    mock_notifier.notify_matches.assert_not_called()


def test_pre_filter_runs_before_matcher(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr("src.pipeline_runner.notifier", MagicMock())

    jobs = [
        _job(title="Engine Overhaul Manager", url="https://example.test/keep"),
        _job(title="Finance Manager", url="https://example.test/drop"),
    ]
    spec = PipelineSpec(
        "example",
        "Example",
        _fetcher(jobs),
        "seen.json",
        pre_filter=lambda job: "engine" in job["title"].lower(),
    )
    result = run_pipeline(spec, seen_path=seen)

    assert result["total_fetched"] == 2
    assert result["pre_filter_dropped"] == 1
    assert result["total_matched"] == 1


def test_zero_fetch_health_warning_on_third_successful_zero(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text("[]", encoding="utf-8")
    health = tmp_path / "health.json"
    mock_notifier = MagicMock()
    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", health)
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)

    spec = PipelineSpec("example", "Example", _fetcher([]), "seen.json")
    for _ in range(3):
        run_pipeline(spec, seen_path=seen)

    data = json.loads(health.read_text(encoding="utf-8"))
    assert data["example"]["zero_streak"] == 3
    mock_notifier.send_email.assert_called_once()
