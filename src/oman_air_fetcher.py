import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

# Oman Air's careers portal runs on a legacy Java/Struts "eRecruit" system
# (JSESSIONID cookies, .do servlet actions). The public-facing www.omanair.com
# host sits behind an Incapsula bot challenge that blocks plain HTTP clients,
# but the services.omanair.com host serves the identical backend without any
# challenge — use it for both fetching and the browseable URL.
#
# KNOWN LIMITATION: at the time this fetcher was written, Oman Air had zero
# active vacancies (confirmed via "No vacancies found" sentinel), so the
# listing-row and detail-page markup below could only be inferred from the
# confirmed URL contract (rmJobDetailedDisplay.do?vacancyId=N, found indexed
# by search engines) and generic Struts/displaytag conventions — not verified
# against a real populated result page. If this pipeline returns 0 fetched
# jobs indefinitely even after Oman Air is known to be hiring, the row
# selector below is the first thing to re-check against live HTML.

BASE_URL = "https://services.omanair.com"
SEARCH_URL = f"{BASE_URL}/erecruit/guest/vacancy_show.do"
DETAIL_URL = f"{BASE_URL}/erecruit/guest/rmJobDetailedDisplay.do"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_NO_RESULTS_MARKERS = ("No vacancies found", "Currently No Vacancy")


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_URL + "/erecruit/guest/rmSearchVacancy.do",
    })
    return s


def _parse_listing_page(html):
    """
    Parse one page of Oman Air vacancy search results.

    The only confirmed-stable signal is the detail-page link pattern
    (rmJobDetailedDisplay.do?vacancyId=N) — row/column structure is not
    verified (see module docstring), so this extracts by href rather than
    by table class names, which is more resilient to markup drift.
    """
    if any(marker in html for marker in _NO_RESULTS_MARKERS):
        return []

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_ids = set()

    for a in soup.find_all("a", href=re.compile(r"rmJobDetailedDisplay\.do\?vacancyId=")):
        href = a.get("href", "")
        m = re.search(r"vacancyId=(\d+)", href)
        if not m:
            continue
        vacancy_id = m.group(1)
        if vacancy_id in seen_ids:
            continue
        seen_ids.add(vacancy_id)

        title = a.get_text(strip=True)
        if not title:
            continue

        jobs.append({
            "id": vacancy_id,
            "title": title,
            "company": "Oman Air",
            "location": "Oman",
            "posting_date": "",
            "url": f"{DETAIL_URL}?vacancyId={vacancy_id}",
            "source": "oman_air",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.5):
    """
    Fetch all open jobs from Oman Air's eRecruit portal.

    GET with all filter fields set to "-1" (All) returns every active
    vacancy across every department — no separate Engineering-only query,
    same approach as GMR/Air India (Gate 1-4 do the domain filtering).
    Paginates via displaytag-style `d-4001840-p=N`, stopping on an empty
    or repeated page.
    """
    session = _get_session()
    all_jobs = []
    seen_ids = set()
    page = 1

    while len(all_jobs) < max_listings:
        params = {
            "vacancyForm.categoryId": "-1",
            "vacancyForm.categoryName": "-1",
            "vacancyForm.mainCategoryId": "-1",
            "vacancyForm.jobLocation": "-1",
            "vacancyForm.jobTitle": "-1",
            "vacancyForm.jobTypeTechId": "-1",
            "vacancyForm.jobDescription": "",
            "d-4001840-p": str(page),
        }

        resp = None
        for attempt in range(3):
            try:
                resp = session.get(SEARCH_URL, params=params, timeout=20)
                if resp.status_code == 429:
                    raise RateLimitError(f"429 from {SEARCH_URL}")
                break
            except RateLimitError:
                raise
            except Exception as exc:
                if attempt == 2:
                    print(f"[oman_air] page={page}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[oman_air] page={page}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            if page == 1:
                print("[oman_air] No vacancies currently posted (confirmed empty result, not a fetch failure)")
            break

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break

        all_jobs.extend(new_jobs)
        print(f"[oman_air] page={page}: {len(page_jobs)} jobs, {len(new_jobs)} new — total: {len(all_jobs)}")

        page += 1
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch the full job description from an rmJobDetailedDisplay.do page.

    Returns (description_text, posting_date) — posting_date is always ''
    (not reliably available; see module docstring on markup uncertainty).
    Returns ("", "") on any failure — never raises (except RateLimitError on 429).
    """
    if not application_url or "vacancyId=" not in application_url:
        return ("", "")

    session = _get_session()

    try:
        resp = session.get(application_url, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {application_url}")
        if resp.status_code != 200:
            return ("", "")
        if "Internal Server Error" in resp.text:
            return ("", "")  # expired/invalid vacancyId

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["nav", "footer", "script", "style"]):
            tag.decompose()

        content = soup.find("div", class_="middle") or soup.find(id="outer_div") or soup
        description = content.get_text(separator=" ", strip=True)

        return (description, "")

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
