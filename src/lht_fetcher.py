import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import time
import requests
from bs4 import BeautifulSoup

# Lufthansa Technik uses a custom Lufthansa Group ATS at apply.lufthansagroup.careers.
# REST API (plain JSON over GET) returns all Lufthansa Group jobs in one call.
# Filter locally by ParentOrganizationName containing "Lufthansa Technik".
# Description pages accessible via plain requests (no Playwright needed).

_API = "https://api-apply.lufthansagroup.careers/search/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_API_PAYLOAD = {
    "LanguageCode": "EN",
    "SearchParameters": {
        "FirstItem": 1,
        "CountItem": 500,
        "Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}],
        "MatchedObjectDescriptor": [
            "ID",
            "PositionTitle",
            "PositionURI",
            "PositionLocation.CountryName",
            "PositionLocation.CityName",
            "ParentOrganizationName",
            "PublicationStartDate",
        ],
    },
    "SearchCriteria": [],
}


class RateLimitError(Exception):
    pass


def fetch_jobs(max_listings: int = 500, inter_page_delay: float = 0.3) -> list[dict]:
    """
    Fetch all active Lufthansa Technik job listings.

    Calls the Lufthansa Group REST API once, fetches up to 500 jobs, then filters
    locally for entries whose ParentOrganizationName contains 'Lufthansa Technik'.
    Typically ~100 LHT jobs out of ~305 total Lufthansa Group jobs.
    """
    try:
        resp = requests.get(
            _API,
            params={"data": json.dumps(_API_PAYLOAD, separators=(",", ":"))},
            headers=_HEADERS,
            timeout=25,
        )
        if resp.status_code == 429:
            raise RateLimitError("Rate-limited by LHT API")
        resp.raise_for_status()
        data = resp.json()
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[lht] API fetch failed: {exc}")
        return []

    result = data.get("SearchResult", {})
    total_group = result.get("SearchResultCountAll", 0)
    items = result.get("SearchResultItems", [])
    print(f"[lht] Lufthansa Group total: {total_group}, fetched: {len(items)}")

    jobs = []
    for item in items:
        d = item.get("MatchedObjectDescriptor", {})
        org = d.get("ParentOrganizationName") or ""
        if "Lufthansa Technik" not in org:
            continue

        loc_list = d.get("PositionLocation") or []
        if loc_list:
            city = loc_list[0].get("CityName") or ""
            country = loc_list[0].get("CountryName") or ""
            location = f"{city}, {country}".strip(", ")
        else:
            location = ""

        job_id = str(d.get("ID", ""))
        jobs.append({
            "id": job_id,
            "title": d.get("PositionTitle") or "",
            "location": location,
            "posting_date": (d.get("PublicationStartDate") or "")[:10],
            "url": d.get("PositionURI") or f"https://apply.lufthansagroup.careers/index.php?ac=jobad&id={job_id}",
            "company": org,
            "source": "lht",
        })

    print(f"[lht] Lufthansa Technik jobs: {len(jobs)}")
    return jobs[:max_listings]


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Fetch the full description text for an LHT job.

    Returns (description_text, posting_date). posting_date is always "" since
    it's already set at listing time. Returns ("", "") on failure.
    """
    if not url:
        return ("", "")

    try:
        resp = requests.get(
            url,
            headers={**_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            timeout=20,
        )
        if resp.status_code == 429:
            raise RateLimitError(f"Rate-limited fetching description: {url}")
        resp.raise_for_status()
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[lht] Description fetch failed ({url}): {exc}")
        return ("", "")

    soup = BeautifulSoup(resp.text, "lxml")
    container = soup.find(id="content") or soup.find("main")
    if not container:
        return ("", "")

    text = container.get_text(separator=" ", strip=True)
    return (text, "")
