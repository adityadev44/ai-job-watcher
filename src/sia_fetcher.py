import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# SIA Engineering Company uses SAP SuccessFactors J2W — same ATS as GMR Group.
# Portal: careers.singaporeair.com/siaec (shared SIA Group domain, SIAEC tenant).
# No Playwright needed — plain requests works.
# Location field is always a 2-letter country code (e.g. "SG"); map to country name.

BASE_URL = "https://careers.singaporeair.com"
SEARCH_URL = f"{BASE_URL}/siaec/search/"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_COUNTRY_CODES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "CN": "China",
    "KR": "South Korea",
    "IN": "India",
}


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_URL + "/siaec",
    })
    return s


def _parse_date(date_str):
    """Convert 'D Mon YYYY' (e.g. '11 Jun 2026') to YYYY-MM-DD. Returns '' on failure."""
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _clean_location(raw_location):
    """
    Map J2W location code or string to a human-readable location.
    SIAEC portal returns bare 2-letter ISO country codes (e.g. 'SG', 'MY').
    Falls back to GMR-style comma-split cleaning for any future city+code strings.
    """
    if not raw_location:
        return "Singapore"
    raw = raw_location.strip()
    if raw.upper() in _COUNTRY_CODES:
        return _COUNTRY_CODES[raw.upper()]
    # Fallback: "City, Code - Detail (CODE), CC" — strip codes, use first part
    parts = raw.split(",")
    city = re.sub(r'\s*[\-\(][^)]*\)?.*$', '', parts[0]).strip()
    return city if city else "Singapore"


def _get_total_jobs(html):
    """Extract total job count from aria-label like 'Results 1 to 10 of 11'."""
    m = re.search(r"Results \d+ to \d+ of (\d+)", html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_listing_page(html):
    """
    Parse one J2W listing page. Returns list of job dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for row in soup.find_all("tr", class_="data-row"):
        title_a = row.find("a", class_="jobTitle-link")
        if not title_a:
            continue

        href = title_a.get("href", "")
        m = re.search(r"/job/[^/]+/(\d+)/?", href)
        if not m:
            continue

        job_id = m.group(1)
        title = title_a.get_text(strip=True)
        url = BASE_URL + href if href.startswith("/") else href

        loc_span = row.find("span", class_="jobLocation")
        raw_location = loc_span.get_text(strip=True) if loc_span else ""
        location = _clean_location(raw_location)

        date_span = row.find("span", class_="jobDate")
        raw_date = date_span.get_text(strip=True) if date_span else ""
        posting_date = _parse_date(raw_date)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "SIA Engineering",
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "source": "sia",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from careers.singaporeair.com/siaec (SAP SuccessFactors J2W).

    Paginates via ?start=N. Stops when no new jobs seen or start >= total.
    No server-side keyword filtering — all jobs returned, filter locally.
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
                    print(f"[sia] start={start}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[sia] start={start}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        if total is None:
            total = _get_total_jobs(resp.text)
            print(f"[sia] Total jobs available: {total}")

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break  # all jobs on this page already seen — portal may be wrapping

        all_jobs.extend(new_jobs)
        print(f"[sia] start={start}: {len(page_jobs)} jobs, {len(new_jobs)} new — total so far: {len(all_jobs)}")

        start += len(page_jobs)
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch the full job description from a /siaec/job/{slug}/{id}/ detail page.

    Returns (description_text, posting_date_iso) tuple.
    posting_date is returned as '' — the listing date from fetch_jobs() is used.
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

        desc_span = soup.find("span", class_="jobdescription")
        description = desc_span.get_text(separator=" ", strip=True) if desc_span else ""

        # Detail page does not reliably expose a date field — use listing date (already in job dict)
        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
