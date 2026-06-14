import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://fltechnics.com"
LISTING_URL = f"{BASE_URL}/careers/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


def _get(url, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[fltechnics] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _parse_page(html: str) -> list[dict]:
    """Parse one page of the FL Technics careers listing."""
    soup = BeautifulSoup(html, "lxml")
    items = soup.find_all("div", class_="asgc-list-item-details")
    jobs = []
    for item in items:
        title_col = item.find("div", class_="col-title")
        a = title_col.find("a") if title_col else None
        if not a:
            continue
        title = a.get_text(strip=True)
        url = a.get("href", "").strip()
        if not url:
            continue

        company_col = item.find("div", class_="col-company")
        company = company_col.get_text(strip=True) if company_col else "FL Technics"

        location_col = item.find("div", class_="col-location")
        location = location_col.get_text(strip=True) if location_col else ""

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "company": company,
            "source": "fltechnics",
            "posting_date": "",
        })
    return jobs


def fetch_jobs() -> list[dict]:
    """
    Fetch all FL Technics job listings across paginated pages.
    Descriptions are not available via static HTML (rendered via JS modal).
    fetch_job_description returns ('', '') — Gate 2 is bypassed for this source.
    """
    all_jobs: list[dict] = []
    seen_urls: set[str] = set()
    page = 1

    while True:
        url = LISTING_URL if page == 1 else f"{LISTING_URL}?p-page={page}"
        print(f"[fltechnics] Fetching page {page}...")
        try:
            resp = _get(url)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[fltechnics] Fetch error (page {page}): {exc}")
            break

        jobs = _parse_page(resp.text)
        if not jobs:
            print(f"[fltechnics] Page {page}: 0 items — stopping")
            break

        new = 0
        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                all_jobs.append(job)
                new += 1
        print(f"[fltechnics] Page {page}: {len(jobs)} items, {new} new unique")
        page += 1
        time.sleep(0.5)

    print(f"[fltechnics] Total unique jobs: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Descriptions are JS-rendered via modal on the listing page — not available
    from static HTML. Returns ('', '') unconditionally, which causes Gate 2 bypass.
    """
    return ("", "")
