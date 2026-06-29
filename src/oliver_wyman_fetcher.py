import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

# Oliver Wyman / CAVOK careers — Phenom People ATS via Marsh McLennan parent portal
# Portal:     https://careers.marsh.com (Marsh McLennan Companies shared portal)
# refNum:     MAMCGLOBAL  (confirmed from job URL pattern: MAMCGLOBALR######EXTERNALENGLOBAL)
# OW search:  /global/en/oliver-wyman-search  (Oliver Wyman-scoped landing page)
# Bootstrap:  GET /global/en/oliver-wyman-search → CSRF + pageId/pageName from phApp config
# Widget API: POST /widgets with ddoKey:"refineSearch" (list) or "jobDetail" (description)
# Pre-filter: The MAMCGLOBAL portal serves ALL Marsh McLennan companies (Marsh, Guy Carpenter,
#             Mercer, Oliver Wyman). Pre-filter to Oliver Wyman roles is applied in
#             run_oliver_wyman.py — keep only jobs with "oliver wyman" in title or company field.
# Note:       CAVOK (aviation MRO consulting brand) is integrated into Oliver Wyman aviation
#             practice; job titles appear as "Oliver Wyman - [Role]", not "CAVOK - [Role]".
# Note:       If 403 errors appear in production, switch to curl_cffi with
#             impersonate="chrome120" (same fix as RTX/careers.rtx.com).

BASE_URL = "https://careers.marsh.com"
BOOTSTRAP_PAGE = "/global/en/oliver-wyman-search"
REF_NUM = "MAMCGLOBAL"
PAGE_SIZE = 20

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


# Module-level session; set by _bootstrap(), reused by fetch_job_description().
_session: requests.Session | None = None
_page_id = "page1"            # fallback — overwritten by _bootstrap() from phApp config
_page_name = "search-results"  # fallback


def _bootstrap() -> None:
    """
    Bootstrap a requests session from the Oliver Wyman search page on careers.marsh.com.
    Extracts CSRF token and auto-discovers pageId/pageName from inline phApp JS config.
    """
    global _session, _page_id, _page_name
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    resp = s.get(f"{BASE_URL}{BOOTSTRAP_PAGE}", timeout=20)
    resp.raise_for_status()

    m_csrf = re.search(r"id='csrfToken'[^>]*>([^<]+)<", resp.text)
    csrf = m_csrf.group(1).strip() if m_csrf else ""

    m_pid = re.search(r'"pageId"\s*:\s*"([^"]+)"', resp.text)
    m_pname = re.search(r'"pageName"\s*:\s*"([^"]+)"', resp.text)
    if m_pid:
        _page_id = m_pid.group(1)
    if m_pname:
        _page_name = m_pname.group(1)

    print(f"[oliver_wyman] Bootstrap OK — pageId={_page_id!r}, pageName={_page_name!r}, csrf={'<found>' if csrf else '<empty>'}")

    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "csrf-token": csrf,
        "Referer": f"{BASE_URL}{BOOTSTRAP_PAGE}",
    })
    _session = s


