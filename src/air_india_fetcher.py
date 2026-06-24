import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://careers.airindia.com"
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


def _get_total_jobs(html):
    """Extract total job count from 'Showing X to Y of Z Jobs'."""
    m = re.search(r"Showing \d+ to \d+ of (\d+)", html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _parse_listing_page(html):
    """
    Parse one listing page from the SAP SuccessFactors J2W portal (Air India variant).
    Container: li.job-tile (not tr.data-row as in GMR/SIA).
    Returns list of job dicts: id, title, company, location, posting_date, url, source.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for tile in soup.find_all("li", class_="job-tile"):
        title_a = tile.find("a", class_="jobTitle-link")
        if not title_a:
            continue

        href = title_a.get("href", "")
        m = re.search(r"/job/[^/]+/(\d+)/?", href)
        if not m:
            continue

        job_id = m.group(1)
        title = title_a.get_text(strip=True)
        url = BASE_URL + href if href.startswith("/") else href

        # Location: div.city contains a label span + a value div
        city_div = tile.find("div", class_="city")
        if city_div:
            val_div = city_div.find("div", id=re.compile(r"-section-city-value"))
            raw_city = val_div.get_text(strip=True) if val_div else ""
        else:
            raw_city = ""
        location = f"{raw_city}, India" if raw_city else "India"

        # No posting date on listing page for this J2W variant
        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Air India",
            "location": location,
            "posting_date": "",
            "url": url,
            "source": "air_india",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.5):
    """
    Fetch all open jobs from careers.airindia.com (SAP SuccessFactors J2W).

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
                    print(f"[air_india] start={start}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[air_india] start={start}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        if total is None:
            total = _get_total_jobs(resp.text)

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break

        all_jobs.extend(new_jobs)
        print(f"[air_india] start={start}: {len(page_jobs)} jobs, {len(new_jobs)} new — total: {len(all_jobs)}")

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

        desc_span = soup.find("span", class_="jobdescription")
        description = desc_span.get_text(separator=" ", strip=True) if desc_span else ""

        # Air India detail pages do not carry a parseable posting date
        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
