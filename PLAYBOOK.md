# Aviation MRO Job Watcher — Playbook

Reference for maintaining this project and adding new company pipelines.

---

## What This System Does

Monitors job postings from global aerospace and MRO companies every 3 hours via GitHub Actions.
Filters for **senior engine operations, MRO leadership, quality, compliance, and powerplant roles**
at the right seniority level. Sends Telegram + email alerts only for jobs not seen before.
Each company has its own fetcher, run script, seen-jobs file, and config section — all isolated.

---

## Core Design Principles (read before touching anything)

**1. Precision over recall — but never drop on empty fetch.**
This is not a high-volume search. A false positive (wrong role alerted) is annoying.
A false negative (real senior role missed) is a career cost. The 3-gate filter is strict,
but if a description fails to fetch or returns under 100 characters, the job is KEPT.
Absence of proof is not proof of absence for a rare senior role.

**2. Failure isolation is non-negotiable.**
With 18+ sources, something is always broken. One company's crash must never affect others.
Every `run_<company>.py` wraps its `__main__` in try/except. Every fetcher raises `RateLimitError`
on 429 so matcher.py can log a warning and continue — never propagate a crash upward.

**3. Silence needs to be distinguishable from broken.**
Senior MRO roles appear once a month, sometimes less. A watcher that's quiet for 3 weeks
looks identical to a watcher that's been broken for 3 weeks. Two mechanisms prevent this:
- Gate-by-gate summary printed on every run (fetched → G1 → G3 → G2 → new → sent)
- Weekly near-miss digest email (proves the system ran and what almost matched)

**4. UTF-8 everywhere, always.**
Job titles at Safran, Emirates, Lufthansa, and Sanad contain Arabic, French, German characters.
Every file that prints output must have at the top:
```python
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```
Missing this causes Windows to crash the entire run on a single non-ASCII character.

**5. Location is metadata, not a gate.**
Unlike Shivangi's India-only search, this watcher is global. There are no location exclusions.
Location appears in the alert so the candidate can decide — the filter never rejects on geography.

**6. Parallel pipelines, polite cadence.**
All company pipelines run in parallel (`& pid=$!` pattern). The 3-hour schedule is deliberate —
rare postings don't need aggressive polling, and 18 sources need API politeness.
Never reduce below 2 hours.

---

## The 3-Gate AND Filter

**All three gates must pass. Gates run in this order to minimise API calls.**

```
fetch_jobs()
    └─ Gate 1: Title family check          → [gate1] tag if fails
    └─ Gate 3: Exclude terms check         → [gate3] tag if fails
        └─ fetch_job_description()         ← only fetched if G1 + G3 pass
            └─ Gate 2: Engine domain check → [gate2] tag if fails
                └─ MATCH
```

**Gate 1 — Title family (leadership/specialist shape)**
Title must contain at least one term from `matching.title_family`.
Catches the right seniority shape: manager, head, director, lead, chief, consultant,
advisor, quality, compliance, safety, powerplant, engine, mro, shop, production,
technical services, instructor, overhaul.

**Gate 3 — Exclude terms (title-based only)**
Title must NOT contain any term from `matching.exclude_terms`.
Excludes: technician, apprentice, trainee, intern, fresher, graduate, new grad,
software, "it " (with trailing space — avoids matching "quality"), avionics, cabin,
pilot, finance, sales, structures, airframe.
**IMPORTANT: description-based exclusion is a trap.** Engine shop JDs casually mention
"avionics interface" or "software systems" — description exclusions silently kill real roles.
Use title-only for Gate 3. Let Gate 2's positive requirement handle wrong-domain filtering.

**Gate 2 — Engine domain (description-based, ≥2 hits including ≥1 engine-specific)**
Description must contain:
- At least 1 hit from `engine_specific_terms` (GE90, GEnx, LEAP, Part 145, test cell, etc.)
- At least 2 total hits from `engine_specific_terms` + `domain_terms` combined
If description fetch fails or returns < 100 chars → KEEP THE JOB UNCONDITIONALLY.

