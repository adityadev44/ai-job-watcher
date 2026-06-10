import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.ge_fetcher as ge_fetcher

# ── Fixtures ─────────────────────────────────────────────────────────────────

RAW_JOB_1 = {
    "reqId": "R1001",
    "jobId": "R1001",
    "title": "Engine Overhaul Shop Manager",
    "location": "Evendale, Ohio, United States of America",
    "postedDate": "2026-05-01T00:00:00.000+0000",
    "company": "GE Aerospace",
    "companyName": "GE Aerospace",
}

RAW_JOB_2 = {
    "reqId": "R1002",
    "jobId": "R1002",
    "title": "MRO Quality Director",
    "location": "Singapore",
    "postedDate": "2026-05-02T00:00:00.000+0000",
    "companyName": "GE Aerospace",
}

RAW_JOB_NOCOMPANY = {
    "reqId": "R1003",
    "title": "Production Supervisor",
    "location": "Cincinnati, Ohio",
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
                "description": "<h1>Engine Overhaul Shop Manager</h1><p>Responsible for GE90 and CF6 engine overhaul operations. Requires Part 145 knowledge and MRO experience. Must have FAA/EASA airworthiness background.</p>",
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


# ── _build_job tests ──────────────────────────────────────────────────────────

class TestBuildJob(unittest.TestCase):

    def test_standard_fields(self):
        job = ge_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["id"], "R1001")
        self.assertEqual(job["title"], "Engine Overhaul Shop Manager")
        self.assertEqual(job["location"], "Evendale, Ohio, United States of America")
        self.assertEqual(job["posting_date"], "2026-05-01T00:00:00.000+0000")
        self.assertEqual(job["source"], "ge")

    def test_url_pattern(self):
        job = ge_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["url"], "https://careers.geaerospace.com/global/en/job/R1001")

    def test_company_from_company_field(self):
        job = ge_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["company"], "GE Aerospace")

    def test_company_fallback_to_companyName(self):
        job = ge_fetcher._build_job(RAW_JOB_2)
        self.assertEqual(job["company"], "GE Aerospace")

    def test_company_ultimate_fallback(self):
        job = ge_fetcher._build_job(RAW_JOB_NOCOMPANY)
        self.assertEqual(job["company"], "GE Aerospace")

    def test_uses_reqId_over_jobId(self):
        raw = {"reqId": "R9999", "jobId": "R8888", "title": "Test"}
        job = ge_fetcher._build_job(raw)
        self.assertEqual(job["id"], "R9999")
        self.assertIn("R9999", job["url"])

    def test_missing_reqId_falls_back_to_jobId(self):
        raw = {"jobId": "R7777", "title": "Test"}
        job = ge_fetcher._build_job(raw)
        self.assertEqual(job["id"], "R7777")


