import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import unittest

from src.notifier import format_job_message, _date_sortable, _display_date


# ── _date_sortable tests ──────────────────────────────────────────────────────

class TestDateSortable(unittest.TestCase):

    def test_yyyy_mm_dd(self):
        self.assertEqual(_date_sortable({"posting_date": "2026-06-15"}), "2026-06-15")

    def test_iso_8601_extracts_date(self):
        self.assertEqual(
            _date_sortable({"posting_date": "2026-05-01T00:00:00.000+0000"}),
            "2026-05-01",
        )

    def test_safran_d_m_yyyy_single_digit(self):
        # "6/10/2026" = day 6, month 10 (D/M/YYYY, European format used by Safran)
        self.assertEqual(_date_sortable({"date": "6/10/2026"}), "2026-10-06")

    def test_safran_dd_mm_yyyy_two_digit(self):
        self.assertEqual(_date_sortable({"date": "06/10/2026"}), "2026-10-06")

    def test_safran_single_digit_month_and_day(self):
        # "6/9/2026" = day 6, month 9
        self.assertEqual(_date_sortable({"date": "6/9/2026"}), "2026-09-06")

    def test_prefers_posting_date_over_date(self):
        # posting_date takes priority over date (checked first)
        self.assertEqual(
            _date_sortable({"posting_date": "2026-01-01", "date": "6/10/2026"}),
            "2026-01-01",
        )

    def test_missing_date_returns_sentinel(self):
        self.assertEqual(_date_sortable({}), "0000-00-00")

    def test_empty_date_returns_sentinel(self):
        self.assertEqual(_date_sortable({"posting_date": ""}), "0000-00-00")


# ── _display_date tests ───────────────────────────────────────────────────────

class TestDisplayDate(unittest.TestCase):

    def test_yyyy_mm_dd_shown_as_is(self):
        self.assertEqual(_display_date({"posting_date": "2026-06-15"}), "2026-06-15")

    def test_iso_8601_shows_date_only(self):
        self.assertEqual(
            _display_date({"posting_date": "2026-05-01T00:00:00.000+0000"}),
            "2026-05-01",
        )

    def test_safran_date_normalized(self):
        self.assertEqual(_display_date({"date": "6/10/2026"}), "2026-10-06")

    def test_no_date_returns_na(self):
        self.assertEqual(_display_date({}), "N/A")

    def test_empty_date_returns_na(self):
        self.assertEqual(_display_date({"posting_date": ""}), "N/A")


# ── format_job_message tests ──────────────────────────────────────────────────

class TestFormatJobMessage(unittest.TestCase):

    def _make_job(self, **overrides):
        base = {
            "title": "Senior MRO Manager",
            "company": "Emirates Engineering",
            "location": "Dubai, UAE",
            "url": "https://example.com/job/123",
            "posting_date": "2026-06-10",
        }
        base.update(overrides)
        return base

    def test_contains_title(self):
        msg = format_job_message(self._make_job())
        self.assertIn("Senior MRO Manager", msg)

    def test_contains_company(self):
        msg = format_job_message(self._make_job())
        self.assertIn("Emirates Engineering", msg)

    def test_contains_location(self):
        msg = format_job_message(self._make_job())
        self.assertIn("Dubai, UAE", msg)

    def test_contains_url(self):
        msg = format_job_message(self._make_job())
        self.assertIn("https://example.com/job/123", msg)

    def test_shows_posting_date_yyyy_mm_dd(self):
        msg = format_job_message(self._make_job(posting_date="2026-06-10"))
        self.assertIn("Posted  : 2026-06-10", msg)

    def test_shows_posting_date_from_iso_8601(self):
        # GE Aerospace date format
        msg = format_job_message(self._make_job(posting_date="2026-05-01T00:00:00.000+0000"))
        self.assertIn("Posted  : 2026-05-01", msg)

    def test_shows_safran_date_normalized(self):
        # Safran uses D/M/YYYY with the "date" key
        job = self._make_job()
        del job["posting_date"]
        job["date"] = "6/10/2026"
        msg = format_job_message(job)
        self.assertIn("Posted  : 2026-10-06", msg)

    def test_shows_na_when_no_date(self):
        job = {"title": "MRO Manager", "company": "Safran", "location": "Paris", "url": "https://x.com"}
        msg = format_job_message(job)
        self.assertIn("Posted  : N/A", msg)

    def test_title_wrapped_in_bold_tags(self):
        msg = format_job_message(self._make_job())
        self.assertIn("<b>Senior MRO Manager</b>", msg)


if __name__ == "__main__":
    unittest.main()
