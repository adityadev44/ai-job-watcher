import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# AMMROC (military helicopter/aircraft MRO, Abu Dhabi) was folded into EDGE
# Group's unified careers portal — ammroc.ae and ammroc.edgegroup.ae do not
# resolve at all (DNS failure); the real portal is careers.edgegroup.ae,
# powered by SAP SuccessFactors J2W (same ATS family as GMR/SIA/STE/Air
# India), just routed through a Taleo-style "/go/View-All-Jobs/{catId}/"
# URL instead of "/search/?start=N". Confirmed via the same
# tr.data-row / a.jobTitle-link / span.jobFacility / span.jobdescription
# markup as the other J2W portals.
#
# The portal covers ~25 EDGE Group subsidiaries (POWERTECH, ADASI, CARACAL
# LIGHT, EPI, etc.) — AMMROC is one of them. run_ammroc.py pre-filters to
# the AMMROC entity only, same pattern as ST Engineering's Commercial
# Aerospace pre-filter.

BASE_URL = "https://careers.edgegroup.ae"
CATEGORY_ID = "4166222"  # EDGE Group "View All Jobs" category
PAGE_SIZE = 25

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
    """Convert 'D Mon YYYY' (e.g. '25 Jun 2026') to YYYY-MM-DD. Returns '' on failure."""
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _get_total_jobs(html_text):
    """Extract total job count from 'Results <b>1 – 25</b> of <b>145</b>'."""
    m = re.search(r"of\s*<b>(\d+)</b>", html_text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_listing_page(html_text):
    """Parse one J2W listing page. Returns list of job dicts including entity field."""
    soup = BeautifulSoup(html_text, "html.parser")
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
        entity = fac_span.get_text(strip=True) if fac_span else ""

        loc_span = row.find("span", class_="jobLocation")
        location = loc_span.get_text(strip=True) if loc_span else "Abu Dhabi, UAE"

        date_span = row.find("span", class_="jobDate")
        raw_date = date_span.get_text(strip=True) if date_span else ""
        posting_date = _parse_date(raw_date)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "EDGE Group",
            "entity": entity,
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "source": "ammroc",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from careers.edgegroup.ae (SAP SuccessFactors J2W,
    Taleo-style "/go/View-All-Jobs/{catId}/{offset}/" pagination).

    Returns jobs across all ~25 EDGE Group subsidiaries; run_ammroc.py
    pre-filters by entity to AMMROC only.
    """
    session = _get_session()
    all_jobs = []
    seen_ids = set()
    offset = 0
    total = None

    while len(all_jobs) < max_listings:
        if total is not None and offset >= total:
            break

        url = f"{BASE_URL}/go/View-All-Jobs/{CATEGORY_ID}/{offset}/?q=&sortColumn=referencedate&sortDirection=desc"

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
                    print(f"[ammroc] offset={offset}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[ammroc] offset={offset}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        if total is None:
            total = _get_total_jobs(resp.text)
            print(f"[ammroc] Total EDGE Group jobs available: {total}")

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break

        all_jobs.extend(new_jobs)
        print(f"[ammroc] offset={offset}: {len(page_jobs)} jobs, {len(new_jobs)} new — total so far: {len(all_jobs)}")

        offset += PAGE_SIZE
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch the full job description from a /job/{slug}/{id}/ detail page.

    Returns (description_text, posting_date_iso) — date is always ''
    (use the listing date already in the job dict).
    Returns ("", "") on any failure — never raises (except RateLimitError).
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