**Near-miss logging format (must match exactly):**
```
[gate1] Senior Avionics Technician (no title family match)
[gate3] MRO Software Engineer (exclude hit: "software")
[gate2] Production Manager (engine_hits=0, domain_hits=3, needed ≥1 engine + ≥2 total)
```

---

## Architecture

```
config.yaml                       ← all config: shared matching rules + per-company search params
src/
  matcher.py                      ← shared 3-gate filter engine + weekly digest builder
  notifier.py                     ← Telegram (chunked) + Gmail (multi-recipient) alerts
  <company>_fetcher.py            ← data source: fetch_jobs() + fetch_job_description()
  run_<company>.py                ← pipeline entry point (fetch → match → dedupe → alert → persist)
seen_jobs_<company>.json          ← deduplication memory (tracked by git, never gitignored)
near_misses_<company>.json        ← near-miss accumulator for weekly digest (tracked by git)
.github/workflows/watcher.yml     ← parallel pipeline runner, every 3 hours
```

**matcher.py interface contract — every fetcher must export exactly:**
```python
class RateLimitError(Exception): ...

def fetch_jobs() -> list[dict]:
    # Returns list of dicts, each with at minimum:
    # {"title": str, "url": str, "location": str, "company": str, "source": str}
    # Optional: "id", "posting_date", "date" — used for alert sorting

def fetch_job_description(application_url) -> str | tuple[str, str]:
    # Canonical (new fetchers):  return (description_text, posting_date_string)
    # Legacy (Safran only):       return description_text as plain str
    # matcher.py handles both via isinstance(raw, tuple) — always returns "" or ("","") on failure
    # On ANY failure: return "" or ("", "") — never raise, never crash
```

**Dual return type:** matcher.py uses `isinstance(raw, tuple)` so both forms work. New fetchers
should always return the tuple. Safran is the only legacy `str` returner and will be updated
when next touched. Until then, do not rely on the str form in new code.

---

## Current Companies

| Company | ATS | Fetch method | Entry point | Notes |
|---|---|---|---|---|
| Safran | Custom ASP.NET | HTML scraping (requests + BeautifulSoup) | `run_safran.py` | GET `/job/list-of-all-jobs.aspx?LCID=1033&Keywords={kw}&mode=list&page={n}` — fully stateless, no session. Description at `<div id="contenu-ficheoffre">`. Company name in `<meta name="Description">`. Newest-first by default. |
| GE Aerospace | Phenom People | JSON API (requests + BeautifulSoup) | `run_ge.py` | `refNum=GAOGAYGLOBAL`. Session bootstrap: GET `/global/en/search-results` for CSRF token + session cookie, then POST `/widgets` with `ddoKey:"refineSearch"`. Keywords ignored server-side — all ~570 jobs returned regardless; filter locally. Description via POST `/widgets` with `ddoKey:"jobDetail"` + `jobId`. Browseable URL: `/global/en/job/{reqId}`. `fetch_job_description` returns `(str, str)` tuple. |

---

## How to Add a New Company

> **Every company is different.** These steps capture what worked across past integrations.
> Read what the new system actually does before reaching for copy-paste. The goal is accurate
> alerts — the playbook saves time, it doesn't constrain good judgment.

### Step 1 — Identify the ATS (10–20 min)

Open the careers page, search for a role, open DevTools → Network tab → XHR/Fetch calls. Ask:
- Does `requests.get/post` return job data? → REST API (fast path)
- Are API responses empty or 403? → Playwright/Firefox needed
- Is Chromium blocked? → Always use Firefox (Akamai blocks headless Chromium)

**Common ATS signals:**