def _post_widgets(payload: dict, max_retries: int = 3, base_delay: float = 2.0) -> dict:
    """POST to /widgets with exponential back-off on 429. Raises RateLimitError after max_retries."""
    for attempt in range(max_retries + 1):
        resp = _session.post(f"{BASE_URL}/widgets", json=payload, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[oliver_wyman] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on /widgets")
        resp.raise_for_status()
        return resp.json()
    raise RateLimitError("Rate-limited: exhausted retries for /widgets")


def _refine_search(from_: int, size: int) -> dict:
    return _post_widgets({
        "searchText": "",
        "sortBy": "",
        "subsearch": "",
        "from": from_,
        "jobs": True,
        "counts": False,
        "all_fields": [],
        "pageName": _page_name,
        "size": size,
        "clearAll": False,
        "jdsource": "facets",
        "isSliderEnable": False,
        "pageId": _page_id,
        "siteType": "external",
        "deviceType": "desktop",
        "lang": "en_global",
        "refNum": REF_NUM,
        "ddoKey": "refineSearch",
    })


def _build_job(raw: dict) -> dict:
    req_id = raw.get("reqId") or raw.get("jobId", "")
    # Try businessUnit first (confirms sub-brand), then company/companyName
    company = (
        raw.get("businessUnit")
        or raw.get("company")
        or raw.get("companyName")
        or "Oliver Wyman"
    )
    return {
        "id": req_id,
        "title": raw.get("title", ""),
        "location": raw.get("location", ""),
        "posting_date": raw.get("postedDate", ""),
        "url": f"{BASE_URL}/global/en/job/{req_id}",
        "company": company,
        "source": "oliver_wyman",
    }


def fetch_jobs(max_listings: int = 200, inter_page_delay: float = 0.2) -> list:
    """
    Fetch Oliver Wyman / CAVOK job listings via the Marsh McLennan Phenom People API.

    The MAMCGLOBAL portal serves all Marsh McLennan companies. This fetcher returns
    all jobs in the newest max_listings; the run script pre-filters to Oliver Wyman
    roles (title contains "oliver wyman" or company field indicates Oliver Wyman).

    Uses tail-end pagination to retrieve the newest max_listings jobs.
    Returns a deduplicated list of job dicts.
    """
    _bootstrap()

    # Probe to get total job count.
    try:
        probe = _refine_search(from_=0, size=1)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[oliver_wyman] Probe call failed: {exc}")
        return []

    total_avail = probe.get("refineSearch", {}).get("totalHits", 0)
    if total_avail == 0:
        print("[oliver_wyman] No jobs found — check API connectivity")
        return []

    # Fetch from the tail so we always get the newest jobs.
    start_offset = max(0, total_avail - max_listings)
    print(f"[oliver_wyman] totalHits={total_avail}, fetching from offset {start_offset} (newest {max_listings})")

    seen_ids: set = set()
    all_jobs: list = []
    from_ = start_offset

    while from_ < total_avail:
        size = min(PAGE_SIZE, total_avail - from_)
        try:
            data = _refine_search(from_=from_, size=size)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[oliver_wyman] Fetch error at from={from_}: {exc}")
            break

        rs = data.get("refineSearch", {})
        jobs_raw = rs.get("data", {}).get("jobs", [])

        if not jobs_raw:
            print(f"[oliver_wyman]   from={from_}: no results — stopping pagination")
            break

        new = 0
        for raw in jobs_raw:
            job = _build_job(raw)
            if job["id"] and job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
                new += 1

        print(f"[oliver_wyman]   from={from_}: {len(jobs_raw)} results, {new} new (server total: {total_avail})")

        from_ += len(jobs_raw)
        if inter_page_delay > 0 and from_ < total_avail:
            time.sleep(inter_page_delay)

    print(f"[oliver_wyman] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch the full description for an Oliver Wyman job via the Phenom jobDetail widget API.
    Returns (description_text, posting_date_string).
    On ANY failure: returns ("", "") — never raises (except RateLimitError).
    """
    if not application_url:
        return ("", "")

    m = re.search(r"/job/([^/?#\s]+)", application_url)
    if not m:
        return ("", "")
    req_id = m.group(1)

    if _session is None:
        _bootstrap()

    try:
        data = _post_widgets({
            "jobId": req_id,
            "refNum": REF_NUM,
            "ddoKey": "jobDetail",
            "lang": "en_global",
            "deviceType": "desktop",
            "pageName": _page_name,
            "siteType": "external",
        })
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[oliver_wyman] Description fetch failed ({req_id}): {exc}")
        return ("", "")

    job = data.get("jobDetail", {}).get("data", {}).get("job", {})
    if not job:
        return ("", "")

    html_desc = job.get("description", "")
    posting_date = job.get("postedDate", "")

    if not html_desc:
        return ("", posting_date)

    soup = BeautifulSoup(html_desc, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    return (text, posting_date)
