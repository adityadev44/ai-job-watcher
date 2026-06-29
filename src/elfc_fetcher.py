import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import requests
from bs4 import BeautifulSoup

JOBS_URL = "https://elfc.pinpointhq.com/postings.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://elfc.pinpointhq.com/",
}


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


def _get(url: str, max_retries: int = 3, base_delay: float = 2.0):
    """GET with exponential backoff on 429."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[elfc] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text. Returns '' on any failure."""
    if not html:
        return ""
    try:
        return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)
    except Exception:
        return ""


def _build_location(loc: dict) -> str:
    """Build a human-readable location string from the PinPoint location object."""
    parts = []
    name = (loc.get("name") or "").strip()
    province = (loc.get("province") or "").strip()
    if name:
        parts.append(name)
    if province and province.lower() != name.lower():
        parts.append(province)
    return ", ".join(parts) if parts else "Shannon, Ireland"


def fetch_jobs() -> list[dict]:
    """
    Fetch all job listings from ELFC's PinPoint HQ portal.

    API: GET https://elfc.pinpointhq.com/postings.json
    Returns {"data": [...]} with all active postings.

    ELFC is a small engine lessor (~50 employees). Expect 0-5 postings;
    engine technical roles (Engine Asset Manager, Technical Director) are
    the target — currently the portal shows mostly support/legal roles
    which will fail Gate 1 naturally.
    """
    try:
        resp = _get(JOBS_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[elfc] Fetch error: {exc}")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"[elfc] JSON parse error: {exc}")
        return []

    raw_jobs = data.get("data", [])
    jobs = []

    for raw in raw_jobs:
        job_id = str(raw.get("id", "")).strip()
        title = (raw.get("title") or "").strip()
        if not title or not job_id:
            continue

        # Browseable URL — the 'url' field is canonical (e.g. elfc.pinpointhq.com/en/postings/{uuid})
        url = (raw.get("url") or "").strip()
        if not url:
            continue

        # Location from nested location object
        loc_obj = raw.get("location") or {}
        location = _build_location(loc_obj)

        # Combine all description sections for Gate 2 matching
        desc_parts = [
            _strip_html(raw.get("description") or ""),
            _strip_html(raw.get("key_responsibilities") or ""),
            _strip_html(raw.get("skills_knowledge_expertise") or ""),
        ]
        # Store combined description in cache keyed by url
        # (fetch_job_description will retrieve it)
        _desc_cache[url] = " ".join(p for p in desc_parts if p)

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "company": "ELFC",
            "source": "elfc",
            "posting_date": "",  # PinPoint doesn't expose a published_at date; deadline_at often null
        })

    print(f"[elfc] Fetched {len(jobs)} job listing(s) from PinPoint portal")
    return jobs


# Description cache — populated by fetch_jobs(), read by fetch_job_description().
_desc_cache: dict = {}


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Return the cached description for the given PinPoint job URL.

    Descriptions (combined from description + key_responsibilities +
    skills_knowledge_expertise) are fetched inline during fetch_jobs()
    — no extra HTTP call needed. Returns ("", "") on any failure.
    Never raises.
    """
    try:
        return (_desc_cache.get(url, ""), "")
    except Exception:
        return ("", "")
