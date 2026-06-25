import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import unittest
from unittest.mock import patch, MagicMock

import src.kuwait_airways_fetcher as kuwait_airways_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

_RAW_JOBS = [
    {
        "id": "691536000000999001",
        "Posting_Title": "Head of Engine Maintenance",
        "Job_Opening_Name": "Head of Engine Maintenance",
        "City": "Kuwait City",
        "State": None,
        "Country": "Kuwait",
        "Date_Opened": "2026-06-20",
        "Job_Description": "Lead the engine overhaul shop covering A320 and B787 fleets. "
                            "Manage test cell scheduling, borescope inspections, and shop "
                            "visit workscope. Requires CAMO and EASA Part 145 knowledge.",
    },
    {
        "id": "691536000000999002",
        "Posting_Title": "Cabin Crew",
        "Job_Opening_Name": "Cabin Crew",
        "City": None,
        "State": None,
        "Country": None,
        "Date_Opened": "2026-06-18",
        "Job_Description": "Deliver excellent in-flight service.",
    },
]


def _html_with_jobs(jobs):
    import html as html_mod
    value = html_mod.escape(json.dumps(jobs), quote=True)
    return f'<html><body><input type="hidden" value="{value}" id="jobs"></body></html>'


LISTING_HTML_WITH_JOBS = _html_with_jobs(_RAW_JOBS)
LISTING_HTML_EMPTY = _html_with_jobs([])
LISTING_HTML_NO_INPUT = "<html><body>No jobs input at all</body></html>"


def _make_mock_response(text, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    return mock


def _reset_cache():
    kuwait_airways_fetcher._desc_cache = {}


# ── _slugify ──────────────────────────────────────────────────────────────────

class TestSlugify(unittest.TestCase):

    def test_basic_title(self):
        self.assertEqual(kuwait_airways_fetcher._slugify("Head of Engine Maintenance"), "Head-of-Engine-Maintenance")

    def test_special_chars_collapsed(self):
        self.assertEqual(kuwait_airways_fetcher._slugify("Manager (Kuwait)"), "Manager-Kuwait")

    def test_empty_title_returns_fallback(self):
        self.assertEqual(kuwait_airways_fetcher._slugify(""), "job")

    def test_none_returns_fallback(self):
        self.assertEqual(kuwait_airways_fetcher._slugify(None), "job")


# ── _build_location ───────────────────────────────────────────────────────────

class TestBuildLocation(unittest.TestCase):

    def test_city_and_country(self):
        loc = kuwait_airways_fetcher._build_location({"City": "Kuwait City", "Country": "Kuwait"})
        self.assertEqual(loc, "Kuwait City, Kuwait")

    def test_all_null_defaults_to_kuwait(self):
        loc = kuwait_airways_fetcher._build_location({"City": None, "State": None, "Country": None})
        self.assertEqual(loc, "Kuwait")


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    def setUp(self):
        _reset_cache()

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(len(jobs), 2)

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_required_keys(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_url_uses_id_and_slug(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(
            jobs[0]["url"],
            "https://careers.kuwaitairways.com/jobs/Careers/691536000000999001/Head-of-Engine-Maintenance?source=CareerSite",
        )

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_posting_date_passthrough(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs[0]["posting_date"], "2026-06-20")

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_company_is_kuwait_airways(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            self.assertEqual(job["company"], "Kuwait Airways")

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_empty_jobs_list_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_EMPTY)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_missing_jobs_input_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_NO_INPUT)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(kuwait_airways_fetcher.RateLimitError):
            kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        _reset_cache()

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_uses_cache_with_zero_extra_calls(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}

        jobs = kuwait_airways_fetcher.fetch_jobs(inter_page_delay=0)
        call_count_after_fetch = MockSession.return_value.get.call_count

        text, date = kuwait_airways_fetcher.fetch_job_description(jobs[0]["url"])
        self.assertEqual(MockSession.return_value.get.call_count, call_count_after_fetch)
        self.assertIn("CAMO", text)
        self.assertEqual(date, "")

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_cache_miss_falls_back_to_refetch(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}

        text, _ = kuwait_airways_fetcher.fetch_job_description(
            "https://careers.kuwaitairways.com/jobs/Careers/691536000000999001/Head-of-Engine-Maintenance?source=CareerSite"
        )
        self.assertIn("test cell", text)

    def test_empty_url_returns_empty(self):
        self.assertEqual(kuwait_airways_fetcher.fetch_job_description(""), ("", ""))

    def test_url_without_id_returns_empty(self):
        self.assertEqual(
            kuwait_airways_fetcher.fetch_job_description("https://careers.kuwaitairways.com/jobs/Careers"),
            ("", "")
        )

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        result = kuwait_airways_fetcher.fetch_job_description(
            "https://careers.kuwaitairways.com/jobs/Careers/691536000000999001/slug?source=CareerSite"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_rate_limit_raises_on_cache_miss(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(kuwait_airways_fetcher.RateLimitError):
            kuwait_airways_fetcher.fetch_job_description(
                "https://careers.kuwaitairways.com/jobs/Careers/691536000000999001/slug?source=CareerSite"
            )

    @patch("src.kuwait_airways_fetcher.requests.Session")
    def test_id_not_found_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = kuwait_airways_fetcher.fetch_job_description(
            "https://careers.kuwaitairways.com/jobs/Careers/999999999999999/slug?source=CareerSite"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
