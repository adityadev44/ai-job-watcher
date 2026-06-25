import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.ste_fetcher as ste_fetcher

# ── HTML Fixtures ─────────────────────────────────────────────────────────────

LISTING_HTML = """
<!DOCTYPE html>
<html>
<body>
<div aria-label="Search results for . Page 1 of 14, Results 1 to 25 of 344">Results 1 to 25 of 344</div>
<table id="resultBody">
  <tbody>
    <tr class="data-row">
      <td>
        <a class="jobTitle-link" href="/job/Aero-501-Airport-Rd-Technical-Services-Engineer/1213266466/">
          Technical Services Engineer
        </a>
        <span class="jobFacility">Commercial Aerospace</span>
        <span class="jobLocation">Aero - 501 Airport Rd, SG</span>
        <span class="jobDate">23 Jun 2026</span>
      </td>
    </tr>
    <tr class="data-row">
      <td>
        <a class="jobTitle-link" href="/job/Defence-Senior-Technician/1213266999/">
          Senior Technician
        </a>
        <span class="jobFacility">Defence Aerospace</span>
        <span class="jobLocation">Defence - 1 Defence Way, SG</span>
        <span class="jobDate">22 Jun 2026</span>
      </td>
    </tr>
    <tr class="data-row">
      <td>
        <a class="jobTitle-link" href="/job/Aero-600-West-Camp-Road-Manager-Aircraft-Leasing/1357569466/">
          Manager, Aircraft Leasing
        </a>
        <span class="jobFacility">Commercial Aerospace</span>
        <span class="jobLocation">Aero - 600 West Camp Road, MY</span>
        <span class="jobDate">10 Jun 2026</span>
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
<table id="resultBody">
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
<h1>Technical Services Engineer</h1>
<span class="jobdescription">
  Liaise with customers on engine condition and technical issues. Prescribe workscope for engine
  overhaul or rectification of CFM56 and PW4000 engines. Generate Engine Condition Reports and
  support borescope inspection findings. Liaise with OEM for technical support on test cell runs
  and shop visit planning. Knowledge of CAMO and Part-M continuing airworthiness requirements
  preferred. The successful candidate will support engine ground run and LLP tracking activities.
</span>
</body>
</html>
"""

DETAIL_HTML_NO_DESC = "<html><body><p>No description available.</p></body></html>"


