import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.ethiopian_fetcher as ethiopian_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

# Mirrors the actual Ethiopian Airlines vacancies page structure.
# - Two <section> groups: International and Local
# - Each job is a <li> with a header <a href="#collapseXxx_N"> and a matching div
# - Pagination links: /AboutEthiopian/careers/vacancies/2

LISTING_HTML_PAGE1 = """
<!DOCTYPE html><html><body>
<div class="container">
  <h2>International Job Openings</h2>
  <div id="accordion_4">
    <div class="panel panel-default" id="panel_4">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseOne_4" href="#collapseOne_4">
          <strong>Position : </strong>&nbsp;&nbsp;Expat Captain B767<br>
          <strong>Location : </strong>&nbsp;&nbsp;Send to Expatrecruitment@ethiopianairlines.com<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;Open<br>
        </a>
      </div>
      <div id="collapseOne_4" class="panel-collapse collapse in">
        <div class="panel-body">
          Position: Expat Captain B767
          Qualification: Valid ATPL, current B767 type rating, minimum 3500 hours jet time.
          Send CV to Expatrecruitment@ethiopianairlines.com
        </div>
      </div>
    </div>
  </div>
  <div id="accordion_20">
    <div class="panel panel-default" id="panel_20">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseOne_20" href="#collapseOne_20">
          <strong>Position : </strong>&nbsp;&nbsp;Head of Engine Shop Operations<br>
          <strong>Location : </strong>&nbsp;&nbsp;Addis Ababa<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;June 25, 2026<br>
        </a>
      </div>
      <div id="collapseOne_20" class="panel-collapse collapse in">
        <div class="panel-body">
          Position: Head of Engine Shop Operations
          VACANCY ANNOUNCEMENT
          ABOUT THE JOB: Lead the engine MRO facility covering GE90, CFM56, and Trent 700 engines.
          Responsibilities include overseeing engine overhaul, shop visit planning, test cell operations,
          workscope management, and LLP tracking. Part 145 EASA/GCAA approved facility.
          Minimum 10 years MRO maintenance experience required. Continuing airworthiness knowledge
          is essential. The role involves coordinating borescope inspections and on-wing repairs.
          REGISTRATION: Ethiopian Airlines Head Quarter, 1st floor.
          Closing Date: June 25, 2026
        </div>
      </div>
    </div>
  </div>
  <h2>Local Job Openings</h2>
  <div id="accordion_local_0">
    <div class="panel panel-default" id="panel_local_0">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseTwo_0" href="#collapseTwo_0">
          <strong>Position : </strong>&nbsp;&nbsp;Assistant Catering Attendant<br>
          <strong>Location : </strong>&nbsp;&nbsp;Addis Ababa<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;May 20, 2026<br>
        </a>
      </div>
      <div id="collapseTwo_0" class="panel-collapse collapse in">
        <div class="panel-body">
          Position: Assistant Catering Attendant
          Requirements: Certificate in hotel management. No aviation experience required.
          Closing Date: May 20, 2026
        </div>
      </div>
    </div>
  </div>
  <div id="accordion_local_1">
    <div class="panel panel-default" id="panel_local_1">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseTwo_1" href="#collapseTwo_1">
          <strong>Position : </strong>&nbsp;&nbsp;MRO Quality Manager<br>
          <strong>Location : </strong>&nbsp;&nbsp;Addis Ababa<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;June 30, 2026<br>
        </a>
      </div>
      <div id="collapseTwo_1" class="panel-collapse collapse in">
        <div class="panel-body">
          Position: MRO Quality Manager
          VACANCY ANNOUNCEMENT
          Responsible for quality assurance across our Part 145 EASA approved MRO facility.
          Experience with CFM56, GE90, and Trent engine maintenance programmes required.
          Oversee engine overhaul quality checks, airworthiness compliance, workscope approvals,
          and shop visit reporting. Strong MRO background mandatory. GCAA/EASA knowledge essential.
          Aviation degree preferred. 8+ years maintenance experience.
          Closing Date: June 30, 2026
        </div>
      </div>
    </div>
  </div>
  <ul class="pagination">
    <li class="active page-item">
      <a class="page-link" href="/AboutEthiopian/careers/vacancies/1">1</a>
    </li>
    <li class="page-item">
      <a class="page-link" href="/AboutEthiopian/careers/vacancies/2">2</a>
    </li>
  </ul>
</div>
</body></html>
"""

