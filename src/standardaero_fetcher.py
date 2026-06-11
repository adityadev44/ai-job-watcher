import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

# StandardAero uses Oracle HCM Cloud Recruiting — same ATS as Etihad Engineering.
# The careers portal redirects standardaero.com/careers → Oracle HCM hosted at
# cva.fa.us1.oraclecloud.com (US1 data centre; Etihad uses a different data centre).
# No Playwright needed — plain curl_cffi GET calls work.

BASE_API = "https://cva.fa.us1.oraclecloud.com"
SITE = "CX_3"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Browseable URL pattern: /hcmUI/CandidateExperience/en/sites/CX_3/job/{id}
_JOB_URL_TMPL = BASE_API + "/hcmUI/CandidateExperience/en/sites/" + SITE + "/job/{job_id}"

_DETAIL_URL_TMPL = (
    BASE_API
    + "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    + "?expand=all&onlyData=true"
    + '&finder=ById;Id="{job_id}",siteNumber=' + SITE
)


class RateLimitError(Exception):
    pass


_session: curl_requests.Session | None = None


def _get_session() -> curl_requests.Session:
    global _session
    if _session is None:
        s = curl_requests.Session(impersonate="chrome120")
        s.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
            "Referer": BASE_API + "/hcmUI/CandidateExperience/en/sites/" + SITE + "/",
            "Origin": BASE_API,
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
                print(f"[standardaero] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
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
        "url": _JOB_URL_TMPL.format(job_id=job_id),
        "company": "StandardAero",
        "source": "standardaero",
    }


def fetch_jobs(max_listings: int = 300, inter_page_delay: float = 0.2) -> list[dict]:
    """
    Fetch all active StandardAero job listings via Oracle HCM Cloud REST API.

    Paginates with offset= in the finder string (100 jobs per page). Typically ~250 active.
    Returns all jobs; 3-gate matcher handles domain filtering.
    """
    all_jobs = []
    seen_ids: set[str] = set()
    offset = 0
    total: int | None = None

    while len(all_jobs) < max_listings:
        if total is not None and offset >= total:
            break

        url = (
            BASE_API
            + "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            + "?onlyData=true"
            + "&expand=requisitionList.secondaryLocations"
            + f"&finder=findReqs;siteNumber={SITE},"
              f"facetsList=NONE,limit=100,sortBy=POSTING_DATES_DESC,offset={offset}"
        )

        try:
            data = _get(url)
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[standardaero] Fetch failed at offset={offset}: {exc}")
            break

        items = data.get("items", [])
        if not items:
            break

        req_list = items[0].get("requisitionList", [])
        if total is None:
            total = items[0].get("TotalJobsCount", None)
            print(f"[standardaero] Total available: {total}")

        if not req_list:
            break

        new_jobs = [_build_job(r) for r in req_list if r.get("Id") and str(r["Id"]) not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break

        all_jobs.extend(new_jobs)
        print(f"[standardaero] offset={offset}: {len(req_list)} jobs, {len(new_jobs)} new — total so far: {len(all_jobs)}")

        offset += len(req_list)
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Fetch full description for a StandardAero job via Oracle HCM detail API.

    Returns (description_text, posting_date). Returns ("", "") on any failure.
    Description is in ExternalDescriptionStr (HTML). Posting date from ExternalPostedStartDate.
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
        print(f"[standardaero] Description fetch failed ({job_id}): {exc}")
        return ("", "")

    items = data.get("items", [])
    if not items:
        return ("", "")

    detail = items[0]
    # ExternalDescriptionStr holds the full job description (HTML)
    html_parts = [
        detail.get("ExternalDescriptionStr") or "",
        detail.get("ExternalResponsibilitiesStr") or "",
        detail.get("ExternalQualificationsStr") or "",
    ]
    combined_html = " ".join(p for p in html_parts if p)

    if not combined_html.strip():
        return ("", "")

    soup = BeautifulSoup(combined_html, "lxml")
    text = soup.get_text(separator=" ", strip=True)

    # Fallback to listing PostedDate (already YYYY-MM-DD) — detail has ExternalPostedStartDate
    posting_date = (detail.get("ExternalPostedStartDate") or "")[:10]
    return (text, posting_date)