# ── fetch_jobs tests ──────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_returns_job_list(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = ge_fetcher.fetch_jobs(max_listings=20)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Engine Overhaul Shop Manager")
        self.assertEqual(jobs[1]["title"], "MRO Quality Director")

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_stops_when_no_results(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_EMPTY
        jobs = ge_fetcher.fetch_jobs(max_listings=200)
        self.assertEqual(jobs, [])
        mock_post.assert_called_once()

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_deduplicates_by_id(self, mock_post, mock_bootstrap):
        duplicate_response = {
            "refineSearch": {
                "status": 200,
                "hits": 2,
                "totalHits": 2,
                "data": {"jobs": [RAW_JOB_1, RAW_JOB_1]},
            }
        }
        mock_post.return_value = duplicate_response
        jobs = ge_fetcher.fetch_jobs(max_listings=20)
        self.assertEqual(len(jobs), 1)

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_respects_max_listings(self, mock_post, mock_bootstrap):
        big_response = {
            "refineSearch": {
                "status": 200,
                "hits": 20,
                "totalHits": 570,
                "data": {"jobs": [{"reqId": f"R{i}", "title": f"Job {i}"} for i in range(20)]},
            }
        }
        # max_listings=5 should only request 1 page with size=5
        small_response = {
            "refineSearch": {
                "status": 200,
                "hits": 5,
                "totalHits": 570,
                "data": {"jobs": [{"reqId": f"R{i}", "title": f"Job {i}"} for i in range(5)]},
            }
        }
        mock_post.return_value = small_response
        jobs = ge_fetcher.fetch_jobs(max_listings=5)
        self.assertLessEqual(len(jobs), 5)

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_job_has_required_keys(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = ge_fetcher.fetch_jobs(max_listings=20)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, jobs[0])

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_stops_when_total_reached(self, mock_post, mock_bootstrap):
        # Server says totalHits=2, so should stop after first page
        mock_post.return_value = REFINE_RESPONSE_PAGE1
        jobs = ge_fetcher.fetch_jobs(max_listings=200)
        self.assertEqual(len(jobs), 2)
        mock_post.assert_called_once()

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_calls_bootstrap(self, mock_post, mock_bootstrap):
        mock_post.return_value = REFINE_RESPONSE_EMPTY
        ge_fetcher.fetch_jobs()
        mock_bootstrap.assert_called_once()

    @patch("src.ge_fetcher._bootstrap")
    @patch("src.ge_fetcher._post_widgets")
    def test_raises_rate_limit_error(self, mock_post, mock_bootstrap):
        mock_post.side_effect = ge_fetcher.RateLimitError("429")
        with self.assertRaises(ge_fetcher.RateLimitError):
            ge_fetcher.fetch_jobs()


# ── fetch_job_description tests ───────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        # Ensure _session is not None so _post_widgets can be called
        ge_fetcher._session = MagicMock()

    def tearDown(self):
        ge_fetcher._session = None

    @patch("src.ge_fetcher._post_widgets")
    def test_returns_tuple(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        result = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.ge_fetcher._post_widgets")
    def test_strips_html_from_description(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, date = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")
        self.assertNotIn("<h1>", text)
        self.assertNotIn("<p>", text)
        self.assertIn("Engine Overhaul Shop Manager", text)

    @patch("src.ge_fetcher._post_widgets")
    def test_returns_posting_date(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, date = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")
        self.assertEqual(date, "2026-05-01T00:00:00.000+0000")

    @patch("src.ge_fetcher._post_widgets")
    def test_extracts_req_id_from_url(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R5009951")
        call_payload = mock_post.call_args[0][0]
        self.assertEqual(call_payload["jobId"], "R5009951")

    @patch("src.ge_fetcher._post_widgets")
    def test_empty_url_returns_empty_tuple(self, mock_post):
        result = ge_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))
        mock_post.assert_not_called()

    @patch("src.ge_fetcher._post_widgets")
    def test_bad_url_returns_empty_tuple(self, mock_post):
        result = ge_fetcher.fetch_job_description("https://example.com/no-job-id-here")
        self.assertEqual(result, ("", ""))
        mock_post.assert_not_called()

    @patch("src.ge_fetcher._post_widgets")
    def test_empty_job_returns_empty_tuple(self, mock_post):
        mock_post.return_value = JOB_DETAIL_EMPTY
        result = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R9999")
        self.assertEqual(result, ("", ""))

    @patch("src.ge_fetcher._post_widgets")
    def test_network_error_returns_empty_tuple(self, mock_post):
        mock_post.side_effect = Exception("connection refused")
        result = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")
        self.assertEqual(result, ("", ""))

    @patch("src.ge_fetcher._post_widgets")
    def test_rate_limit_propagates(self, mock_post):
        mock_post.side_effect = ge_fetcher.RateLimitError("429")
        with self.assertRaises(ge_fetcher.RateLimitError):
            ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")

    @patch("src.ge_fetcher._post_widgets")
    def test_description_contains_domain_keywords(self, mock_post):
        mock_post.return_value = JOB_DETAIL_RESPONSE
        text, _ = ge_fetcher.fetch_job_description("https://careers.geaerospace.com/global/en/job/R1001")
        self.assertIn("GE90", text)
        self.assertIn("MRO", text)
        self.assertIn("Part 145", text)


if __name__ == "__main__":
    unittest.main()
