import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import requests

CAREERS_API = "https://magnetic.bamboohr.com/careers/list"
CAREERS_BASE = "https://magnetic.bamboohr.com/careers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class RateLimitError(Exception):
    """Raised when the server returns HTTP 429 after all retries are exhausted."""


def _get(url, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                print(f"[magnetic] 429 — waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise RateLimitError(f"Rate-limited after {max_retries} retries on {url}")
        resp.raise_for_status()
        return resp
    raise RateLimitError(f"Rate-limited: exhausted retries for {url}")


def fetch_jobs() -> list[dict]:
    """
    Fetch all Magnetic MRO job listings via BambooHR JSON API.
    BambooHR detail pages are React SPAs — descriptions not available via
    static HTTP. fetch_job_description returns ('', ''), bypassing Gate 2.
    """
    print("[magnetic] Fetching BambooHR careers list...")
    try:
        resp = _get(CAREERS_API)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[magnetic] Fetch error: {exc}")
        return []

    data = resp.json()
    total = data.get("meta", {}).get("totalCount", 0)
    results = data.get("result", [])
    print(f"[magnetic] API reports {total} total jobs, got {len(results)} in response")

    jobs = []
    seen_ids: set = set()

    for item in results:
        job_id = item.get("id")
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = item.get("jobOpeningName", "").strip()
        if not title:
            continue

        dept = item.get("departmentLabel", "")
        loc = item.get("location", {}) or {}
        city = loc.get("city", "") or ""
        state = loc.get("state", "") or ""
        location = f"{city}, {state}".strip(", ") if state else city

        # Magnetic Engines = engine MRO subsidiary (V2500, CFM56-5B)
        if "engine" in dept.lower():
            company = "Magnetic Engines"
        else:
            company = "Magnetic MRO"

        jobs.append({
            "title": title,
            "url": f"{CAREERS_BASE}/{job_id}",
            "location": location,
            "company": company,
            "source": "magnetic",
            "posting_date": "",
        })

    print(f"[magnetic] Total unique jobs: {len(jobs)}")
    return jobs


def fetch_job_description(application_url: str) -> tuple[str, str]:
    """
    BambooHR job detail pages are React SPAs — descriptions are not in static HTML.
    Returns ('', '') unconditionally, which causes Gate 2 bypass.
    """
    return ("", "")
