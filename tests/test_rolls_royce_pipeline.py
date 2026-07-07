import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from unittest.mock import MagicMock

from src.pipeline_registry import get_spec


DESC = (
    "Lead GE90 engine overhaul maintenance and shop visit workscope planning. "
    "Ensure Part 145 airworthiness compliance for engine MRO operations."
)


def test_rolls_royce_reposted_requisition_does_not_realert(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    seen.write_text(json.dumps(["RR-REQ-1"]), encoding="utf-8")
    mock_fetcher = MagicMock()
    mock_fetcher.fetch_jobs.return_value = [{
        "id": "RR-REQ-1",
        "title": "Engine Overhaul Manager",
        "url": "https://careers.rolls-royce.com/en/job/engine-overhaul-manager-999999",
        "location": "Derby, United Kingdom",
        "company": "Rolls-Royce Civil Aerospace",
        "source": "rolls_royce",
    }]
    mock_fetcher.fetch_job_description.return_value = (DESC, "")

    class RateLimitError(Exception):
        pass

    mock_fetcher.RateLimitError = RateLimitError
    spec = get_spec("rolls_royce")
    spec = type(spec)(**{**spec.__dict__, "fetcher": mock_fetcher})
    mock_notifier = MagicMock()

    monkeypatch.setattr("src.pipeline_runner.HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr("src.pipeline_runner.notifier", mock_notifier)

    from src.pipeline_runner import run_pipeline
    result = run_pipeline(spec, seen_path=seen)

    assert result["alert_sent"] is False
    assert result["new_matches"] == []
    assert json.loads(seen.read_text(encoding="utf-8")) == ["RR-REQ-1"]
    mock_notifier.notify_matches.assert_not_called()