LISTING_HTML_PAGE2 = """
<!DOCTYPE html><html><body>
<div class="container">
  <h2>International Job Openings</h2>
  <div id="accordion_4">
    <div class="panel panel-default" id="panel_4">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseOne_4" href="#collapseOne_4">
          <strong>Position : </strong>&nbsp;&nbsp;Expat Captain B767<br>
          <strong>Location : </strong>&nbsp;&nbsp;Send to Expatrecruitment@ethiopianairlines.com<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;Open<br>
        </a>
      </div>
      <div id="collapseOne_4" class="panel-collapse collapse in">
        <div class="panel-body">Expat Captain B767 description repeated on page 2.</div>
      </div>
    </div>
  </div>
  <h2>Local Job Openings</h2>
  <div id="accordion_local_5">
    <div class="panel panel-default" id="panel_local_5">
      <div class="card-header">
        <a data-toggle="collapse" data-target="#collapseTwo_5" href="#collapseTwo_5">
          <strong>Position : </strong>&nbsp;&nbsp;Engine Maintenance Manager<br>
          <strong>Location : </strong>&nbsp;&nbsp;Addis Ababa<br>
          <strong>Closing Date : </strong>&nbsp;&nbsp;July 15, 2026<br>
        </a>
      </div>
      <div id="collapseTwo_5" class="panel-collapse collapse in">
        <div class="panel-body">
          Position: Engine Maintenance Manager
          Manage day-to-day engine shop operations including GEnx and LEAP overhaul.
          Part 145 facility. Test cell coordination, borescope, workscope planning. MRO experience essential.
          Closing Date: July 15, 2026
        </div>
      </div>
    </div>
  </div>
  <ul class="pagination">
    <li class="page-item">
      <a class="page-link" href="/AboutEthiopian/careers/vacancies/1">1</a>
    </li>
    <li class="active page-item">
      <a class="page-link" href="/AboutEthiopian/careers/vacancies/2">2</a>
    </li>
  </ul>
</div>
</body></html>
"""

LISTING_HTML_EMPTY = """
<!DOCTYPE html><html><body>
<div class="container"><p>No vacancies available.</p></div>
</body></html>
"""


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


# ── _parse_closing_date tests ─────────────────────────────────────────────────

class TestParseClosingDate(unittest.TestCase):

    def test_standard_format(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("June 25, 2026"), "2026-06-25")

    def test_single_digit_day(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("July 5, 2026"), "2026-07-05")

    def test_open_returns_empty(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("Open"), "")

    def test_empty_returns_empty(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date(""), "")

    def test_case_insensitive_open(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("open"), "")

    def test_whitespace_stripped(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("  June 25, 2026  "), "2026-06-25")

    def test_unknown_format_returns_empty(self):
        self.assertEqual(ethiopian_fetcher._parse_closing_date("25-06-2026"), "")


# ── _get_total_pages tests ────────────────────────────────────────────────────

