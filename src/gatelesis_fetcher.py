import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://gatelesis.applytojob.com"
LISTING_URL = f"{BASE_URL}/apply/jobs/"

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
                print(f"[gatelesis] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def _parse_row_date(row_id: str) -> str:
    """Extract YYYY-MM-DD from row_job_YYYYMMDDHHMMSS_* row ID."""
    m = re.match(r"row_job_(\d{4})(\d{2})(\d{2})\d{6}_", row_id)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def fetch_jobs() -> list[dict]:
    """Fetch all GA Telesis job listings (all jobs on a single page)."""
    print("[gatelesis] Fetching listing page...")
    try:
        resp = _get(LISTING_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[gatelesis] Fetch error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    rows = soup.find_all("tr", class_=re.compile(r"resumator_(even|odd)_row"))
    print(f"[gatelesis] Found {len(rows)} job rows")

    jobs = []
    seen_ids: set[str] = set()

    for row in rows:
        row_id = row.get("id", "")
        a = row.find("a", class_="job_title_link")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")

        # Extract job ID from /apply/jobs/details/{ID}?& (relative href)
        m = re.search(r"/apply/jobs/details/([^?/]+)", href)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        tds = row.find_all("td")
        location = tds[1].get_text(strip=True) if len(tds) > 1 else ""

        dept = row.find("span", class_="resumator_department")
        dept_label = dept.get_text(strip=True) if dept else ""

        posting_date = _parse_row_date(row_id)
        url = f"{BASE_URL}/apply/jobs/details/{job_id}"

        # GATES = GA Telesis Engine Services (Dubai and Finland engine shops)
        company = "GA Telesis Engine Services" if "GATES" in dept_label else "GA Telesis"

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "company": company,
            "source": "gatelesis",
            "posting_date": posting_date,
        })

    print(f"[gatelesis] Total unique jobs: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """Fetch the full job description from a GA Telesis detail page."""
    if not application_url:
        return ("", "")
    try:
        resp = _get(application_url)
        soup = BeautifulSoup(resp.text, "lxml")
        desc_div = soup.find("div", class_=re.compile(r"job_full_listing"))
        if desc_div:
            return (desc_div.get_text(separator=" ", strip=True), "")
        return ("", "")
    except Exception as exc:
        print(f"[gatelesis] Description fetch error for {application_url}: {exc}")
        return ("", "")
