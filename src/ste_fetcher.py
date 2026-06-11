import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# ST Engineering uses SAP SuccessFactors J2W — same ATS as GMR and SIA.
# Portal: careers.stengg.com — multi-division company.
# Pagination uses startrow= (not start= as SIA/GMR use).
# run_ste.py pre-filters to Commercial Aerospace before passing to matcher.

BASE_URL = "https://careers.stengg.com"
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
        "Referer": BASE_URL,
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
    Convert 'Division - Address, CC' to 'Address, Country'.
    e.g. 'Aero - 501 Airport Rd, SG' → '501 Airport Rd, Singapore'.
    """
    if not raw_location:
        return "Singapore"
    raw = raw_location.strip()
    # Strip division prefix: "Division - Address, CC"
    if " - " in raw:
        raw = raw.split(" - ", 1)[1]
    parts = raw.rsplit(", ", 1)
    if len(parts) == 2:
        address, cc = parts
        cc_map = {"SG": "Singapore", "MY": "Malaysia", "AU": "Australia"}
        country = cc_map.get(cc.strip().upper(), cc.strip())
        return f"{address.strip()}, {country}"
    return raw


def _get_total_jobs(html):
    """Extract total job count from aria-label 'Results 1 to 25 of 346'."""
    m = re.search(r"Results \d+ to \d+ of (\d+)", html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_listing_page(html):
    """Parse one J2W listing page. Returns list of job dicts including facility field."""
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

        fac_span = row.find("span", class_="jobFacility")
        facility = fac_span.get_text(strip=True) if fac_span else ""

        loc_span = row.find("span", class_="jobLocation")
        raw_location = loc_span.get_text(strip=True) if loc_span else ""
        location = _clean_location(raw_location)

        date_span = row.find("span", class_="jobDate")
        raw_date = date_span.get_text(strip=True) if date_span else ""
        posting_date = _parse_date(raw_date)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "ST Engineering",
            "facility": facility,
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "source": "ste",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from careers.stengg.com (SAP SuccessFactors J2W).

    Paginates via ?startrow=N (note: differs from SIA/GMR which use ?start=N).
    Returns all jobs across all divisions; run_ste.py pre-filters by facility.
    """
    session = _get_session()
    all_jobs = []
    seen_ids = set()
    startrow = 0
    total = None

    while len(all_jobs) < max_listings:
        if total is not None and startrow >= total:
            break

        url = f"{SEARCH_URL}?q=&sortColumn=referencedate&sortDirection=desc&startrow={startrow}"

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
                    print(f"[ste] startrow={startrow}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[ste] startrow={startrow}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        if total is None:
            total = _get_total_jobs(resp.text)
            print(f"[ste] Total jobs available: {total}")

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break

        all_jobs.extend(new_jobs)
        print(f"[ste] startrow={startrow}: {len(page_jobs)} jobs, {len(new_jobs)} new — total so far: {len(all_jobs)}")

        startrow += len(page_jobs)
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch full job description from a /job/{slug}/{id}/ detail page.

    Returns (description_text, posting_date_iso) — date is always '' (use listing date).
    Never raises except RateLimitError on 429.
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
        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
