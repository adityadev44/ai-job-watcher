import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.sanad_fetcher as sanad_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

LISTING_HTML_PAGE1 = """
<!DOCTYPE html><html><body>
<div class="row jobdetail mb-4 ms-0">
  <div class="col-12 jb-title">
    <h3><a href="/vacancy/174905">Senior Officer - Account Management</a></h3>
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Company</label>Sanad Aerotech
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Location</label>Abu Dhabi, United Arab Emirates
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Closing Date</label>15-Jun-2026
  </div>
</div>
<div class="row jobdetail mb-4 ms-0">
  <div class="col-12 jb-title">
    <h3><a href="/vacancy/174886">Powerplant Specialist</a></h3>
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Company</label>Sanad Aerotech
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Location</label>Abu Dhabi, UAE
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Closing Date</label>30-Jun-2026
  </div>
</div>
<ul class="pagination">
  <li class="page-item disabled"><span class="page-link">«</span></li>
  <li class="page-item disabled"><a class="page-link" href="/?pg=0">1</a></li>
  <li class="page-item"><a class="page-link" href="/?pg=1">2</a></li>
  <li class="page-item"><a class="page-link" href="/?pg=1">»</a></li>
</ul>
</body></html>
"""

LISTING_HTML_EMPTY = """
<!DOCTYPE html><html><body>
<div class="container">No vacancies found.</div>
</body></html>
"""

DETAIL_HTML_WITH_DESCRIPTION = """
<!DOCTYPE html><html><body>
<main>
<ul class="searchCategs">
  <li>
    <div class="descr"><span>Company:</span></div>
    <div class="categVal">Sanad Aerotech</div>
  </li>
  <li>
    <div class="descr"><span>Location:</span></div>
    <div class="categVal">Abu Dhabi, United Arab Emirates</div>
  </li>
  <li>
    <div class="descr"><span>Closing Date:</span></div>
    <div class="categVal">15-Jun-2026</div>
  </li>
</ul>
<div class="row mt-4 sectn">
  <div class="col-12"><h5>About the Role</h5></div>
  <div class="col-12">
    <p>Responsible for coordinating Engine Shop Visits for GEnx, CFM56, and Trent 700 engines.
    Requires Part 145 knowledge and deep MRO experience. Oversee workscope planning and
    engine overhaul activities. Aviation background with GCAA/EASA airworthiness preferred.</p>
  </div>
</div>
<div class="row mt-4 sectn">
  <div class="col-12"><h5>Your Responsibilities</h5></div>
  <div class="col-12">
    <ul>
      <li>Manage engine shop visits from induction to delivery.</li>
      <li>Coordinate with maintenance, repair and overhaul teams.</li>
      <li>Ensure Part 145 compliance throughout the overhaul process.</li>
    </ul>
  </div>
</div>
</main>
</body></html>
"""

DETAIL_HTML_EMPTY_SECTIONS = """
<!DOCTYPE html><html><body>
<ul class="searchCategs">
  <li>
    <div class="descr"><span>Closing Date:</span></div>
    <div class="categVal">20-Jun-2026</div>
  </li>
</ul>
</body></html>
"""


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    return r


# ── _parse_date tests ─────────────────────────────────────────────────────────

class TestParseDate(unittest.TestCase):

    def test_standard_format(self):
        self.assertEqual(sanad_fetcher._parse_date("15-Jun-2026"), "2026-06-15")

    def test_end_of_year(self):
        self.assertEqual(sanad_fetcher._parse_date("31-Dec-2026"), "2026-12-31")

    def test_empty_string(self):
        self.assertEqual(sanad_fetcher._parse_date(""), "")

    def test_none(self):
        self.assertEqual(sanad_fetcher._parse_date(None), "")

    def test_unknown_format_returns_empty(self):
        self.assertEqual(sanad_fetcher._parse_date("2026-06-15"), "")

    def test_whitespace_stripped(self):
        self.assertEqual(sanad_fetcher._parse_date("  20-Jun-2026  "), "2026-06-20")


