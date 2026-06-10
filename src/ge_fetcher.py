import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://careers.geaerospace.com"
SEARCH_PAGE = "/global/en/search-results"
REF_NUM = "GAOGAYGLOBAL"
PAGE_SIZE = 20

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


# Module-level session; set by _bootstrap(), reused by fetch_job_description().
_session: requests.Session | None = None


def _bootstrap() -> None:
    """Create a fresh requests session and obtain a CSRF token from the careers page."""
    global _session
    s = requests.Session()
    s.headers.update({"User-Agent": _BROWSER_UA, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"})
    resp = s.get(f"{BASE_URL}{SEARCH_PAGE}", timeout=20)
    resp.raise_for_status()
    m = re.search(r"id='csrfToken'[^>]*>([^<]+)<", resp.text)
    csrf = m.group(1).strip() if m else ""
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "csrf-token": csrf,
        "Referer": f"{BASE_URL}{SEARCH_PAGE}",
    })
    _session = s


def _post_widgets(payload: dict, max_retries: int = 3, base_delay: float = 2.0) -> dict:
    """POST to /widgets with exponential back-off on 429. Raises RateLimitError after max_retries."""
    for attempt in range(max_retries + 1):
        resp = _session.post(f"{BASE_URL}/widgets", json=payload, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[ge] 429 rate-limit — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
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
        "pageName": "search-results",
        "size": size,
        "clearAll": False,
        "jdsource": "facets",
        "isSliderEnable": False,
        "pageId": "page20",
        "siteType": "external",
        "deviceType": "desktop",
        "lang": "en_global",
        "refNum": REF_NUM,
        "ddoKey": "refineSearch",
    })


def _build_job(raw: dict) -> dict:
    req_id = raw.get("reqId") or raw.get("jobId", "")
    return {
        "id": req_id,
        "title": raw.get("title", ""),
        "location": raw.get("location", ""),
        "posting_date": raw.get("postedDate", ""),
        "url": f"{BASE_URL}/global/en/job/{req_id}",
        "company": raw.get("company") or raw.get("companyName", "GE Aerospace"),
        "source": "ge",
    }


def fetch_jobs(max_listings: int = 200, inter_page_delay: float = 0.2) -> list:
    """
    Fetch GE Aerospace job listings.
    The Phenom People API does not filter server-side by keyword, so all jobs are
    fetched and filtering happens downstream in matcher.py.
    Returns a deduplicated list of job dicts.
    """
    _bootstrap()
    seen_ids: set = set()
    all_jobs: list = []
    from_ = 0

    while from_ < max_listings:
        size = min(PAGE_SIZE, max_listings - from_)
        try:
            data = _refine_search(from_=from_, size=size)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[ge] Fetch error at from={from_}: {exc}")
            break

        rs = data.get("refineSearch", {})
        total_avail = rs.get("totalHits", 0)
        jobs_raw = rs.get("data", {}).get("jobs", [])

        if not jobs_raw:
            print(f"[ge]   from={from_}: no results — stopping pagination")
            break

        new = 0
        for raw in jobs_raw:
            job = _build_job(raw)
            if job["id"] and job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
                new += 1

        print(f"[ge]   from={from_}: {len(jobs_raw)} results, {new} new (server total: {total_avail})")

        from_ += len(jobs_raw)
        if from_ >= total_avail:
            break
        if inter_page_delay > 0:
            time.sleep(inter_page_delay)

    print(f"[ge] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch the full description for a GE Aerospace job via the Phenom jobDetail API.
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
            "pageName": "search-results",
            "siteType": "external",
        })
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[ge] Description fetch failed ({req_id}): {exc}")
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
