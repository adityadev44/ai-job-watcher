import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.sia_fetcher as sia_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

LISTING_PAGE_HTML = """
<html><body>
<div aria-label="Results 1 to 10 of 11">Results 1 to 10 of 11</div>
<table>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/siaec/job/Component-Services-CRU-CMC-Supervisor/54821144/">
    Component Services CRU &amp; CMC Supervisor
  </a></td>
  <td><span class="jobLocation">SG</span></td>
  <td><span class="jobDate">6 Jun 2026</span></td>
</tr>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/siaec/job/Technical-Planner-Training-Programme/46165344/">
    Technical Planner Training Programme
  </a></td>
  <td><span class="jobLocation">SG</span></td>
  <td><span class="jobDate">31 May 2026</span></td>
</tr>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/siaec/job/Trainee-Technician-Malaysia/55123456/">
    Trainee Technician - Malaysia
  </a></td>
  <td><span class="jobLocation">MY</span></td>
  <td><span class="jobDate">19 May 2026</span></td>
</tr>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/siaec/job/Quality-Manager-Engine-Shop/99887766/">
    Quality Manager, Engine Shop
  </a></td>
  <td><span class="jobLocation">SG</span></td>
  <td><span class="jobDate">1 Jun 2026</span></td>
</tr>
</table>
</body></html>
"""

LISTING_PAGE_NO_TOTAL = """
<html><body>
<table>
<tr class="data-row">
  <td><a class="jobTitle-link" href="/siaec/job/Some-Job/12345678/">Some Job</a></td>
  <td><span class="jobLocation">SG</span></td>
  <td><span class="jobDate">10 Jun 2026</span></td>
</tr>
</table>
</body></html>
"""

LISTING_PAGE_EMPTY = "<html><body><table></table></body></html>"

DETAIL_PAGE_HTML = """
<html><body>
<span class="jobdescription">
Lead and oversee the tracking and expediting of aircraft component returns from local and
overseas airline customers to ensure timely recovery of assets. Manage the end-to-end
component return process, including loan and exchange order closures, and ensure timely
return of parts to vendors to prevent late return penalties. Knowledge of CFM56 and V2500
engine components and Part 145 MRO procedures required.
</span>
</body></html>
"""

DETAIL_PAGE_NO_DESC = "<html><body><p>No description available.</p></body></html>"


