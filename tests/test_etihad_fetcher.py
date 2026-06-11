import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.etihad_fetcher as etihad_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

RAW_JOB_MRO = {
    "Id": "501",
    "Title": "Manager - Engine Overhaul",
    "PostedDate": "2026-06-10",
    "PrimaryLocation": "Abu Dhabi, United Arab Emirates",
    "PostingEndDate": None,
}

RAW_JOB_ADMIN = {
    "Id": "812",
    "Title": "Security Administrator",
    "PostedDate": "2026-06-08",
    "PrimaryLocation": "Abu Dhabi, United Arab Emirates",
    "PostingEndDate": None,
}

RAW_JOB_NO_ID = {
    "Title": "Quality Manager",
    "PostedDate": "2026-06-01",
    "PrimaryLocation": "Abu Dhabi, United Arab Emirates",
}

LIST_RESPONSE_TWO = {
    "items": [{
        "TotalJobsCount": 2,
        "requisitionList": [RAW_JOB_MRO, RAW_JOB_ADMIN],
    }],
    "count": 1,
    "hasMore": False,
}

LIST_RESPONSE_EMPTY = {
    "items": [{"TotalJobsCount": 0, "requisitionList": []}],
    "count": 1,
    "hasMore": False,
}

LIST_NO_ITEMS = {"items": [], "count": 0, "hasMore": False}

DETAIL_RESPONSE = {
    "items": [{
        "Id": "501",
        "Title": "Manager - Engine Overhaul",
        "PostedDate": "2026-06-10",
        "ExternalPostedStartDate": "2026-06-10T09:00:00+00:00",
        "ExternalResponsibilitiesStr": (
            "<p>Lead the GE90 and CFM56 engine overhaul programme at our Abu Dhabi MRO facility. "
            "Responsible for shop visit planning, workscope management, and Part 145 compliance. "
            "Manage a team of licensed AMEs and ensure GCAA airworthiness standards are maintained.</p>"
        ),
        "ExternalQualificationsStr": (
            "<p>10+ years in engine MRO management. EASA Part 145 knowledge required. "
            "Experience with borescope inspection and test cell operations preferred.</p>"
        ),
        "ExternalDescriptionStr": "",
        "PrimaryLocation": "Abu Dhabi, United Arab Emirates",
    }],
    "count": 1,
}

DETAIL_RESPONSE_EMPTY_DESC = {
    "items": [{
        "Id": "812",
        "PostedDate": "2026-06-08",
        "ExternalPostedStartDate": "2026-06-08T12:55:10+00:00",
        "ExternalResponsibilitiesStr": "",
        "ExternalQualificationsStr": "",
        "ExternalDescriptionStr": "",
    }],
    "count": 1,
}

DETAIL_RESPONSE_NO_ITEMS = {"items": [], "count": 0}


# ── _build_job ────────────────────────────────────────────────────────────────

