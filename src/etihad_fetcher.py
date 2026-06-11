import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

# Etihad Engineering (Abu Dhabi MRO) uses Oracle HCM Cloud Recruiting.
# The careers site is careers.etihadengineering.com; the API backend is
# fa-eurv-saasfaprod1.fa.ocs.oraclecloud.com. No authentication, session
# bootstrap, or Playwright required — plain curl_cffi GET calls work.

BASE_CAREERS = "https://careers.etihadengineering.com"
BASE_API = "https://fa-eurv-saasfaprod1.fa.ocs.oraclecloud.com"
SITE = "CX_1"

_LIST_URL = (
    BASE_API
    + "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    + "?onlyData=true"
    + "&expand=requisitionList.secondaryLocations"
    + f"&finder=findReqs;siteNumber={SITE},"
      "facetsList=NONE,limit=100,sortBy=POSTING_DATES_DESC"
)

_DETAIL_URL_TMPL = (
    BASE_API
    + "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    + "?expand=all&onlyData=true"
    + '&finder=ById;Id="{job_id}",siteNumber=' + SITE
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    """Raised when Oracle HCM returns HTTP 429 after retries."""


_session: curl_requests.Session | None = None


def _get_session() -> curl_requests.Session:
    global _session
    if _session is None:
        s = curl_requests.Session(impersonate="chrome120")
        s.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
            "Referer": BASE_CAREERS + "/",
            "Origin": BASE_CAREERS,
        })
        _session = s
    return _session


def _get(url: str, max_retries: int = 3, base_delay: float = 2.0) -> dict:
    s = _get_session()
    for attempt in range(max_retries + 1):
        resp = s.get(url, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[etihad] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries")
        resp.raise_for_status()
        return resp.json()
    raise RateLimitError("Rate-limited: exhausted retries")


def _build_job(raw: dict) -> dict:
    job_id = str(raw.get("Id", ""))
    return {
        "id": job_id,
        "title": raw.get("Title", ""),
        "location": raw.get("PrimaryLocation", ""),
        "posting_date": raw.get("PostedDate", ""),
        "url": f"{BASE_CAREERS}/en/sites/careers/job/{job_id}",
        "company": "Etihad Engineering",
        "source": "etihad",
    }


def fetch_jobs() -> list[dict]:
    """
    Fetch all active Etihad Engineering job listings via Oracle HCM Cloud REST API.
    Returns jobs sorted newest-first. Typically 5–30 active listings.
    """
    print("[etihad] Fetching job list …")
    try:
        data = _get(_LIST_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[etihad] Fetch failed: {exc}")
        return []

    items = data.get("items", [])
    if not items:
        print("[etihad] No items in response")
        return []

    req_list = items[0].get("requisitionList", [])
    total = items[0].get("TotalJobsCount", len(req_list))
    print(f"[etihad] Total available: {total}, fetched: {len(req_list)}")

    jobs = [_build_job(raw) for raw in req_list if raw.get("Id")]
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch full description for an Etihad Engineering job via Oracle HCM detail API.
    Returns (description_text, posting_date). Returns ("", "") on any failure.
    """
    if not application_url:
        return ("", "")

    m = re.search(r"/job/(\d+)", application_url)
    if not m:
        return ("", "")
    job_id = m.group(1)

    try:
        data = _get(_DETAIL_URL_TMPL.format(job_id=job_id))
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[etihad] Description fetch failed ({job_id}): {exc}")
        return ("", "")

    items = data.get("items", [])
    if not items:
        return ("", "")

    detail = items[0]
    # Combine responsibilities + qualifications; both may be HTML
    html_parts = [
        detail.get("ExternalResponsibilitiesStr") or "",
        detail.get("ExternalQualificationsStr") or "",
        detail.get("ExternalDescriptionStr") or "",
    ]
    combined_html = " ".join(p for p in html_parts if p)

    if not combined_html.strip():
        return ("", detail.get("ExternalPostedStartDate", "")[:10])

    soup = BeautifulSoup(combined_html, "lxml")
    text = soup.get_text(separator=" ", strip=True)

    posting_date = detail.get("PostedDate") or (detail.get("ExternalPostedStartDate") or "")[:10]
    return (text, posting_date)
