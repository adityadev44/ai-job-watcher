import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch

import src.standardaero_fetcher as standardaero_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

RAW_JOB_1 = {
    "Id": 8983,
    "Title": "Customer Service Director, MRO",
    "PrimaryLocation": "Augusta, GA, United States",
    "PostedDate": "2026-06-05",
}

RAW_JOB_2 = {
    "Id": 9145,
    "Title": "Program Manager",
    "PrimaryLocation": "Gonesse, Ile-de-France, France",
    "PostedDate": "2026-04-28",
}

LIST_RESPONSE_PAGE1 = {
    "items": [
        {
            "TotalJobsCount": 2,
            "requisitionList": [RAW_JOB_1, RAW_JOB_2],
        }
    ]
}

LIST_RESPONSE_EMPTY = {"items": [{"TotalJobsCount": 0, "requisitionList": []}]}

DETAIL_RESPONSE = {
    "items": [
        {
            "ExternalDescriptionStr": (
                "<p>Lead the MRO engine overhaul shop, responsible for CFM56 and GEnx "
                "test cell operations, borescope inspection, and workscope planning. "
                "Requires Part 145 and CAMO airworthiness management experience, plus "
                "deep knowledge of engine shop visit processes and LLP tracking.</p>"
            ),
            "ExternalResponsibilitiesStr": "",
            "ExternalQualificationsStr": "",
            "ExternalPostedStartDate": "2026-06-05T00:00:00.000+0000",
        }
    ]
}

DETAIL_RESPONSE_EMPTY = {"items": [{"ExternalDescriptionStr": "", "ExternalResponsibilitiesStr": "", "ExternalQualificationsStr": ""}]}


# ── _build_job ────────────────────────────────────────────────────────────────

class TestBuildJob(unittest.TestCase):

    def test_standard_fields(self):
        job = standardaero_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(job["id"], "8983")
        self.assertEqual(job["title"], "Customer Service Director, MRO")
        self.assertEqual(job["location"], "Augusta, GA, United States")
        self.assertEqual(job["posting_date"], "2026-06-05")
        self.assertEqual(job["company"], "StandardAero")
        self.assertEqual(job["source"], "standardaero")

    def test_url_is_browseable(self):
        job = standardaero_fetcher._build_job(RAW_JOB_1)
        self.assertEqual(
            job["url"],
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983",
        )
        self.assertIn("/hcmUI/CandidateExperience/", job["url"])
        self.assertNotIn("/hcmRestApi/", job["url"])

    def test_posting_date_is_yyyy_mm_dd(self):
        job = standardaero_fetcher._build_job(RAW_JOB_1)
        self.assertRegex(job["posting_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_job_has_required_keys(self):
        job = standardaero_fetcher._build_job(RAW_JOB_1)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, job)


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.standardaero_fetcher._get")
    def test_returns_job_list(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_PAGE1
        jobs = standardaero_fetcher.fetch_jobs(max_listings=20, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Customer Service Director, MRO")
        self.assertEqual(jobs[1]["title"], "Program Manager")

    @patch("src.standardaero_fetcher._get")
    def test_stops_when_no_results(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_EMPTY
        jobs = standardaero_fetcher.fetch_jobs(max_listings=300, inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.standardaero_fetcher._get")
    def test_deduplicates_by_id(self, mock_get):
        dup_response = {
            "items": [{"TotalJobsCount": 2, "requisitionList": [RAW_JOB_1, RAW_JOB_1]}]
        }
        mock_get.return_value = dup_response
        jobs = standardaero_fetcher.fetch_jobs(max_listings=20, inter_page_delay=0)
        self.assertEqual(len(jobs), 1)

    @patch("src.standardaero_fetcher._get")
    def test_pagination_uses_offset_in_finder(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_EMPTY
        standardaero_fetcher.fetch_jobs(max_listings=300, inter_page_delay=0)
        called_url = mock_get.call_args[0][0]
        self.assertIn("offset=0", called_url)
        self.assertIn("finder=findReqs", called_url)

    @patch("src.standardaero_fetcher._get")
    def test_raises_rate_limit_error(self, mock_get):
        mock_get.side_effect = standardaero_fetcher.RateLimitError("429")
        with self.assertRaises(standardaero_fetcher.RateLimitError):
            standardaero_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.standardaero_fetcher._get")
    def test_source_is_standardaero(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_PAGE1
        jobs = standardaero_fetcher.fetch_jobs(max_listings=20, inter_page_delay=0)
        self.assertTrue(all(j["source"] == "standardaero" for j in jobs))

    @patch("src.standardaero_fetcher._get")
    def test_fetch_failure_breaks_loop_without_raising(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        jobs = standardaero_fetcher.fetch_jobs(max_listings=300, inter_page_delay=0)
        self.assertEqual(jobs, [])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.standardaero_fetcher._get")
    def test_returns_tuple(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        result = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.standardaero_fetcher._get")
    def test_description_non_empty_and_html_stripped(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        text, date = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertGreater(len(text), 100)
        self.assertNotIn("<p>", text)
        self.assertIn("CFM56", text)
        self.assertIn("CAMO", text)

    @patch("src.standardaero_fetcher._get")
    def test_returns_posting_date(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        text, date = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertEqual(date, "2026-06-05")

    @patch("src.standardaero_fetcher._get")
    def test_extracts_job_id_from_url(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/99999"
        )
        called_url = mock_get.call_args[0][0]
        self.assertIn('Id="99999"', called_url)

    @patch("src.standardaero_fetcher._get")
    def test_empty_url_returns_empty_tuple(self, mock_get):
        result = standardaero_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))
        mock_get.assert_not_called()

    @patch("src.standardaero_fetcher._get")
    def test_bad_url_returns_empty_tuple(self, mock_get):
        result = standardaero_fetcher.fetch_job_description("https://example.com/no-job-id-here")
        self.assertEqual(result, ("", ""))
        mock_get.assert_not_called()

    @patch("src.standardaero_fetcher._get")
    def test_empty_detail_returns_empty_tuple(self, mock_get):
        mock_get.return_value = {"items": []}
        result = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.standardaero_fetcher._get")
    def test_empty_description_fields_return_empty_tuple(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE_EMPTY
        result = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.standardaero_fetcher._get")
    def test_network_error_returns_empty_tuple(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        result = standardaero_fetcher.fetch_job_description(
            "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.standardaero_fetcher._get")
    def test_rate_limit_propagates(self, mock_get):
        mock_get.side_effect = standardaero_fetcher.RateLimitError("429")
        with self.assertRaises(standardaero_fetcher.RateLimitError):
            standardaero_fetcher.fetch_job_description(
                "https://cva.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/8983"
            )


if __name__ == "__main__":
    unittest.main()