class TestGetTotalPages(unittest.TestCase):

    def test_two_page_pagination(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(LISTING_HTML_PAGE1, "lxml")
        self.assertEqual(ethiopian_fetcher._get_total_pages(soup), 2)

    def test_no_pagination_returns_one(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(LISTING_HTML_EMPTY, "lxml")
        self.assertEqual(ethiopian_fetcher._get_total_pages(soup), 1)


# ── _parse_page tests ─────────────────────────────────────────────────────────

class TestParsePage(unittest.TestCase):

    def setUp(self):
        ethiopian_fetcher._desc_cache.clear()

    def test_returns_four_jobs(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        self.assertEqual(len(jobs), 4)

    def test_required_fields_present(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            for key in ("title", "url", "location", "company", "source", "posting_date"):
                self.assertIn(key, job, f"Missing key '{key}' in job: {job.get('title')}")

    def test_mro_job_title(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        titles = [j["title"] for j in jobs]
        self.assertIn("Head of Engine Shop Operations", titles)
        self.assertIn("MRO Quality Manager", titles)

    def test_posting_date_is_yyyy_mm_dd(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            if job["posting_date"]:
                self.assertRegex(job["posting_date"], r"^\d{4}-\d{2}-\d{2}$",
                                 f"Bad date format for: {job['title']}")

    def test_open_date_stored_as_empty(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        captain = next(j for j in jobs if j["title"] == "Expat Captain B767")
        self.assertEqual(captain["posting_date"], "")

    def test_url_contains_vacancies_path(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertIn("/AboutEthiopian/careers/vacancies", job["url"])

    def test_url_has_fragment(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertIn("#", job["url"])

    def test_url_does_not_contain_api_endpoint(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertNotIn("/api/", job["url"])

    def test_location_is_addis_ababa(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertEqual(job["location"], "Addis Ababa, Ethiopia")

    def test_source_is_ethiopian(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertEqual(job["source"], "ethiopian")

    def test_company_is_ethiopian_airlines(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        for job in jobs:
            self.assertEqual(job["company"], "Ethiopian Airlines")

    def test_descriptions_cached(self):
        ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        self.assertGreater(len(ethiopian_fetcher._desc_cache), 0)

    def test_description_content_cached(self):
        jobs = ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)
        mro_job = next(j for j in jobs if j["title"] == "Head of Engine Shop Operations")
        cached = ethiopian_fetcher._desc_cache.get(mro_job["url"])
        self.assertIsNotNone(cached)
        desc, _ = cached
        self.assertIn("GE90", desc)
        self.assertIn("CFM56", desc)


# ── fetch_jobs tests ──────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    def setUp(self):
        ethiopian_fetcher._desc_cache.clear()

    @patch("src.ethiopian_fetcher.requests.get")
    def test_returns_unique_jobs_across_pages(self, mock_get):
        mock_get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),  # page 1
            _make_mock_response(LISTING_HTML_PAGE2),  # page 2
        ]
        jobs = ethiopian_fetcher.fetch_jobs()
        titles = [j["title"] for j in jobs]
        # Expat Captain B767 appears on both pages — should deduplicate to 1
        self.assertEqual(titles.count("Expat Captain B767"), 1)

    @patch("src.ethiopian_fetcher.requests.get")
    def test_new_jobs_on_page2_included(self, mock_get):
        mock_get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_PAGE2),
        ]
        jobs = ethiopian_fetcher.fetch_jobs()
        titles = [j["title"] for j in jobs]
        self.assertIn("Engine Maintenance Manager", titles)

    @patch("src.ethiopian_fetcher.requests.get")
    def test_raises_rate_limit_error(self, mock_get):
        mock_get.return_value = _make_mock_response("", status=429)
        with self.assertRaises(ethiopian_fetcher.RateLimitError):
            ethiopian_fetcher.fetch_jobs()

    @patch("src.ethiopian_fetcher.requests.get")
    def test_network_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        jobs = ethiopian_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.ethiopian_fetcher.requests.get")
    def test_populates_desc_cache(self, mock_get):
        mock_get.side_effect = [
            _make_mock_response(LISTING_HTML_PAGE1),
            _make_mock_response(LISTING_HTML_PAGE2),
        ]
        ethiopian_fetcher.fetch_jobs()
        self.assertGreater(len(ethiopian_fetcher._desc_cache), 0)


# ── fetch_job_description tests ───────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        ethiopian_fetcher._desc_cache.clear()

    def _prime_cache(self):
        """Run _parse_page to populate _desc_cache with fixture data."""
        return ethiopian_fetcher._parse_page(LISTING_HTML_PAGE1, 1)

    def test_returns_tuple(self):
        jobs = self._prime_cache()
        mro_job = next(j for j in jobs if j["title"] == "Head of Engine Shop Operations")
        result = ethiopian_fetcher.fetch_job_description(mro_job["url"])
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_description_contains_engine_terms(self):
        jobs = self._prime_cache()
        mro_job = next(j for j in jobs if j["title"] == "Head of Engine Shop Operations")
        desc, _ = ethiopian_fetcher.fetch_job_description(mro_job["url"])
        self.assertIn("GE90", desc)
        self.assertIn("CFM56", desc)
        self.assertIn("engine overhaul", desc)

    def test_returns_closing_date(self):
        jobs = self._prime_cache()
        mro_job = next(j for j in jobs if j["title"] == "Head of Engine Shop Operations")
        _, date = ethiopian_fetcher.fetch_job_description(mro_job["url"])
        self.assertEqual(date, "2026-06-25")

    def test_empty_url_returns_empty_tuple(self):
        self.assertEqual(ethiopian_fetcher.fetch_job_description(""), ("", ""))

    def test_unknown_url_returns_empty_tuple(self):
        result = ethiopian_fetcher.fetch_job_description("https://example.com/not-a-job")
        self.assertEqual(result, ("", ""))

    def test_never_raises(self):
        # Should silently return ("", "") for any unknown URL — never raise
        try:
            result = ethiopian_fetcher.fetch_job_description("https://corporate.ethiopianairlines.com/bogus")
            self.assertEqual(result, ("", ""))
        except Exception as exc:
            self.fail(f"fetch_job_description raised unexpectedly: {exc}")

    def test_open_date_job_returns_empty_date(self):
        jobs = self._prime_cache()
        captain = next(j for j in jobs if j["title"] == "Expat Captain B767")
        _, date = ethiopian_fetcher.fetch_job_description(captain["url"])
        self.assertEqual(date, "")

    def test_catering_description_fetched(self):
        jobs = self._prime_cache()
        catering = next(j for j in jobs if j["title"] == "Assistant Catering Attendant")
        desc, _ = ethiopian_fetcher.fetch_job_description(catering["url"])
        self.assertGreater(len(desc), 10)


if __name__ == "__main__":
    unittest.main()
