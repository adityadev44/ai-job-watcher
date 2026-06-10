import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.rtx_fetcher as rtx_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

RAW_JOB_1 = {
    "reqId": "PW-10001",
    "jobId": "PW-10001",
    "title": "Engine Overhaul Shop Manager",
    "location": "East Hartford, Connecticut, United States of America",
    "postedDate": "2026-05-01T00:00:00.000+0000",
    "businessUnit": "Pratt & Whitney",
}

RAW_JOB_2 = {
    "reqId": "PW-10002",
    "jobId": "PW-10002",
    "title": "MRO Quality Director",
    "location": "Singapore",
    "postedDate": "2026-05-10T00:00:00.000+0000",
    "businessUnit": "Collins Aerospace",
}

RAW_JOB_NOCOMPANY = {
    "reqId": "PW-10003",
    "title": "Production Manager, Powerplant",
    "location": "Middletown, Connecticut",
    "postedDate": "2026-04-20T00:00:00.000+0000",
}

REFINE_RESPONSE_PAGE1 = {
    "refineSearch": {
        "status": 200,
        "hits": 2,
        "totalHits": 2,
        "data": {"jobs": [RAW_JOB_1, RAW_JOB_2]},
    }
}

REFINE_RESPONSE_EMPTY = {
    "refineSearch": {
        "status": 200,
        "hits": 0,
        "totalHits": 0,
        "data": {"jobs": []},
    }
}

JOB_DETAIL_RESPONSE = {
    "jobDetail": {
        "status": 200,
        "hits": 1,
        "totalHits": 1,
        "data": {
            "job": {
                "description": (
                    "<h1>Engine Overhaul Shop Manager</h1>"
                    "<p>Responsible for PW4000 and GTF engine overhaul operations at our Eagle Services facility. "
                    "Requires Part 145 knowledge and MRO leadership experience. "
                    "Must have FAA/EASA airworthiness background and shop visit planning expertise.</p>"
                ),
                "postedDate": "2026-05-01T00:00:00.000+0000",
                "title": "Engine Overhaul Shop Manager",
            }
        },
    }
}

JOB_DETAIL_EMPTY = {
    "jobDetail": {
        "status": 200,
        "hits": 0,
        "totalHits": 0,
        "data": {},
    }
}


# ── _build_job ────────────────────────────────────────────────────────────────

