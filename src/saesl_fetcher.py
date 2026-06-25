import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import time
import requests
from bs4 import BeautifulSoup

# SAESL (Singapore Aero Engine Services, a Rolls-Royce / SIA Engineering joint
# venture, Trent engine MRO) uses the ApplyOurJobs ATS — a custom ASP.NET
# WebForms vendor. The search form's normal postback throws a server-side
# "Unable to serialize the session state" error for plain HTTP clients (and is
# 500 even from a fresh session), but the underlying ASP.NET PageMethod it
# calls via AJAX (default.aspx/GetJobList) is a clean JSON endpoint that needs
# no session, cookies, or ViewState at all. No Playwright needed.

BASE_URL = "https://saesl.applyourjobs.com"
API_URL = f"{BASE_URL}/default.aspx/GetJobList"

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
        "Accept": "application/json, text/javascript, */*",
        "Referer": BASE_URL + "/",
    })
    return s


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open jobs from SAESL's ApplyOurJobs portal.

    The GetJobList PageMethod returns the full result set in one call when
    endCount >= total (currently ~30 jobs) — no UI pagination to walk through.
    No server-side keyword filtering — empty srcArr returns everything.
    """
    session = _get_session()
    payload = {
        "srcArr": [],
        "sortingColumn": "POSTINGDATE",
        "sortDirection": "desc",
        "startCount": "0",
        "endCount": max_listings,
    }

    resp = None
    for attempt in range(3):
        try:
            resp = session.post(
                API_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=20,
            )
            if resp.status_code == 429:
                raise RateLimitError(f"429 from {API_URL}")
            break
        except RateLimitError:
            raise
        except Exception as exc:
            if attempt == 2:
                print(f"[saesl] request failed: {exc}")
                return []
            time.sleep(2 ** (attempt + 1))

    if resp is None or resp.status_code != 200:
        print(f"[saesl] HTTP {getattr(resp, 'status_code', '?')} — stopping")
        return []

    try:
        outer = resp.json()
        raw_jobs = json.loads(outer["d"]["JsonData"])
    except Exception as exc:
        print(f"[saesl] failed to parse response: {exc}")
        return []

    jobs = []
    for raw in raw_jobs:
        title = raw.get("JOBTITLE", "")
        job_code = raw.get("JOBCODE", "")
        if not title or not job_code:
            continue

        posting_date = (raw.get("POSTINGDATE") or "").split("T")[0]
        location = raw.get("JOBLOCATION") or "Singapore"

        jobs.append({
            "id": raw.get("REFERENCENUMBER", ""),
            "title": title,
            "company": "SAESL",
            "location": location,
            "posting_date": posting_date,
            "url": f"{BASE_URL}/jobdetails.aspx?ID={job_code}",
            "source": "saesl",
        })

    print(f"[saesl] Fetched {len(jobs)} jobs")
    if inter_page_delay:
        time.sleep(inter_page_delay)

    return jobs[:max_listings]


def fetch_job_description(application_url):
    """
    Fetch the full job description from a SAESL jobdetails.aspx page.

    Returns (description_text, posting_date) — posting_date is always '' since
    the listing date from fetch_jobs() is already accurate.
    Returns ("", "") on any failure — never raises (except RateLimitError on 429).
    """
    if not application_url or "jobdetails.aspx" not in application_url:
        return ("", "")

    session = _get_session()

    try:
        resp = session.get(application_url, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {application_url}")
        if resp.status_code != 200:
            return ("", "")

        soup = BeautifulSoup(resp.text, "html.parser")
        desc_el = soup.find(id="ctl00_body_tbJobDesc")
        description = desc_el.get_text(separator=" ", strip=True) if desc_el else ""

        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
