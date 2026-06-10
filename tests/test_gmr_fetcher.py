import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.gmr_fetcher as gmr_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

LISTING_HTML = """
<!DOCTYPE html>
<html>
<body>
<table id="resultBody" aria-label="Results 1 to 2 of 2">
  <tbody>
    <tr class="data-row">
      <td>
        <a class="jobTitle-link" href="/job/quality-manager-engine-shop/1196717201/">
          Quality Manager - Engine Shop
        </a>
        <span class="jobLocation">Hyderabad, GMR AT - Hyderabad (HYD01), IN</span>
        <span class="jobDate">10 Jun 2026</span>
      </td>
    </tr>
    <tr class="data-row">
      <td>
        <a class="jobTitle-link" href="/job/production-manager-mro/1196717202/">
          Production Manager MRO
        </a>
        <span class="jobLocation">Goa, GMR AA - Goa (PG11AA06), IN</span>
        <span class="jobDate">5 May 2026</span>
      </td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""

LISTING_HTML_EMPTY = """
<!DOCTYPE html>
<html>
<body>
<table id="resultBody" aria-label="Results 1 to 0 of 0">
  <tbody>
  </tbody>
</table>
</body>
</html>
"""

DETAIL_HTML = """
<!DOCTYPE html>
<html>
<body>
<h1>Quality Manager - Engine Shop</h1>
<p>Date:10 Jun 2026</p>
<span class="jobdescription">
  Lead and manage the engine shop quality management system at GMR Aero Technic.
  Responsible for ensuring compliance with Part 145 regulations, DGCA and EASA airworthiness
  standards, and overseeing all MRO activities for CFM56 and GEnx engine overhaul programs.
  The role requires deep knowledge of engine shop operations, test cell procedures, borescope
  inspection, and workscope planning. Candidate must have experience in shop visit management,
  aviation quality systems, and engine maintenance leadership. Familiarity with SMS and human
  factors principles is essential for this senior role overseeing the production team.
</span>
</body>
</html>
"""


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    return r


# ── test_correct_fields ───────────────────────────────────────────────────────

class TestCorrectFields(unittest.TestCase):

    def test_correct_fields(self):
        """Parse listing HTML, verify all required fields including posting_date YYYY-MM-DD."""
        jobs = gmr_fetcher._parse_listing_page(LISTING_HTML)
        self.assertEqual(len(jobs), 2)

        j = jobs[0]
        # Required fields present
        for key in ("id", "title", "company", "location", "posting_date", "url", "source"):
            self.assertIn(key, j, f"Missing field: {key}")

        # Field values
        self.assertEqual(j["id"], "1196717201")
        self.assertEqual(j["title"], "Quality Manager - Engine Shop")
        self.assertEqual(j["company"], "GMR Group")
        self.assertIn("Hyderabad", j["location"])
        self.assertIn("India", j["location"])

        # posting_date in YYYY-MM-DD format
        self.assertEqual(j["posting_date"], "2026-06-10")

        # URL contains /job/
        self.assertIn("/job/", j["url"])
        self.assertTrue(j["url"].startswith("https://careers.gmrgroup.in"))

        # source is "gmr"
        self.assertEqual(j["source"], "gmr")

    def test_location_cleaning(self):
        """Location should strip internal codes and append ', India'."""
        jobs = gmr_fetcher._parse_listing_page(LISTING_HTML)
        self.assertEqual(jobs[0]["location"], "Hyderabad, India")
        self.assertEqual(jobs[1]["location"], "Goa, India")

    def test_second_job_date(self):
        """Second job date parses correctly."""
        jobs = gmr_fetcher._parse_listing_page(LISTING_HTML)
        self.assertEqual(jobs[1]["posting_date"], "2026-05-05")


# ── test_fetch_job_description_non_empty ──────────────────────────────────────

class TestFetchJobDescriptionNonEmpty(unittest.TestCase):

    @patch("src.gmr_fetcher.requests.Session")
    def test_fetch_job_description_non_empty(self, mock_session_cls):
        """Parse detail HTML with span.jobdescription, verify len > 100."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML)

        text, date = gmr_fetcher.fetch_job_description(
            "https://careers.gmrgroup.in/job/quality-manager-engine-shop/1196717201/"
        )

        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 100, "Description should be longer than 100 chars")
        self.assertIsInstance(date, str)

    @patch("src.gmr_fetcher.requests.Session")
    def test_description_date_parsed(self, mock_session_cls):
        """Date regex on detail page extracts correct ISO date."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response(DETAIL_HTML)

        text, date = gmr_fetcher.fetch_job_description(
            "https://careers.gmrgroup.in/job/quality-manager-engine-shop/1196717201/"
        )
        self.assertEqual(date, "2026-06-10")


# ── test_rate_limit_error_on_429 ──────────────────────────────────────────────

class TestRateLimitError(unittest.TestCase):

    @patch("src.gmr_fetcher.requests.Session")
    def test_rate_limit_error_on_429_fetch_jobs(self, mock_session_cls):
        """fetch_jobs raises RateLimitError on 429 response."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)

        with self.assertRaises(gmr_fetcher.RateLimitError):
            gmr_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.gmr_fetcher.requests.Session")
    def test_rate_limit_error_on_429_fetch_description(self, mock_session_cls):
        """fetch_job_description raises RateLimitError on 429 response."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("", status=429)

        with self.assertRaises(gmr_fetcher.RateLimitError):
            gmr_fetcher.fetch_job_description(
                "https://careers.gmrgroup.in/job/some-role/1234/"
            )


# ── test_returns_empty_tuple_on_failure ───────────────────────────────────────

class TestReturnsEmptyTupleOnFailure(unittest.TestCase):

    @patch("src.gmr_fetcher.requests.Session")
    def test_returns_empty_tuple_on_failure(self, mock_session_cls):
        """fetch_job_description returns ("", "") on network exception, never raises."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = Exception("connection refused")

        result = gmr_fetcher.fetch_job_description(
            "https://careers.gmrgroup.in/job/some-role/1234/"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.gmr_fetcher.requests.Session")
    def test_returns_empty_tuple_on_404(self, mock_session_cls):
        """fetch_job_description returns ("", "") on 404."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _make_mock_response("<html>Not Found</html>", status=404)

        result = gmr_fetcher.fetch_job_description(
            "https://careers.gmrgroup.in/job/some-role/1234/"
        )
        self.assertEqual(result, ("", ""))

    def test_returns_empty_tuple_on_bad_url(self):
        """fetch_job_description returns ("", "") for URLs without /job/."""
        result = gmr_fetcher.fetch_job_description("https://careers.gmrgroup.in/search/")
        self.assertEqual(result, ("", ""))

    def test_returns_empty_tuple_on_empty_url(self):
        """fetch_job_description returns ("", "") for empty URL."""
        result = gmr_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
