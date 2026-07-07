import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest
from unittest.mock import patch, MagicMock

import src.delta_fetcher as delta_fetcher


def _list_page_html(jobs):
    """jobs: list of (title, url, location, ref_number)"""
    items = ""
    for title, url, location, ref in jobs:
        items += f"""
        <li class="list__item">
            <div class="list__item__text">
                <div class="list__item__text__title"><a href="{url}">{title}</a></div>
                <div class="list__item__text__subtitle">
                    <span>{location}.</span>
                    <span>Ref #{ref}</span>
                </div>
            </div>
        </li>
        """
    return f'<html><body><ul class="list list--jobs">{items}</ul></body></html>'


DETAIL_HTML = """
<html><body>
<div class="section__content">
    <article class="article article--details">
        <div class="article__content">
            <p class="paragraph"><i class="fa fa-globe"></i> <strong>United States, Georgia, Atlanta</strong></p>
            <p class="paragraph"><i class="fa fa-archive"></i> <strong>TechOps</strong></p>
            <p class="paragraph"><i class="fa fa-calendar-o"></i><strong> 26-Jun-2026</strong></p>
            <p class="paragraph"><i class="fa fa-suitcase"></i> <strong>Ref #: 33122</strong></p>
        </div>
    </article>
</div>
<div class="section__content">
    <article class="article article--details">
        <div class="article__content article__content--rich-text" itemprop="description">
            <div><div>Oversee GE90 and CFM56 engine overhaul shop operations, workscope planning,
            and Part 145 airworthiness compliance for the MRO engine shop.</div></div>
        </div>
    </article>
</div>
</body></html>
"""


class TestParseListPage(unittest.TestCase):

    def test_parses_correct_count(self):
        html = _list_page_html([
            ("Manager, Engine Shop", "https://delta.avature.net/en_US/careers/JobDetail/Manager-Engine-Shop/1001?jobId=1001", "United States, Georgia, Atlanta", "1001"),
            ("Aircraft Maintenance Technician", "https://delta.avature.net/en_US/careers/JobDetail/AMT/1002?jobId=1002", "United States, Minnesota, Minneapolis", "1002"),
        ])
        jobs = delta_fetcher._parse_list_page(html)
        self.assertEqual(len(jobs), 2)

    def test_required_keys_present(self):
        html = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001")])
        jobs = delta_fetcher._parse_list_page(html)
        for key in ("id", "title", "location", "posting_date", "url", "company", "source"):
            self.assertIn(key, jobs[0])

    def test_id_from_ref_number(self):
        html = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001")])
        jobs = delta_fetcher._parse_list_page(html)
        self.assertEqual(jobs[0]["id"], "1001")

    def test_location_strips_trailing_period(self):
        html = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "United States, Georgia, Atlanta", "1001")])
        jobs = delta_fetcher._parse_list_page(html)
        self.assertEqual(jobs[0]["location"], "United States, Georgia, Atlanta")

    def test_source_is_delta(self):
        html = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001")])
        jobs = delta_fetcher._parse_list_page(html)
        self.assertEqual(jobs[0]["source"], "delta")

    def test_empty_page_returns_empty_list(self):
        jobs = delta_fetcher._parse_list_page('<html><body><ul class="list list--jobs"></ul></body></html>')
        self.assertEqual(jobs, [])

    def test_row_without_link_skipped(self):
        html = '<html><body><ul class="list list--jobs"><li class="list__item"><div class="list__item__text"></div></li></ul></body></html>'
        jobs = delta_fetcher._parse_list_page(html)
        self.assertEqual(jobs, [])


class TestParsePostingDate(unittest.TestCase):

    def test_converts_dd_mon_yyyy(self):
        self.assertEqual(delta_fetcher._parse_posting_date("26-Jun-2026"), "2026-06-26")

    def test_single_digit_day(self):
        self.assertEqual(delta_fetcher._parse_posting_date("6-Jan-2026"), "2026-01-06")

    def test_no_match_returns_empty(self):
        self.assertEqual(delta_fetcher._parse_posting_date("no date here"), "")