| ATS | URL signal | Best approach |
|---|---|---|
| **Workday** | `wd1.myworkdayjobs.com` or apply button goes there | `POST /wday/cxs/{code}/{tenant}/jobs` with JSON body. Find India/global WID from facets response. |
| **Phenom People** | `cdn.phenompeople.com` in page source; `phApp.refNum` in inline JS | Session bootstrap required — see Phenom People Notes below |
| **Oracle HCM CE** | `fa.ocs.oraclecloud.com` | Playwright/Firefox — JS SPA, API blocked server-side |
| **iCIMS** | `icims.com` in URL | REST API or HTML scraping |
| **Greenhouse** | `greenhouse.io` | Public REST API, well-documented |
| **Lever** | `lever.co` | Public REST API |
| **Taleo** | `taleo.net` | HTML scraping usually required |
| **SAP SuccessFactors** | `successfactors.com` | REST API, may need session token |
| **Custom** | `.aspx` URLs, ViewState tokens in HTML | HTML scraping with BeautifulSoup/lxml |

### Step 2 — Map the response structure

Find: job ID, title, location, posting date, application URL.
Watch for:
- Relative dates ("Posted 3 Days Ago") — convert to YYYY-MM-DD
- Abbreviated titles ("Mgr" not "Manager", "Engr" not "Engineer") — add to `title_family` in config
- JS-rendered descriptions — plain requests returns empty; use Playwright or a JSON detail API
- Company name — often only on detail page, not list page (cache during description fetch, zero extra requests)

### Step 3 — Create `src/<company>_fetcher.py`

Copy the closest existing fetcher:
- HTML scraping → copy `safran_fetcher.py`
- Workday REST → use Workday pattern (see Workday notes below)
- Playwright needed → use Firefox, never Chromium

Must always include:
- UTF-8 stdout reconfiguration at top
- Retry loop (3 attempts, exponential backoff: 2s → 4s → 8s)
- `RateLimitError` on 429 — matcher.py catches this, logs warning, continues
- Browser-like `User-Agent` header (Chrome/124 on Windows)
- `fetch_job_description` returns `("", "")` on ANY failure — never raises

### Step 4 — Create `src/run_<company>.py`

Copy `run_safran.py` exactly. Change 5 things:
```python
from src import safran_fetcher     →  from src import <company>_fetcher
"safran_search"                    →  "<company>_search"
"seen_jobs_safran.json"            →  "seen_jobs_<company>.json"
"near_misses_safran.json"          →  "near_misses_<company>.json"
source="Safran"                    →  source="<Company Display Name>"
```

Always wrap `__main__` in try/except — a crash here must not affect parallel pipelines.

### Step 5 — Add to `config.yaml`

Add before `notifications:`:
```yaml
<company>_search:
  max_listings: 200
  inter_page_delay: 0.3       # 0.1 for fast REST APIs, 0.5 for slow HTML scrapers
  keywords:
    - "engine overhaul"
    - "MRO manager"
    - "shop manager"
    - "powerplant"
    - "engine shop"
    - "quality manager"
    - "production manager"
    - "technical services"
    - "engine maintenance"
    - "Part 145"
  locations:
    - "all"                   # No location filtering — global search
```

