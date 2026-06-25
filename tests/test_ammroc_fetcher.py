import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.ammroc_fetcher as ammroc_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

LISTING_HTML = """
<!DOCTYPE html><html><body>
<span class="paginationLabel" aria-label="Results 1 – 2">Results <b>1 – 2</b> of <b>2</b></span>
<table>
<tbody>
<tr class="data-row">
  <td>
    <a class="jobTitle-link" href="/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/">
      Head of Engine Overhaul
    </a>
    <span class="jobFacility">AMMROC</span>
    <span class="jobLocation">Abu Dhabi, AE</span>
    <span class="jobDate">25 Jun 2026</span>
  </td>
</tr>
<tr class="data-row">
  <td>
    <a class="jobTitle-link" href="/job/Abu-Dhabi-Safety-Senior-Engineer/732942722/">
      Safety Senior Engineer
    </a>
    <span class="jobFacility">POWERTECH</span>
    <span class="jobLocation">Abu Dhabi, AE</span>
    <span class="jobDate">25 Jun 2026</span>
  </td>
</tr>
</tbody>
</table>
</body></html>
"""

LISTING_HTML_EMPTY = """
<!DOCTYPE html><html><body>
<span class="paginationLabel" aria-label="Results 0">Results <b>0</b> of <b>0</b></span>
<table><tbody></tbody></table>
</body></html>
"""

DETAIL_HTML = """
<!DOCTYPE html><html><body>
<h1>Head of Engine Overhaul</h1>
<p>Date:25 Jun 2026</p>
<span class="jobdescription">
Lead AMMROC's engine overhaul shop covering military helicopter and fixed-wing
propulsion. Manage test cell scheduling, borescope inspections, and shop visit
workscope planning. Requires CAMO, Part-M, and EASA Part 145 knowledge across
the engine maintenance, repair, and overhaul programme.
</span>
</body></html>
"""


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    return r


# ── _get_total_jobs ───────────────────────────────────────────────────────────

class TestGetTotalJobs(unittest.TestCase):

    def test_parses_count(self):
        self.assertEqual(ammroc_fetcher._get_total_jobs(LISTING_HTML), 2)

    def test_zero_count(self):
        self.assertEqual(ammroc_fetcher._get_total_jobs(LISTING_HTML_EMPTY), 0)


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def test_returns_two_jobs(self):
        jobs = ammroc_fetcher._parse_listing_page(LISTING_HTML)
        self.assertEqual(len(jobs), 2)

    def test_required_fields(self):
        j = ammroc_fetcher._parse_listing_page(LISTING_HTML)[0]
        for key in ("id", "title", "company", "entity", "location", "posting_date", "url", "source"):
            self.assertIn(key, j)
        self.assertEqual(j["id"], "732111722")
        self.assertEqual(j["title"], "Head of Engine Overhaul")
        self.assertEqual(j["company"], "EDGE Group")
        self.assertEqual(j["entity"], "AMMROC")
        self.assertEqual(j["posting_date"], "2026-06-25")
        self.assertTrue(j["url"].startswith("https://careers.edgegroup.ae/job/"))
        self.assertEqual(j["source"], "ammroc")

    def test_entity_distinguishes_divisions(self):
        jobs = ammroc_fetcher._parse_listing_page(LISTING_HTML)
        self.assertEqual(jobs[0]["entity"], "AMMROC")
        self.assertEqual(jobs[1]["entity"], "POWERTECH")

    def test_empty_page_returns_empty(self):
        self.assertEqual(ammroc_fetcher._parse_listing_page(LISTING_HTML_EMPTY), [])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.ammroc_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ammroc_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(len(jobs), 2)

    @patch("src.ammroc_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(ammroc_fetcher.RateLimitError):
            ammroc_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.ammroc_fetcher.requests.Session")
    def test_network_error_returns_partial(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = ammroc_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.ammroc_fetcher.requests.Session")
    def test_empty_listing_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_EMPTY)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ammroc_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.ammroc_fetcher.requests.Session")
    def test_returns_tuple(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = ammroc_fetcher.fetch_job_description(
            "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.ammroc_fetcher.requests.Session")
    def test_description_contains_engine_keywords(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = ammroc_fetcher.fetch_job_description(
            "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
        )
        self.assertIn("test cell", text)
        self.assertIn("CAMO", text)
        self.assertIn("Part 145", text)

    @patch("src.ammroc_fetcher.requests.Session")
    def test_date_always_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        _, date = ammroc_fetcher.fetch_job_description(
            "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
        )
        self.assertEqual(date, "")

    def test_empty_url_returns_empty_tuple(self):
        self.assertEqual(ammroc_fetcher.fetch_job_description(""), ("", ""))

    def test_non_job_url_returns_empty_tuple(self):
        self.assertEqual(
            ammroc_fetcher.fetch_job_description("https://careers.edgegroup.ae/go/View-All-Jobs/4166222/"),
            ("", "")
        )

    @patch("src.ammroc_fetcher.requests.Session")
    def test_network_error_returns_empty_tuple(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("connection refused")
        result = ammroc_fetcher.fetch_job_description(
            "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.ammroc_fetcher.requests.Session")
    def test_rate_limit_propagates(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(ammroc_fetcher.RateLimitError):
            ammroc_fetcher.fetch_job_description(
                "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
            )

    @patch("src.ammroc_fetcher.requests.Session")
    def test_404_returns_empty_tuple(self, MockSession):
        mock_resp = _make_mock_response("Not Found", status=404)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = ammroc_fetcher.fetch_job_description(
            "https://careers.edgegroup.ae/job/Abu-Dhabi-Head-of-Engine-Overhaul/732111722/"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
