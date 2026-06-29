import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.wlfc.global"
CAREERS_URL = f"{BASE_URL}/careers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


# Keyed by job URL (CAREERS_URL + #slug) — populated during fetch_jobs().
# fetch_job_description() reads from this cache: zero extra HTTP calls needed.
_desc_cache: dict = {}


def _slugify(text: str, max_len: int = 80) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]


def _get(url: str, max_retries: int = 3, base_delay: float = 2.0):
    """GET with exponential backoff on 429."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[wlfc] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def fetch_jobs() -> list[dict]:
    """
    Fetch all job listings from wlfc.global/careers.

    WLFC publishes all jobs on a single page (ul#careerfilter-result) with
    full inline descriptions — no individual job pages exist. Apply buttons
    open a modal form. We cache each description during this call so
    fetch_job_description() needs zero extra HTTP requests.

    URL: CAREERS_URL#{title-location-slug} — stable across runs.
    No posting_date available.
    """
    global _desc_cache
    _desc_cache = {}

    try:
        resp = _get(CAREERS_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[wlfc] Fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    ul = soup.find("ul", id="careerfilter-result")
    if not ul:
        print("[wlfc] Could not find ul#careerfilter-result — page structure may have changed")
        return []

    jobs = []
    seen_slugs: set[str] = set()

    for li in ul.find_all("li", recursive=False):
        # Title
        title_div = li.find("div", class_="careerfilter-title")
        if not title_div:
            continue
        title = title_div.get_text(strip=True)
        if not title:
            continue

        # Location — first filt-function span found in the li
        location = ""
        func_div = li.find("div", class_="careerfilter-clfunction")
        if func_div:
            func_span = func_div.find("span", class_="filt-function")
            if func_span:
                location = func_span.get_text(strip=True)

        # Company / business area — first filt-business span found
        company = "Willis Lease Finance"
        biz_divs = li.find_all("div", class_="careerfilter-clbusiness")
        for biz in biz_divs:
            biz_span = biz.find("span", class_="filt-business")
            if biz_span:
                name = biz_span.get_text(strip=True)
                if name:
                    company = name
                    break

        # Full inline description (summary + responsibilities + qualifications)
        desc_div = li.find("div", class_="careerfilter-cltxt")
        description = desc_div.get_text(separator=" ", strip=True) if desc_div else ""

        # Build stable URL fragment from title + location.
        # Append counter if two jobs share the same title+location slug.
        base_slug = _slugify(f"{title}-{location}")
        slug = base_slug
        counter = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        seen_slugs.add(slug)

        url = f"{CAREERS_URL}#{slug}"
        _desc_cache[url] = description

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "company": company,
            "source": "wlfc",
            "posting_date": "",  # not available on the WLFC careers page
        })

    print(f"[wlfc] Fetched {len(jobs)} job listing(s)")
    return jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Return the cached inline description for the given job URL.

    Descriptions are scraped during fetch_jobs() — no HTTP call needed here.
    Returns ("", "") on any problem; never raises.
    """
    try:
        return (_desc_cache.get(url, ""), "")
    except Exception:
        return ("", "")
