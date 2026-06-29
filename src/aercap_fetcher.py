import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.aercap.com"
LISTING_PATH = "/careers/career-opportunities"

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
                print(f"[aercap] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch AerCap job listings from their custom careers portal.

    All jobs listed on a single HTML page in a <table class="content-table">.
    No keyword filtering server-side — all jobs returned and filtered downstream.
    No posting date is visible on the listing or detail pages.
    Returns list of job dicts.
    """
    url = f"{BASE_URL}{LISTING_PATH}"
    try:
        resp = _get(url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[aercap] Listing fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", class_="content-table")
    if not table:
        print("[aercap] No content-table found on careers page — 0 jobs returned")
        return []

    jobs = []
    tbody = table.find("tbody")
    if not tbody:
        return []

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        a = cells[0].find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        location = cells[1].get_text(strip=True)
        if not title or not href:
            continue

        # Extract job ID from URL path: /careers/career-opportunities/job/{id}/{slug}
        m = re.search(r"/job/(\d+)/", href)
        job_id = m.group(1) if m else href

        job_url = BASE_URL + href if href.startswith("/") else href

        jobs.append({
            "id": job_id,
            "title": title,
            "url": job_url,
            "location": location,
            "company": "AerCap",
            "source": "aercap",
            "posting_date": "",  # AerCap does not display posting dates
        })

        if len(jobs) >= max_listings:
            break

    print(f"[aercap] Total jobs fetched: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch the job description from an AerCap job detail page.

    The detail page has <h3>Job Summary</h3> followed by one or more <p> description paragraphs.
    A PDF download link is also present for the full JD — PDFs are not parsed.
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
        print(f"[aercap] Description fetch failed ({application_url}): {exc}")
        return ("", "")

    try:
        soup = BeautifulSoup(resp.text, "lxml")

        # Find the "Job Summary" h3 and collect text from all following siblings
        summary_h3 = soup.find("h3", string=re.compile(r"Job\s+Summary", re.I))
        if not summary_h3:
            return ("", "")

        parts = []
        for sibling in summary_h3.find_next_siblings():
            # Stop at the next heading or the Download link (marks end of description)
            if sibling.name in ("h1", "h2", "h3", "h4"):
                break
            if sibling.name == "a" and "download" in sibling.get_text(strip=True).lower():
                break
            text = sibling.get_text(separator=" ", strip=True)
            if text:
                parts.append(text)

        description = " ".join(parts).strip()
        return (description, "")
    except Exception as exc:
        print(f"[aercap] Description parse error ({application_url}): {exc}")
        return ("", "")
