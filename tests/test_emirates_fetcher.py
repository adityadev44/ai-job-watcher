import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import unittest
from unittest.mock import patch, MagicMock

import src.emirates_fetcher as emirates_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

# postingdate 1748736000000 ms = 2025-06-01 UTC
SAMPLE_JOB = {
    "reqid": "EKE-123456",
    "title": "Senior Quality Manager - Engine Shop",
    "brand": "Emirates Engineering",
    "city": "Dubai",
    "country": "UAE",
    "postingdate": 1748736000000,
    "jobdescription": (
        "<p>Responsible for GE90 and GEnx engine overhaul quality oversight. "
        "Requires Part 145 certification and MRO management experience. "
        "Engine shop visit coordination and workscope planning. "
        "GCAA/EASA airworthiness compliance essential throughout the overhaul process.</p>"
    ),
}

SAMPLE_API_RESPONSE = {"status": "success", "data": [SAMPLE_JOB]}


def _make_mock_response(body, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if isinstance(body, dict) else {}
    r.text = json.dumps(body) if isinstance(body, dict) else str(body)
    return r


# ── fetch_jobs tests ──────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    def setUp(self):
        emirates_fetcher._desc_cache = {}

    @patch("src.emirates_fetcher.requests.Session")
    def test_correct_fields_returned(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(SAMPLE_API_RESPONSE)

        jobs = emirates_fetcher.fetch_jobs()

        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j["id"], "EKE-123456")
        self.assertEqual(j["title"], "Senior Quality Manager - Engine Shop")
        self.assertEqual(j["company"], "Emirates Engineering")
        self.assertEqual(j["location"], "Dubai, UAE")
        self.assertEqual(j["posting_date"], "2025-06-01")
        self.assertIn("jobId=EKE-123456", j["url"])
        self.assertIn("ApplicationMethods", j["url"])
        self.assertNotIn("JobDetails", j["url"])
        self.assertEqual(j["source"], "emirates")

    @patch("src.emirates_fetcher.requests.Session")
    def test_raises_rate_limit_error_on_429(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)

        with self.assertRaises(emirates_fetcher.RateLimitError):
            emirates_fetcher.fetch_jobs()

    @patch("src.emirates_fetcher.requests.Session")
    def test_returns_empty_on_non_200(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        r = MagicMock()
        r.status_code = 503
        mock_session.get.return_value = r

        jobs = emirates_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.emirates_fetcher.requests.Session")
    def test_uses_redirectionurl_when_present(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        job_with_redirect = {**SAMPLE_JOB, "redirectionurl": "https://external.emiratesgroupcareers.com/careersmarketplace/ApplicationMethods?jobId=EKE-123456&source=CareerWebsite"}
        mock_session.get.return_value = _make_mock_response({"status": "success", "data": [job_with_redirect]})

        jobs = emirates_fetcher.fetch_jobs()
        self.assertEqual(jobs[0]["url"], "https://external.emiratesgroupcareers.com/careersmarketplace/ApplicationMethods?jobId=EKE-123456&source=CareerWebsite")

    @patch("src.emirates_fetcher.requests.Session")
    def test_populates_desc_cache(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(SAMPLE_API_RESPONSE)

        emirates_fetcher.fetch_jobs()
        self.assertIn("EKE-123456", emirates_fetcher._desc_cache)


# ── fetch_job_description tests ───────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        emirates_fetcher._desc_cache = {}

    def test_returns_non_empty_description_from_cache(self):
        """Cache populated by fetch_jobs — no HTTP call needed."""
        from bs4 import BeautifulSoup
        html_desc = SAMPLE_JOB["jobdescription"]
        expected_text = BeautifulSoup(html_desc, "html.parser").get_text(separator=" ", strip=True)

        emirates_fetcher._desc_cache["EKE-123456"] = (expected_text, "2025-06-01")

        text, date = emirates_fetcher.fetch_job_description(
            "https://external.emiratesgroupcareers.com/en_US/careersmarketplace/JobDetails?jobId=EKE-123456"
        )
        self.assertGreater(len(text), 100)
        self.assertIn("GE90", text)
        self.assertIn("Part 145", text)
        self.assertEqual(date, "2025-06-01")

    @patch("src.emirates_fetcher.requests.Session")
    def test_raises_rate_limit_error_on_429(self, mock_session_cls):
        """429 during fallback fetch propagates as RateLimitError."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)

        with self.assertRaises(emirates_fetcher.RateLimitError):
            emirates_fetcher.fetch_job_description(
                "https://external.emiratesgroupcareers.com/en_US/careersmarketplace/JobDetails?jobId=EKE-999"
            )

    @patch("src.emirates_fetcher.requests.Session")
    def test_returns_empty_tuple_on_network_failure(self, mock_session_cls):
        """Network error in fallback path returns ("", "") — never raises."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = Exception("connection refused")

        result = emirates_fetcher.fetch_job_description(
            "https://external.emiratesgroupcareers.com/en_US/careersmarketplace/JobDetails?jobId=EKE-999"
        )
        self.assertEqual(result, ("", ""))

    def test_empty_url_returns_empty_tuple(self):
        result = emirates_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))

    def test_url_without_job_id_returns_empty_tuple(self):
        result = emirates_fetcher.fetch_job_description("https://www.emiratesgroupcareers.com/search")
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