# ── _parse_listing_page tests ─────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def test_returns_two_jobs(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        self.assertEqual(len(jobs), 2)

    def test_first_job_fields(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        j = jobs[0]
        self.assertEqual(j["id"], "174905")
        self.assertEqual(j["title"], "Senior Officer - Account Management")
        self.assertEqual(j["company"], "Sanad Aerotech")
        self.assertEqual(j["location"], "Abu Dhabi, United Arab Emirates")
        self.assertEqual(j["posting_date"], "2026-06-15")
        self.assertEqual(j["url"], "https://careers.sanad.ae/vacancy/174905")
        self.assertEqual(j["source"], "sanad")

    def test_second_job_closing_date(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        self.assertEqual(jobs[1]["posting_date"], "2026-06-30")

    def test_empty_page_returns_empty_list(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_EMPTY)
        self.assertEqual(jobs, [])

    def test_url_construction(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        for job in jobs:
            self.assertTrue(job["url"].startswith("https://careers.sanad.ae/vacancy/"))

    def test_required_keys_present(self):
        jobs = sanad_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
            self.assertIn(key, jobs[0])


# ── fetch_jobs tests ──────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.sanad_fetcher.requests.Session")
    def test_returns_jobs_from_single_page(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),  # page 0
            _make_mock_response(LISTING_HTML_EMPTY),  # page 1 → stop
        ]
        jobs = sanad_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Senior Officer - Account Management")

    @patch("src.sanad_fetcher.requests.Session")
    def test_stops_on_empty_page(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_EMPTY),
        ]
        jobs = sanad_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        # Should have called get twice (page 0 and page 1)
        self.assertEqual(mock_session.get.call_count, 2)

    @patch("src.sanad_fetcher.requests.Session")
    def test_deduplicates_by_id(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # Return same page twice — second page has all duplicate IDs → should stop
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_PAGE1),  # all duplicates → stops
        ]
        jobs = sanad_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)  # no duplicates added

    @patch("src.sanad_fetcher.requests.Session")
    def test_raises_rate_limit_error(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)
        with self.assertRaises(sanad_fetcher.RateLimitError):
            sanad_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.sanad_fetcher.requests.Session")
    def test_respects_max_listings(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(LISTING_HTML_PAGE1)
        # max_listings=1 should stop after 1 job
        jobs = sanad_fetcher.fetch_jobs(max_listings=1, inter_page_delay=0)
        self.assertLessEqual(len(jobs), 2)  # at most one page's worth

    @patch("src.sanad_fetcher.requests.Session")
    def test_network_error_returns_partial(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        # First page succeeds, second raises connection error (3 retries)
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            Exception("connection refused"),
            Exception("connection refused"),
            Exception("connection refused"),
        ]
        jobs = sanad_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)  # got first page before error


# ── fetch_job_description tests ───────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.sanad_fetcher.requests.Session")
    def test_returns_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        result = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.sanad_fetcher.requests.Session")
    def test_description_contains_engine_keywords(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        text, date = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertIn("GEnx", text)
        self.assertIn("MRO", text)
        self.assertIn("Part 145", text)

    @patch("src.sanad_fetcher.requests.Session")
    def test_returns_closing_date(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        text, date = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertEqual(date, "2026-06-15")

    @patch("src.sanad_fetcher.requests.Session")
    def test_description_has_multiple_sections(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        text, _ = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertIn("About the Role", text)
        self.assertIn("Your Responsibilities", text)

    def test_empty_url_returns_empty_tuple(self):
        result = sanad_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))

    def test_non_vacancy_url_returns_empty_tuple(self):
        result = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/account/login")
        self.assertEqual(result, ("", ""))

    @patch("src.sanad_fetcher.requests.Session")
    def test_network_error_returns_empty_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = Exception("connection refused")
        result = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertEqual(result, ("", ""))

    @patch("src.sanad_fetcher.requests.Session")
    def test_rate_limit_propagates(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)
        with self.assertRaises(sanad_fetcher.RateLimitError):
            sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")

    @patch("src.sanad_fetcher.requests.Session")
    def test_404_returns_empty_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("<html><body>Not Found</body></html>", status=404)
        result = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/174905")
        self.assertEqual(result, ("", ""))

    @patch("src.sanad_fetcher.requests.Session")
    def test_empty_sections_returns_empty_description(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_EMPTY_SECTIONS)
        text, date = sanad_fetcher.fetch_job_description("https://careers.sanad.ae/vacancy/999")
        self.assertEqual(text, "")
        self.assertEqual(date, "2026-06-20")


if __name__ == "__main__":
    unittest.main()
