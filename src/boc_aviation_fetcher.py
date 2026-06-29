import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import datetime
import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.bocaviation.com"
LISTING_URL = "https://www.bocaviation.com/en/careers"

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


def _get(url, max_retries=3, base_delay=2.0):
    """GET with exponential backoff on 429. Raises RateLimitError after max_retries."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[boc_aviation] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _parse_date(date_str: str) -> str:
    """
    Parse BOC Aviation date format: "06 May 2026" → "2026-05-06".
    Returns "" on any parse failure.
    """
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch BOC Aviation job listings from their custom careers portal.

    Jobs are displayed as cards: <div class="bg-gray-4 p-3 text-white flex-grow-1 mb-3">
    Each card contains date, city, title, and "Find Out More" link.
    All jobs on a single page (no pagination).
    Returns list of job dicts.
    """
    try:
        resp = _get(LISTING_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[boc_aviation] Listing fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Current openings section: <div class="container py-4"> → <div class="row"> → cards
    # Each card: <div class="bg-gray-4 p-3 text-white flex-grow-1 mb-3">
    jobs = []
    cards = soup.find_all("div", class_=lambda c: c and "bg-gray-4" in c and "p-3" in c)

    for card in cards:
        # Date: <p class="font-weight-semibold font-size-14 mb-0 text-uppercase">06 May 2026</p>
        date_p = card.find("p", class_=lambda c: c and "font-weight-semibold" in c and "mb-0" in c)
        date_str = date_p.get_text(strip=True) if date_p else ""

        # Location: <p class="font-weight-light font-size-14 text-uppercase">Singapore</p>
        loc_p = card.find("p", class_=lambda c: c and "font-weight-light" in c)
        location = loc_p.get_text(strip=True) if loc_p else "Singapore"

        # Title: <h6 class="font-weight-semibold font-size-18 flex-grow-1 mb-3 text-white">
        title_h6 = card.find("h6", class_=lambda c: c and "font-size-18" in c)
        title = title_h6.get_text(strip=True) if title_h6 else ""

        # URL: <a href="/en/Careers/{slug}" class="text-uppercase text-white">Find Out More</a>
        link_a = card.find("a", href=re.compile(r"/en/Careers/", re.I))
        href = link_a.get("href", "") if link_a else ""

        if not title or not href:
            continue

        job_url = BASE_URL + href if href.startswith("/") else href
        posting_date = _parse_date(date_str)

        jobs.append({
            "title": title,
            "url": job_url,
            "location": location,
            "company": "BOC Aviation",
            "source": "boc_aviation",
            "posting_date": posting_date,
        })

        if len(jobs) >= max_listings:
            break

    print(f"[boc_aviation] Total jobs fetched: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch the job description from a BOC Aviation job detail page.

    The detail page has a <div class="content"> containing the full job description HTML.
    Returns (description_text, posting_date_string).
    On ANY failure: returns ("", "") — never raises (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    try:
        resp = _get(application_url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[boc_aviation] Description fetch failed ({application_url}): {exc}")
        return ("", "")

    try:
        soup = BeautifulSoup(resp.text, "lxml")

        # Primary container: <div class="content"> holds the full job description
        content_div = soup.find("div", class_="content")
        if not content_div:
            return ("", "")

        text = content_div.get_text(separator=" ", strip=True)
        if len(text) < 100:
            return ("", "")
        return (text, "")
    except Exception as exc:
        print(f"[boc_aviation] Description parse error ({application_url}): {exc}")
        return ("", "")
