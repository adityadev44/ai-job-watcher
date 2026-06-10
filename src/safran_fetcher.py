import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://careers.safran-group.com"
SEARCH_PATH = "/job/list-of-all-jobs.aspx"
LCID = "1033"  # English (US)
PAGES_PER_KEYWORD = 3

SEARCH_KEYWORDS = [
    "engine overhaul",
    "MRO manager",
    "shop manager",
    "powerplant",
    "engine shop",
    "quality manager",
    "production manager",
    "technical services",
]

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


# Populated by fetch_job_description() as a side-effect of the page fetch.
# Keyed by the job URL exactly as it appears in the job dict (no LCID suffix).
_company_cache: dict = {}


def get_company(url: str) -> str:
    """Return the cached company name for a job URL, or empty string if not cached."""
    return _company_cache.get(url, "")


def _get(url, params=None, max_retries=3, base_delay=2.0):
    """
    GET with exponential backoff on 429.
    Raises RateLimitError after max_retries.
    Raises requests.HTTPError on other 4xx/5xx.
    """
    for attempt in range(max_retries + 1):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[safran] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _parse_list_page(html):
    """
    Parse one search-results page.
    Returns list of job dicts: title, url, date, location, contract, ref, company.
    Company is empty here — populated by fetch_job_description().
    """
    soup = BeautifulSoup(html, "lxml")
    items = soup.find_all("li", class_="ts-offer-list-item")
    jobs = []
    for item in items:
        title_el = item.find("a", class_="ts-offer-list-item__title-link")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        url = (BASE_URL + href) if href.startswith("/") else href

        meta_ul = item.find("ul", class_="ts-offer-list-item__description")
        meta = [li.get_text(strip=True) for li in meta_ul.find_all("li")] if meta_ul else []

        jobs.append({
            "title": title,
            "url": url,
            "ref": meta[0] if len(meta) > 0 else "",
            "date": meta[1] if len(meta) > 1 else "",
            "contract": meta[2] if len(meta) > 2 else "",
            "location": meta[3] if len(meta) > 3 else "",
            "company": "",
            "source": "safran",
        })
    return jobs


def _total_pages(html, per_page=20):
    """Extract total offer count from the page and calculate page count."""
    soup = BeautifulSoup(html, "lxml")
    el = soup.find(id=re.compile(r"TotalOffers", re.I))
    if not el:
        return 1
    m = re.search(r"(\d+)", el.get_text())
    if not m:
        return 1
    total = int(m.group(1))
    return max(1, (total + per_page - 1) // per_page)


def fetch_jobs():
    """
    Fetch Safran job listings across all search keywords.
    Returns a deduplicated list of job dicts sorted newest-first.
    """
    seen_urls = set()
    all_jobs = []

    for keyword in SEARCH_KEYWORDS:
        print(f"[safran] Searching: '{keyword}'")
        page = 1

        while page <= PAGES_PER_KEYWORD:
            params = {
                "LCID": LCID,
                "Keywords": keyword,
                "mode": "list",
            }
            if page > 1:
                params["page"] = str(page)

            try:
                resp = _get(BASE_URL + SEARCH_PATH, params=params)
            except RateLimitError:
                raise
            except Exception as exc:
                print(f"[safran] Fetch error (keyword='{keyword}', page={page}): {exc}")
                break

            html = resp.text
            jobs = _parse_list_page(html)

            if not jobs:
                print(f"[safran]   Page {page}: no results — stopping pagination")
                break

            new = 0
            for job in jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
                    new += 1

            print(f"[safran]   Page {page}: {len(jobs)} results, {new} new")

            # Don't exceed PAGES_PER_KEYWORD even if more pages exist
            page += 1

            # Small polite delay between pages
            if page <= PAGES_PER_KEYWORD:
                time.sleep(0.5)

        time.sleep(1.0)  # polite delay between keyword searches

    print(f"[safran] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(url):
    """
    Fetch the full text of a Safran job description page.
    Returns plain text of the description body (contenu-ficheoffre div).
    Returns empty string on any failure — never raises (except RateLimitError).
    As a side-effect, populates _company_cache[url] with the entity name.
    """
    if not url:
        return ""

    original_url = url  # cache key — as given, without LCID suffix

    # Ensure LCID is on the URL for English content
    if "LCID=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}LCID={LCID}"

    try:
        resp = _get(url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[safran] Description fetch failed ({url}): {exc}")
        return ""

    soup = BeautifulSoup(resp.text, "lxml")

    # Extract company name from meta description: "Job {Company} of '{Title}'..."
    meta = soup.find("meta", attrs={"name": "Description"})
    if meta and meta.get("content"):
        m = re.match(r"Job (.+?) of '", meta["content"])
        if m:
            _company_cache[original_url] = m.group(1).strip()

    # Primary: description content area
    content_div = soup.find(id="contenu-ficheoffre")
    if content_div:
        return content_div.get_text(separator=" ", strip=True)

    # Fallback: meta description text
    if meta and meta.get("content"):
        return meta["content"]

    return ""
