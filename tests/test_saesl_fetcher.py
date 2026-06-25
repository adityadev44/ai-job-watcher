import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import unittest
from unittest.mock import patch, MagicMock

import src.saesl_fetcher as saesl_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

_RAW_JOBS = [
    {
        "JOBTITLE": "MR3210 - Senior Engineer (Engineering Systems)",
        "JOBLOCATION": "Singapore",
        "POSTINGDATE": "2026-06-23T17:00:00",
        "JOBCODE": "X8jNnYqTn6hclS24h7KiXQ%3d%3d",
        "REFERENCENUMBER": "260600368",
    },
    {
        "JOBTITLE": "Head of Engine Shop Operations",
        "JOBLOCATION": "Singapore",
        "POSTINGDATE": "2026-06-20T09:00:00",
        "JOBCODE": "abcDEF123%3d%3d",
        "REFERENCENUMBER": "260600350",
    },
    {
        "JOBTITLE": "Logistics Assistant",
        "JOBLOCATION": "",
        "POSTINGDATE": "2026-06-18T08:00:00",
        "JOBCODE": "ghiJKL456%3d%3d",
        "REFERENCENUMBER": "260600340",
    },
]

API_RESPONSE_JSON = json.dumps({
    "d": {
        "__type": "SearchResult",
        "JsonData": json.dumps(_RAW_JOBS),
    }
})

API_RESPONSE_EMPTY = json.dumps({
    "d": {"__type": "SearchResult", "JsonData": json.dumps([])}
})

DETAIL_PAGE_HTML = """
<html><body>
<div id="ctl00_body_tbJobDesc">
Lead the Trent engine overhaul shop, managing test cell scheduling, borescope
inspections, and shop visit workscope planning. Knowledge of Part-M, CAMO, and
EASA Part 145 procedures required. LLP tracking and on-wing support oversight.
</div>
</body></html>
"""

DETAIL_PAGE_NO_DESC = "<html><body><p>No description available.</p></body></html>"


def _make_mock_response(text, status=200, json_data=None):
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    if json_data is not None:
        mock.json.return_value = json_data
    return mock


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.saesl_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(len(jobs), 3)

    @patch("src.saesl_fetcher.requests.Session")
    def test_required_keys(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)

    @patch("src.saesl_fetcher.requests.Session")
    def test_posting_date_extracted(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs[0]["posting_date"], "2026-06-23")

    @patch("src.saesl_fetcher.requests.Session")
    def test_url_uses_jobcode(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(
            jobs[0]["url"],
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=X8jNnYqTn6hclS24h7KiXQ%3d%3d",
        )

    @patch("src.saesl_fetcher.requests.Session")
    def test_url_not_default_aspx(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            self.assertNotIn("default.aspx", job["url"])
            self.assertIn("jobdetails.aspx", job["url"])

    @patch("src.saesl_fetcher.requests.Session")
    def test_missing_location_defaults_singapore(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs[2]["location"], "Singapore")

    @patch("src.saesl_fetcher.requests.Session")
    def test_company_is_saesl(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_JSON, json_data=json.loads(API_RESPONSE_JSON))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            self.assertEqual(job["company"], "SAESL")

    @patch("src.saesl_fetcher.requests.Session")
    def test_empty_result_returns_empty_list(self, MockSession):
        mock_resp = _make_mock_response(API_RESPONSE_EMPTY, json_data=json.loads(API_RESPONSE_EMPTY))
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.saesl_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(saesl_fetcher.RateLimitError):
            saesl_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.saesl_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.post.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.saesl_fetcher.requests.Session")
    def test_malformed_response_returns_empty(self, MockSession):
        mock_resp = _make_mock_response("not json", json_data={"d": {}})
        MockSession.return_value.post.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = saesl_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.saesl_fetcher.requests.Session")
    def test_returns_tuple(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=X8jNnYqTn6hclS24h7KiXQ%3d%3d"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.saesl_fetcher.requests.Session")
    def test_description_text_returned(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=X8jNnYqTn6hclS24h7KiXQ%3d%3d"
        )
        self.assertIn("Trent", text)
        self.assertIn("CAMO", text)
        self.assertIn("test cell", text)

    @patch("src.saesl_fetcher.requests.Session")
    def test_date_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        _, date = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=X8jNnYqTn6hclS24h7KiXQ%3d%3d"
        )
        self.assertEqual(date, "")

    @patch("src.saesl_fetcher.requests.Session")
    def test_no_desc_div_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_NO_DESC)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=abcDEF123%3d%3d"
        )
        self.assertEqual(text, "")

    def test_empty_url_returns_empty(self):
        self.assertEqual(saesl_fetcher.fetch_job_description(""), ("", ""))

    def test_url_without_jobdetails_returns_empty(self):
        self.assertEqual(
            saesl_fetcher.fetch_job_description("https://saesl.applyourjobs.com/"),
            ("", "")
        )

    @patch("src.saesl_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        result = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=abcDEF123%3d%3d"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.saesl_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(saesl_fetcher.RateLimitError):
            saesl_fetcher.fetch_job_description(
                "https://saesl.applyourjobs.com/jobdetails.aspx?ID=abcDEF123%3d%3d"
            )

    @patch("src.saesl_fetcher.requests.Session")
    def test_404_returns_empty(self, MockSession):
        mock_resp = _make_mock_response("Not Found", status=404)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = saesl_fetcher.fetch_job_description(
            "https://saesl.applyourjobs.com/jobdetails.aspx?ID=abcDEF123%3d%3d"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
