import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.gulf_air_fetcher as gulf_air_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

LISTING_HTML_PAGE1 = """
<!DOCTYPE html><html><body>
<div class="row jobdetail mb-4 ms-0">
  <div class="col-12 jb-title">
    <h3><a href="/vacancy/175498">MANAGER &#x2013; SYSTEM ADMINISTRATION</a></h3>
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Company</label>Gulf Air Group
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Location</label>Bahrain - Head Quarter
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Closing Date</label>30-Jun-2026
  </div>
</div>
<div class="row jobdetail mb-4 ms-0">
  <div class="col-12 jb-title">
    <h3><a href="/vacancy/175412">Head of Engine Overhaul</a></h3>
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Company</label>Gulf Air
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Location</label>Bahrain
  </div>
  <div class="col-lg col-md-12 searchcaption">
    <label>Closing Date</label>29-Jun-2026
  </div>
</div>
<ul class="pagination">
  <li class="page-item disabled"><a class="page-link" href="/?pg=0">1</a></li>
  <li class="page-item"><a class="page-link" href="/?pg=1">2</a></li>
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
<ul class="searchCategs">
  <li>
    <div class="descr"><strong>Company</strong></div>
    <div class="sc-val">Gulf Air</div>
  </li>
  <li>
    <div class="descr"><strong>Closing Date</strong></div>
    <div class="sc-val">29-Jun-2026</div>
  </li>
</ul>
<div class="row mt-3 sectn">
  <div class="col-12"><h5>About the Role</h5></div>
  <div class="col-12">
    <p>Lead the engine overhaul shop covering A320 and B787 fleets, managing
    test cell scheduling, borescope inspections, and shop visit workscope
    planning. Requires GACA/EASA Part 145 and CAMO compliance knowledge.</p>
  </div>
</div>
<div class="row mt-3 sectn">
  <div class="col-12"><h5>Your Responsibilities</h5></div>
  <div class="col-12">
    <ul><li>Manage engine shop visits from induction to delivery.</li></ul>
  </div>
</div>
</body></html>
"""

DETAIL_HTML_EMPTY_SECTIONS = """
<!DOCTYPE html><html><body>
<ul class="searchCategs">
  <li>
    <div class="descr"><strong>Closing Date</strong></div>
    <div class="sc-val">20-Jun-2026</div>
  </li>
</ul>
</body></html>
"""


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    return r


# ── _parse_date ────────────────────────────────────────────────────────────────

class TestParseDate(unittest.TestCase):

    def test_standard_format(self):
        self.assertEqual(gulf_air_fetcher._parse_date("30-Jun-2026"), "2026-06-30")

    def test_empty_string(self):
        self.assertEqual(gulf_air_fetcher._parse_date(""), "")

    def test_none(self):
        self.assertEqual(gulf_air_fetcher._parse_date(None), "")

    def test_unknown_format_returns_empty(self):
        self.assertEqual(gulf_air_fetcher._parse_date("2026-06-30"), "")


# ── _parse_listing_page ──────────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def test_returns_two_jobs(self):
        jobs = gulf_air_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        self.assertEqual(len(jobs), 2)

    def test_first_job_fields(self):
        j = gulf_air_fetcher._parse_listing_page(LISTING_HTML_PAGE1)[0]
        self.assertEqual(j["id"], "175498")
        self.assertEqual(j["title"], "MANAGER – SYSTEM ADMINISTRATION")
        self.assertEqual(j["company"], "Gulf Air Group")
        self.assertEqual(j["location"], "Bahrain - Head Quarter")
        self.assertEqual(j["posting_date"], "2026-06-30")
        self.assertEqual(j["url"], "https://gulfairgroup.sniperhire.net/vacancy/175498")
        self.assertEqual(j["source"], "gulf_air")

    def test_second_job_company(self):
        jobs = gulf_air_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        self.assertEqual(jobs[1]["company"], "Gulf Air")

    def test_empty_page_returns_empty_list(self):
        self.assertEqual(gulf_air_fetcher._parse_listing_page(LISTING_HTML_EMPTY), [])

    def test_required_keys_present(self):
        jobs = gulf_air_fetcher._parse_listing_page(LISTING_HTML_PAGE1)
        for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
            self.assertIn(key, jobs[0])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_returns_jobs_from_single_page(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_EMPTY),
        ]
        jobs = gulf_air_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_deduplicates_by_id(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_PAGE1),
        ]
        jobs = gulf_air_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_raises_rate_limit_error(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)
        with self.assertRaises(gulf_air_fetcher.RateLimitError):
            gulf_air_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_network_error_returns_partial(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            Exception("connection refused"),
            Exception("connection refused"),
            Exception("connection refused"),
        ]
        jobs = gulf_air_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        self.assertEqual(len(jobs), 2)


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_returns_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        result = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_description_contains_engine_keywords(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        text, _ = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")
        self.assertIn("test cell", text)
        self.assertIn("CAMO", text)
        self.assertIn("Part 145", text)

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_returns_closing_date_via_sc_val(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_WITH_DESCRIPTION)
        _, date = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")
        self.assertEqual(date, "2026-06-29")

    def test_empty_url_returns_empty_tuple(self):
        self.assertEqual(gulf_air_fetcher.fetch_job_description(""), ("", ""))

    def test_non_vacancy_url_returns_empty_tuple(self):
        self.assertEqual(
            gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/account/login"),
            ("", "")
        )

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_network_error_returns_empty_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = Exception("connection refused")
        result = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")
        self.assertEqual(result, ("", ""))

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_rate_limit_propagates(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)
        with self.assertRaises(gulf_air_fetcher.RateLimitError):
            gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_404_returns_empty_tuple(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("Not Found", status=404)
        result = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/175412")
        self.assertEqual(result, ("", ""))

    @patch("src.gulf_air_fetcher.requests.Session")
    def test_empty_sections_returns_empty_description(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML_EMPTY_SECTIONS)
        text, date = gulf_air_fetcher.fetch_job_description("https://gulfairgroup.sniperhire.net/vacancy/999")
        self.assertEqual(text, "")
        self.assertEqual(date, "2026-06-20")


if __name__ == "__main__":
    unittest.main()
