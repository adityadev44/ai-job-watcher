"""
MTU Aero Engines job fetcher.

Source  : https://www.mtu.de/careers/online-job-market/
ATS     : Custom HTML portal (no pagination — all jobs on one page)
Strategy: Parse div.jobs-list__item cards filtered to data-locale="en_US".
          Descriptions fetched from individual job pages (<main> tag).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
import requests
from bs4 import BeautifulSoup

SOURCE = "mtu"
CAREERS_URL = "https://www.mtu.de/careers/online-job-market/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)


class RateLimitError(Exception):
    """Raised when the MTU portal returns HTTP 429."""


def fetch_jobs(config: dict | None = None):
    """
    Return a list of job dicts with keys:
        title, url, location, source
    Only English-locale (data-locale="en_US") jobs are returned.
    """
    resp = _SESSION.get(CAREERS_URL, timeout=30)
    if resp.status_code == 429:
        raise RateLimitError("MTU rate-limited (429)")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.jobs-list__item")

    jobs = []
    seen_urls: set[str] = set()

    for card in cards:
        # data-locale is on the inner anchor, not on the div
        anchor = card.find("a", class_="jobs-list__item_anchor")
        if not anchor:
            continue

        locale = anchor.get("data-locale", "")
        if locale != "en_US":
            continue

        href = anchor.get("href", "").strip()
        if not href:
            continue

        # Normalise URL
        if href.startswith("/"):
            url = "https://www.mtu.de" + href
        elif href.startswith("http"):
            url = href
        else:
            url = "https://www.mtu.de/" + href.lstrip("/")

        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Title from h3 inside anchor
        h3 = anchor.find("h3", class_="jobs-list__title")
        title = h3.get_text(strip=True) if h3 else card.get("data-title", "").strip()

        # Location from data attribute
        location = card.get("data-location", "").strip().title()

        jobs.append({
            "title": title,
            "url": url,
            "location": location,
            "source": SOURCE,
        })

    return jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Fetch the plain-text description and posting date for a job URL.
    Returns ("", "") on any error — never raises.
    """
    try:
        time.sleep(0.5)
        resp = _SESSION.get(url, timeout=30)
        if resp.status_code == 429:
            return ("", "")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        main = soup.find("main")
        if main:
            text = main.get_text(separator=" ", strip=True)
        else:
            text = soup.get_text(separator=" ", strip=True)
        # MTU does not show posting dates
        return (text[:8000], "")
    except Exception:
        return ("", "")