class TestBuildJob(unittest.TestCase):

    def test_id(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["id"], "501")

    def test_title(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["title"], "Manager - Engine Overhaul")

    def test_location(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["location"], "Abu Dhabi, United Arab Emirates")

    def test_posting_date_format(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["posting_date"], "2026-06-10")

    def test_url_format(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["url"], "https://careers.etihadengineering.com/en/sites/careers/job/501")

    def test_url_is_browseable(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertIn("careers.etihadengineering.com", job["url"])
        self.assertIn("/en/sites/careers/job/", job["url"])
        self.assertNotIn("hcmRestApi", job["url"])
        self.assertNotIn("fa.ocs.oraclecloud.com", job["url"])

    def test_company(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["company"], "Etihad Engineering")

    def test_source(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        self.assertEqual(job["source"], "etihad")

    def test_required_keys(self):
        job = etihad_fetcher._build_job(RAW_JOB_MRO)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, job)


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    def setUp(self):
        etihad_fetcher._session = None

    @patch("src.etihad_fetcher._get")
    def test_returns_job_list(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_TWO
        jobs = etihad_fetcher.fetch_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Manager - Engine Overhaul")

    @patch("src.etihad_fetcher._get")
    def test_returns_empty_on_no_requisitions(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_EMPTY
        jobs = etihad_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.etihad_fetcher._get")
    def test_returns_empty_on_no_items(self, mock_get):
        mock_get.return_value = LIST_NO_ITEMS
        jobs = etihad_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.etihad_fetcher._get")
    def test_skips_jobs_without_id(self, mock_get):
        resp = {
            "items": [{"TotalJobsCount": 2, "requisitionList": [RAW_JOB_MRO, RAW_JOB_NO_ID]}],
        }
        mock_get.return_value = resp
        jobs = etihad_fetcher.fetch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "501")

    @patch("src.etihad_fetcher._get")
    def test_fetch_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        jobs = etihad_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.etihad_fetcher._get")
    def test_rate_limit_propagates(self, mock_get):
        mock_get.side_effect = etihad_fetcher.RateLimitError("429")
        with self.assertRaises(etihad_fetcher.RateLimitError):
            etihad_fetcher.fetch_jobs()

    @patch("src.etihad_fetcher._get")
    def test_all_jobs_have_required_keys(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_TWO
        jobs = etihad_fetcher.fetch_jobs()
        for job in jobs:
            for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
                self.assertIn(key, job)

    @patch("src.etihad_fetcher._get")
    def test_source_is_etihad(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_TWO
        jobs = etihad_fetcher.fetch_jobs()
        self.assertTrue(all(j["source"] == "etihad" for j in jobs))

    @patch("src.etihad_fetcher._get")
    def test_company_is_etihad_engineering(self, mock_get):
        mock_get.return_value = LIST_RESPONSE_TWO
        jobs = etihad_fetcher.fetch_jobs()
        self.assertTrue(all(j["company"] == "Etihad Engineering" for j in jobs))


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        etihad_fetcher._session = None

    @patch("src.etihad_fetcher._get")
    def test_returns_tuple(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        result = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.etihad_fetcher._get")
    def test_strips_html(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        text, _ = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        self.assertNotIn("<p>", text)
        self.assertNotIn("<ul>", text)
        self.assertIn("GE90", text)

    @patch("src.etihad_fetcher._get")
    def test_description_contains_mro_terms(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        text, _ = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        self.assertIn("Part 145", text)
        self.assertIn("MRO", text)
        self.assertIn("CFM56", text)

    @patch("src.etihad_fetcher._get")
    def test_returns_posting_date(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        _, date = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        self.assertEqual(date, "2026-06-10")

    @patch("src.etihad_fetcher._get")
    def test_empty_description_returns_empty_tuple(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE_EMPTY_DESC
        result = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/812"
        )
        self.assertEqual(result[0], "")

    @patch("src.etihad_fetcher._get")
    def test_no_items_returns_empty_tuple(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE_NO_ITEMS
        result = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/812"
        )
        self.assertEqual(result, ("", ""))

    def test_empty_url_returns_empty_tuple(self):
        result = etihad_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))

    def test_bad_url_returns_empty_tuple(self):
        result = etihad_fetcher.fetch_job_description("https://careers.etihadengineering.com/")
        self.assertEqual(result, ("", ""))

    @patch("src.etihad_fetcher._get")
    def test_network_error_returns_empty_tuple(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        result = etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.etihad_fetcher._get")
    def test_rate_limit_propagates(self, mock_get):
        mock_get.side_effect = etihad_fetcher.RateLimitError("429")
        with self.assertRaises(etihad_fetcher.RateLimitError):
            etihad_fetcher.fetch_job_description(
                "https://careers.etihadengineering.com/en/sites/careers/job/501"
            )

    @patch("src.etihad_fetcher._get")
    def test_extracts_job_id_from_url(self, mock_get):
        mock_get.return_value = DETAIL_RESPONSE
        etihad_fetcher.fetch_job_description(
            "https://careers.etihadengineering.com/en/sites/careers/job/501"
        )
        called_url = mock_get.call_args[0][0]
        self.assertIn("501", called_url)
        self.assertIn("recruitingCEJobRequisitionDetails", called_url)


if __name__ == "__main__":
    unittest.main()
