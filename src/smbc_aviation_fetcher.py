"""
SMBC Aviation Capital job fetcher.

Source  : https://smbcaviationcapital.bamboohr.com/careers/list
ATS     : BambooHR (tenant confirmed at smbcaviationcapital.bamboohr.com)
Status  : BambooHR public job listing API (/careers/list) redirects to
          bamboohr.com main page — not publicly accessible as of 2026-06.
          The /jobs page returns HTTP 403. Fetcher returns [] until SMBC
          enables public job listing or an alternative endpoint is found.
Note    : www.smbcac.com/careers is a JavaScript redirect to a GoDaddy
          parking page and contains no job data.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import requests

SOURCE = "smbc_aviation"
CAREERS_API = "https://smbcaviationcapital.bamboohr.com/careers/list"
CAREERS_BASE = "https://smbcaviationcapital.bamboohr.com/careers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://smbcaviationcapital.bamboohr.com",
    "Referer": "https://smbcaviationcapital.bamboohr.com/careers",
}


class RateLimitError(Exception):
    """Raised when the portal returns HTTP 429 after all retries are exhausted."""


def _get(url: str, max_retries: int = 3, base_delay: float = 2.0):
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=False)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[smbc_aviation] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def fetch_jobs(config: dict | None = None) -> list[dict]:
    """
    Fetch SMBC Aviation Capital job listings via BambooHR JSON API.

    As of 2026-06, the public BambooHR careers/list API is not accessible
    (redirects to bamboohr.com main page). Returns [] until resolved.
    """
    print("[smbc_aviation] Fetching BambooHR careers list …")
    try:
        resp = _get(CAREERS_API)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[smbc_aviation] Fetch error: {exc}")
        return []

    if resp.status_code in (301, 302, 303, 307, 308):
        redir = resp.headers.get("Location", "")
        print(
            f"[smbc_aviation] BambooHR API returned HTTP {resp.status_code} "
            f"→ {redir!r}. Public listing not available — returning 0 jobs."
        )
        return []

    if resp.status_code == 403:
        print("[smbc_aviation] HTTP 403 — BambooHR listing not publicly accessible.")
        return []

    if not resp.ok:
        print(f"[smbc_aviation] HTTP {resp.status_code} — returning 0 jobs.")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"[smbc_aviation] JSON parse error: {exc}")
        return []

    total = data.get("meta", {}).get("totalCount", 0)
    results = data.get("result", [])
    print(f"[smbc_aviation] API reports {total} total jobs, got {len(results)} in response")

    jobs = []
    seen_ids: set[str] = set()

    for item in results:
        job_id = item.get("id")
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(str(job_id))

        title = item.get("jobOpeningName", "").strip()
        if not title:
            continue

        loc = item.get("location", {}) or {}
        city = loc.get("city", "") or ""
        state = loc.get("state", "") or ""
        location = f"{city}, {state}".strip(", ") if state else city

        jobs.append({
            "title": title,
            "url": f"{CAREERS_BASE}/{job_id}",
            "location": location,
            "company": "SMBC Aviation Capital",
            "source": SOURCE,
            "posting_date": "",
        })

    print(f"[smbc_aviation] Total unique jobs: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    BambooHR job detail pages are React SPAs — descriptions are not in static HTML.
    Returns ('', '') unconditionally, which causes Gate 2 bypass (jobs kept by default).
    """
    return ("", "")
