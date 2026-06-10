import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import json
from playwright.sync_api import sync_playwright

BASE_URL = "https://career-in10.hr.cloud.sap"
CAREERS_PATH = "/careers?company=interglobe"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# IndiGo uses SAP SuccessFactors VERP/JUIC/DWR. The search widget on
# /careers?company=interglobe exposes window.careerJobSearchController whose
# .searchJobs() method triggers a DWR POST and returns 10 jobs (page 1 only).
# Pagination is server-session-bound and not accessible from the search page;
# the separate listing URL (/career?career_ns=job_listing_summary&...) that
# hosts the paginator requires login. We therefore fetch page 1 (10 newest)
# on each run — sufficient since new postings surface here within 24 h.
#
# Job detail pages use SAP UI5 and do not render in headless Firefox; the
# jobReqSecKey in the detail URL is also session-scoped. fetch_job_description
# returns ("", "") so the matcher keeps Gate-1-passing jobs unconditionally
# (matcher.py line 83: len(description) < 100 → kept).


class RateLimitError(Exception):
    """Raised when the carrier portal blocks the request (not applicable for
    Playwright-based fetcher, but required by the matcher interface)."""


def _parse_dwr_jobs(text: str) -> list[dict]:
    """Parse DWR variable-assignment response into a list of job dicts."""
    vars_dict: dict = {}
    for m in re.finditer(
        r'(s\d+)\.(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(-?\d+\.?\d*)|null|true|false)\s*;',
        text
    ):
        var, field, str_val, num_val = m.group(1), m.group(2), m.group(3), m.group(4)
        vars_dict.setdefault(var, {})
        if str_val is not None:
            vars_dict[var][field] = (
                str_val.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n')
            )
        elif num_val is not None:
            vars_dict[var][field] = int(num_val) if '.' not in num_val else float(num_val)
        else:
            vars_dict[var][field] = None

    arrays_dict: dict = {}
    for m in re.finditer(r'(s\d+)\[(\d+)\]\s*=\s*(s\d+)\s*;', text):
        arrays_dict.setdefault(m.group(1), {})[int(m.group(2))] = m.group(3)

    # The root results object has both .postings and .applyWithLinkedInEnabled
    postings_array_var = ""
    for m in re.finditer(r'(s\d+)\.postings\s*=\s*(s\d+)\s*;', text):
        if "applyWithLinkedInEnabled" in vars_dict.get(m.group(1), {}):
            postings_array_var = m.group(2)
            break

    if not postings_array_var:
        return []

    jobs = []
    for idx in sorted(arrays_dict.get(postings_array_var, {}).keys()):
        job_var = arrays_dict[postings_array_var][idx]
        props = vars_dict.get(job_var, {})
        if "title" not in props:
            continue

        location = _extract_location(text, job_var, arrays_dict, vars_dict)

        # jobReqSecKey is session-scoped (changes every DWR session) — unusable
        # as a stable identifier. Build the detail URL from the numeric id instead.
        # The numeric career_job_req_id is stable across sessions and accepted by
        # the VERP detail page (user may need to log in, but the URL doesn't expire).
        job_id_num = str(props.get("id", ""))
        job_url = (
            BASE_URL
            + "/career?career%5fns=job%5flisting&company=interglobe"
              "&navBarLevel=JOB%5fSEARCH&rcm%5fsite%5flocale=en%5fGB"
              "&career_job_req_id=" + job_id_num
        ) if job_id_num else ""

        posting_date = props.get("postingDate", "")
        m_date = re.match(r'(\d{2})/(\d{2})/(\d{4})', posting_date)
        if m_date:
            posting_date = f"{m_date.group(3)}-{m_date.group(2)}-{m_date.group(1)}"

        jobs.append({
            "id": str(props.get("id", "")),
            "title": props.get("title", ""),
            "posting_date": posting_date,
            "location": location,
            "url": job_url,
            "company": "IndiGo",
            "source": "indigo",
        })

    return jobs


def _extract_location(text: str, job_var: str, arrays_dict: dict, vars_dict: dict) -> str:
    """Dig into the otherValues DWR tree to find location_obj → city name."""
    m_ov = re.search(rf'{re.escape(job_var)}\.otherValues\s*=\s*(s\d+)\s*;', text)
    if not m_ov:
        return ""
    ov_array_var = arrays_dict.get(m_ov.group(1), {}).get(0, "")
    for fi_var in arrays_dict.get(ov_array_var, {}).values():
        fprop = vars_dict.get(fi_var, {})
        if fprop.get("fieldId") == "location_obj" and fprop.get("shortVal"):
            try:
                loc_list = json.loads(fprop["shortVal"])
                return loc_list[-1] if isinstance(loc_list, list) else fprop["shortVal"]
            except (ValueError, TypeError):
                return fprop["shortVal"]
    return ""


def fetch_jobs() -> list[dict]:
    """
    Fetch the 10 most recently posted IndiGo jobs via Playwright + DWR.

    Launches a headless Firefox session, loads the VERP careers page, and
    calls window.careerJobSearchController.searchJobs() to trigger the DWR
    AJAX request. Intercepts the response and parses the DWR variable format.

    Returns up to 10 job dicts, newest first. Total available at IndiGo is ~30;
    only page 1 is accessible from the search widget without server-side login.
    """
    jobs: list[dict] = []

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            dwr_body: list[bytes] = []

            def _on_response(response):
                if "searchJobs.dwr" in response.url:
                    try:
                        dwr_body.append(response.body())
                    except Exception:
                        pass

            page.on("response", _on_response)

            print(f"[indigo] Loading careers page …")
            page.goto(BASE_URL + CAREERS_PATH, wait_until="load", timeout=45000)
            page.wait_for_timeout(6000)

            print("[indigo] Calling searchJobs() …")
            page.evaluate("() => { window.careerJobSearchController.searchJobs(null); }")
            page.wait_for_timeout(5000)

            if not dwr_body:
                print("[indigo] WARNING: no searchJobs DWR response captured")
                return []

            raw_text = dwr_body[0].decode("utf-8", errors="replace")
            jobs = _parse_dwr_jobs(raw_text)
            print(f"[indigo] Parsed {len(jobs)} jobs from DWR response")

        finally:
            browser.close()

    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    Job detail pages require server-side session state and SAP UI5 JS rendering
    that is inaccessible in headless mode. Returns ("", "") so the matcher
    keeps all Gate-1-passing IndiGo jobs unconditionally.
    """
    return ("", "")
