import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

# Qatar Airways uses Avature (portal ID 23). Jobs are server-side rendered HTML.
# Pagination: GET /global/SearchJobs?jobRecordsPerPage=6&jobOffset=N
# jobRecordsPerPage is locked at 6 regardless of parameter value.
# Total jobs: ~150 across all Qatar Airways Group (airline + engineering + executive).
# Description: GET /global/JobDetail/{slug}/{id} — description in first <section> tag.

BASE = "https://careers.qatarairways.com"
SEARCH_URL = BASE + "/global/SearchJobs"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/global",
}


class RateLimitError(Exception):
    pass


def _get(url: str, params: dict = None) -> requests.Response:
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
            if resp.status_code == 429:
                if attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                raise RateLimitError("Rate-limited by Qatar Airways")
            resp.raise_for_status()
            return resp
        except RateLimitError:
            raise
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2)
    raise RuntimeError("Exhausted retries")


def _parse_articles(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    articles = soup.select("article.article--result")
    jobs = []
    for art in articles:
        link = art.find("a", href=re.compile(r"/global/JobDetail/"))
        if not link:
            continue
        title = link.get_text(strip=True)
        url = link.get("href", "")
        if not url.startswith("http"):
            url = BASE + url

        id_match = re.search(r"/(\d+)$", url)
        job_id = id_match.group(1) if id_match else ""

        art_text = art.get_text(" ", strip=True)
        loc_match = re.search(r"Work locations?:\s*([^|P]+?)(?:\s+Posting date|$)", art_text)
        location = loc_match.group(1).strip() if loc_match else ""

        date_match = re.search(r"Posting date\s*:?\s*(\d{2}-\d{2}-\d{4})", art_text)
        if date_match:
            # Convert DD-MM-YYYY to YYYY-MM-DD
            parts = date_match.group(1).split("-")
            posting_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            posting_date = ""

        jobs.append({
            "id": job_id,
            "title": title,
            "location": location,
            "posting_date": posting_date,
            "url": url,
            "company": "Qatar Airways Engineering",
            "source": "qatar",
        })
    return jobs


def fetch_jobs(max_listings: int = 200, inter_page_delay: float = 0.5) -> list[dict]:
    """
    Fetch all active Qatar Airways job listings via Avature HTML scraping.

    Paginates with jobOffset= (page size locked at 6 by server). Total ~150 jobs
    across Qatar Airways Group — all divisions; Gate 1 filters to MRO/engineering roles.
    Returns up to max_listings jobs.
    """
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0

    while len(all_jobs) < max_listings:
        try:
            resp = _get(SEARCH_URL, params={"jobRecordsPerPage": 6, "jobOffset": offset})
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[qatar] Fetch failed at offset={offset}: {exc}")
            break

        page_jobs = _parse_articles(resp.text)
        if not page_jobs:
            break

        new = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new:
            seen_ids.add(j["id"])

        all_jobs.extend(new)
        print(f"[qatar] offset={offset}: {len(page_jobs)} jobs, {len(new)} new — total: {len(all_jobs)}")

        if len(page_jobs) < 6:
            break

        offset += len(page_jobs)
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Fetch full description for a Qatar Airways job.

    Returns (description_text, posting_date). posting_date is already set at
    listing time so this returns "". Returns ("", "") on failure.
    """
    if not url:
        return ("", "")

    try:
        resp = _get(url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[qatar] Description fetch failed ({url}): {exc}")
        return ("", "")

    soup = BeautifulSoup(resp.text, "lxml")
    section = soup.find("section")
    if not section:
        return ("", "")

    text = section.get_text(separator=" ", strip=True)
    return (text, "")
