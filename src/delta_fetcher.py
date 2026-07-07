"""
Delta Air Lines TechOps job fetcher.

Source  : https://delta.avature.net/en_US/careers/SearchJobs
ATS     : Avature (same platform as Emirates Group) — this tenant sits
          behind an AWS WAF JS challenge. Plain requests/curl_cffi get a
          202 challenge page (window.gokuProps + awswaf.com/challenge.js);
          Playwright (any real browser engine) clears it automatically in a
          few seconds — it is a proof-of-work/fingerprint check, not a
          CAPTCHA requiring interaction.

Strategy: Playwright loads the search page once to clear the WAF challenge
          and capture cookies/tokens on a module-level singleton page. From
          then on:
            - Listing pages ARE server-rendered — cheap pagination via
              page.request.get(f"{SEARCH_URL}/?jobOffset=N"), no fresh
              navigation needed.
            - Individual job detail pages are NOT server-rendered — the
              description text is assembled client-side after the initial
              shell loads (confirmed: page.request.get() on a detail URL
              returns the page shell but no description text, even with a
              valid WAF cookie and navigation-like headers; only a real
              page.goto() + wait produces it). fetch_job_description() does
              a real per-job navigation on the shared page and extracts:
                - div[itemprop="description"]                -> description
                - article.article--details .paragraph (fa-archive icon)
                                                               -> division
                - article.article--details .paragraph (fa-calendar-o icon)
                                                               -> posting date
          The Playwright browser/page is never explicitly closed — each
          pipeline run is an isolated short-lived subprocess (src/run_all.py),
          so it is cleaned up on process exit.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SOURCE = "delta"
SEARCH_URL = "https://delta.avature.net/en_US/careers/SearchJobs"
PAGE_SIZE = 10

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
)}


class RateLimitError(Exception):
    """Raised when the portal returns HTTP 429."""


# Lazily-started Playwright singleton, reused by fetch_jobs() and
# fetch_job_description() within one pipeline process.
_playwright = None
_browser = None
_page = None

# Extra fields (division, posting_date) captured during fetch_job_description(),
# looked up afterward by get_company()/get_posting_date() for the small set of
# jobs that make it into a final alert (matcher.py discards fetch_job_description's
# own tuple date — see PLAYBOOK.md "Bugs We Hit").
_desc_cache: dict[str, dict] = {}


def _ensure_page():
    global _playwright, _browser, _page
    if _page is not None:
        return _page
    _playwright = sync_playwright().start()
    _browser = _playwright.firefox.launch(headless=True)
    _page = _browser.new_page(user_agent=_BROWSER_UA)
    print(f"[{SOURCE}] Loading {SEARCH_URL} to clear AWS WAF challenge...")
    _page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
    try:
        _page.wait_for_selector("li.list__item", timeout=20000)
    except Exception:
        _page.wait_for_timeout(6000)
    return _page


def _parse_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for li in soup.select("li.list__item"):
        a = li.select_one(".list__item__text__title a")
        if not a:
            continue
        title = a.get_text(strip=True)
        url = (a.get("href") or "").strip()
        if not (title and url):
            continue
        subtitle_spans = li.select(".list__item__text__subtitle span")
        location = subtitle_spans[0].get_text(strip=True).rstrip(".") if subtitle_spans else ""
        ref_text = subtitle_spans[1].get_text(strip=True) if len(subtitle_spans) > 1 else ""
        m = re.search(r"(\d+)", ref_text)
        job_id = m.group(1) if m else ""
        if not job_id:
            m = re.search(r"jobId=(\d+)", url)
            job_id = m.group(1) if m else ""
        jobs.append({
            "id": job_id,
            "title": title,
            "url": url,
            "location": location,
            "posting_date": "",
            "company": "",
            "source": SOURCE,
        })
    return jobs


def fetch_jobs(max_listings: int = 150, inter_page_delay: float = 0.3) -> list[dict]:
    page = _ensure_page()
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0

    while len(all_jobs) < max_listings:
        list_url = f"{SEARCH_URL}/?jobOffset={offset}"
        try:
            resp = page.request.get(list_url)
        except Exception as exc:
            print(f"[{SOURCE}] Pagination request failed at offset={offset}: {exc}")
            break
        if resp.status == 429:
            raise RateLimitError(f"Rate-limited at offset {offset}")
        if not resp.ok:
            print(f"[{SOURCE}] HTTP {resp.status} at offset={offset} - stopping")
            break

        page_jobs = _parse_list_page(resp.text())
        if not page_jobs:
            break

        new_count = 0
        for job in page_jobs:
            if job["id"] and job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
                new_count += 1
        print(f"[{SOURCE}]   offset={offset}: {len(page_jobs)} jobs ({new_count} new)")
        if new_count == 0:
            break

        offset += PAGE_SIZE
        time.sleep(inter_page_delay)

    print(f"[{SOURCE}] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs[:max_listings]


def _parse_posting_date(text: str) -> str:
    m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text)
    if not m:
        return ""
    day, mon, year = m.groups()
    month_num = _MONTHS.get(mon.lower())
    if not month_num:
        return ""
    return f"{year}-{month_num:02d}-{int(day):02d}"


def fetch_job_description(url: str) -> tuple[str, str]:
    if not url:
        return ("", "")
    if url in _desc_cache:
        cached = _desc_cache[url]
        return (cached.get("description", ""), cached.get("posting_date", ""))

    try:
        page = _ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('[itemprop="description"]', timeout=20000)
        html = page.content()
    except Exception as exc:
        print(f"[{SOURCE}] Description fetch failed for {url}: {exc}")
        return ("", "")

    soup = BeautifulSoup(html, "html.parser")
    desc_el = soup.find(attrs={"itemprop": "description"})
    description = desc_el.get_text(separator=" ", strip=True)[:8000] if desc_el else ""

    division = ""
    posting_date = ""
    details = soup.select_one("article.article--details .article__content")
    if details:
        for p in details.select("p.paragraph"):
            icon = p.find("i")
            icon_class = icon.get("class", []) if icon else []
            text = p.get_text(strip=True)
            if "fa-archive" in icon_class:
                division = text
            elif "fa-calendar-o" in icon_class:
                posting_date = _parse_posting_date(text)

    _desc_cache[url] = {"description": description, "division": division, "posting_date": posting_date}
    return (description, posting_date)


def get_company(url: str) -> str:
    division = _desc_cache.get(url, {}).get("division", "")
    if division and "delta" not in division.lower():
        return f"Delta {division}"
    return "Delta Air Lines"


def get_posting_date(url: str) -> str:
    return _desc_cache.get(url, {}).get("posting_date", "")
