import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# Saudia Technic (maintenance arm of Saudia Airlines) uses Talentera by Bayt.com.
# Portal: careers.saudiatechnic.com — plain requests works, no Playwright needed.
# Session setup: GET listing page to extract USER_token, then POST to AJAX manager.
# Typically low volume (~1-10 active jobs). Monitor for engine MRO roles.

BASE_URL = "https://careers.saudiatechnic.com"
LISTING_URL = BASE_URL + "/en/saudi-arabia/jobs/"
AJAX_URL = BASE_URL + "/app/control/byt_job_search_manager"
JOBS_PER_PAGE = 10

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json, text/html, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LISTING_URL,
    })
    return s


def _get_token(session):
    """Fetch listing page and extract USER_token from inline JS."""
    resp = session.get(LISTING_URL, timeout=20)
    if resp.status_code == 429:
        raise RateLimitError(f"429 on listing page")
    m = re.search(r"USER_token = '([^']+)'", resp.text)
    return m.group(1) if m else ""


def _parse_date(date_str):
    """Convert 'YYYY-MM-DD HH:MM:SS' to 'YYYY-MM-DD'. Returns '' on failure."""
    if not date_str:
        return ""
    return date_str[:10]


def _search_page(session, token, page, max_retries=3):
    """POST to Talentera AJAX manager for one page of results."""
    for attempt in range(max_retries):
        try:
            resp = session.post(
                AJAX_URL,
                data={"action": "1", "token": token, "keyword": "", "page": page},
                timeout=20,
            )
            if resp.status_code == 429:
                raise RateLimitError(f"429 on page {page}")
            if resp.status_code != 200:
                print(f"[saudia_technic] page={page}: HTTP {resp.status_code}")
                return None
            return resp.json()
        except RateLimitError:
            raise
        except Exception as exc:
            if attempt == max_retries - 1:
                print(f"[saudia_technic] page={page}: request failed: {exc}")
                return None
            time.sleep(2 ** (attempt + 1))
    return None


def fetch_jobs(max_listings=200, inter_page_delay=0.5):
    """
    Fetch all active Saudia Technic job listings via Talentera AJAX API.

    Paginates via page=N (10 jobs/page). Returns all jobs.
    Typically very low volume (~1-10 active listings).
    """
    session = _get_session()

    try:
        token = _get_token(session)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[saudia_technic] Token fetch failed: {exc}")
        return []

    all_jobs = []
    seen_ids: set[str] = set()
    page = 1
    total: int | None = None

    while len(all_jobs) < max_listings:
        data = _search_page(session, token, page)
        if not data:
            break

        if total is None:
            total = data.get("totalJobs", 0)
            print(f"[saudia_technic] Total available: {total}")

        jobs_raw = data.get("jobs", [])
        if not jobs_raw:
            break

        new_jobs = []
        for raw in jobs_raw:
            job_id = str(raw.get("id", ""))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            relative_url = raw.get("url", "")
            url = BASE_URL + relative_url if relative_url.startswith("/") else relative_url

            new_jobs.append({
                "id": job_id,
                "title": raw.get("title", ""),
                "company": "Saudia Technic",
                "location": raw.get("loc", ""),
                "posting_date": _parse_date(raw.get("crtDate", "")),
                "url": url,
                "source": "saudia_technic",
            })

        all_jobs.extend(new_jobs)
        print(f"[saudia_technic] page={page}: {len(jobs_raw)} jobs, {len(new_jobs)} new — total so far: {len(all_jobs)}")

        if total is not None and len(all_jobs) >= total:
            break
        if len(jobs_raw) < JOBS_PER_PAGE:
            break

        page += 1
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch full description from the Saudia Technic job detail page.

    Returns (description_text, posting_date). Returns ("", "") on any failure.
    Description is in div.job-desc on the detail page.
    """
    if not application_url or "saudiatechnic.com" not in application_url:
        return ("", "")

    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,*/*",
        "Referer": LISTING_URL,
    })

    try:
        resp = s.get(application_url, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {application_url}")
        if resp.status_code != 200:
            return ("", "")

        soup = BeautifulSoup(resp.text, "html.parser")
        desc_div = soup.find(class_="job-desc")
        description = desc_div.get_text(separator=" ", strip=True) if desc_div else ""
        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
