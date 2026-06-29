"""
Honeywell Aerospace job fetcher.

Source  : https://careers.honeywell.com/en/sites/Honeywell/jobs
ATS     : Oracle HCM Candidate Experience (ORC)
Backend : https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
Strategy: Direct REST call to the Oracle HCM CE API — publicly accessible without
          authentication. Tail-end pagination returns newest max_listings jobs.
          TotalJobsCount discovered from first probe request.

API response structure:
  items[0].TotalJobsCount  — total jobs available
  items[0].requisitionList — list of job dicts for current page
    .Id, .Title, .PostedDate, .PrimaryLocation, .PrimaryLocationCountry
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests

SOURCE = "honeywell"
ORC_BASE_URL = "https://ibqbjb.fa.ocs.oraclecloud.com"
ORC_API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
SITE_NUMBER = "CX_1"
CAREERS_BASE = "https://careers.honeywell.com"
PAGE_SIZE = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": CAREERS_BASE,
    "Referer": f"{CAREERS_BASE}/en/sites/Honeywell/jobs",
}

_session = requests.Session()
_session.headers.update(HEADERS)


class RateLimitError(Exception):
    """Raised when the portal returns HTTP 429 after all retries are exhausted."""


def _build_url(limit: int, offset: int) -> str:
    finder = (
        f"findReqs;siteNumber={SITE_NUMBER},"
        "facetsList=LOCATIONS,"
        f"limit={limit},"
        f"offset={offset},"
        "sortBy=POSTING_DATES_DESC"
    )
    return (
        f"{ORC_BASE_URL}{ORC_API_PATH}"
        f"?onlyData=true"
        f"&expand=requisitionList.workLocation"
        f"&finder={finder}"
    )


def _get(url: str, max_retries: int = 3, base_delay: float = 2.0) -> dict:
    for attempt in range(max_retries + 1):
        resp = _session.get(url, timeout=30)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[honeywell] 429 rate-limit — waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries")
        resp.raise_for_status()
        return resp.json()
    raise RateLimitError("Exhausted retries")


def _build_job_url(job_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{CAREERS_BASE}/en/sites/Honeywell/job/{job_id}/{slug}"


def _parse_job(raw: dict) -> dict:
    job_id = str(raw.get("Id", ""))
    title = raw.get("Title", "").strip()
    return {
        "id": job_id,
        "title": title,
        "location": raw.get("PrimaryLocation", "").strip(),
        "posting_date": raw.get("PostedDate", ""),
        "url": _build_job_url(job_id, title),
        "company": "Honeywell Aerospace",
        "source": SOURCE,
    }


def fetch_jobs(config: dict | None = None) -> list[dict]:
    """
    Fetch Honeywell Aerospace job listings via Oracle HCM CE REST API.

    All Honeywell jobs are fetched; Gate 1-4 filters downstream to aerospace
    MRO / engine roles. Uses tail-end pagination to return newest max_listings
    jobs. Returns a deduplicated list of job dicts.
    """
    cfg = (config or {}).get("honeywell_search", {})
    max_listings = cfg.get("max_listings", 200)
    inter_page_delay = cfg.get("inter_page_delay", 0.2)

    # Probe to get total job count
    try:
        probe = _get(_build_url(limit=1, offset=0))
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[honeywell] Probe call failed: {exc}")
        return []

    total_avail = probe.get("items", [{}])[0].get("TotalJobsCount", 0)
    if total_avail == 0:
        print("[honeywell] No jobs found — check API connectivity")
        return []

    # Tail-end pagination: fetch newest jobs first
    start_offset = max(0, total_avail - max_listings)
    print(f"[honeywell] TotalJobsCount={total_avail}, fetching from offset {start_offset} (newest {max_listings})")

    seen_ids: set = set()
    all_jobs: list = []
    offset = start_offset

    while offset < total_avail:
        limit = min(PAGE_SIZE, total_avail - offset)
        try:
            data = _get(_build_url(limit=limit, offset=offset))
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[honeywell] Fetch error at offset={offset}: {exc}")
            break

        req_list = data.get("items", [{}])[0].get("requisitionList", [])
        if not req_list:
            print(f"[honeywell]   offset={offset}: no results — stopping")
            break

        new = 0
        for raw in req_list:
            job = _parse_job(raw)
            if job["id"] and job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
                new += 1

        print(f"[honeywell]   offset={offset}: {len(req_list)} results, {new} new (total: {total_avail})")
        offset += len(req_list)
        if inter_page_delay > 0 and offset < total_avail:
            time.sleep(inter_page_delay)

    print(f"[honeywell] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Honeywell job detail pages are Oracle HCM CE React SPAs — descriptions
    are not available in static HTML. Returns ("", "") unconditionally.
    The matcher keeps all Gate-1-passing jobs when description is unavailable.
    """
    return ("", "")
