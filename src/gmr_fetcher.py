import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://careers.gmrgroup.in"
SEARCH_URL = f"{BASE_URL}/search/"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _parse_date(date_str):
    """Convert 'D Mon YYYY' (e.g. '10 Jun 2026') to YYYY-MM-DD. Returns '' on failure."""
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _clean_location(raw_location):
    """
    Clean SuccessFactors J2W location string.
    e.g. 'Goa, GMR AA - Goa (PG11AA06), IN' -> 'Goa, India'
    """
    if not raw_location:
        return "India"
    parts = raw_location.split(",")
    city = re.sub(r'\s*\([^)]+\).*$', '', parts[0]).strip()
    return f"{city}, India"


def _get_total_jobs(html):
    """Extract total job count from aria-label like 'Results 1 to 5 of 5'."""
    m = re.search(r"Results \d+ to \d+ of (\d+)", html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_listing_page(html):
    """
    Parse one listing page from the SAP SuccessFactors J2W search results.
    Returns list of job dicts: id, title, company, location, posting_date, url, source.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for row in soup.find_all("tr", class_="data-row"):
        title_a = row.find("a", class_="jobTitle-link")
        if not title_a:
            continue

        href = title_a.get("href", "")
        # href like /job/some-slug/1196717201/
        m = re.search(r"/job/[^/]+/(\d+)/?", href)
        if not m:
            continue

        job_id = m.group(1)
        title = title_a.get_text(strip=True)
        url = BASE_URL + href if href.startswith("/") else href

        # Location
        loc_span = row.find("span", class_="jobLocation")
        raw_location = loc_span.get_text(strip=True) if loc_span else ""
        location = _clean_location(raw_location)

        # Date
        date_span = row.find("span", class_="jobDate")
        raw_date = date_span.get_text(strip=True) if date_span else ""
        posting_date = _parse_date(raw_date)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "GMR Group",
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "source": "gmr",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from careers.gmrgroup.in (SAP SuccessFactors J2W).

    Paginates via ?start=N parameter. Stops when no new jobs are found or
    start >= total. No server-side keyword filtering — fetch all, filter locally.

    Returns list of job dicts.
    """
    session = _get_session()
    all_jobs = []
    seen_ids = set()
    start = 0
    total = None

    while len(all_jobs) < max_listings:
        if total is not None and start >= total:
            break

        url = f"{SEARCH_URL}?q=&sortColumn=referencedate&sortDirection=desc&start={start}"

        resp = None
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=20)
                if resp.status_code == 429:
                    raise RateLimitError(f"429 from {url}")
                break
            except RateLimitError:
                raise
            except Exception as exc:
                if attempt == 2:
                    print(f"[gmr] start={start}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[gmr] start={start}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        # Read total on first page
        if total is None:
            total = _get_total_jobs(resp.text)

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break  # no rows found — done

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break  # all jobs on this page already seen — stop

        all_jobs.extend(new_jobs)
        print(f"[gmr] start={start}: {len(page_jobs)} jobs, {len(new_jobs)} new — total: {len(all_jobs)}")

        start += len(page_jobs)
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch the full job description from a /job/{slug}/{id}/ detail page.

    Returns (description_text, posting_date_iso) tuple.
    Returns ("", "") on any failure — never raises (except RateLimitError on 429).
    """
    if not application_url or "/job/" not in application_url:
        return ("", "")

    session = _get_session()

    try:
        resp = session.get(application_url, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {application_url}")
        if resp.status_code != 200:
            return ("", "")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Description in span.jobdescription
        desc_span = soup.find("span", class_="jobdescription")
        description = desc_span.get_text(separator=" ", strip=True) if desc_span else ""

        # Posting date from raw page text: "Date:20 May 2026"
        posting_date = ""
        m = re.search(r"Date:\s*(\d{1,2}\s+\w+\s+\d{4})", resp.text)
        if m:
            posting_date = _parse_date(m.group(1))

        return (description, posting_date)

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
