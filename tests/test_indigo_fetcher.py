import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.indigo_fetcher as indigo_fetcher

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Minimal DWR response with 2 job objects.
# Structure mirrors the real searchJobs.dwr response format:
# - root object (s1) has .postings + .applyWithLinkedInEnabled + .detailURLPrefix
# - s2 is the postings array; s3/s4 are job objects
# - each job has .otherValues → array → field object with fieldId=location_obj
DWR_TWO_JOBS = """\
throw 'allowScriptTagRemoting is false.';
//#DWR-INSERT
//#DWR-REPLY
var s0={};
var s1={};
var s2={};
var s3={};
var s4={};
var s5={};
var s6={};
var s7={};
var s8={};
var s9={};
var s10={};
s1.applyWithLinkedInEnabled=false;
s1.detailURLPrefix="/career?career%5fns=job%5flisting&company=interglobe&navBarLevel=JOB%5fSEARCH&rcm%5fsite%5flocale=en%5fGB&career_job_req_id=";
s1.postings=s2;
s2[0]=s3;
s2[1]=s4;
s3.id=9001;
s3.title="Manager - Engine Shop";
s3.postingDate="10/06/2026";
s3.jobReqSecKey="SECKEY001";
s3.otherValues=s5;
s5[0]=s6;
s6[0]=s7;
s7.fieldId="location_obj";
s7.shortVal="[\\"Location\\",1,\\"Delhi\\"]";
s4.id=9002;
s4.title="Quality Assurance Engineer";
s4.postingDate="09/06/2026";
s4.jobReqSecKey="SECKEY002";
s4.otherValues=s8;
s8[0]=s9;
s9[0]=s10;
s10.fieldId="location_obj";
s10.shortVal="[\\"Location\\",1,\\"Mumbai\\"]";
"""

DWR_EMPTY = """\
throw 'allowScriptTagRemoting is false.';
//#DWR-INSERT
//#DWR-REPLY
var s0={};
"""

DWR_MALFORMED = "not a dwr response at all"


# ── _parse_dwr_jobs ───────────────────────────────────────────────────────────

class TestParseDwrJobs(unittest.TestCase):

    def test_parses_correct_count(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertEqual(len(jobs), 2)

    def test_title_extracted(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertEqual(jobs[0]["title"], "Manager - Engine Shop")
        self.assertEqual(jobs[1]["title"], "Quality Assurance Engineer")

    def test_id_is_string(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertIsInstance(jobs[0]["id"], str)
        self.assertEqual(jobs[0]["id"], "9001")

    def test_url_built_from_numeric_id(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        # URL uses the stable numeric id, not the session-scoped jobReqSecKey
        self.assertIn("9001", jobs[0]["url"])
        self.assertIn("career-in10.hr.cloud.sap", jobs[0]["url"])
        self.assertNotIn("SECKEY", jobs[0]["url"])

    def test_date_converted_to_iso(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertEqual(jobs[0]["posting_date"], "2026-06-10")
        self.assertEqual(jobs[1]["posting_date"], "2026-06-09")

    def test_location_extracted_from_othervalues(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertEqual(jobs[0]["location"], "Delhi")
        self.assertEqual(jobs[1]["location"], "Mumbai")

    def test_company_is_indigo(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertTrue(all(j["company"] == "IndiGo" for j in jobs))

    def test_source_is_indigo(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        self.assertTrue(all(j["source"] == "indigo" for j in jobs))

    def test_empty_dwr_returns_empty_list(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_EMPTY)
        self.assertEqual(jobs, [])

    def test_malformed_dwr_returns_empty_list(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_MALFORMED)
        self.assertEqual(jobs, [])

    def test_required_keys_present(self):
        jobs = indigo_fetcher._parse_dwr_jobs(DWR_TWO_JOBS)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, jobs[0])


# ── fetch_jobs ────────────────────────────────────────────────────────────────

class TestFetchJobs(unittest.TestCase):

    def _make_mock_browser(self, dwr_response_text: str):
        """Build a mock Playwright context that fires the searchJobs DWR response."""
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_browser = MagicMock()

        # Simulate page.on("response", handler) by capturing the handler and
        # firing it when page.evaluate() is called.
        captured = {}

        def fake_on(event, handler):
            captured[event] = handler

        mock_page.on.side_effect = fake_on

        def fake_evaluate(_js):
            if "response" in captured:
                mock_resp = MagicMock()
                mock_resp.url = "https://career-in10.hr.cloud.sap/xi/ajax/remoting/call/plaincall/careerJobSearchControllerProxy.searchJobs.dwr"
                mock_resp.body.return_value = dwr_response_text.encode("utf-8")
                captured["response"](mock_resp)

        mock_page.evaluate.side_effect = fake_evaluate
        mock_context.new_page.return_value = mock_page
        mock_browser.new_context.return_value = mock_context

        return mock_browser

    @patch("src.indigo_fetcher.sync_playwright")
    def test_returns_job_list(self, mock_pw):
        mock_browser = self._make_mock_browser(DWR_TWO_JOBS)
        mock_pw.return_value.__enter__.return_value.firefox.launch.return_value = mock_browser

        jobs = indigo_fetcher.fetch_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "Manager - Engine Shop")

    @patch("src.indigo_fetcher.sync_playwright")
    def test_returns_empty_on_no_dwr(self, mock_pw):
        mock_browser = self._make_mock_browser("")
        mock_pw.return_value.__enter__.return_value.firefox.launch.return_value = mock_browser

        jobs = indigo_fetcher.fetch_jobs()
        self.assertEqual(jobs, [])

    @patch("src.indigo_fetcher.sync_playwright")
    def test_jobs_have_required_keys(self, mock_pw):
        mock_browser = self._make_mock_browser(DWR_TWO_JOBS)
        mock_pw.return_value.__enter__.return_value.firefox.launch.return_value = mock_browser

        jobs = indigo_fetcher.fetch_jobs()
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, jobs[0])

    @patch("src.indigo_fetcher.sync_playwright")
    def test_browser_always_closed(self, mock_pw):
        mock_browser = self._make_mock_browser(DWR_TWO_JOBS)
        mock_pw.return_value.__enter__.return_value.firefox.launch.return_value = mock_browser

        indigo_fetcher.fetch_jobs()
        mock_browser.close.assert_called_once()

    @patch("src.indigo_fetcher.sync_playwright")
    def test_source_is_indigo(self, mock_pw):
        mock_browser = self._make_mock_browser(DWR_TWO_JOBS)
        mock_pw.return_value.__enter__.return_value.firefox.launch.return_value = mock_browser

        jobs = indigo_fetcher.fetch_jobs()
        self.assertTrue(all(j["source"] == "indigo" for j in jobs))


# ── fetch_job_description ─────────────────────────────────────────────────────

class TestFetchJobDescription(unittest.TestCase):

    def test_returns_tuple(self):
        result = indigo_fetcher.fetch_job_description("https://career-in10.hr.cloud.sap/career?career_job_req_id=abc")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_returns_empty_strings(self):
        result = indigo_fetcher.fetch_job_description("https://career-in10.hr.cloud.sap/career?career_job_req_id=abc")
        self.assertEqual(result, ("", ""))

    def test_empty_url_returns_empty(self):
        result = indigo_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))

    def test_no_network_call_made(self):
        with patch("src.indigo_fetcher.sync_playwright") as mock_pw:
            indigo_fetcher.fetch_job_description("https://career-in10.hr.cloud.sap/career?career_job_req_id=abc")
            mock_pw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
