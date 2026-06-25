import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import json
import html
import requests
from bs4 import BeautifulSoup

# Kuwait Airways careers portal runs on Zoho Recruit's "Career Site 2.0"
# product (static.zohocdn.com/recruit/..., Lyte web-component framework).
# The entire job list — including full plain-text descriptions — is server-
# rendered into a single hidden <input id="jobs" value="[...]"> on the
# listing page itself; the client-side JS just parses that blob, it never
# makes a separate XHR call for job data. One GET returns everything, no
# pagination, and fetch_job_description needs zero extra HTTP calls.
#
# Browseable URL pattern: /jobs/Careers/{id}/{any-slug}?source=CareerSite —
# confirmed the trailing slug is cosmetic only (a wrong or missing slug
# still resolves the same job page), so we build our own simple slug rather
# than reverse-engineering Zoho's exact slugification.

BASE_URL = "https://careers.kuwaitairways.com"
LIST_URL = f"{BASE_URL}/jobs/Careers"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Cache populated by fetch_jobs() so fetch_job_description() needs zero extra HTTP calls.
_desc_cache: dict[str, str] = {}


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


def _slugify(title):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")
    return slug or "job"


def _build_location(raw):
    parts = [raw.get(k) for k in ("City", "State", "Country") if raw.get(k)]
    return ", ".join(parts) if parts else "Kuwait"


def _parse_jobs_blob(html_text):
    """
    Extract and parse the hidden #jobs input's JSON value.
    Returns a list of raw Zoho Recruit job-record dicts (possibly empty).
    """
    soup = BeautifulSoup(html_text, "html.parser")
    jobs_input = soup.find("input", id="jobs")
    if not jobs_input:
        return []
    raw_value = jobs_input.get("value", "")
    if not raw_value:
        return []
    try:
        return json.loads(html.unescape(raw_value))
    except (json.JSONDecodeError, TypeError):
        return []


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from Kuwait Airways' Zoho Recruit career site.

    Single GET returns the full job list (and full descriptions) inline —
    no pagination, no server-side keyword filtering. Populates the
    module-level _desc_cache so fetch_job_description needs no extra calls.
    """
    global _desc_cache

    session = _get_session()
    resp = None
    for attempt in range(3):
        try:
            resp = session.get(LIST_URL, timeout=20)
            if resp.status_code == 429:
                raise RateLimitError(f"429 from {LIST_URL}")
            break
        except RateLimitError:
            raise
        except Exception as exc:
            if attempt == 2:
                print(f"[kuwait_airways] request failed: {exc}")
                return []
            time.sleep(2 ** (attempt + 1))

    if resp is None or resp.status_code != 200:
        print(f"[kuwait_airways] HTTP {getattr(resp, 'status_code', '?')} — stopping")
        return []

    raw_jobs = _parse_jobs_blob(resp.text)
    if not raw_jobs:
        print("[kuwait_airways] No open jobs currently posted (empty #jobs list, not a fetch failure)")
        return []

    jobs = []
    new_cache: dict[str, str] = {}

    for raw in raw_jobs[:max_listings]:
        job_id = str(raw.get("id") or "")
        title = raw.get("Posting_Title") or raw.get("Job_Opening_Name") or ""
        if not job_id or not title:
            continue

        url = f"{BASE_URL}/jobs/Careers/{job_id}/{_slugify(title)}?source=CareerSite"
        description = raw.get("Job_Description") or ""
        new_cache[job_id] = description

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Kuwait Airways",
            "location": _build_location(raw),
            "posting_date": raw.get("Date_Opened") or "",
            "url": url,
            "source": "kuwait_airways",
        })

    _desc_cache = new_cache
    print(f"[kuwait_airways] Fetched {len(jobs)} jobs, {len(new_cache)} descriptions cached")
    if inter_page_delay:
        time.sleep(inter_page_delay)

    return jobs


def fetch_job_description(application_url):
    """
    Return (description_text, posting_date) for a given job URL.

    Normal path: looks up the job id (parsed from the URL) in _desc_cache —
    zero extra HTTP calls, since fetch_jobs() always runs first in the
    pipeline. Falls back to re-fetching the listing page if the cache is
    empty (test isolation / direct-call scenarios).
    Returns ("", "") on any failure — never raises (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    m = re.search(r"/jobs/Careers/(\d+)", application_url)
    if not m:
        return ("", "")
    job_id = m.group(1)

    if job_id in _desc_cache:
        return (_desc_cache[job_id], "")

    try:
        session = _get_session()
        resp = session.get(LIST_URL, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {LIST_URL}")
        if resp.status_code != 200:
            return ("", "")

        for raw in _parse_jobs_blob(resp.text):
            if str(raw.get("id") or "") == job_id:
                description = raw.get("Job_Description") or ""
                _desc_cache[job_id] = description
                return (description, "")

        return ("", "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