Check: does this ATS use server-side keyword filtering (Workday does) or ignore keywords
(Safran doesn't — all keywords return the same result set, deduplication handles it)?
If it ignores keywords, reduce to 2–3 representative keywords to avoid redundant fetches.

### Step 6 — Update `.github/workflows/watcher.yml`

**In the parallel run step** — add next pid:
```yaml
python -u -m src.run_<company> & pid<N>=$!
...
wait $pid<N> || fail=1
```

**In the save step** — add both state files:
```bash
test -f seen_jobs_<company>.json && git add seen_jobs_<company>.json || true
test -f near_misses_<company>.json && git add near_misses_<company>.json || true
```

### Step 7 — Create state files

```
seen_jobs_<company>.json   → []
near_misses_<company>.json → []
```

Both must be committed to git (NOT in .gitignore) — they are the cloud memory.

### Step 8 — Tests

Write `tests/test_<company>_fetcher.py`:
- Use saved sample HTML/JSON fixtures — never call live API in tests
- Test: `fetch_jobs` returns correct fields from sample
- Test: `fetch_job_description` returns non-empty string from sample
- Test: `RateLimitError` raised on mocked 429 response
- Test: `fetch_job_description` returns `("", "")` on network failure (not raise)

Run pytest — all tests must pass before pushing.

### Step 9 — Local test

```bash
python -u -m src.run_<company>
```

Verify:
- Non-zero jobs fetched
- Gate-by-gate summary looks sane (not all passing, not all failing)
- No obviously wrong roles in matched list (wrong division, wrong seniority)
- Alert fires (or "no new matches" if already seen)

### Step 10 — Update this playbook

Add the company to the **Current Companies** table with:
- ATS discovered
- Fetch method
- Entry point
- Key quirks (rate limits, field name oddities, pagination behavior, bot protection)

---

## Workday Notes (most common corporate ATS)

```python
# Discovery: POST to get facets (finds location WIDs)
POST https://<tenant>.wd1.myworkdayjobs.com/wday/cxs/<code>/<tenant>/jobs
Body: {"limit": 1, "offset": 0, "searchText": "engine"}

# Real search with global location (no WID filter = all locations)
POST same URL
Body: {
    "limit": 20,
    "offset": 0,
    "searchText": "engine overhaul",
    "appliedFacets": {}   # empty = global, or add {"Location_Country": [WID]} for country
}

# Job detail (Workday pages are JS SPAs — use JSON detail API)
GET https://<tenant>.wd1.myworkdayjobs.com/wday/cxs/<code>/<tenant>/jobs/<externalPath>
# externalPath comes from the search result's "externalPath" field
```

Key Workday quirks:
- `limit=0` returns HTTP 400 — always use limit ≥ 1
- `postedOn` field uses relative strings ("Posted Yesterday", "Posted 3 Days Ago") — parse explicitly
- Description is HTML in a `jobDescription` field — strip tags for Gate 2 matching
- Rate limits are generous but don't hammer — keep `inter_page_delay: 0.2`

---

## Phenom People Notes (GE Aerospace confirmed; Emirates, Etihad, others likely)

### Detection
Look for `cdn.phenompeople.com` in page source. Then find `refNum` in the inline `phApp` config:
```html
<script>var phApp = phApp || {"refNum":"GAOGAYGLOBAL", "widgetApiEndpoint":".../widgets", ...}</script>
```
The `refNum` is the tenant identifier. It is NOT in the URL — the careers site runs on a custom
domain (e.g. `careers.geaerospace.com`). The `pageId` (e.g. `"page20"`) and `pageName`
(e.g. `"search-results"`) are also in `phApp` — you need these for widget API calls.

**Critical trap:** The "Apply" button on Phenom pages often links to Workday
(`geaerospace.wd5.myworkdayjobs.com`). Workday is used for candidate tracking; Phenom is the
search UI. Do not probe Workday. The Phenom `careers.*` domain is the correct target.

### Step 1 — Session bootstrap (mandatory)
Phenom's `/widgets` API returns `{"tokenAvailable": false}` and 0 jobs without a valid session.
```python
session = requests.Session()
r = session.get("https://careers.company.com/global/en/search-results", timeout=20)
csrf = re.search(r"id='csrfToken'[^>]*>([^<]+)<", r.text).group(1).strip()
session.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json",
    "csrf-token": csrf,
    "Referer": "https://careers.company.com/global/en/search-results",
})
# Session now has PLAY_SESSION cookie + csrf-token header — reuse for all POST calls
```

### Step 2 — Job search (`ddoKey: "refineSearch"`)
```python
POST /widgets
{
    "ddoKey": "refineSearch",
    "refNum": "GAOGAYGLOBAL",      # from phApp.refNum
    "pageId": "page20",            # from phApp.pageId on the search-results page
    "pageName": "search-results",  # from phApp.pageName
    "siteType": "external",
    "deviceType": "desktop",
    "lang": "en_global",
    "from": 0,                     # pagination offset
    "size": 20,                    # page size (20 is safe)
    "jobs": true,
    "counts": false,
    "all_fields": [],
    "clearAll": false,
    "jdsource": "facets",
    "isSliderEnable": false,
    "sortBy": "",
    "subsearch": "",
    "searchText": ""               # ignored server-side — returns all jobs regardless
}
# Response: {"refineSearch": {"totalHits": 570, "hits": 20, "data": {"jobs": [...]}}}
# Paginate: increment "from" by len(jobs) until from >= totalHits or max_listings
```
**`searchText` is ignored.** All ~570 jobs are returned regardless of keyword. Fetch everything
and filter locally through the 3-gate matcher. This is different from Workday, which does
filter server-side.

Key list-view job fields: `reqId`, `jobId`, `title`, `location`, `postedDate`, `company`,
`companyName`, `applyUrl` (Workday link — do not use as browseable URL).

### Step 3 — Job detail (`ddoKey: "jobDetail"`)
```python
POST /widgets
{
    "ddoKey": "jobDetail",
    "refNum": "GAOGAYGLOBAL",
    "jobId": "R5009951",           # reqId from list-view job
    "lang": "en_global",
    "deviceType": "desktop",
    "pageName": "search-results",
    "siteType": "external",
}
# Response: {"jobDetail": {"data": {"job": {"description": "<h1>...", "postedDate": "..."}}}}
# "description" is HTML — strip with BeautifulSoup before Gate 2 matching
```

### Browseable job URL
```
https://careers.company.com/global/en/job/{reqId}
```
Use this in alerts. The `applyUrl` from the API is the Workday apply link — not useful for
"here's a role to look at."

### fetch_job_description return
Must return `(description_text, posting_date_string)` — the tuple form. See interface contract
above. `posting_date` from jobDetail is ISO 8601: `"2026-05-01T00:00:00.000+0000"`.

### Key Phenom quirks
- `pageId` and `pageName` vary per tenant and per page — always read from `phApp` in the HTML
- Session expires after ~30 min of inactivity; pipeline runs end-to-end in < 3 min so this is safe
- CSRF token is tied to the session cookie — do not mix tokens from different sessions
- Rate limits are generous; `inter_page_delay: 0.2` is sufficient

---

## Bugs We Hit (Do Not Repeat)

| Bug | Root cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | `python -u src/run_x.py` doesn't add project root to sys.path | Always use `python -u -m src.run_x` (module mode) |
| Non-ASCII title crashes Windows run | Missing UTF-8 stdout reconfiguration | Add `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at top of every file that prints |
| Chromium `ERR_HTTP2_PROTOCOL_ERROR` | Akamai TLS fingerprinting blocks headless Chromium | Always use Firefox for Playwright — never Chromium |
| Description fetch returns < 100 chars | Matched wrong HTML element (label div, not content) | Add `len(text) > 100` guard; fall back to empty string |
| Company name empty in alerts | Company only on detail page, not list page | Cache company name during `fetch_job_description` (same HTTP request, zero extra calls) |
| GitHub Actions cron drifts 30–90 min | GitHub scheduler is best-effort, not guaranteed | Wire cron-job.org as external trigger; keep GitHub cron as backup |
| `[skip ci]` commit re-triggers workflow | Missing tag on state commit message | Always use `[skip ci]` in the git commit message for seen_jobs updates |
| Alert fires for wrong Safran division | Gate 2 passed on generic MRO words for non-engine divisions | Acceptable for now — add optional company-name filter later if noise grows |
| Parallel pipeline: one crash kills all | Exception escaped `__main__` try/except | Every `run_<company>.py` must wrap `__main__` in try/except with `sys.exit(1)` |
| Phenom site probed as Workday (wasted 30 min) | GE's "Apply" button links to `wd5.myworkdayjobs.com` — looks like Workday | Workday is the downstream ATS for applications; Phenom is the job search UI. Check page source for `cdn.phenompeople.com` before assuming Workday. |
| Phenom API returns 0 jobs / `tokenAvailable:false` | POST to `/widgets` without a valid session — no CSRF token | Bootstrap a `requests.Session` first: GET the search-results page to get the `PLAY_SESSION` cookie and `csrfToken` div, then add `csrf-token` header to all subsequent POSTs. |

---

## GitHub Actions Workflow Structure

```yaml
# Key patterns — don't change these without understanding the why

# 1. Module mode — required for src imports
run: python -u -m src.run_<company>

# 2. Parallel execution — all pipelines run simultaneously
python -u -m src.run_safran  & pid1=$!
python -u -m src.run_ge      & pid2=$!
wait $pid1 || fail=1
wait $pid2 || fail=1

# 3. State persistence — only commit if files changed
git diff --quiet seen_jobs_safran.json near_misses_safran.json || \
  git commit -m "chore: update state [skip ci]"

# 4. Firefox cache — keyed on requirements.txt hash
key: playwright-firefox-${{ hashFiles('requirements.txt') }}

# 5. Node.js 24 future-proofing
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
```

---

## Config Reference

```yaml
matching:                          # shared across ALL companies
  title_family: [...]              # Gate 1: title must contain ≥1
  exclude_terms: [...]             # Gate 3: title must contain 0
  engine_specific_terms: [...]     # Gate 2: description must contain ≥1 of these
  domain_terms: [...]              # Gate 2: combined with engine_specific, total ≥2

<company>_search:                  # per-company, fully isolated
  max_listings: 200
  inter_page_delay: 0.3
  keywords: [...]
  locations:
    - "all"                        # always "all" — no location filtering in this project
```

---

## Weekly Digest

`near_misses_<company>.json` accumulates jobs that passed 1 or 2 gates but not all 3,
with timestamps. The digest surfaces these weekly so you can:
1. Spot real roles the filter almost missed (tune config if needed)
2. Confirm the watcher is alive even during a quiet week with no full matches

The digest runs as part of the normal pipeline — if 7+ days of near-misses exist, it sends
a summary email before clearing the old entries.

---

## Company Pipeline Roadmap

| Phase | Company | ATS guess | Priority reason |
|---|---|---|---|
| ✅ 1 | Safran | Custom ASP.NET | Hyderabad SAESI ramping now |
| ✅ 2 | GE Aerospace | Phenom People (not Workday — apply button misleads) | Native engine match (GE90/GEnx CRS) |
| 2 | Sanad (Abu Dhabi) | Custom/Taleo | Best single Middle East target |
| 2 | Emirates Engineering | Taleo/Custom | Highest Middle East prestige |
| 2 | RTX / Pratt & Whitney | Workday | PW4000 match, Eagle Services Singapore |
| 3 | IndiGo | iCIMS/Custom | Largest India fleet, heavy engine workload |
| 3 | Air India / AIESL | Custom | Incumbent employer network |
| 3 | GMR Aero Technic | Custom/Small | Hyderabad, ramping |
| 3 | Akasa Air | Small/LinkedIn | Low volume — assess before building |
| 4 | SIA Engineering | Custom | Singapore anchor |
| 4 | ST Engineering Aerospace | Workday/Custom | Singapore |
| 4 | SAESL | Rolls-Royce affiliate | Singapore Trent shop |
| 5 | Etihad Engineering | Taleo | Middle East |
| 5 | Joramco | Custom/Small | Middle East — assess volume first |
| 5 | Saudia Technic | Custom | Middle East |
| 6 | Lufthansa Technik | Custom German | Global chain |
| 6 | StandardAero | Workday | US/Canada/Singapore |
| 6 | MTU Maintenance | Custom | Germany/Canada/Serbia |
| 6 | AFI KLM E&M | Custom French | Global chain |
