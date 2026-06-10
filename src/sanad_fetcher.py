import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://careers.sanad.ae"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class RateLimitError(Exception):
    pass


def _get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _parse_date(date_str):
    """Convert DD-Mon-YYYY (e.g. '15-Jun-2026') to YYYY-MM-DD. Returns '' on failure."""
    if not date_str:
        return ""
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _parse_listing_page(html):
    """
    Parse one listings HTML page.
    Returns list of job dicts: id, title, company, location, posting_date, url, source.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for card in soup.find_all("div", class_="row jobdetail mb-4 ms-0"):
        # Title + URL
        title_a = card.find("a", href=re.compile(r"^/vacancy/\d+$"))
        if not title_a:
            continue
        href = title_a["href"]
        m = re.search(r"/vacancy/(\d+)", href)
        if not m:
            continue

        vacancy_id = m.group(1)
        title = title_a.get_text(strip=True)
        url = BASE_URL + href

        # searchcaption divs hold Company / Location / Closing Date
        fields = {}
        for cap in card.find_all("div", class_="searchcaption"):
            label = cap.find("label")
            if label:
                key = label.get_text(strip=True).rstrip(":")
                val = cap.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
                fields[key] = val

        company = fields.get("Company", "Sanad")
        location = fields.get("Location", "Abu Dhabi, UAE")
        closing_date = _parse_date(fields.get("Closing Date", ""))

        jobs.append({
            "id": vacancy_id,
            "title": title,
            "company": company,
            "location": location,
            "posting_date": closing_date,  # only date signal on this portal
            "url": url,
            "source": "sanad",
        })

    return jobs


def fetch_jobs(max_listings=200, inter_page_delay=0.3):
    """
    Fetch all open vacancies from careers.sanad.ae.

    Paginates via /?pg=0, /?pg=1, ... No server-side keyword filtering —
    all jobs returned; filter locally through the 3-gate matcher.

    Returns list of job dicts.
    """
    session = _get_session()
    all_jobs = []
    seen_ids = set()
    page = 0

    while len(all_jobs) < max_listings:
        url = f"{BASE_URL}/?pg={page}"

        resp = None
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=20)
                if resp.status_code == 429:
                    raise RateLimitError(f"429 from {url}")
                break
            except RateLimitError:
                raise
            except Exception as exc:
                if attempt == 2:
                    print(f"[sanad] Page {page}: request failed: {exc}")
                    return all_jobs
                time.sleep(2 ** (attempt + 1))

        if resp is None or resp.status_code != 200:
            print(f"[sanad] Page {page}: HTTP {getattr(resp, 'status_code', '?')} — stopping")
            break

        page_jobs = _parse_listing_page(resp.text)
        if not page_jobs:
            break  # no vacancies on this page — done

        new_jobs = [j for j in page_jobs if j["id"] not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j["id"])

        if not new_jobs:
            break  # server returned a duplicate page (out-of-bounds pg wraps around)

        all_jobs.extend(new_jobs)
        print(f"[sanad] Page {page}: {len(page_jobs)} jobs, {len(new_jobs)} new — total: {len(all_jobs)}")

        page += 1
        if inter_page_delay:
            time.sleep(inter_page_delay)

    return all_jobs


def fetch_job_description(application_url):
    """
    Fetch the full job description from a /vacancy/{id} detail page.

    Returns (description_text, closing_date_iso) tuple.
    Returns ("", "") on any failure — never raises (except RateLimitError).
    """
    if not application_url or "/vacancy/" not in application_url:
        return ("", "")

    session = _get_session()

    try:
        resp = session.get(application_url, timeout=20)
        if resp.status_code == 429:
            raise RateLimitError(f"429 from {application_url}")
        if resp.status_code != 200:
            return ("", "")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Description sections: div.sectn (class list includes "sectn")
        # Covers "About the Role", "Your Responsibilities", "Who we are looking for"
        sections = soup.find_all("div", class_="sectn")
        description = "\n\n".join(
            sec.get_text(separator=" ", strip=True)
            for sec in sections
            if sec.get_text(strip=True)
        )

        # Closing date from ul.searchCategs > li > div.descr (label) + div.categVal (value)
        closing_date = ""
        categs = soup.find("ul", class_="searchCategs")
        if categs:
            for li in categs.find_all("li"):
                label_div = li.find("div", class_="descr")
                value_div = li.find("div", class_="categVal")
                if label_div and value_div:
                    label = label_div.get_text(strip=True).rstrip(":")
                    if label == "Closing Date":
                        closing_date = _parse_date(value_div.get_text(strip=True))
                        break

        return (description, closing_date)

    except RateLimitError:
        raise
    except Exception:
        return ("", "")
