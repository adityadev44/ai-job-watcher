import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://corporate.ethiopianairlines.com"
VACANCIES_URL = f"{BASE_URL}/AboutEthiopian/careers/vacancies"

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


# Keyed by job URL (page URL + #slug fragment) — populated during fetch_jobs().
_desc_cache: dict = {}


def _get(url, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[ethiopian] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _parse_closing_date(raw: str) -> str:
    """Convert 'Month DD, YYYY' → 'YYYY-MM-DD'. Returns '' for 'Open' or unparseable."""
    raw = raw.strip()
    if not raw or raw.lower() == "open":
        return ""
    for fmt in ("%B %d, %Y", "%B %d,%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _make_slug(title: str) -> str:
    """Title → URL-safe fragment slug, max 80 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80]


def _get_total_pages(soup) -> int:
    """Read max page number from pagination links."""
    max_page = 1
    for a in soup.find_all("a", href=True):
        m = re.match(r"^/AboutEthiopian/careers/vacancies/(\d+)$", a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def _extract_header_fields(header_a) -> dict[str, str]:
    """
    Extract label→value pairs from a card-header anchor element.
    Labels are in <strong> tags with format 'Position : ' (space before colon).
    Values follow as text nodes, possibly starting with &nbsp; (\xa0).
    """
    parts: dict[str, str] = {}
    for strong in header_a.find_all("strong"):
        # Normalise label: strip whitespace and trailing colon+space
        key = re.sub(r"[\s:]+$", "", strong.get_text(strip=True))
        sibling = strong.next_sibling
        if sibling and isinstance(sibling, str):
            # &nbsp; decodes to \xa0 — strip those along with regular whitespace
            value = sibling.replace("\xa0", " ").strip()
            parts[key] = value
    return parts


def _parse_page(html: str, page_num: int) -> list[dict]:
    """
    Parse one vacancies page.
    Each job is a Bootstrap panel: <div class="card-header"> wrapping an
    <a data-toggle="collapse" href="#collapseXxx_N"> with Position/Closing Date fields.
    Caches descriptions in _desc_cache keyed by the job's browseable URL.
    Returns list of job dicts.
    """
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    for card_header in soup.find_all("div", class_="card-header"):
        header_a = card_header.find("a", attrs={"data-toggle": "collapse"})
        if not header_a:
            continue

        fields = _extract_header_fields(header_a)
        title = fields.get("Position", "").strip()
        if not title:
            continue

        closing_raw = fields.get("Closing Date", "")
        closing_date = _parse_closing_date(closing_raw)

        # Find the collapse div for the full description (case-insensitive ID lookup)
        collapse_id = header_a.get("href", "").lstrip("#")
        collapse_div = soup.find(id=re.compile(f"^{re.escape(collapse_id)}$", re.I))
        description = collapse_div.get_text(separator=" ", strip=True) if collapse_div else ""

        slug = _make_slug(title)
        # page_num=1 → canonical base URL; 2+ → /N
        page_url = VACANCIES_URL if page_num == 1 else f"{VACANCIES_URL}/{page_num}"
        browseable_url = f"{page_url}#{slug}"

        job = {
            "title": title,
            "url": browseable_url,
            "location": "Addis Ababa, Ethiopia",
            "company": "Ethiopian Airlines",
            "source": "ethiopian",
            "posting_date": closing_date,  # closing date is the only date available
        }

        _desc_cache[browseable_url] = (description, closing_date)
        jobs.append(job)

    return jobs


def fetch_jobs() -> list[dict]:
    """
    Fetch all Ethiopian Airlines job listings across all pagination pages.
    Returns deduplicated list of job dicts.
    """
    _desc_cache.clear()

    print("[ethiopian] Fetching page 1...")
    try:
        resp = _get(VACANCIES_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[ethiopian] Fetch error (page 1): {exc}")
        return []

    soup1 = BeautifulSoup(resp.text, "lxml")
    total_pages = _get_total_pages(soup1)
    print(f"[ethiopian] Total pages: {total_pages}")

    all_jobs: list[dict] = []
    seen_keys: set[str] = set()  # title_slug|closing_date — dedup across pages

    def _add_unique(jobs: list[dict]) -> int:
        added = 0
        for job in jobs:
            key = _make_slug(job["title"]) + "|" + job["posting_date"]
            if key not in seen_keys:
                seen_keys.add(key)
                all_jobs.append(job)
                added += 1
        return added

    jobs1 = _parse_page(resp.text, 1)
    new1 = _add_unique(jobs1)
    print(f"[ethiopian] Page 1: {len(jobs1)} entries, {new1} unique")

    for page_num in range(2, total_pages + 1):
        time.sleep(0.5)
        url = f"{VACANCIES_URL}/{page_num}"
        try:
            resp = _get(url)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[ethiopian] Fetch error (page {page_num}): {exc}")
            continue

        jobs = _parse_page(resp.text, page_num)
        new = _add_unique(jobs)
        print(f"[ethiopian] Page {page_num}: {len(jobs)} entries, {new} new unique")

    print(f"[ethiopian] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Return the cached inline description from fetch_jobs().
    Returns ("", "") on any failure — never raises.
    """
    if not application_url:
        return ("", "")
    return _desc_cache.get(application_url, ("", ""))
