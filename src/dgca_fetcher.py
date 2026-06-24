import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import datetime
from urllib.parse import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

VACANCY_URL = "https://www.dgca.gov.in/digigov-portal/?page=4368/4646/servicename"
BASE_PORTAL = "https://www.dgca.gov.in/digigov-portal/"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    pass


def _parse_date(date_str: str) -> str:
    """Convert 'DD/MM/YYYY' to 'YYYY-MM-DD'. Returns '' on failure."""
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _parse_table(html: str, max_listings: int) -> list[dict]:
    """Extract vacancy rows from the rendered DGCA datatable."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="datatable")
    if not table:
        print("[dgca] WARNING: datatable not found in rendered HTML")
        return []

    rows = table.find_all("tr")[1:]  # skip header row
    jobs = []

    for row in rows[:max_listings]:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        date_str = cells[1].get_text(strip=True)
        subject = cells[2].get_text(strip=True)

        link_a = cells[3].find("a", attrs={"data-url": True})
        if not link_a:
            continue

        data_url = link_a.get("data-url", "").strip()
        if not data_url:
            continue

        # URL-encode only the filename portion (preserve path separators)
        parts = data_url.split("/")
        encoded = "/".join(quote(p, safe="") for p in parts)
        url = BASE_PORTAL + encoded

        jobs.append({
            "title": subject,
            "url": url,
            "location": "New Delhi, India",
            "company": "DGCA",
            "source": "dgca",
            "posting_date": _parse_date(date_str),
        })

    return jobs


def fetch_jobs(max_listings: int = 50) -> list[dict]:
    """
    Fetch the most recent DGCA vacancy circulars via Playwright.

    The DGCA portal (NIC DigiGov) loads vacancy content via AJAX — plain
    requests return an empty shell. Playwright renders the full page, then
    the datatable (Reference Number | Date | Subject | Document) is parsed.

    Returns up to max_listings vacancy dicts, newest first.
    Gate 2 is bypassed downstream: fetch_job_description returns ("","").
    """
    html = ""
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            print("[dgca] Loading vacancy page …")
            try:
                page.goto(VACANCY_URL, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                # networkidle may time out on slow gov sites — grab what's there
                print("[dgca] networkidle timeout — reading partial content")
            page.wait_for_timeout(5000)
            html = page.content()
        finally:
            browser.close()

    if not html:
        print("[dgca] No HTML captured")
        return []

    jobs = _parse_table(html, max_listings)
    print(f"[dgca] Parsed {len(jobs)} vacancy circulars (max_listings={max_listings})")
    return jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    DGCA vacancy documents are PDFs — not parseable as text without extra libs.
    Returns ('','') so the matcher keeps all Gate-1+3-passing rows unconditionally.
    """
    return ("", "")
