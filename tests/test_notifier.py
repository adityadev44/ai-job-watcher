import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import src.notifier as notifier
from src.notifier import format_job_message, _date_sortable, _display_date


@contextlib.contextmanager
def _tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


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


# ── pipeline_failures.json concurrency ────────────────────────────────────
#
# run_all.py runs every company pipeline as its own SUBPROCESS (not just a
# thread), so up to 40 independent processes can call
# notify_pipeline_error()/reset_failure_count() around the same moment.
# Without a cross-process lock around the read-modify-write cycle, two
# concurrent writers touching different keys in the same JSON file can
# silently clobber each other's update (classic lost-update race).

class TestFailuresConcurrency(unittest.TestCase):

    def setUp(self):
        self._tmp = self.enterContext(_tmp_dir())
        self._failures_path = self._tmp / "pipeline_failures.json"
        self._lock_path = self._tmp / ".pipeline_failures.lock"
        self._patches = [
            patch.object(notifier, "_FAILURES_PATH", self._failures_path),
            patch.object(notifier, "_FAILURES_LOCK_PATH", self._lock_path),
            patch.object(notifier, "send_email", lambda *a, **kw: None),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_cross_process_lock_serializes_access(self):
        """While one holder has the lock, a second acquire attempt must wait
        for release rather than succeeding immediately (real mutual exclusion,
        not just non-crashing)."""
        lock = notifier._CrossProcessLock(self._lock_path, timeout=5.0, poll=0.01)
        order = []

        def _holder():
            with lock:
                order.append("A-enter")
                time.sleep(0.2)
                order.append("A-exit")

        def _waiter():
            time.sleep(0.05)  # ensure A has the lock first
            with lock:
                order.append("B-enter")

        t1 = threading.Thread(target=_holder)
        t2 = threading.Thread(target=_waiter)
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(order, ["A-enter", "A-exit", "B-enter"])

    def test_concurrent_notify_pipeline_error_no_lost_updates(self):
        """40 'companies' (simulating run_all.py's subprocess fan-out) each
        report exactly one failure concurrently, each under its own key. Every
        key must end up recorded with count=1 -- none silently dropped."""
        sources = [f"company_{i}" for i in range(40)]

        # Widen the read-modify-write race window so a missing lock would
        # reliably manifest as lost updates instead of passing by luck.
        real_write = notifier._write_failures

        def _slow_write(data):
            time.sleep(0.005)
            real_write(data)

        with patch.object(notifier, "_write_failures", side_effect=_slow_write):
            with ThreadPoolExecutor(max_workers=len(sources)) as pool:
                list(pool.map(
                    lambda s: notifier.notify_pipeline_error(s, RuntimeError("boom")),
                    sources,
                ))

        final = json.loads(self._failures_path.read_text(encoding="utf-8"))
        for s in sources:
            self.assertEqual(final.get(s), 1, f"lost update for {s}: {final.get(s)!r}")

    def test_reset_failure_count_clears_to_zero(self):
        self._failures_path.write_text(json.dumps({"rolls_royce": 2}), encoding="utf-8")
        notifier.reset_failure_count("rolls_royce")
        final = json.loads(self._failures_path.read_text(encoding="utf-8"))
        self.assertEqual(final["rolls_royce"], 0)

    def test_notify_pipeline_error_fires_and_resets_at_threshold(self):
        with patch.object(notifier, "send_email") as mock_send:
            notifier.notify_pipeline_error("aar", RuntimeError("1"))
            notifier.notify_pipeline_error("aar", RuntimeError("2"))
            mock_send.assert_not_called()
            notifier.notify_pipeline_error("aar", RuntimeError("3"))
            mock_send.assert_called_once()

        final = json.loads(self._failures_path.read_text(encoding="utf-8"))
        self.assertEqual(final["aar"], 0)


if __name__ == "__main__":
    unittest.main()
