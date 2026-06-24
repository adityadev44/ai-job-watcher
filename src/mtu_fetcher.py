import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import requests
from bs4 import BeautifulSoup

# MTU Maintenance uses a custom TYPO3 CMS job board at mtu.de/careers.
# All MTU entities (Aero Engines + all Maintenance subsidiaries) appear
# on a single professionals-filter page — no pagination.
# run_mtu.py pre-filters to "MTU Maintenance" company name before handing to matcher.
# German-language titles fail Gate 1 naturally (same limitation as LHT German branches).
# No posting date is available anywhere on this portal.

BASE = "https://www.mtu.de"
LIST_URL = BASE + "/careers/online-job-market/s/all/all/all/professionals/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class RateLimitError(Exception):
    pass


def _get(url: str) -> requests.Response:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            if resp.status_code == 429:
                if attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                raise RateLimitError("Rate-limited by MTU")
            resp.raise_for_status()
            return resp
        except RateLimitError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)
    raise RuntimeError("Exhausted retries")


def fetch_jobs(max_listings: int = 300, inter_page_delay: float = 0.3) -> list[dict]:
    """
    Fetch all professional-level MTU job listings from a single page (no pagination).

    Returns all entities — run_mtu.py pre-filters to MTU Maintenance companies.
    inter_page_delay unused (single page); kept for interface consistency.
    """
    try:
        resp = _get(LIST_URL)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[mtu] Fetch failed: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    jobs = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"/careers/online-job-market/job-posting/")):
        href = a.get("href", "")
        url = BASE + href if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        h3 = a.find("h3")
        if not h3:
            continue
        title = re.sub(r"\s*New\s*$", "", h3.get_text(strip=True), flags=re.IGNORECASE).strip()
        if not title:
            continue

        lis = a.find_all("li")
        company = lis[0].get_text(strip=True) if len(lis) > 0 else ""
        location = lis[1].get_text(strip=True) if len(lis) > 1 else ""

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "company": company,
            "source": "mtu",
            "posting_date": "",
        })

        if len(jobs) >= max_listings:
            break

    print(f"[mtu] Fetched {len(jobs)} total listings (all MTU entities)")
    return jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Fetch job description from MTU detail page.

    Description is in semantic HTML (h2, h4, p, ul/li) with no dedicated wrapper.
    Strips nav/header/footer, extracts text from job-title h2 onwards.
    No posting date on detail pages. Returns ("", "") on any failure.
    """
    if not url:
        return ("", "")

    try:
        resp = _get(url)
    except RateLimitError:
        raise
    except Exception as exc:
        print(f"[mtu] Description fetch failed ({url}): {exc}")
        return ("", "")

    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    h2 = soup.find("h2")
    if h2:
        parts = [h2.get_text(separator=" ", strip=True)]
        for sib in h2.find_next_siblings():
            t = sib.get_text(separator=" ", strip=True)
            if t:
                parts.append(t)
        text = " ".join(parts)
    else:
        main = soup.find("main") or soup.find("body")
        text = main.get_text(separator=" ", strip=True) if main else ""

    return (text, "")