class TestFetchJobs(unittest.TestCase):

    def setUp(self):
        delta_fetcher._desc_cache = {}

    def _mock_page(self, pages_by_offset):
        page = MagicMock()

        def fake_get(url):
            resp = MagicMock()
            resp.status = 200
            resp.ok = True
            for offset, html in pages_by_offset.items():
                if f"jobOffset={offset}" in url:
                    resp.text.return_value = html
                    return resp
            resp.text.return_value = '<html><body><ul class="list list--jobs"></ul></body></html>'
            return resp

        page.request.get.side_effect = fake_get
        return page

    @patch("src.delta_fetcher._ensure_page")
    def test_returns_job_list(self, mock_ensure):
        html = _list_page_html([
            ("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001"),
            ("Aircraft Maintenance Technician", "https://x/JobDetail/b/1002?jobId=1002", "Minneapolis", "1002"),
        ])
        mock_ensure.return_value = self._mock_page({0: html})

        jobs = delta_fetcher.fetch_jobs(max_listings=50)
        self.assertEqual(len(jobs), 2)

    @patch("src.delta_fetcher._ensure_page")
    def test_stops_pagination_on_empty_page(self, mock_ensure):
        page1 = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001")])
        mock_ensure.return_value = self._mock_page({0: page1})

        jobs = delta_fetcher.fetch_jobs(max_listings=50)
        self.assertEqual(len(jobs), 1)

    @patch("src.delta_fetcher._ensure_page")
    def test_dedupes_by_id_across_pages(self, mock_ensure):
        page1 = _list_page_html([("Manager, Engine Shop", "https://x/JobDetail/a/1001?jobId=1001", "Atlanta", "1001")])
        mock_ensure.return_value = self._mock_page({0: page1, 10: page1})

        jobs = delta_fetcher.fetch_jobs(max_listings=50)
        self.assertEqual(len(jobs), 1)

    @patch("src.delta_fetcher._ensure_page")
    def test_raises_rate_limit_error_on_429(self, mock_ensure):
        page = MagicMock()
        resp = MagicMock()
        resp.status = 429
        page.request.get.return_value = resp
        mock_ensure.return_value = page

        with self.assertRaises(delta_fetcher.RateLimitError):
            delta_fetcher.fetch_jobs(max_listings=50)

    @patch("src.delta_fetcher._ensure_page")
    def test_respects_max_listings(self, mock_ensure):
        html = _list_page_html([
            (f"Manager {i}", f"https://x/JobDetail/a/{i}?jobId={i}", "Atlanta", str(i))
            for i in range(1, 11)
        ])
        mock_ensure.return_value = self._mock_page({0: html})

        jobs = delta_fetcher.fetch_jobs(max_listings=5)
        self.assertEqual(len(jobs), 5)


class TestFetchJobDescription(unittest.TestCase):

    def setUp(self):
        delta_fetcher._desc_cache = {}

    @patch("src.delta_fetcher._ensure_page")
    def test_returns_description_and_date(self, mock_ensure):
        page = MagicMock()
        page.content.return_value = DETAIL_HTML
        mock_ensure.return_value = page

        desc, posting_date = delta_fetcher.fetch_job_description("https://delta.avature.net/en_US/careers/JobDetail/x/33122?jobId=33122")
        self.assertIn("GE90", desc)
        self.assertIn("CFM56", desc)
        self.assertEqual(posting_date, "2026-06-26")

    @patch("src.delta_fetcher._ensure_page")
    def test_caches_result(self, mock_ensure):
        page = MagicMock()
        page.content.return_value = DETAIL_HTML
        mock_ensure.return_value = page

        url = "https://delta.avature.net/en_US/careers/JobDetail/x/33122?jobId=33122"
        delta_fetcher.fetch_job_description(url)
        delta_fetcher.fetch_job_description(url)
        self.assertEqual(page.goto.call_count, 1)

    @patch("src.delta_fetcher._ensure_page")
    def test_populates_get_company_and_get_posting_date(self, mock_ensure):
        page = MagicMock()
        page.content.return_value = DETAIL_HTML
        mock_ensure.return_value = page

        url = "https://delta.avature.net/en_US/careers/JobDetail/x/33122?jobId=33122"
        delta_fetcher.fetch_job_description(url)
        self.assertEqual(delta_fetcher.get_company(url), "Delta TechOps")
        self.assertEqual(delta_fetcher.get_posting_date(url), "2026-06-26")

    def test_empty_url_returns_empty(self):
        result = delta_fetcher.fetch_job_description("")
        self.assertEqual(result, ("", ""))

    @patch("src.delta_fetcher._ensure_page")
    def test_navigation_failure_returns_empty(self, mock_ensure):
        page = MagicMock()
        page.goto.side_effect = Exception("navigation timeout")
        mock_ensure.return_value = page

        result = delta_fetcher.fetch_job_description("https://delta.avature.net/en_US/careers/JobDetail/x/1?jobId=1")
        self.assertEqual(result, ("", ""))

    def test_get_company_falls_back_to_delta_air_lines(self):
        self.assertEqual(delta_fetcher.get_company("https://unseen-url"), "Delta Air Lines")

    def test_get_posting_date_falls_back_to_empty(self):
        self.assertEqual(delta_fetcher.get_posting_date("https://unseen-url"), "")


if __name__ == "__main__":
    unittest.main()
