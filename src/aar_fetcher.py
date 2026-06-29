"""
AAR Corp job fetcher.

Source  : https://aarcorp.taleo.net/careersection/2/jobsearch.ftl?lang=en
ATS     : Oracle Taleo Enterprise Edition (JavaScript-rendered, session-based)
Strategy: Playwright loads the job search page, waits for job rows to render,
          then parses the table for title, location, and requisition link.
          Description pages are fetched with a shared requests.Session using
          the Playwright-established cookies.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SOURCE = "aar"
BASE_URL = "https://aarcorp.taleo.net"
SEARCH_URL = f"{BASE_URL}/careersection/2/jobsearch.ftl?lang=en"
JOB_DETAIL_BASE = f"{BASE_URL}/careersection/2/jobdetail.ftl"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Shared requests session for description fetches (re-uses Playwright cookies)
_requests_session: requests.Session | None = None


class RateLimitError(Exception):
    """Raised when the portal returns HTTP 429."""


def _parse_jobs_from_html(html: str) -> list[dict]:
    """Parse job rows from the Taleo job listing table."""
    soup = BeautifulSoup(html, "html.parser")

    # Taleo Enterprise renders jobs in a table with id="list" or class containing "job-list"
    # Rows are <tr> elements; each row has data attributes or links for the job
    jobs = []
    seen_ids: set[str] = set()

    # Look for job links: they match /careersection/2/jobdetail.ftl?job=NNNNN
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r"jobdetail\.ftl\?job=(\d+)", href)
        if not m:
            continue
        job_num = m.group(1)
        if job_num in seen_ids:
            continue
        seen_ids.add(job_num)

        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        # Build canonical URL
        url = f"{JOB_DETAIL_BASE}?job={job_num}&lang=en"

        # Location: find the nearest <td> sibling with location text
        location = ""
        tr = a.find_parent("tr")
        if tr:
            cells = tr.find_all("td")
            for i, cell in enumerate(cells):
                if a in cell.find_all("a"):
                    # Location is often 1-2 cells to the right of the title cell
                    if i + 1 < len(cells):
                        location = cells[i + 1].get_text(strip=True)
                    break

        jobs.append({
            "id": job_num,
            "title": title,
            "url": url,
            "location": location,
            "company": "AAR Corp",
            "source": SOURCE,
        })

    return jobs


def fetch_jobs(config: dict | None = None) -> list[dict]:
    """
    Fetch AAR Corp job listings via Playwright.

    Uses headless Firefox to render the Taleo careers page, waits for job rows
    to appear, then parses the HTML for job data.

    Returns a list of job dicts.
    """
    global _requests_session
    jobs: list[dict] = []

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = context.new_page()

            print(f"[aar] Loading {SEARCH_URL} …")
            try:
                page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
            except Exception:
                page.wait_for_timeout(8000)

            page.wait_for_timeout(4000)

            # Try to wait for job rows to appear (Taleo renders them via AJAX)
            try:
                page.wait_for_selector(
                    "a[href*='jobdetail.ftl'], tr.listRow, .job-title",
                    timeout=15000,
                )
            except Exception:
                pass  # Proceed anyway — parse whatever is in the DOM

            html = page.content()

            # Capture cookies for description fetches
            cookies = context.cookies()
            _requests_session = requests.Session()
            _requests_session.headers.update({
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            })
            for cookie in cookies:
                _requests_session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie.get("domain", "")
                )

        except Exception as exc:
            print(f"[aar] Playwright error: {exc}")
            html = ""
        finally:
            browser.close()

    if html:
        jobs = _parse_jobs_from_html(html)
        print(f"[aar] Parsed {len(jobs)} jobs from Taleo HTML")
    else:
        print("[aar] No HTML captured — returning 0 jobs")

    return jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Fetch the plain-text description from a Taleo job detail page.
    Uses the requests.Session established during fetch_jobs() if available.
    Returns ("", "") on any error — never raises.
    """
    try:
        if _requests_session is not None:
            sess = _requests_session
        else:
            sess = requests.Session()
            sess.headers.update({"User-Agent": _BROWSER_UA})

        time.sleep(0.5)
        resp = sess.get(url, timeout=30)
        if resp.status_code == 429:
            return ("", "")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        # Taleo job details are in <div class="aspf-content"> or a main section
        content = (
            soup.find("div", class_="aspf-content")
            or soup.find("div", id="jobdetails")
            or soup.find("main")
        )
        if content:
            text = content.get_text(separator=" ", strip=True)
        else:
            text = soup.get_text(separator=" ", strip=True)

        return (text[:8000], "")
    except Exception:
        return ("", "")