def _make_mock_response(html, status=200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    return r


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate(unittest.TestCase):

    def test_normal_date(self):
        self.assertEqual(ste_fetcher._parse_date("23 Jun 2026"), "2026-06-23")

    def test_single_digit_day(self):
        self.assertEqual(ste_fetcher._parse_date("1 Jan 2026"), "2026-01-01")

    def test_empty_string(self):
        self.assertEqual(ste_fetcher._parse_date(""), "")

    def test_none(self):
        self.assertEqual(ste_fetcher._parse_date(None), "")

    def test_bad_format(self):
        self.assertEqual(ste_fetcher._parse_date("2026-06-01"), "")


# ── _clean_location ───────────────────────────────────────────────────────────

class TestCleanLocation(unittest.TestCase):

    def test_strips_division_prefix_and_maps_sg(self):
        self.assertEqual(
            ste_fetcher._clean_location("Aero - 501 Airport Rd, SG"),
            "501 Airport Rd, Singapore",
        )

    def test_strips_division_prefix_and_maps_my(self):
        self.assertEqual(
            ste_fetcher._clean_location("Aero - 600 West Camp Road, MY"),
            "600 West Camp Road, Malaysia",
        )

    def test_maps_au(self):
        self.assertEqual(
            ste_fetcher._clean_location("Aero - 1 Some St, AU"),
            "1 Some St, Australia",
        )

    def test_unknown_country_code_passthrough(self):
        self.assertEqual(
            ste_fetcher._clean_location("Aero - 1 Some St, XX"),
            "1 Some St, XX",
        )

    def test_no_division_prefix(self):
        # No " - " separator — should still split on ", " for country code
        self.assertEqual(ste_fetcher._clean_location("501 Airport Rd, SG"), "501 Airport Rd, Singapore")

    def test_empty_defaults_to_singapore(self):
        self.assertEqual(ste_fetcher._clean_location(""), "Singapore")

    def test_none_defaults_to_singapore(self):
        self.assertEqual(ste_fetcher._clean_location(None), "Singapore")


# ── _get_total_jobs ───────────────────────────────────────────────────────────

class TestGetTotalJobs(unittest.TestCase):

    def test_parses_count(self):
        self.assertEqual(ste_fetcher._get_total_jobs(LISTING_HTML), 344)

    def test_returns_none_when_absent(self):
        self.assertIsNone(ste_fetcher._get_total_jobs(LISTING_HTML_EMPTY))


# ── _parse_listing_page ───────────────────────────────────────────────────────

class TestParseListingPage(unittest.TestCase):

    def _jobs(self):
        return ste_fetcher._parse_listing_page(LISTING_HTML)

    def test_job_count(self):
        self.assertEqual(len(self._jobs()), 3)

    def test_title(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["title"], "Technical Services Engineer")

    def test_id_extracted(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["id"], "1213266466")

    def test_url_is_absolute_and_browseable_pattern(self):
        jobs = self._jobs()
        self.assertTrue(jobs[0]["url"].startswith("https://careers.stengg.com/job/"))

    def test_url_not_api_endpoint(self):
        for job in self._jobs():
            self.assertNotIn("/search/", job["url"])

    def test_facility_field_present_commercial_aerospace(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["facility"], "Commercial Aerospace")
        self.assertEqual(jobs[2]["facility"], "Commercial Aerospace")

    def test_facility_field_present_other_division(self):
        jobs = self._jobs()
        self.assertEqual(jobs[1]["facility"], "Defence Aerospace")

    def test_location_cleaned_sg(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["location"], "501 Airport Rd, Singapore")

    def test_location_cleaned_my(self):
        jobs = self._jobs()
        self.assertEqual(jobs[2]["location"], "600 West Camp Road, Malaysia")

    def test_posting_date_format(self):
        jobs = self._jobs()
        self.assertEqual(jobs[0]["posting_date"], "2026-06-23")

    def test_company(self):
        for job in self._jobs():
            self.assertEqual(job["company"], "ST Engineering")

    def test_source(self):
        for job in self._jobs():
            self.assertEqual(job["source"], "ste")

    def test_required_keys(self):
        for job in self._jobs():
            for key in ("id", "title", "company", "facility", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)

    def test_empty_page_returns_empty_list(self):
        self.assertEqual(ste_fetcher._parse_listing_page(LISTING_HTML_EMPTY), [])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    @patch("src.ste_fetcher.requests.Session")
    def test_returns_jobs(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ste_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(len(jobs), 3)

    @patch("src.ste_fetcher.requests.Session")
    def test_uses_startrow_pagination_param(self, MockSession):
        """ST Engineering paginates via startrow=, not start= (the only J2W portal that does)."""
        mock_resp = _make_mock_response(LISTING_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        ste_fetcher.fetch_jobs(inter_page_delay=0)
        called_url = MockSession.return_value.get.call_args[0][0]
        self.assertIn("startrow=", called_url)
        self.assertNotIn("start=0", called_url.replace("startrow=0", ""))

    @patch("src.ste_fetcher.requests.Session")
    def test_deduplicates_repeated_ids(self, MockSession):
        # Same page served forever — fetch_jobs must stop once no new IDs appear,
        # not loop until max_listings or hang.
        mock_resp = _make_mock_response(LISTING_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ste_fetcher.fetch_jobs(max_listings=200, inter_page_delay=0)
        ids = [j["id"] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(jobs), 3)

    @patch("src.ste_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(ste_fetcher.RateLimitError):
            ste_fetcher.fetch_jobs(inter_page_delay=0)

    @patch("src.ste_fetcher.requests.Session")
    def test_network_error_returns_partial(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        jobs = ste_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.ste_fetcher.requests.Session")
    def test_empty_page_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML_EMPTY)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ste_fetcher.fetch_jobs(inter_page_delay=0)
        self.assertEqual(jobs, [])

    @patch("src.ste_fetcher.requests.Session")
    def test_all_jobs_have_required_keys(self, MockSession):
        mock_resp = _make_mock_response(LISTING_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        jobs = ste_fetcher.fetch_jobs(inter_page_delay=0)
        for job in jobs:
            for key in ("id", "title", "company", "facility", "location", "posting_date", "url", "source"):
                self.assertIn(key, job)


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    @patch("src.ste_fetcher.requests.Session")
    def test_returns_tuple(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/Aero-501-Airport-Rd-Technical-Services-Engineer/1213266466/"
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("src.ste_fetcher.requests.Session")
    def test_description_text_returned(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/Aero-501-Airport-Rd-Technical-Services-Engineer/1213266466/"
        )
        self.assertIn("CFM56", text)
        self.assertIn("workscope", text)
        self.assertGreater(len(text), 100)

    @patch("src.ste_fetcher.requests.Session")
    def test_date_returns_empty(self, MockSession):
        """ste_fetcher always returns '' for date — listing date is authoritative."""
        mock_resp = _make_mock_response(DETAIL_HTML)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        _, date = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/Aero-501-Airport-Rd-Technical-Services-Engineer/1213266466/"
        )
        self.assertEqual(date, "")

    @patch("src.ste_fetcher.requests.Session")
    def test_no_desc_span_returns_empty(self, MockSession):
        mock_resp = _make_mock_response(DETAIL_HTML_NO_DESC)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        text, _ = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/some-role/1234/"
        )
        self.assertEqual(text, "")

    def test_empty_url_returns_empty(self):
        self.assertEqual(ste_fetcher.fetch_job_description(""), ("", ""))

    def test_url_without_job_returns_empty(self):
        self.assertEqual(
            ste_fetcher.fetch_job_description("https://careers.stengg.com/search/"),
            ("", "")
        )

    @patch("src.ste_fetcher.requests.Session")
    def test_network_error_returns_empty(self, MockSession):
        MockSession.return_value.get.side_effect = Exception("timeout")
        MockSession.return_value.headers = {}
        result = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/some-role/1234/"
        )
        self.assertEqual(result, ("", ""))

    @patch("src.ste_fetcher.requests.Session")
    def test_rate_limit_raises(self, MockSession):
        mock_resp = _make_mock_response("", status=429)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        with self.assertRaises(ste_fetcher.RateLimitError):
            ste_fetcher.fetch_job_description(
                "https://careers.stengg.com/job/some-role/1234/"
            )

    @patch("src.ste_fetcher.requests.Session")
    def test_404_returns_empty(self, MockSession):
        mock_resp = _make_mock_response("Not Found", status=404)
        MockSession.return_value.get.return_value = mock_resp
        MockSession.return_value.headers = {}
        result = ste_fetcher.fetch_job_description(
            "https://careers.stengg.com/job/some-role/1234/"
        )
        self.assertEqual(result, ("", ""))


if __name__ == "__main__":
    unittest.main()
