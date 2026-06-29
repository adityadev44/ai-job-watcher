import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://avolon.aero"
CAREERS_URL = "https://avolon.aero/careers"

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

# Sentinel text shown when no jobs are available
_NO_JOBS_SENTINEL = "no jobs currently available"


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


def _get(url, max_retries=3, base_delay=2.0):
    """GET with exponential backoff on 429. Raises RateLimitError after max_retries."""
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[avolon] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch Avolon job listings from avolon.aero/careers.

    Avolon uses a custom static HTML page with a "LATEST JOBS" section.
    When no jobs are available, the section displays a sentinel message and returns [].
    When jobs ARE present, they appear as <a> links within the LATEST JOBS content div.

    NOTE: This fetcher was built while Avolon had 0 active vacancies (June 2026).
    The job card HTML structure when jobs are present is inferred from the page template
    and has not been verified against live data. On first actual Avolon posting, verify
    the returned title/URL/location fields in the run log and update this fetcher if needed.

    Returns list of job dicts.
    """
    try:
        resp = _get(CAREERS_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[avolon] Careers page fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Find the "LATEST JOBS" section heading and navigate to its content container
    latest_jobs_h2 = soup.find("h2", string=re.compile(r"LATEST\s+JOBS", re.I))
    if not latest_jobs_h2:
        print("[avolon] LATEST JOBS section not found on careers page — 0 jobs returned")
        return []

    # The content div is a sibling/nearby div after the heading
    # Page structure: <h2>LATEST JOBS</h2><hr><div style="...">content</div>
    container = latest_jobs_h2.find_parent("div", class_="col-md-8")
    if not container:
        container = latest_jobs_h2.find_parent()

    content_div = container.find("div", style=True) if container else None
    if not content_div:
        # Fallback: use the full container
        content_div = container

    page_text = content_div.get_text(" ", strip=True) if content_div else ""

    # Check for the "no jobs" sentinel
    if _NO_JOBS_SENTINEL in page_text.lower():
        print("[avolon] No jobs currently available (sentinel found)")
        return []

    # Parse job links from the LATEST JOBS content div
    # When jobs exist, they should appear as <a href="...">title</a> elements
    jobs = []
    nav_links = {"/insights", "/care", "/newsroom", "/thoughts", "/about",
                 "/contact", "/people", "/sustainability", "/team"}

    for a in (content_div.find_all("a", href=True) if content_div else []):
        href = a.get("href", "").strip()
        if not href or href.startswith("#"):
            continue
        # Skip navigation links
        if any(href.startswith(nav) for nav in nav_links):
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        job_url = BASE_URL + href if href.startswith("/") else href

        jobs.append({
            "title": title,
            "url": job_url,
            "location": "Dublin, Ireland",  # Avolon HQ — update if location shown per job
            "company": "Avolon",
            "source": "avolon",
            "posting_date": "",
        })

        if len(jobs) >= max_listings:
            break

    if jobs:
        print(f"[avolon] NOTE: {len(jobs)} job link(s) found in LATEST JOBS section.")
        print("[avolon] NOTE: Job structure was built with 0 vacancies — verify title/url/location on first real posting.")
    else:
        print("[avolon] 0 jobs in LATEST JOBS section (no sentinel, no links — page may have changed structure)")

    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch the description from an Avolon job page.

    Avolon's individual job pages are assumed to be simple HTML pages on avolon.aero.
    The exact structure is unknown (built with 0 vacancies) — attempt a generic GET
    and return all main body text. Returns ("", "") on any failure.
    On ANY failure: returns ("", "") — never raises (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    try:
        resp = _get(application_url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[avolon] Description fetch failed ({application_url}): {exc}")
        return ("", "")

    try:
        soup = BeautifulSoup(resp.text, "lxml")
        # Remove nav, footer, header
        for tag in soup.find_all(["nav", "footer", "header"]):
            tag.decompose()
        main = soup.find("main") or soup.find("body")
        if not main:
            return ("", "")
        text = main.get_text(separator=" ", strip=True)
        return (text, "")
    except Exception as exc:
        print(f"[avolon] Description parse error ({application_url}): {exc}")
        return ("", "")
