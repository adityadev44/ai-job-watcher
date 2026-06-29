import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://boeing.wd1.myworkdayjobs.com"
TENANT = "boeing"
SITE = "EXTERNAL_CAREERS"
API_BASE = f"{BASE_URL}/wday/cxs/{TENANT}/{SITE}"
BROWSE_BASE = f"{BASE_URL}/{SITE}"
PAGE_SIZE = 20

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries."""


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def _parse_posted_on(posted_on_str):
    """
    Parse Workday relative date strings to YYYY-MM-DD.
    Examples: 'Posted Today', 'Posted Yesterday', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'
    """
    if not posted_on_str:
        return ""
    s = posted_on_str.lower().strip()
    today = datetime.date.today()
    if "today" in s:
        return today.strftime("%Y-%m-%d")
    if "yesterday" in s:
        return (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)\+?\s*days?\s*ago", s)
    if m:
        days = min(int(m.group(1)), 30)  # cap at 30 for "30+ Days Ago"
        return (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    return ""


def get_company(url):
    """Return company display name — always Boeing Global Services for this pipeline."""
    return "Boeing Global Services"


def fetch_jobs(max_listings=200, inter_page_delay=0.2):
    """
    Fetch Boeing job listings from Workday CXS API.

    Boeing uses Workday at boeing.wd1.myworkdayjobs.com, tenant EXTERNAL_CAREERS.
    No server-side keyword filtering — all ~1078 Boeing jobs are returned.
    Gate 2 (engine domain) handles division filtering; Gate 4 (US citizenship)
    handles defense roles. No BGS pre-filter needed: BGS MRO descriptions
    clearly mention GE90/GEnx/LEAP and engine shop activities, while
    Commercial/Defense descriptions do not match the engine_specific_terms.

    Returns list of job dicts.
    """
    session = _get_session()
    all_jobs = []
    seen_paths = set()
    offset = 0
    total = None

    while len(all_jobs) < max_listings:
        if total is not None and offset >= total:
            break

        limit = min(PAGE_SIZE, max_listings - len(all_jobs))
        body = {
            "limit": limit,
            "offset": offset,
            "searchText": "",
            "appliedFacets": {},
        }

        resp = None
        for attempt in range(3):
            try:
                resp = session.post(f"{API_BASE}/jobs", json=body, timeout=20)
                if resp.status_code == 429:
                    raise RateLimitError("429 from Boeing Workday jobs API")
                break
            except RateLimitError:
                raise
            except Exception as exc:
                if attempt == 2:
                    print(f"[boeing] offset={offset}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(
                f"[boeing] offset={offset}: "
                f"HTTP {getattr(resp, 'status_code', '?')} — stopping"
            )
            break

        data = resp.json()
        if total is None:
            total = data.get("total", 0)
            print(f"[boeing] Total jobs available: {total}")

        postings = data.get("jobPostings", [])
        if not postings:
            print(f"[boeing] offset={offset}: no results — stopping")
            break

        new_count = 0
        for raw in postings:
            ext_path = raw.get("externalPath", "")
            if not ext_path or ext_path in seen_paths:
                continue
            seen_paths.add(ext_path)

            # bulletFields[0] is the job requisition ID (e.g. "JR2026516840")
            bullet = raw.get("bulletFields", [])
            job_id = bullet[0] if bullet else ext_path

            job = {
                "id": job_id,
                "title": raw.get("title", ""),
                "location": raw.get("locationsText", ""),
                "posting_date": _parse_posted_on(raw.get("postedOn", "")),
                "url": f"{BROWSE_BASE}{ext_path}",
                "company": "Boeing Global Services",
                "source": "boeing",
            }
            all_jobs.append(job)
            new_count += 1

        print(
            f"[boeing] offset={offset}: {len(postings)} returned, "
            f"{new_count} new — running total: {len(all_jobs)}"
        )
        offset += len(postings)

        if inter_page_delay > 0:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch job description from Boeing Workday CXS job detail endpoint.

    Browseable URL:  https://boeing.wd1.myworkdayjobs.com/EXTERNAL_CAREERS/job/LOC/Title_JR...
    Detail API URL:  https://boeing.wd1.myworkdayjobs.com/wday/cxs/boeing/EXTERNAL_CAREERS/job/LOC/Title_JR...

    Returns (description_text, posting_date_string).
    On ANY failure: returns ("", "") — never raises (except RateLimitError on 429).
    """
    if not application_url:
        return ("", "")

    # Extract the /job/... path from the browseable URL
    # e.g. https://boeing.wd1.myworkdayjobs.com/EXTERNAL_CAREERS/job/IND---Bangalore-India/...
    #   → /job/IND---Bangalore-India/...
    m = re.search(r"/" + re.escape(SITE) + r"(/job/[^\s?#]+)", application_url)
    if not m:
        return ("", "")
    job_path = m.group(1)

    session = _get_session()
    detail_url = f"{API_BASE}{job_path}"

    resp = None
    for attempt in range(3):
        try:
            resp = session.get(detail_url, timeout=20)
            if resp.status_code == 429:
                raise RateLimitError(f"429 from {detail_url}")
            if resp.status_code != 200:
                return ("", "")
            break
        except RateLimitError:
            raise
        except Exception:
            if attempt == 2:
                return ("", "")
            time.sleep(2 ** (attempt + 1))
    else:
        return ("", "")

    try:
        data = resp.json()
        info = data.get("jobPostingInfo", {})
        html_desc = info.get("jobDescription", "")
        posting_date = _parse_posted_on(info.get("postedOn", ""))

        if not html_desc:
            return ("", posting_date)

        soup = BeautifulSoup(html_desc, "lxml")
        text = soup.get_text(separator=" ", strip=True)
        return (text, posting_date)

    except Exception:
        return ("", "")
