"""
Rolls-Royce Civil Aerospace job fetcher.

Source  : https://careers.rolls-royce.com/en/jobs
ATS     : ConnectID (rollsroyceats-prod-api.connectid.cloud)
Strategy: Playwright loads the careers page, which triggers:
            1. GET /auth/gettoken  → short-lived Bearer JWT
            2. POST /api/jobs?page=1&perPage=10  → first page of jobs
          We capture the Bearer token from step 1 via a request interceptor,
          then use page.request.fetch() (which carries session cookies) to
          POST subsequent pages.

API: POST https://rollsroyceats-prod-api.connectid.cloud/api/jobs?page=N&perPage=10
Headers: Authorization: Bearer <jwt>  (+ AWSALB / Cloudflare cookies via browser)
Body: {}
Response: {
  jobs: [{ id, jobTitle, jobDescription (HTML), jobLocation, postedOn }],
  meta: { totalCount, totalPages, pageNumber, perPage }
}
Note: jobDescription is returned inline — fetch_job_description() reads from cache.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import re
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SOURCE = "rolls_royce"
CAREERS_URL = "https://careers.rolls-royce.com/en/jobs"
API_HOST = "rollsroyceats-prod-api.connectid.cloud"
TOKEN_URL = f"https://{API_HOST}/auth/gettoken"
JOBS_URL = f"https://{API_HOST}/api/jobs"
JOB_DETAIL_BASE = "https://careers.rolls-royce.com/en/job"
PAGE_SIZE = 10  # default used by the React app

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Description cache — filled during fetch_jobs() from inline API JSON
_desc_cache: dict[str, str] = {}


class RateLimitError(Exception):
    """Raised when the portal returns HTTP 429."""


def _parse_location(raw_loc) -> str:
    if isinstance(raw_loc, str):
        return raw_loc.strip()
    if isinstance(raw_loc, dict):
        parts = list(filter(None, [
            raw_loc.get("city"),
            raw_loc.get("country"),
        ]))
        return ", ".join(parts)
    return ""


def _build_url(job: dict) -> str:
    url = job.get("url") or job.get("canonical_url") or job.get("externalUrl") or ""
    if url and url.startswith("http"):
        return url
    title = job.get("jobTitle") or job.get("title") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    job_id = job.get("id", "")
    return f"{JOB_DETAIL_BASE}/{slug}-{job_id}" if job_id else ""


def _parse_job(raw: dict) -> dict:
    # `id` is a per-POSTING identifier that ConnectID regenerates every time the
    # same requisition is reposted/refreshed (confirmed live: the same job title
    # cycled through 6+ different `id`/URL values over consecutive runs while
    # `jobRequisitionId` stayed constant). Dedup must key on the stable
    # requisition id, not the posting id or the URL built from it.
    posting_id = str(raw.get("id", ""))
    req_id = str(raw.get("jobRequisitionId") or "").strip() or posting_id
    title = (raw.get("jobTitle") or raw.get("title") or "").strip()

    html_desc = raw.get("jobDescription") or raw.get("description") or ""
    if html_desc and posting_id:
        soup = BeautifulSoup(html_desc, "html.parser")
        _desc_cache[posting_id] = soup.get_text(separator=" ", strip=True)[:8000]

    location = _parse_location(
        raw.get("jobLocation") or raw.get("location") or raw.get("city") or ""
    )
    posted = raw.get("postedOn") or raw.get("posted_at") or raw.get("createdAt") or ""

    return {
        "id": req_id,
        "title": title,
        "url": _build_url(raw),
        "location": location,
        "posting_date": str(posted),
        "company": "Rolls-Royce Civil Aerospace",
        "source": SOURCE,
    }


def fetch_jobs(config: dict | None = None) -> list[dict]:
    """
    Fetch Rolls-Royce job listings via Playwright + ConnectID API pagination.

    Playwright establishes browser session (AWSALB + Cloudflare cookies) and
    captures the Bearer JWT. page.request.fetch() is used for all POST calls
    so cookies flow automatically within the same browser context.

    Job descriptions are returned inline and cached in _desc_cache — no
    separate HTTP calls in fetch_job_description().
    """
    global _desc_cache
    _desc_cache = {}

    cfg = (config or {}).get("rolls_royce_search", {})
    max_listings = cfg.get("max_listings", 200)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=_BROWSER_UA,
                viewport={"width": 1280, "height": 900},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://careers.rolls-royce.com",
                },
            )
            page = context.new_page()

            bearer_token: list[str] = []

            def _on_request(request):
                if TOKEN_URL in request.url or (API_HOST in request.url and "/api/jobs" in request.url):
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer ") and not bearer_token:
                        bearer_token.append(auth)

            page.on("request", _on_request)

            print(f"[rolls_royce] Loading {CAREERS_URL} to capture JWT …")
            try:
                page.goto(CAREERS_URL, wait_until="networkidle", timeout=90000)
            except Exception:
                page.wait_for_timeout(8000)
            page.wait_for_timeout(4000)

            if not bearer_token:
                # Try fetching the token directly via page.request
                try:
                    tok_resp = page.request.get(TOKEN_URL, headers={"Accept": "application/json"})
                    if tok_resp.ok:
                        tok_data = tok_resp.json()
                        token_val = tok_data.get("token") or tok_data.get("accessToken") or ""
                        if token_val:
                            bearer_token.append(f"Bearer {token_val}")
                except Exception as exc:
                    print(f"[rolls_royce] Token fallback failed: {exc}")

            if not bearer_token:
                print("[rolls_royce] WARNING: Bearer token not captured — returning 0 jobs")
                return []

            print(f"[rolls_royce] Bearer JWT captured — paginating API")
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": bearer_token[0],
                "Referer": "https://careers.rolls-royce.com/",
            }

            def _post_page(p_num: int):
                url = f"{JOBS_URL}?page={p_num}&perPage={PAGE_SIZE}"
                resp = page.request.fetch(
                    url,
                    method="POST",
                    data="{}",
                    headers=headers,
                )
                if resp.status == 429:
                    raise RateLimitError(f"Rate-limited at page {p_num}")
                if not resp.ok:
                    raise RuntimeError(f"HTTP {resp.status} on page {p_num}")
                return resp.json()

            # First page
            try:
                data1 = _post_page(1)
            except Exception as exc:
                print(f"[rolls_royce] Page 1 fetch failed: {exc}")
                return []

            meta = data1.get("meta", {})
            total_count = meta.get("totalCount") or meta.get("total_count") or 0
            total_pages = meta.get("totalPages") or meta.get("total_pages") or 1
            print(f"[rolls_royce] totalCount={total_count}, totalPages={total_pages}")

            for job in (_parse_job(r) for r in data1.get("jobs", []) if r.get("jobTitle") or r.get("title")):
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            print(f"[rolls_royce]   page 1/{total_pages}: {len(data1.get('jobs', []))} jobs")

            for p_num in range(2, total_pages + 1):
                if len(all_jobs) >= max_listings:
                    break
                try:
                    data = _post_page(p_num)
                except RateLimitError:
                    raise
                except Exception as exc:
                    print(f"[rolls_royce] Page {p_num} error: {exc} — stopping")
                    break
                raw_jobs = data.get("jobs", [])
                for job in (_parse_job(r) for r in raw_jobs if r.get("jobTitle") or r.get("title")):
                    if job["id"] not in seen_ids:
                        seen_ids.add(job["id"])
                        all_jobs.append(job)
                print(f"[rolls_royce]   page {p_num}/{total_pages}: {len(raw_jobs)} jobs")

        except Exception as exc:
            print(f"[rolls_royce] Fatal error: {exc}")
        finally:
            browser.close()

    print(f"[rolls_royce] Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Returns cached description from fetch_jobs() call — no extra HTTP needed.
    Falls back to ("", "") if not found. Never raises.
    """
    m = re.search(r"-(\d+)(?:[/?#]|$)", url)
    if m and m.group(1) in _desc_cache:
        return (_desc_cache[m.group(1)], "")
    for job_id, desc in _desc_cache.items():
        if job_id in url:
            return (desc, "")
    return ("", "")