class TestBuildJob(unittest.TestCase):

    def test_standard_fields(self):
        job = rtx_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["id"], "PW-10001")
        self.assertEqual(job["title"], "Engine Overhaul Shop Manager")
        self.assertEqual(job["location"], "East Hartford, Connecticut, United States of America")
        self.assertEqual(job["posting_date"], "2026-05-01T00:00:00.000+0000")
        self.assertEqual(job["source"], "rtx")

    def test_url_is_browseable(self):
        job = rtx_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["url"], "https://careers.rtx.com/global/en/job/PW-10001")
        self.assertIn("/global/en/job/", job["url"])
        self.assertNotIn("/widgets", job["url"])
        self.assertNotIn("/api/", job["url"])

    def test_company_from_businessUnit_field(self):
        job = rtx_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["company"], "Pratt & Whitney")

    def test_company_from_businessUnit_collins(self):
        job = rtx_fetcher._build_job(RAW_JOB_2)
        self.assertEqual(job["company"], "Collins Aerospace")

    def test_company_ultimate_fallback_is_rtx(self):
        job = rtx_fetcher._build_job(RAW_JOB_NOCOMPANY)
        self.assertEqual(job["company"], "RTX")

    def test_uses_reqId_over_jobId(self):
        raw = {"reqId": "PW-9999", "jobId": "PW-8888", "title": "Test"}
        job = rtx_fetcher._build_job(raw)
        self.assertEqual(job["id"], "PW-9999")
        self.assertIn("PW-9999", job["url"])

    def test_missing_reqId_falls_back_to_jobId(self):
        raw = {"jobId": "PW-7777", "title": "Test"}
        job = rtx_fetcher._build_job(raw)
        self.assertEqual(job["id"], "PW-7777")

    def test_posting_date_not_empty(self):
        job = rtx_fetcher._build_job(RAW_JOB_1)
        self.assertTrue(job["posting_date"])

    def test_posting_date_is_iso_format(self):
        job = rtx_fetcher._build_job(RAW_JOB_1)
        # Must be ISO 8601 or YYYY-MM-DD — not a raw integer timestamp
        self.assertIsInstance(job["posting_date"], str)
        self.assertRegex(job["posting_date"], r"^\d{4}-\d{2}-\d{2}")


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_returns_job_list(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = rtx_fetcher.fetch_jobs(max_listings=20)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Engine Overhaul Shop Manager")
        self.assertEqual(jobs[1]["title"], "MRO Quality Director")

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_stops_when_no_results(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_EMPTY
        jobs = rtx_fetcher.fetch_jobs(max_listings=200)
        self.assertEqual(jobs, [])
        mock_post.assert_called_once()

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_deduplicates_by_id(self, mock_post, mock_bootstrap):
        dup_response = {
            "refineSearch": {
                "status": 200,
                "hits": 2,
                "totalHits": 2,
                "data": {"jobs": [RAW_JOB_1, RAW_JOB_1]},
            }
        }
        mock_post.return_value = dup_response
        jobs = rtx_fetcher.fetch_jobs(max_listings=20)
        self.assertEqual(len(jobs), 1)

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_stops_when_total_reached(self, mock_post, mock_bootstrap):
        # fetch_jobs makes a probe call (size=1) to get totalHits, then a data call — 2 total.
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = rtx_fetcher.fetch_jobs(max_listings=200)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(mock_post.call_count, 2)

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_job_has_required_keys(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = rtx_fetcher.fetch_jobs(max_listings=20)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, jobs[0])

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_calls_bootstrap(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_EMPTY
        rtx_fetcher.fetch_jobs()
        mock_bootstrap.assert_called_once()

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_raises_rate_limit_error(self, mock_post, mock_bootstrap):
        mock_post.side_effect = rtx_fetcher.RateLimitError("429")
        with self.assertRaises(rtx_fetcher.RateLimitError):
            rtx_fetcher.fetch_jobs()

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_source_is_rtx(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = rtx_fetcher.fetch_jobs(max_listings=20)
        self.assertTrue(all(j["source"] == "rtx" for j in jobs))

    @patch("src.rtx_fetcher._bootstrap")
    @patch("src.rtx_fetcher._post_widgets")
    def test_url_is_not_backend_endpoint(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = rtx_fetcher.fetch_jobs(max_listings=20)
        for job in jobs:
            self.assertNotIn("/widgets", job["url"])
            self.assertIn("careers.rtx.com/global/en/job/", job["url"])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        rtx_fetcher._session = MagicMock()

    def tearDown(self):
        rtx_fetcher._session = None

    @patch("src.rtx_fetcher._post_widgets")
    def test_returns_tuple(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        result = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.rtx_fetcher._post_widgets")
    def test_strips_html_from_description(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, date = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")
        self.assertNotIn("<h1>", text)
        self.assertNotIn("<p>", text)
        self.assertIn("Engine Overhaul Shop Manager", text)

    @patch("src.rtx_fetcher._post_widgets")
    def test_returns_posting_date(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, date = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")
        self.assertEqual(date, "2026-05-01T00:00:00.000+0000")

    @patch("src.rtx_fetcher._post_widgets")
    def test_extracts_req_id_from_url(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-99999")
        call_payload = mock_post.call_args[0][0]
        self.assertEqual(call_payload["jobId"], "PW-99999")

    @patch("src.rtx_fetcher._post_widgets")
    def test_empty_url_returns_empty_tuple(self, mock_post):
        result = rtx_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))
        mock_post.assert_not_called()

    @patch("src.rtx_fetcher._post_widgets")
    def test_bad_url_returns_empty_tuple(self, mock_post):
        result = rtx_fetcher.fetch_job_description("https://example.com/no-job-id-here")
        self.assertEqual(result, ("", ""))
        mock_post.assert_not_called()

    @patch("src.rtx_fetcher._post_widgets")
    def test_empty_job_returns_empty_tuple(self, mock_post):
        mock_post.return_value = JOB_DETAIL_EMPTY
        result = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-9999")
        self.assertEqual(result, ("", ""))

    @patch("src.rtx_fetcher._post_widgets")
    def test_network_error_returns_empty_tuple(self, mock_post):
        mock_post.side_effect = Exception("connection refused")
        result = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")
        self.assertEqual(result, ("", ""))

    @patch("src.rtx_fetcher._post_widgets")
    def test_rate_limit_propagates(self, mock_post):
        mock_post.side_effect = rtx_fetcher.RateLimitError("429")
        with self.assertRaises(rtx_fetcher.RateLimitError):
            rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")

    @patch("src.rtx_fetcher._post_widgets")
    def test_description_contains_domain_keywords(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, _ = rtx_fetcher.fetch_job_description("https://careers.rtx.com/global/en/job/PW-10001")
        self.assertIn("PW4000", text)
        self.assertIn("MRO", text)
        self.assertIn("Part 145", text)


if __name__ == "__main__":
    unittest.main()
