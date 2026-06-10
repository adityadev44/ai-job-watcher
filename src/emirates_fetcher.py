import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# Custom REST API on the Emirates Group careers wrapper site (backed by Avature).
# GET /api/v1/jobs?showAll=true returns all ~79 active jobs with inline full descriptions.
# No pagination. No server-side keyword filtering — fetch all, filter locally.
BASE_URL = "https://www.emiratesgroupcareers.com"
AVATURE_BASE = "https://external.emiratesgroupcareers.com"
_JOBS_ENDPOINT = "/api/v1/jobs?showAll=true"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Cache populated by fetch_jobs() so fetch_job_description() needs zero extra HTTP calls.
_desc_cache: dict[str, tuple[str, str]] = {}


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.emiratesgroupcareers.com/search-and-apply/",
    })
    return s


def _parse_posting_date(ts_ms):
    """Convert millisecond Unix timestamp to YYYY-MM-DD string. Returns '' on failure."""
    if not ts_ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            ts_ms / 1000, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all active vacancies from the Emirates Group careers API.

    Single GET to /api/v1/jobs?showAll=true returns all ~79 jobs with inline
    full HTML descriptions. No pagination, no keyword iteration — filter locally.
    Populates the module-level _desc_cache so fetch_job_description needs no
    additional HTTP calls.

    Returns list of job dicts.
    """
    global _desc_cache

    session = _get_session()

    for attempt in range(3):
        try:
            resp = session.get(BASE_URL + _JOBS_ENDPOINT, timeout=25)
            if resp.status_code == 429:
                raise RateLimitError(f"429 from jobs API")
            if resp.status_code != 200:
                print(f"[emirates] Jobs API returned {resp.status_code}")
                return []
            break
        except RateLimitError:
            raise
        except Exception as exc:
            if attempt == 2:
                print(f"[emirates] Jobs API request failed: {exc}")
                return []
            time.sleep(2 ** (attempt + 1))

    try:
        raw_jobs = resp.json().get("data", [])
    except Exception as exc:
        print(f"[emirates] JSON parse failed: {exc}")
        return []

    jobs = []
    new_cache: dict[str, tuple[str, str]] = {}

    for raw in raw_jobs[:max_listings]:
        reqid = str(raw.get("reqid") or raw.get("id") or "")
        if not reqid:
            continue

        title = raw.get("title", "")
        brand = raw.get("brand") or "Emirates Group"

        # Build a human-readable location from city + country; fall back to
        # the location field which contains building names like "EK Engineering Building"
        city = raw.get("city", "")
        country = raw.get("country", "")
        if city and country:
            location = f"{city}, {country}"
        elif city:
            location = city
        elif country:
            location = country
        else:
            location = raw.get("location", "Dubai, UAE")

        posting_date = _parse_posting_date(raw.get("postingdate"))

        # Use the API's own redirectionurl (canonical, opens correctly in browser).
        # Fall back to constructing the ApplicationMethods URL if the field is absent.
        redirect = raw.get("redirectionurl") or ""
        url = redirect if redirect else f"{AVATURE_BASE}/careersmarketplace/ApplicationMethods?jobId={reqid}&source=CareerWebsite"

        # Strip HTML from inline description and cache it
        html_desc = raw.get("jobdescription") or ""
        if html_desc:
            text_desc = BeautifulSoup(html_desc, "html.parser").get_text(separator=" ", strip=True)
        else:
            text_desc = ""
        new_cache[reqid] = (text_desc, posting_date)

        jobs.append({
            "id": reqid,
            "title": title,
            "company": brand,
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "source": "emirates",
        })

    _desc_cache = new_cache
    print(f"[emirates] Fetched {len(jobs)} jobs, {len(new_cache)} descriptions cached")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Return (description_text, posting_date_iso) for a given job URL.

    Normal path: looks up reqid in _desc_cache (zero extra HTTP calls; cache
    is populated by fetch_jobs() which always runs first in the pipeline).

    Fallback path: re-fetches the full jobs API if cache is empty (test isolation
    or direct call scenarios). Returns ("", "") on any failure — never raises
    (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    m = re.search(r"jobId=([\w-]+)", application_url)
    if not m:
        return ("", "")
    reqid = m.group(1)

    if reqid in _desc_cache:
        return _desc_cache[reqid]

    # Fallback: re-fetch the full jobs list and search for this reqid
    try:
        session = _get_session()
        resp = session.get(BASE_URL + _JOBS_ENDPOINT, timeout=25)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from jobs API")
        if resp.status_code != 200:
            return ("", "")

        for raw in resp.json().get("data", []):
            r = str(raw.get("reqid") or raw.get("id") or "")
            if r == reqid:
                html_desc = raw.get("jobdescription") or ""
                text_desc = (
                    BeautifulSoup(html_desc, "html.parser").get_text(separator=" ", strip=True)
                    if html_desc else ""
                )
                posting_date = _parse_posting_date(raw.get("postingdate"))
                _desc_cache[reqid] = (text_desc, posting_date)
                return (text_desc, posting_date)

        return ("", "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
