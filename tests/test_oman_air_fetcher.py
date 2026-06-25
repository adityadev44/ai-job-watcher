import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.oman_air_fetcher as oman_air_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

LISTING_PAGE_NO_VACANCIES = """
<html><body>
<div class="vacancies_head">Vacancy Search : [All Job Types,All Main Categories,All Sub-Categories,All Locations]</div>
<div class="ad_search"><div class="text1">No vacancies found</div></div>
</body></html>
"""

LISTING_PAGE_WITH_JOBS = """
<html><body>
<div class="vacancies_head">Vacancy Search : [All Job Types]</div>
<table class="list">
<tbody>
<tr class="odd">
  <td><a href="/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001">Head of Engine Maintenance</a></td>
  <td>Engineering</td>
  <td>Muscat</td>
</tr>
<tr class="even">
  <td><a href="/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15002">Cabin Crew</a></td>
  <td>Flight Operations</td>
  <td>Muscat</td>
</tr>
<tr class="odd">
  <td><a href="/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001">Head of Engine Maintenance</a></td>
  <td>Engineering</td>
  <td>Muscat</td>
</tr>
</tbody>
</table>
</body></html>
"""

DETAIL_PAGE_HTML = """
<html><body>
<nav>Book Check-in Manage Booking</nav>
<div id="outer_div">
<div class="middle">
Lead the engine maintenance team responsible for CFM56 and Trent engine
overhaul, test cell operations, borescope inspection and shop visit
workscope planning. EASA Part 145 and CAMO compliance required.
</div>
</div>
<footer>About Oman Air Useful links Connect with us</footer>
</body></html>
"""

DETAIL_PAGE_ERROR = """
<html><body><span>Internal Server Error</span></body></html>
"""


def _make_mock_response(text, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    return mock


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def test_no_vacancies_returns_empty(self):
        self.assertEqual(oman_air_fetcher._parse_listing_page(LISTING_PAGE_NO_VACANCIES), [])

    def test_jobs_extracted(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        self.assertEqual(len(jobs), 2)  # third row is a duplicate vacancyId

    def test_title_extracted(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        self.assertEqual(jobs[0]["title"], "Head of Engine Maintenance")

    def test_id_extracted(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        self.assertEqual(jobs[0]["id"], "15001")

    def test_url_uses_vacancy_id(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        self.assertEqual(
            jobs[0]["url"],
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001",
        )

    def test_company_is_oman_air(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        for job in jobs:
            self.assertEqual(job["company"], "Oman Air")

    def test_required_keys(self):
        jobs = oman_air_fetcher._parse_listing_page(LISTING_PAGE_WITH_JOBS)
        for job in jobs:
            for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)

    def test_empty_page_returns_empty(self):
        self.assertEqual(oman_air_fetcher._parse_listing_page("<html><body></body></html>"), [])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.oman_air_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(LISTING_PAGE_WITH_JOBS)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = oman_air_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(len(jobs), 2)

    @patch("src.oman_air_fetcher.requests.Session")
    def test_no_vacancies_returns_empty_list(self, MockSession):
        mock_resp = _make_mock_response(LISTING_PAGE_NO_VACANCIES)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = oman_air_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.oman_air_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(oman_air_fetcher.RateLimitError):
            oman_air_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.oman_air_fetcher.requests.Session")
    def test_network_error_returns_partial(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = oman_air_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.oman_air_fetcher.requests.Session")
    def test_returns_tuple(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.oman_air_fetcher.requests.Session")
    def test_description_text_returned(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
        )
        self.assertIn("CFM56", text)
        self.assertIn("CAMO", text)

    @patch("src.oman_air_fetcher.requests.Session")
    def test_nav_and_footer_stripped(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
        )
        self.assertNotIn("Manage Booking", text)
        self.assertNotIn("Connect with us", text)

    @patch("src.oman_air_fetcher.requests.Session")
    def test_internal_server_error_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_PAGE_ERROR)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=99999"
        )
        self.assertEqual(result, ("", ""))

    def test_empty_url_returns_empty(self):
        self.assertEqual(oman_air_fetcher.fetch_job_description(""), ("", ""))

    def test_url_without_vacancy_id_returns_empty(self):
        self.assertEqual(
            oman_air_fetcher.fetch_job_description("https://services.omanair.com/erecruit/guest/"),
            ("", "")
        )

    @patch("src.oman_air_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        result = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.oman_air_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(oman_air_fetcher.RateLimitError):
            oman_air_fetcher.fetch_job_description(
                "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
            )

    @patch("src.oman_air_fetcher.requests.Session")
    def test_404_returns_empty(self, MockSession):
        mock_resp = _make_mock_response("Not Found", status=404)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = oman_air_fetcher.fetch_job_description(
            "https://services.omanair.com/erecruit/guest/rmJobDetailedDisplay.do?vacancyId=15001"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
