import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.aviationcapitalgroup.com"
CAREERS_URL = "https://www.aviationcapitalgroup.com/careers"

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

# Inline description cache: keyed by url → description text
# Populated during fetch_jobs() so fetch_job_description() needs zero extra HTTP calls.
_desc_cache: dict[str, str] = {}


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


def _get(url, max_retries=3, base_delay=2.0):
    """GET with exponential backoff on 429. Raises RateLimitError after max_retries."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[acg] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _make_slug(title: str) -> str:
    """Convert a job title to a URL-safe slug for use as a page fragment."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80]  # cap length


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch Aviation Capital Group (ACG) job listings from their static careers page.

    ACG uses a WordPress/Elementor accordion on a single careers page.
    Each job is in an <h5 class="elementor-tab-title"> toggle with
    <a class="elementor-toggle-title"> for the title, and a matching
    <div class="elementor-tab-content"> for the full description.

    Title format: "Job Title - Location1; Location2; Location3"
    No individual job URLs exist — fragment URLs (page#slug) are used.
    Descriptions are inline — no extra HTTP calls needed.
    No posting dates are shown on this page.
    Returns list of job dicts.
    """
    global _desc_cache
    _desc_cache = {}

    try:
        resp = _get(CAREERS_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[acg] Careers page fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Find all Elementor toggle title links
    title_links = soup.find_all("a", class_="elementor-toggle-title")
    # Find all Elementor tab content divs (parallel list)
    content_divs = soup.find_all("div", class_="elementor-tab-content")

    jobs = []
    for i, a in enumerate(title_links):
        raw_title = a.get_text(strip=True)
        if not raw_title:
            continue

        # Split "Job Title - Location1; Location2" on first " - "
        if " - " in raw_title:
            title_part, location_part = raw_title.split(" - ", 1)
            title = title_part.strip()
            location = location_part.strip()
        else:
            title = raw_title.strip()
            location = "Dublin / Newport Beach / Miami"

        # Build a fragment URL as the browseable link
        slug = _make_slug(title)
        job_url = f"{CAREERS_URL}#{slug}"

        # Extract inline description from the corresponding content div
        description = ""
        if i < len(content_divs):
            description = content_divs[i].get_text(separator=" ", strip=True)

        # Cache description for fetch_job_description()
        _desc_cache[job_url] = description

        jobs.append({
            "title": title,
            "url": job_url,
            "location": location,
            "company": "Aviation Capital Group",
            "source": "acg",
            "posting_date": "",  # ACG careers page does not show posting dates
        })

        if len(jobs) >= max_listings:
            break

    print(f"[acg] Total jobs fetched: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Return the cached description for an ACG job.

    Descriptions are extracted inline during fetch_jobs() from the Elementor accordion content.
    No extra HTTP calls are made here.
    Returns (description_text, posting_date_string).
    On ANY failure: returns ("", "") — never raises (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    description = _desc_cache.get(application_url, "")
    if not description:
        # Cache miss: the page was not fetched yet, or URL doesn't match.
        # Re-fetch the careers page to refresh the cache.
        try:
            fetch_jobs()
            description = _desc_cache.get(application_url, "")
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[acg] Cache-miss re-fetch failed: {exc}")
            return ("", "")

    return (description, "")