def _make_mock_response(html, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.text = html
    return mock


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate(unittest.TestCase):

    def test_normal_date(self):
        self.assertEqual(sia_fetcher._parse_date("6 Jun 2026"), "2026-06-06")

    def test_double_digit_day(self):
        self.assertEqual(sia_fetcher._parse_date("11 Jun 2026"), "2026-06-11")

    def test_single_digit_day(self):
        self.assertEqual(sia_fetcher._parse_date("1 Jan 2026"), "2026-01-01")

    def test_empty_string(self):
        self.assertEqual(sia_fetcher._parse_date(""), "")

    def test_none(self):
        self.assertEqual(sia_fetcher._parse_date(None), "")

    def test_bad_format(self):
        self.assertEqual(sia_fetcher._parse_date("2026-06-01"), "")


# ── _clean_location ───────────────────────────────────────────────────────────

class TestCleanLocation(unittest.TestCase):

    def test_sg_maps_to_singapore(self):
        self.assertEqual(sia_fetcher._clean_location("SG"), "Singapore")

    def test_my_maps_to_malaysia(self):
        self.assertEqual(sia_fetcher._clean_location("MY"), "Malaysia")

    def test_cn_maps_to_china(self):
        self.assertEqual(sia_fetcher._clean_location("CN"), "China")

    def test_kr_maps_to_south_korea(self):
        self.assertEqual(sia_fetcher._clean_location("KR"), "South Korea")

    def test_lowercase_sg(self):
        self.assertEqual(sia_fetcher._clean_location("sg"), "Singapore")

    def test_empty_defaults_to_singapore(self):
        self.assertEqual(sia_fetcher._clean_location(""), "Singapore")

    def test_none_defaults_to_singapore(self):
        self.assertEqual(sia_fetcher._clean_location(None), "Singapore")


# ── _get_total_jobs ───────────────────────────────────────────────────────────

class TestGetTotalJobs(unittest.TestCase):

    def test_parses_count(self):
        self.assertEqual(sia_fetcher._get_total_jobs(LISTING_PAGE_HTML), 11)

    def test_returns_none_when_absent(self):
        self.assertIsNone(sia_fetcher._get_total_jobs(LISTING_PAGE_EMPTY))


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def _jobs(self):
        return sia_fetcher._parse_listing_page(LISTING_PAGE_HTML)

    def test_job_count(self):
        self.assertEqual(len(self._jobs()), 4)

    def test_title(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["title"], "Component Services CRU & CMC Supervisor")

    def test_id_extracted(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["id"], "54821144")

    def test_url_is_absolute(self):
        jobs = self._jobs()
        self.assertTrue(jobs[0]["url"].startswith("https://careers.singaporeair.com/siaec/job/"))

    def test_url_not_api_endpoint(self):
        for job in self._jobs():
            self.assertNotIn("api", job["url"])
            self.assertNotIn("successfactors.com", job["url"])

    def test_location_sg_mapped(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["location"], "Singapore")

    def test_location_my_mapped(self):
        jobs = self._jobs()
        # Third job has MY location
        self.assertEqual(jobs[2]["location"], "Malaysia")

    def test_posting_date_format(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["posting_date"], "2026-06-06")

    def test_company(self):
        for job in self._jobs():
            self.assertEqual(job["company"], "SIA Engineering")

    def test_source(self):
        for job in self._jobs():
            self.assertEqual(job["source"], "sia")

    def test_required_keys(self):
        for job in self._jobs():
            for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)

    def test_empty_page_returns_empty_list(self):
        self.assertEqual(sia_fetcher._parse_listing_page(LISTING_PAGE_EMPTY), [])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.sia_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(LISTING_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = sia_fetcher.fetch_jobs()
        self.assertEqual(len(jobs), 4)

    @patch("src.sia_fetcher.requests.Session")
    def test_deduplicates_repeated_ids(self, MockSession):
        # Two identical pages returned — second page should add no new jobs
        mock_resp = _make_mock_response(LISTING_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = sia_fetcher.fetch_jobs()
        ids = [j["id"] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))

    @patch("src.sia_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(sia_fetcher.RateLimitError):
            sia_fetcher.fetch_jobs()

    @patch("src.sia_fetcher.requests.Session")
    def test_network_error_returns_partial(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = sia_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.sia_fetcher.requests.Session")
    def test_empty_page_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_PAGE_EMPTY)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = sia_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.sia_fetcher.requests.Session")
    def test_all_jobs_have_required_keys(self, MockSession):
        mock_resp = _make_mock_response(LISTING_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = sia_fetcher.fetch_jobs()
        for job in jobs:
            for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.sia_fetcher.requests.Session")
    def test_returns_tuple(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Component-Services-CRU/54821144/"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.sia_fetcher.requests.Session")
    def test_description_text_returned(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Component-Services-CRU/54821144/"
        )
        self.assertIn("CFM56", text)
        self.assertIn("Part 145", text)
        self.assertIn("MRO", text)

    @patch("src.sia_fetcher.requests.Session")
    def test_date_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        _, date = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Component-Services-CRU/54821144/"
        )
        self.assertEqual(date, "")

    @patch("src.sia_fetcher.requests.Session")
    def test_no_desc_span_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_NO_DESC)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Some-Job/12345678/"
        )
        self.assertEqual(text, "")

    def test_empty_url_returns_empty(self):
        self.assertEqual(sia_fetcher.fetch_job_description(""), ("", ""))

    def test_url_without_job_returns_empty(self):
        self.assertEqual(
            sia_fetcher.fetch_job_description("https://careers.singaporeair.com/siaec/"),
            ("", "")
        )

    @patch("src.sia_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        result = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Some-Job/12345678/"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.sia_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(sia_fetcher.RateLimitError):
            sia_fetcher.fetch_job_description(
                "https://careers.singaporeair.com/siaec/job/Some-Job/12345678/"
            )

    @patch("src.sia_fetcher.requests.Session")
    def test_404_returns_empty(self, MockSession):
        mock_resp = _make_mock_response("Not Found", status=404)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = sia_fetcher.fetch_job_description(
            "https://careers.singaporeair.com/siaec/job/Some-Job/12345678/"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
