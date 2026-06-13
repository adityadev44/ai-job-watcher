# Aviation MRO Job Watcher — Playbook

Reference for maintaining this project and adding new company pipelines.

---

## How to Read This Playbook

**This playbook is instructional guidance, not a rigid recipe.**

Every company is different. Every ATS vendor deploys their product differently. The patterns documented here reflect what worked for the companies already integrated — they are a starting point, not a guarantee. When you encounter something that contradicts the playbook, trust what you observe over what is written here.

When adding a new company: read the playbook for context, then investigate the actual system with fresh eyes. Probe the API yourself. Test URLs in a real browser. Read the HTML. The goal is a working pipeline that catches real senior MRO roles — the playbook saves time getting there, it doesn't replace judgment.

**What "following the playbook" means in practice:**
- Use the patterns as hypotheses to test, not instructions to execute blindly
- When something doesn't work the way a section predicts, that's new information — update the playbook
- The companies in the roadmap all have ATS guesses next to them; treat those as starting guesses, not facts
- If a step produces unexpected results (wrong URL, empty data, 404, wrong job count), stop and investigate before proceeding

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

**All four gates must pass. Gates run in this order to minimise API calls.**

```
fetch_jobs()
    └─ Gate 1: Title family check              → [gate1] tag if fails
    └─ Gate 3: Title exclude terms check       → [gate3] tag if fails
        └─ fetch_job_description()             ← only fetched if G1 + G3 pass
            └─ Gate 4: Description exclusion   → [gate4] tag if fails
                └─ Gate 2: Engine domain check → [gate2] tag if fails
                    └─ MATCH
```

**Gate 1 — Title family (leadership/specialist shape)**
Title must contain at least one term from `matching.title_family`, matched with **word-boundary
regex** (`re.search(r'\b<term>\b', title_lc)`). This prevents "engine" matching "engineer" or
"engineering", and "lead" matching "leader".
Current terms: manager, head, director, lead, chief, consultant, advisor, compliance, powerplant,
engine, engines, mro, shop, technical services, instructor, overhaul, camo, continuing airworthiness.
Added: "camo" catches "CAMO Manager", "Head of CAMO", "CAMO Planner" (CAMO = Continuing
Airworthiness Management Organisation). "continuing airworthiness" catches "Continuing Airworthiness
Manager" as a phrase.
Removed: "quality", "safety", "production" — all covered by "manager"/"director"/"head" at the
right seniority level. Removing them eliminates "Quality Engineer", "Safety Engineer", etc.
Note: "engine" and "engines" are separate entries — `\bengine\b` does NOT match "engines" (plural).

**Gate 3 — Exclude terms (title-based only, word-boundary matched)**
Title must NOT contain any term from `matching.exclude_terms`, also matched with word-boundary regex.
Excludes: technician, apprentice, trainee, intern, fresher, graduate, new grad, software, it,
avionics, cabin, pilot, finance, sales, structures, airframe, hr, human resources, coordinator,
mechanic, inspector, talent acquisition, warehousing, asset management, dnata, skillbridge, operator.
Added: "skillbridge" blocks US DoD SkillBridge internship postings (seen at GE Aerospace) from
slipping through via "lead"/"director" in the role-title suffix. "operator" blocks floor-level
production/machine operator roles ("Engine Assembly Shop Operator", "CNC Machine Operator").
(Note: "it" was previously "it " with trailing space — word-boundary matching replaced it.)

**Gate 4 — Description exclusion (US-citizens-only and inaccessible roles)**
After the description is fetched and confirmed ≥100 chars, the description is checked for
any term in `matching.description_exclude_terms` using case-insensitive substring matching.
If found, the job is rejected regardless of engine domain content.
Current terms: "u.s. citizenship required", "must be a u.s. citizen", "us citizenship required",
"u.s. citizens only", "us citizens only", "u.s. persons only", "us persons only".
Purpose: US defense contractors (RTX/Pratt & Whitney in particular) post engine-adjacent roles
that are legally restricted to US citizens. These jobs are unreachable for non-US candidates
regardless of qualifications. Gate 4 filters them without touching Gate 3 title logic.
Note: short/unavailable descriptions bypass Gate 4 (same as Gate 2) — the job is kept
unconditionally when description fetch fails or returns < 100 chars.
Note: avoid overly broad terms like "security clearance required" — these appear in descriptions
for legitimate international roles involving classified supplier data, not citizenship restrictions.

**Gate 2 — Engine domain (description-based, ≥3 hits including ≥1 engine-specific)**
Description must contain:
- At least 1 hit from `engine_specific_terms`
- At least 3 total hits from `engine_specific_terms` + `domain_terms` combined
(Threshold raised from 2→3 for additional precision — any genuine engine/CAMO description
hits 5+ terms easily; the 3-hit requirement only blocks weak one-engine-hit cases.)

**engine_specific_terms** — only truly engine-or-CAMO-exclusive terms:
Engine model families: GE90, GEnx, PW4000, CF6, CFM56, LEAP, GTF, PW1100, Trent, V2500
Engine shop activities: engine overhaul, test cell, borescope, shop visit, workscope,
  on-wing, engine ground run
Life-limited parts: LLP
CAMO / airworthiness management: CAMO, Part-M, continuing airworthiness

**What was REMOVED from engine_specific_terms:** "Part 145", "CAR 145", "CRS" — these are
MRO certification standards that apply to ALL shops (engines, airframe, avionics, cabin),
not engine-specific. An airframe shop description with "Part 145 approved facility" was
silently passing Gate 2 with engine_hits=1. These three terms are now in domain_terms.

If description fetch fails or returns < 100 chars → KEEP THE JOB UNCONDITIONALLY.

**Near-miss logging format (must match exactly):**
```
[gate1] Senior Avionics Technician (no title family match)
[gate3] MRO Software Engineer (exclude hit: "software")
[gate4] Engine Fleet Manager (description contains 'u.s. citizenship required')
[gate2] Production Manager (engine_hits=0, domain_hits=3, needed ≥1 engine + ≥3 total)
```

---

## Architecture

```
config.yaml                       ← all config: shared matching rules + per-company search params
src/
  matcher.py                      ← shared 4-gate filter engine + weekly digest builder
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
    # Returns list of dicts. Required fields:
    # {
    #   "title":        str,          # job title as shown on the careers page
    #   "url":          str,          # BROWSEABLE URL — must open a real job page in Chrome (see below)
    #   "location":     str,          # human-readable city/country
    #   "company":      str,          # brand/division name (not the parent group)
    #   "source":       str,          # short fetcher name, e.g. "emirates", "safran"
    #   "posting_date": str,          # YYYY-MM-DD or ISO 8601 — shown in every alert
    # }
    # Optional: "id" (dedup key if url isn't stable)
    # "date" is the legacy key used by Safran — new fetchers must use "posting_date"

def fetch_job_description(application_url) -> str | tuple[str, str]:
    # Canonical (new fetchers):  return (description_text, posting_date_string)
    # Legacy (Safran only):       return description_text as plain str
    # matcher.py handles both via isinstance(raw, tuple) — always returns "" or ("","") on failure
    # On ANY failure: return "" or ("", "") — never raise, never crash
```

**Dual return type:** matcher.py uses `isinstance(raw, tuple)` so both forms work. New fetchers
should always return the tuple. Safran is the only legacy `str` returner and will be updated
when next touched. Until then, do not rely on the str form in new code.

**Browseable URL rule (enforced, not optional):**
The `url` field goes directly into Telegram and email alerts. It must open a human-readable
job page when clicked in Chrome. API endpoints that return JSON, 404, or redirect to a login
wall are not acceptable. Before shipping a new fetcher, verify the URL format with a real
HTTP GET — check the response is HTML with real content, not a backend endpoint.

Many ATS APIs return two different URLs for the same job:
- An **application URL** (used by the ATS tracking system — often a Workday or internal link)
- A **browseable URL** (the job listing page a candidate would share or bookmark)

These are different. The API response often has a dedicated field for the browseable URL
(`redirectionurl`, `jobUrl`, `applyUrl`, `externalUrl` — name varies by ATS). Always check
the full API response for such a field before constructing a URL yourself. If the API provides
a canonical URL, use it — don't guess the path.

**Posting date rule:**
Every alert shows `Posted  : YYYY-MM-DD`. The `posting_date` field is required in every job
dict. `notifier._display_date()` normalises these formats automatically:
- YYYY-MM-DD (Sanad, Emirates) — used as-is
- ISO 8601 `2026-05-01T00:00:00.000+0000` (GE Aerospace) — date portion extracted
- D/M/YYYY or DD/MM/YYYY (Safran) — converted to YYYY-MM-DD
If the ATS provides a millisecond Unix timestamp, convert: `datetime.fromtimestamp(ts/1000, tz=utc).strftime("%Y-%m-%d")`.

---

## Current Companies

| Company | ATS | Fetch method | Entry point | Notes |
|---|---|---|---|---|
| Safran | Custom ASP.NET | HTML scraping (requests + BeautifulSoup) | `run_safran.py` | GET `/job/list-of-all-jobs.aspx?LCID=1033&Keywords={kw}&mode=list&page={n}` — fully stateless, no session. Description at `<div id="contenu-ficheoffre">`. Company name in `<meta name="Description">`. Newest-first by default. |
| GE Aerospace | Phenom People | JSON API (requests + BeautifulSoup) | `run_ge.py` | `refNum=GAOGAYGLOBAL`. Session bootstrap: GET `/global/en/search-results` for CSRF token + session cookie, then POST `/widgets` with `ddoKey:"refineSearch"`. Keywords ignored server-side — all ~570 jobs returned regardless; filter locally. Description via POST `/widgets` with `ddoKey:"jobDetail"` + `jobId`. Browseable URL: `/global/en/job/{reqId}`. `fetch_job_description` returns `(str, str)` tuple. |
| Sanad (Aerotech + Capital) | Sniperhire (custom ASP.NET Core Razor Pages) | HTML scraping (requests + BeautifulSoup) | `run_sanad.py` | `careers.sanad.ae` — NOT sanad.aero (that's an unrelated Libyan site). Pagination: `/?pg=0`, `/?pg=1`, ... (0-indexed); stop when page returns no vacancies. 10 jobs/page, ~15–30 total. No keyword filtering — fetch all, filter locally. Job cards: `div.row.jobdetail.mb-4.ms-0`; fields in `div.searchcaption` label/value pairs. Description: all `div.sectn` elements on `/vacancy/{id}`. Closing date only (no posting date) — format `DD-Mon-YYYY`, converted to `YYYY-MM-DD`. **Pre-filtered to Sanad Aerotech only in `run_sanad.py`** (`"capital" not in company.lower()`) — Sanad Capital (engine leasing/finance) roles have descriptions rich enough in engine terminology to pass Gate 2, so division-level exclusion is needed here. |
| Emirates Engineering | Avature (custom REST API wrapper) | JSON REST API (requests + BeautifulSoup) | `run_emirates.py` | `GET https://www.emiratesgroupcareers.com/api/v1/jobs?showAll=true` returns all ~79 active jobs across all Emirates Group brands (Emirates, Emirates Engineering, dnata, etc.) with **inline full HTML descriptions** in a single call — no pagination, no keyword iteration. `reqid` field is the job ID (numeric strings like `"18738"`). Browseable URL taken from the `redirectionurl` field in the API response: `https://external.emiratesgroupcareers.com/careersmarketplace/ApplicationMethods?jobId={reqid}&source=CareerWebsite` — **not** `JobDetails` (404) or any constructed guess. `postingdate` is a millisecond Unix timestamp — convert with `datetime.fromtimestamp(ts/1000, tz=utc)`. Descriptions cached in `_desc_cache` during `fetch_jobs()` so `fetch_job_description()` needs zero extra HTTP calls. Covers all brands — Gate 2 filters to engine/MRO roles. Not Phenom People — Emirates uses Avature; GE uses Phenom People; the two look similar from the outside. |
| GMR Aero Technic | SAP SuccessFactors Job2Web (J2W) | HTML scraping (requests + BeautifulSoup) | `run_gmr.py` | `GET https://careers.gmrgroup.in/search/?q=&sortColumn=referencedate&sortDirection=desc&start=N`. Each row: `tr.data-row`; title+href from `a.jobTitle-link` (relative `/job/{slug}/{id}/`); location from `span.jobLocation` — contains internal codes like `"Goa, GMR AA - Goa (PG11AA06), IN"` — clean with `re.sub(r'\s*\([^)]+\).*$', '', parts[0])` + append `, India`; date from `span.jobDate` format `"D Mon YYYY"`. Total count from `aria-label="Results 1 to N of T"` regex. Company always `"GMR Group"` (portal covers all GMR entities; Gate 2 handles domain filtering). Description at `span.jobdescription`; posting date in detail page text as `"Date:DD Mon YYYY"` regex. Currently ~5 non-MRO jobs — 0 engine matches expected until MRO hiring ramps. |
| RTX / Pratt & Whitney | Phenom People (same ATS as GE Aerospace) | JSON widget API (curl_cffi + BeautifulSoup) | `run_rtx.py` | `POST https://careers.rtx.com/widgets` with `ddoKey:"refineSearch"`, `refNum:"RAYTGLOBAL"`. **Akamai blocks search-results page** — bootstrap from `/global/en/pratt-whitney` (landing page, returns 200). curl_cffi with `impersonate="chrome120"` required for TLS fingerprint; plain `requests` gets 403. API returns oldest-first (no working sort option) — paginate from `totalHits - max_listings` to get newest N jobs. ~4200 total RTX jobs (all divisions: P&W + Collins + Raytheon). Company name from `businessUnit` field in listing (not `company`/`companyName` — always null). `pageId="page2"`, `pageName="category-landing-template"` from landing page phApp config. Browseable URL: `/global/en/job/{reqId}`. **Pre-filtered to Pratt & Whitney only in `run_rtx.py`** (`"pratt" in company.lower()`) — Collins Aerospace and Raytheon roles pass Gate 2 because their descriptions contain aerospace domain terms; division-level exclusion is the correct fix. |
| IndiGo | SAP SuccessFactors VERP/JUIC/DWR | Playwright + Firefox (DWR interception) | `run_indigo.py` | `career-in10.hr.cloud.sap/careers?company=interglobe`. Call `window.careerJobSearchController.searchJobs(null)` via `page.evaluate()`, intercept `searchJobs.dwr` response. **Only 10/30 jobs accessible per run** — paginator lives on a separate login-required URL. `jobReqSecKey` is session-scoped — use numeric `id` field for URL and deduplication. Descriptions unavailable (SAP UI5 detail page doesn't render headlessly) — `fetch_job_description` returns `("","")`. **Pre-filter required:** IndiGo hires across all functions; Gate 1 alone passes admin/finance/analytics titles. `run_indigo.py` drops any job whose title contains no aviation-domain term before handing to the 3-gate matcher. Deduplicates by `id` (not `url`), stored in `seen_jobs_indigo.json`. |
| SIA Engineering | SAP SuccessFactors J2W (same ATS as GMR Group) | HTML scraping (requests + BeautifulSoup) | `run_sia.py` | `careers.singaporeair.com/siaec` — shared SIA Group domain, SIAEC tenant. Search: `GET /siaec/search/?q=&sortColumn=referencedate&sortDirection=desc&start=N`. Rows: `tr.data-row`; title from `a.jobTitle-link` (href: `/siaec/job/{slug}/{id}/`); location from `span.jobLocation` — always a 2-letter ISO code (`"SG"`, `"MY"`, etc.) — map to country name via dict; date from `span.jobDate` format `"D Mon YYYY"`. Description: `span.jobdescription` on detail page — detail page has no date field, use listing date. Company is pure MRO — no aviation pre-filter needed. Currently ~11 active jobs; mostly technician trainee roles. Dedup by URL. |
| Etihad Engineering | Oracle HCM Cloud Recruiting | JSON REST API (curl_cffi) | `run_etihad.py` | `careers.etihadengineering.com` — backend at `fa-eurv-saasfaprod1.fa.ocs.oraclecloud.com`. No Playwright needed — plain curl_cffi GET with `impersonate="chrome120"`. List: `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1,...` returns all jobs in `items[0].requisitionList`. Detail: `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?finder=ById;Id="{id}",siteNumber=CX_1`. Description assembled from `ExternalResponsibilitiesStr` + `ExternalQualificationsStr` + `ExternalDescriptionStr` (all may be HTML — strip with BeautifulSoup). IDs are stable numeric strings (e.g. `"812"`); URL-based dedup using `seen_jobs_etihad.json`. No server-side keyword filtering — all active listings (~5–30) returned per run. **Note: Oracle HCM docs say `Playwright required` — that applies to the consumer-facing SPA, not the REST API backend. The API accepts plain curl_cffi calls if you send correct Referer/Origin headers.** |
| Saudia Technic | Talentera by Bayt.com | HTML scraping + AJAX (requests + BeautifulSoup) | `run_saudia_technic.py` | `careers.saudiatechnic.com` — Powered by Talentera (Middle Eastern ATS by Bayt.com). Session setup required: GET listing page to extract `USER_token` from inline JS (`USER_token = '<token>'`). Jobs fetched via POST to `/app/control/byt_job_search_manager` with `action=1, token=<token>, page=N`. 10 jobs/page; `response['totalJobs']` gives total. Job fields: `id`, `title`, `url` (relative), `loc` (already human-readable), `crtDate` (format `"YYYY-MM-DD HH:MM:SS"` — take first 10 chars). Description in `div.job-desc` on detail page. Currently very low volume (~1 active job) — pipeline is monitoring for when MRO engine roles get posted. |
| StandardAero | Oracle HCM Cloud Recruiting (same ATS as Etihad Engineering; US1 data centre `cva.fa.us1.oraclecloud.com`, site `CX_3`) | JSON REST API (curl_cffi) | `run_standardaero.py` | No Playwright needed — plain curl_cffi GET with `impersonate="chrome120"`. Pagination via `offset=N` in the `finder` string (not as a separate query param). 100 jobs/page, ~251 total. Key difference from Etihad: description field is `ExternalDescriptionStr` (not responsibilities/qualifications — those are empty for StandardAero). Posting date from `PostedDate` in listing (already YYYY-MM-DD). No inline descriptions in listing — must call detail API for each Gate 1+3 pass. Browseable URL: `{BASE_API}/hcmUI/CandidateExperience/en/sites/CX_3/job/{id}`. |
| ST Engineering Aerospace | SAP SuccessFactors J2W (same ATS as GMR and SIA) | HTML scraping (requests + BeautifulSoup) | `run_ste.py` | `careers.stengg.com` — multi-division portal (Commercial Aerospace, Defence Aerospace, Group HQ, Urban Solutions, Marine, Land Systems, Digital Systems). Search: `GET /search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=N` — **note `startrow=` not `start=`** (differs from GMR/SIA). 25 jobs/page, ~350 total across all divisions. Division in `span.jobFacility` column (labelled "Facility" in HTML). **Pre-filtered to Commercial Aerospace only in `run_ste.py`** — ~44 of ~350 total jobs. Description: `span.jobdescription` on detail page (same as GMR/SIA). Total count from `aria-label="Search results for . Page N of M, Results 1 to 25 of T"` — same `r"Results \d+ to \d+ of (\d+)"` regex as SIA. Location format: `"Division - Address, CC"` e.g. `"Aero - 501 Airport Rd, SG"` — strip division prefix with `.split(" - ", 1)[1]`, then map `"SG"` → `"Singapore"`. |
| Lufthansa Technik | Custom Lufthansa Group ATS (`apply.lufthansagroup.careers`) | JSON REST API (requests + BeautifulSoup) | `run_lht.py` | `apply.lufthansagroup.careers` — Lufthansa Group-wide ATS, no Playwright needed. One GET call returns all ~305 Lufthansa Group jobs. Filter locally: `ParentOrganizationName` contains `"Lufthansa Technik"` → ~103 jobs across 14 subsidiary entities (Hamburg, Malta, Sofia, Shannon, Milan, Puerto Rico, Shenzhen, Portugal, etc.). API: `GET https://api-apply.lufthansagroup.careers/search/?data=<JSON>` — JSON `data` param, URL-encoded. `CountItem=500` fetches all in one call. Response: `SearchResult.SearchResultItems[].MatchedObjectDescriptor`. Job URL from `PositionURI` field (already a canonical browseable URL). Description: GET detail page `apply.lufthansagroup.careers/index.php?ac=jobad&id={ID}`, parse `soup.find(id="content")` or `soup.find("main")` (~4600 chars). German-language titles fail Gate 1 naturally (no title_family terms match German job titles). |

---

## How to Add a New Company

> **Every company is different.** These steps capture what worked across past integrations.
> Read what the new system actually does before reaching for copy-paste. The goal is accurate
> alerts — the playbook saves time, it doesn't constrain good judgment.

### Step 0 — Assess feasibility before writing a line of code (5 min)

Three questions that determine your fetch strategy and your alert quality. Answer them from the browser before starting any probing.

**1. Can you get all jobs without login?**
On the public careers page, count the total jobs shown and check if there's a paginator. If the paginator or full listing requires a login to access (common on SAP SuccessFactors VERP portals), you are capped at whatever the first page shows. Accept that ceiling upfront — do not spend hours trying to circumvent it. The daily-run cadence compensates: new jobs always land on page 1.

**2. Is the job URL stable across sessions?**
Open the same job in two separate browser sessions (incognito + normal) and compare the URLs. If the URL contains a long random-looking token (80+ digits, a JWT, a hash) it is likely session-scoped and will change every time. In that case: identify the stable numeric requisition ID in the page JS or API response, and use that for both the URL and the deduplication key — not the session token.

**3. Can you get descriptions without login?**
Click a job to open its detail page. If the page loads the description without prompting for login, `fetch_job_description` can work. If the detail page redirects to login or renders as "job not found" in a headless browser, descriptions are inaccessible — `fetch_job_description` must return `("","")`. In this case: check how domain-diverse the company's hiring is. A pure MRO shop (Safran, Sanad) is fine with Gate 1 alone. A full-service airline or conglomerate (IndiGo, GMR) hires in finance, HR, IT — Gate 1's broad terms ("manager", "consultant") will catch non-aviation roles. **Add a source-specific aviation pre-filter in `run_<company>.py`** that requires at least one aviation-domain term in the title before handing off to the 3-gate matcher.

---

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
| **Oracle HCM Cloud Recruiting** | `fa.ocs.oraclecloud.com/hcmRestApi` in XHR; `recruitingCEJobRequisitions` endpoint name | REST API — curl_cffi with `impersonate="chrome120"` works without Playwright. The consumer careers SPA is a JS app, but the underlying hcmRestApi backend accepts plain GETs with correct Referer/Origin headers. List endpoint: `recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_1,...`; detail: `recruitingCEJobRequisitionDetails?finder=ById;Id="{id}",siteNumber=CX_1`. See Etihad Engineering row for confirmed usage. |
| **iCIMS** | `icims.com` in URL | REST API or HTML scraping |
| **Greenhouse** | `greenhouse.io` | Public REST API, well-documented |
| **Lever** | `lever.co` | Public REST API |
| **Taleo** | `taleo.net` | HTML scraping usually required |
| **SAP SuccessFactors Job2Web (J2W)** | `successfactors.com` or company-hosted domain | HTML scraping — J2W has no JSON API; search results are an HTML table (`tr.data-row`). See J2W Notes below. Do not assume the full SuccessFactors REST API is available — many companies only deploy the J2W front-end. |
| **SAP SuccessFactors VERP/JUIC/DWR** | `career-XX.hr.cloud.sap` in URL; `.dwr` XHR calls; `window.careerJobSearchController` in page JS | Playwright + Firefox required. Call `page.evaluate("() => { window.careerJobSearchController.searchJobs(null); }")` and intercept the `searchJobs.dwr` response. Parse the DWR variable-assignment format (`sN.field=value; sN[idx]=sM;`). See VERP/JUIC/DWR Notes below. **jobReqSecKey in the URL is session-scoped** — use the numeric `id` field for dedup and URL construction, not the seckey. |
| **Avature** | `external.<company>.com` subdomain; `api/v1/jobs` in XHR | REST API — single call returns all jobs with inline descriptions; look for `redirectionurl` field for the browseable URL |
| **Sniperhire** | `/vacancy/{id}` URL pattern; `.sectn` divs in job detail HTML | HTML scraping; pagination via `/?pg=N` (0-indexed) |
| **Talentera (by Bayt.com)** | `b8cdn.com` CDN in scripts; `baytGlobalObj` in inline JS; "POWERED BY Talentera" footer | GET listing page to extract `USER_token`; POST `/app/control/byt_job_search_manager` with `action=1, token, page`. Returns JSON with `totalJobs` and `jobs[]`. Detail page: `div.job-desc`. |
| **Custom** | `.aspx` URLs, ViewState tokens in HTML | HTML scraping with BeautifulSoup/lxml |

### Step 2 — Map the response structure

Find and verify each of the following before writing any code:

**Job ID and deduplication key**
- Identify the stable unique ID for each job (reqid, jobId, reqNo, etc.)
- Confirm it doesn't change between fetches — some ATS systems rotate IDs

**Title, location, company**
- Check for abbreviated titles ("Mgr", "Engr", "Sr.") — add expanded forms to `title_family` in config if needed
- Company/brand field: often the parent group on the list page, but the actual division on the detail page. Fetch the right one.

**Posting date**
- Find the date field and note its format: YYYY-MM-DD, ISO 8601, millisecond Unix timestamp, relative string ("Posted 3 days ago"), or site-specific (DD/MM/YYYY, D/M/YYYY)
- If it's a millisecond Unix timestamp: `datetime.fromtimestamp(ts/1000, tz=utc).strftime("%Y-%m-%d")`
- If it's a relative string: compute approximate absolute date from today's date
- Store as `posting_date` in the job dict — `notifier._display_date()` handles all the formats above

**Browseable URL — this step is mandatory, not optional**
The URL you put in the job dict goes directly into alerts. Candidates click it. It must open
a real job listing page in Chrome. Before writing the fetcher:
1. Scan the full API response for URL-like fields: `redirectionurl`, `jobUrl`, `applyUrl`, `externalUrl`, `jobDetailUrl`, `slug`, `externalPath`. Try the one that looks most like a browseable link.
2. If the API provides a canonical URL in the response, use it directly — don't construct your own.
3. If you must construct a URL, look at the real careers page in DevTools to find the actual path pattern (the URL when you click a job listing in a browser).
4. Test by making a GET request and checking: status 200, response is HTML (not JSON, not a redirect to login), and content length > 5 KB.
5. If you got it wrong and shipped it, fix it and update `seen_jobs_<company>.json` to migrate the old URLs — otherwise those jobs will re-alert.

Common traps:
- **API endpoint ≠ browseable page.** `external.company.com/api/...` and `external.company.com/en_US/...` look similar but one is the API and one is the page. Test both.
- **Apply URL ≠ job listing URL.** Phenom's `applyUrl` links to Workday. Avature's `redirectionurl` links to `ApplicationMethods` (the page). GE's browseable URL is constructed as `/global/en/job/{reqId}`. Each ATS is different.
- **Locale prefix may or may not be required.** `/en_US/path` and `/path` are sometimes the same and sometimes not — test both and use the one the API provides.

**Descriptions**
- JS-rendered descriptions: plain `requests` returns empty — use Playwright/Firefox or a JSON detail endpoint
- Descriptions embedded inline in the list API (Emirates style): cache them during `fetch_jobs()` so `fetch_job_description()` needs zero extra HTTP calls
- Company name: if only on the detail page, cache it during the description fetch (same request, zero extra calls)

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
- `posting_date` in every job dict (YYYY-MM-DD or ISO 8601) — shown in every alert
- Browseable `url` — use the API's canonical URL field if one exists; never guess a path you haven't tested
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

**If descriptions are unavailable AND the company is domain-diverse** (full-service airline, conglomerate, airport group), add an aviation pre-filter before `filter_jobs()`:
```python
_AVIATION_TITLE_TERMS = [
    "engineer", "engineering", "aircraft", "engine", "powerplant",
    "maintenance", "airworthiness", "mro", "overhaul", "shop",
    "technical services", "technical manager", "quality", "safety",
    "compliance", "instructor", "ame", "dgca", "aviation", "propulsion",
]

def _is_aviation_title(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in _AVIATION_TITLE_TERMS)

# In run_pipeline(), before filter_jobs():
aviation_jobs = [j for j in raw_jobs if _is_aviation_title(j["title"])]
```
This is the right fix when Gate 2 is bypassed — tighten Gate 1 at source level rather than adding more generic `exclude_terms` globally (which would break other pipelines).

**If the URL is session-scoped** (see Step 0 question 2), deduplicate by `j["id"]` instead of `j["url"]`:
```python
seen_ids = set(_load_json(seen_path))
new_matches = [j for j in matched if j["id"] not in seen_ids]
# ...
for job in new_matches:
    seen_ids.add(job["id"])
_save_json(seen_path, sorted(seen_ids))
```

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
- Test: `fetch_jobs` returns correct fields from sample (title, url, location, company, source, posting_date)
- Test: `posting_date` is in YYYY-MM-DD or ISO 8601 format — not empty, not a raw timestamp integer
- Test: `url` contains the expected path pattern (assert it contains the browseable endpoint, assert it does NOT contain any backend-only endpoint you discovered was wrong)
- Test: `fetch_job_description` returns non-empty description from sample
- Test: `RateLimitError` raised on mocked 429 response
- Test: `fetch_job_description` returns `("", "")` on network failure (not raise)

Run pytest — all tests must pass before pushing.

### Step 9 — Local test

```bash
python -u -m src.run_<company>
```

Verify:
- Non-zero jobs fetched (if zero, the fetch is broken — don't proceed)
- Gate-by-gate summary looks sane: not all passing (filter is too loose), not all failing (filter is too strict or fetch is broken)
- `Posted  :` line appears in the alert with a real date, not "N/A" — if N/A for all jobs, the date field name is wrong
- Click one of the URLs from the matched jobs in Chrome — confirm it opens a readable job listing page, not a 404 or JSON response
- No obviously wrong roles in matched list (wrong division, wrong seniority, wrong domain)
- **If Gate 2 kills everything (0 matches, like GMR on a slow hiring month):** that is not the same as broken. Check that Gate 1 and Gate 3 pass a reasonable number of jobs. Spot-check the near-misses in `near_misses_<company>.json` — pick a URL from one of them and confirm it opens correctly in Chrome. The system is working; there are just no engine MRO roles posted yet.

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

## Phenom People Notes (GE Aerospace confirmed; Etihad and others possible — verify per company)

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
- **Akamai protection varies by tenant**: GE Aerospace (`careers.geaerospace.com`) works fine with plain `requests`. RTX (`careers.rtx.com`) requires `curl_cffi` with `impersonate="chrome120"`. When a new Phenom tenant returns 403, switch to curl_cffi before trying Playwright.
- **Multi-brand portals (RTX pattern)**: When a Phenom tenant hosts multiple business units on one domain (e.g. RTX hosts P&W + Collins + Raytheon), the API returns all brands mixed. Use `businessUnit` field (not `company`/`companyName`) for the company display name. The API sort may be ascending-by-ID (oldest first) — probe `totalHits` first, then paginate from the tail to get the newest jobs.

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
| Emirates job URLs opened to "page not found" in Chrome | URL was constructed by guessing `/en_US/careersmarketplace/JobDetails?jobId=X` — that path doesn't exist. The API's own `redirectionurl` field had the correct URL: `/careersmarketplace/ApplicationMethods?jobId=X&source=CareerWebsite` | Always look for a canonical URL field in the API response before constructing one. Test the URL with a real GET before shipping. |
| Posting date missing from all alerts | The `posting_date` field was in every job dict but `format_job_message` in `notifier.py` never rendered it | `notifier._display_date()` now normalises all date formats. Every new fetcher must include `posting_date` in the job dict and the local test must confirm "Posted  :" shows a real date. |
| Safran dates sorted as "0000-00-00" | `_date_sortable` regex used `\d{2}` requiring 2-digit day/month; Safran HTML outputs single-digit months like `6/10/2026` | Fixed to `\d{1,2}` with `.zfill(2)` padding. When adding a new company, run the gate-by-gate summary and spot-check that posting dates look right in the sort order. |
| RTX search-results page returns 403 with requests | Akamai TLS fingerprinting blocks Python's `requests` library on `careers.rtx.com/global/en/*-search-results`. The landing page (`/global/en/pratt-whitney`) returns 200. | Use `curl_cffi` with `impersonate="chrome120"` as a drop-in replacement for `requests`. Bootstrap from the landing page, not the search-results page. |
| RTX API returns oldest jobs first — newest 200 missed | Phenom on `careers.rtx.com` returns ~4200 jobs sorted ascending by reqId (oldest first). `sortBy` parameter has no effect. Fetching `from=0, size=200` always returns jobs from weeks ago. | Start pagination at `from = max(0, totalHits - max_listings)`. First call is a probe (size=1) to get `totalHits`, then fetch from the tail. |
| RTX `company`/`companyName` always null in listing | Unlike GE Aerospace (dedicated domain = one company), RTX hosts all divisions on one portal. The `company` and `companyName` Phenom fields are null in listing responses. | Use the `businessUnit` field instead — present in every listing row, correctly set to "Pratt & Whitney", "Collins Aerospace", "Raytheon", etc. |
| Gate 1 substring match: "engine" triggers on "engineer/engineering" (50+ false positives) | `term in title_lc` is plain Python substring — "engine" is literally a substring of "engineer" and "engineering". Same issue: "lead" in "leader", "production" in "production engineer". Root cause of ~50% of all false positives observed across GE, RTX, Emirates, Safran. | Use word-boundary regex in Gate 1 AND Gate 3: `re.search(r'\b' + re.escape(t) + r'\b', title_lc)`. Prevents substring collision between any two terms that share a stem. |
| "engine" (singular) does not match "engines" (plural) after word-boundary fix | `\bengine\b` requires word boundaries on both sides; "engines" has a word character ('s') immediately after "engine", so no boundary. A legitimate role like "Specialist, Strategic Procurement, Engines Materials and USM" at Sanad was silently dropped at Gate 1. | Add both "engine" AND "engines" as separate entries in `title_family`. Treat singular/plural as distinct items whenever both appear in real job titles. |
| Multi-division portals pass Gate 2 on wrong-division descriptions | RTX (Collins + Raytheon + P&W), Sanad (Aerotech + Capital): the wrong division's descriptions are rich in aerospace domain terms and engine model names, so Gate 2 alone cannot distinguish. "Repair Station Quality Manager" at Safran Landing Systems had 10 domain hits but 0 engine-specific hits. | Add a company-name pre-filter in `run_<company>.py` before `filter_jobs()`: `raw_jobs = [j for j in raw_jobs if "pratt" in j.get("company","").lower()]`. Do this whenever a portal mixes divisions and Gate 2 is insufficient. Note: moving MRO/SMS/human factors from engine_specific_terms to domain_terms also helped — a description with only "MRO" + generic aviation terms now fails Gate 2. |
| Broad title_family terms ("quality", "safety", "production") catch unintended roles | "Quality Engineer", "Safety Engineer", "Production Engineer" all passed Gate 1 and Gate 2 (engine company descriptions are generic). These are junior individual-contributor roles, not the senior MRO leadership the system targets. | Remove standalone "quality", "safety", "production" from title_family. "Quality Manager", "Safety Director", "Head of Production" still pass via "manager"/"director"/"head" — the seniority shape is preserved. |
| "Part 145" / "CAR 145" / "CRS" in engine_specific_terms allows airframe/avionics shop roles to pass Gate 2 | These three are MRO certification standards held by ALL Part 145 shops regardless of what they maintain (engines, airframes, avionics, cabin). A description for an airframe base maintenance supervisor saying "our Part 145 approved facility" gave engine_hits=1, allowing it to pass Gate 2 with just one more domain term. | Moved "Part 145", "CAR 145", "CRS" from engine_specific_terms to domain_terms. Gate 2 now requires a hit on something truly exclusive to engine or CAMO work (engine model, test cell, shop visit, CAMO, Part-M, LLP, etc.). Gate 2 total threshold also raised from ≥2 to ≥3 for additional margin. |
| DoD SkillBridge internship postings pass Gate 1 via role-title suffix | GE Aerospace posts US military fellowship roles as "Military DoD SkillBridge Program - [Role] Advanced Lead / Staff Engineer". The "lead"/"director" in the suffix passes Gate 1; descriptions mention LLP or engine terms and pass Gate 2. These are not real jobs — they are ~6-month internships for transitioning US military personnel. | Added "skillbridge" to exclude_terms. Word-boundary match catches "SkillBridge" in title regardless of what follows. Does not affect any other pipeline. |
| "Engine Assembly Shop Operator" passes Gate 1 and Gate 3 | The title passes Gate 1 via "engine" (word-boundary correct) and has no Gate 3 exclusion. "Operator" is a floor-level production role, not a leadership/specialist position. Similar issue: "CNC Machine Operator", "Bench Operator". | Added "operator" to exclude_terms. "Operations Manager" / "Operations Director" are unaffected (word-boundary: `\boperator\b` does not match "operations"). |
| CAMO roles failing Gate 2 (no engine-specific description terms) | CAMO (Continuing Airworthiness Management Organisation) job descriptions focus on regulatory compliance — Part-M, airworthiness directives, maintenance programme management. No engine model names. Previously, engine_hits=0 for all CAMO descriptions → Gate 2 failure even if the role is genuinely in scope. | Added "CAMO", "Part-M", "continuing airworthiness" to engine_specific_terms. A CAMO Manager description hitting "CAMO" + "Part-M" + domain terms now passes Gate 2. Also added "camo" and "continuing airworthiness" to title_family to catch CAMO-specific job titles at Gate 1. |

---

## Avature Notes (Emirates Group confirmed)

### Detection
Look for `external.<company>.com` subdomain in XHR calls, or `/api/v1/jobs` in the Network tab.
Avature powers many airline and MRO group career portals under custom domains — the ATS branding
is invisible to the user. If a portal has a clean REST API returning all jobs in one call, suspect Avature.

### The single-call pattern
```python
GET https://www.<company>careers.com/api/v1/jobs?showAll=true
Headers: {"Accept": "application/json", "User-Agent": "<browser UA>"}
# Returns: {"status": "success", "data": [...all jobs with inline jobdescription HTML...]}
```
Key characteristics:
- All jobs returned in a single response — no pagination, no keyword filtering
- Inline HTML descriptions in `jobdescription` field — strip with BeautifulSoup, cache in `_desc_cache`
- `postingdate` is a **millisecond Unix timestamp** (not seconds, not ISO string)
- `reqid` is the job ID (numeric string)

### Browseable URL — use `redirectionurl` from the response
Each job object contains a `redirectionurl` field with the correct browseable URL.
Use it directly. Do not construct a URL from `reqid` alone — the path structure varies by tenant
and guessing it (e.g. `/JobDetails?jobId=X`) produces 404s.

```python
redirect = raw.get("redirectionurl") or ""
url = redirect if redirect else f"{BASE}/careersmarketplace/ApplicationMethods?jobId={reqid}&source=CareerWebsite"
```

### Posting date conversion
```python
import datetime
def _parse_posting_date(ts_ms):
    if not ts_ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            ts_ms / 1000, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""
```

### Key Avature quirks
- Descriptions are inline — no separate detail API call needed (very fast pipeline)
- `brand` field contains the sub-division (e.g. "Emirates Engineering", "Emirates SkyCargo", "dnata") — use this as `company`, not the parent group name
- All brands across the group are returned together — Gate 2 does the domain filtering
- The `redirectionurl` is always present and canonical — prefer it over any constructed URL

---

## SAP SuccessFactors VERP/JUIC/DWR Notes (IndiGo confirmed)

### Detection

IndiGo's career portal lives at `career-in10.hr.cloud.sap/careers?company=interglobe`.
The `career-in10` subdomain is the SAP SuccessFactors VERP (Virtual External Recruiting
Platform) tier. The search widget uses **JUIC** (SAP's JavaScript UI Component framework)
on the front end and **DWR** (Direct Web Remoting, a Java AJAX framework) on the back end.

Fingerprints to recognise it:
- URL contains `career-in10.hr.cloud.sap` (or similar `career-XX.hr.cloud.sap`)
- Page JS has `window.careerJobSearchController` object
- Network tab shows POST requests to `…/xi/ajax/remoting/call/plaincall/careerJobSearchControllerProxy.METHOD.dwr`
- DWR responses start with `throw 'allowScriptTagRemoting is false.';` (anti-CSRF header)
- Response body uses JS variable assignment format: `sN.field=value; sN[idx]=sM;`

### DWR search method

`window.careerJobSearchController.searchJobs(null)` — callable via `page.evaluate()` in
Playwright. Returns 10 jobs per call (page 1 only, newest first).

Total jobs available at IndiGo: ~30 (confirmed via `s2.postingCount="30"` in
`getInitialJobSearchData` DWR response). Only page 1 is reachable from the widget page.

### Pagination limitation

**Pagination is not accessible from the search widget page.** The paginator lives on a
separate URL (`/career?career_ns=job_listing_summary&company=interglobe&...`) that requires
a server-side login session. The `searchJobs(N)` method throws `SFDWRException` when called
with any argument other than `null`. `updateUserSelectedValues` followed by `searchJobs`
does not advance the page. Direct HTTP DWR calls with captured cookies return 0 results
(DWR `scriptSessionId` is session-scoped and cannot be replayed outside the browser engine).

**Mitigation**: Run every 3 h. New postings always land on page 1. Any engineering role
posted at IndiGo will surface within 24 h of posting.

### Fetcher approach

Use **Playwright + Firefox** (headless):
1. `page.goto("https://career-in10.hr.cloud.sap/careers?company=interglobe")`
2. Wait 6 s for JUIC initialisation
3. `page.evaluate("() => { window.careerJobSearchController.searchJobs(null); }")`
4. Intercept `careerJobSearchControllerProxy.searchJobs.dwr` response via `page.on("response", …)`
5. Parse DWR variable format with regex

**Do not** use `curl_cffi` for the main fetch — DWR `scriptSessionId` is browser-bound.

### DWR response parsing

Key structures in the `searchJobs` response:

```
s1.applyWithLinkedInEnabled=false;          ← marks the root results object
s1.detailURLPrefix="/career?career%5fns=job%5flisting&…&career_job_req_id=";
s1.postings=s2;
s2[0]=s3; s2[1]=s4; …                       ← postings array
s3.id=9759; s3.title="…"; s3.postingDate="10/06/2026";
s3.jobReqSecKey="<100+ digit number>";
s3.otherValues=s5;
s5[0]=s6;                                   ← otherValues array
s6[0]=s7;                                   ← field objects array
s7.fieldId="location_obj";
s7.shortVal='["Location",1,"Gurgaon"]';     ← city is last element
```

Date format in DWR: `DD/MM/YYYY` → convert to `YYYY-MM-DD`.

### Job detail / description

Job detail URLs use `career_ns=job_listing` with a `career_job_req_id=<jobReqSecKey>`.
The `jobReqSecKey` is a session-scoped encrypted token — it changes between DWR sessions.
The detail page uses SAP UI5 (not JUIC) and renders asynchronously; it does **not** load
in headless Firefox (`page_content` shows "This job cannot be viewed at the moment").
`curl_cffi` with or without Playwright session cookies also returns the same error.

`fetch_job_description()` returns `("", "")`. The matcher's `[kept-no-desc]` path
(matcher.py line 83: `len(description) < 100 → kept unconditionally`) handles this.

### Key VERP/JUIC/DWR quirks

| Issue | Root cause | Fix |
|---|---|---|
| `searchJobs(2)` → SFDWRException | Method signature expects null, not page number | Pass `null` always; pagination not exposed |
| Direct HTTP DWR POST returns 0 jobs | `scriptSessionId` is registered by browser's DWR engine init; cannot be replayed | Must use Playwright for the fetch |
| `curl_cffi` description fetch → "cannot be viewed" | `jobReqSecKey` is session-scoped; SAP UI5 detail page doesn't render headlessly | Return ("", "") from `fetch_job_description` |
| Keyword filtering via JUIC events has no effect | JUIC `_onChange` + `updateUserSelectedValues(null, null)` doesn't persist to server-side session | No keyword filtering available; all 10 jobs returned per call |
| Pressing Enter on keyword input → only `getPostingCount.dwr` fires | JUIC `_onEnter` handler calls getPostingCount, not searchJobs | Cannot use keyboard input to trigger filtered search |

---

## SAP SuccessFactors Job2Web (J2W) Notes (GMR Group confirmed)

### Detection
Look for the search URL returning an HTML table, not JSON. J2W is identifiable by `tr.data-row`
rows in the results, `span.jobTitle-link` anchor tags, and URLs in the pattern `/job/{slug}/{id}/`.
**There is no JSON API endpoint.** Do not look for one — J2W does not expose it.

If you see `successfactors.com` in the full SuccessFactors REST API docs, that is a different
product tier. Many companies (GMR included) only deploy the J2W HTML front-end.

### Search URL and pagination
```
GET https://<domain>/search/?q=&sortColumn=referencedate&sortDirection=desc&start=N
```
- `start=0` is the default. Increment by the number of results returned per page.
- Total count is in the `aria-label` attribute of the results table: `"Results 1 to N of T"` —
  regex `r"Results \d+ to \d+ of (\d+)"` on `resp.text`.
- Stop when `start >= total` or when a page returns no new rows.
- No server-side keyword filtering — all jobs are returned; filter locally.

### Listing page structure
```python
for row in soup.find_all("tr", class_="data-row"):
    a = row.find("a", class_="jobTitle-link")   # href = /job/{slug}/{id}/
    loc = row.find("span", class_="jobLocation") # contains internal codes — clean before use
    date = row.find("span", class_="jobDate")    # format: "D Mon YYYY" e.g. "10 Jun 2026"
```

### Location cleaning
J2W location strings embed internal airport/facility codes and redundant text, e.g.:
`"Goa, GMR AA - Goa (PG11AA06), IN"`. Strip codes and normalise:
```python
parts = raw_location.split(",")
city = re.sub(r'\s*\([^)]+\).*$', '', parts[0]).strip()
location = f"{city}, India"   # or the relevant country if known
```

### Date parsing
```python
def _parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""
```
Single-digit days work fine (`"%d"` in strptime handles `"5 May 2026"` correctly).

### Detail page
```
GET https://<domain>/job/{slug}/{id}/
```
- Description: `soup.find("span", class_="jobdescription")` — plain text, typically 2–4 KB
- Posting date on detail page: not in a dedicated span — appears in body text as `"Date:DD Mon YYYY"`.
  Extract with `re.search(r"Date:\s*(\d{1,2}\s+\w+\s+\d{4})", resp.text)` and parse same way.

### Company field
J2W portals often cover an entire group, not just one entity (e.g., `careers.gmrgroup.in`
serves all GMR businesses — airports, aero technic, energy). Set `company` to the group name
(e.g., `"GMR Group"`) and let Gate 2 handle domain filtering. Do not set it to a sub-entity
unless the portal is scoped to that sub-entity only.

### Key J2W quirks
- Browser-like User-Agent required — some J2W deployments 403 on obvious bot UA strings
- `format=json` query parameter does nothing — ignore it, always scrape HTML
- The browseable URL is already the canonical link (the `/job/{slug}/{id}/` path the user clicks)
- Low-volume portals (< 10 total jobs) are common — 0 Gate 2 matches is expected until MRO hiring ramps
- **Pagination parameter varies by deployment**: GMR and SIA use `?start=N`; ST Engineering uses `?startrow=N`. Probe the actual URL before copying from another J2W fetcher.
- **Division/facility column varies by portal**: ST Engineering has a `span.jobFacility` column (HTML header `hdrFacility`) with the business unit name ("Commercial Aerospace", "Marine", etc.). GMR and SIA do not expose this column — their portals are scoped to a single entity. If the portal is multi-division, add a `facility` field to the job dict and pre-filter in `run_<company>.py`.

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
  description_exclude_terms: [...] # Gate 4: description must contain 0 (US-only etc.)
  engine_specific_terms: [...]     # Gate 2: description must contain ≥1 of these
  domain_terms: [...]              # Gate 2: combined with engine_specific, total ≥3

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
| ✅ 2 | Sanad (Abu Dhabi) | Sniperhire (not Taleo — careers.sanad.ae, NOT sanad.aero) | Best single Middle East target |
| ✅ 2 | Emirates Engineering | Avature (custom REST API) | Highest Middle East prestige |
| ✅ 2 | RTX / Pratt & Whitney | Phenom People (not Workday — apply button links to Workday but search is Phenom; curl_cffi required for Akamai) | PW4000 match, Eagle Services Singapore |
| ✅ 3 | IndiGo | SAP SuccessFactors VERP/JUIC/DWR (Playwright; page 1 of 3 only — pagination unavailable) | Largest India fleet, heavy engine workload |
| 3 | Air India / AIESL | Custom | Incumbent employer network |
| ✅ 3 | GMR Aero Technic | SAP SuccessFactors J2W (HTML scraping) | Hyderabad, ramping |
| 3 | Akasa Air | Small/LinkedIn | Low volume — assess before building |
| ✅ 4 | SIA Engineering | SAP SuccessFactors J2W (not Custom — same ATS as GMR; portal at careers.singaporeair.com/siaec) | Singapore anchor; ~11 active jobs, mostly trainees |
| ✅ 4 | ST Engineering Aerospace | SAP SuccessFactors J2W (same as GMR/SIA; `startrow=` pagination; pre-filter to Commercial Aerospace) | Singapore |
| 4 | SAESL | Rolls-Royce affiliate | Singapore Trent shop |
| ✅ 3 | Etihad Engineering | Oracle HCM Cloud Recruiting (not Taleo — confirmed via XHR) | Abu Dhabi MRO facility; curl_cffi, no Playwright |
| ❌ 5 | Joramco (Amman) | LinkedIn / Bayt.com only — no scrapeable career portal | Middle East — careers.joramco.com unreachable; joramco.talentera.com 404; careers.dubaiaerospace.com (parent) also unreachable. Monitor LinkedIn manually. |
| ✅ 5 | Saudia Technic | Talentera by Bayt.com (NOT Custom — AJAX via POST /app/control/byt_job_search_manager; USER_token from page HTML) | Middle East |
| ✅ 6 | Lufthansa Technik | Custom Lufthansa Group ATS (REST JSON API at api-apply.lufthansagroup.careers; no Playwright; one GET call for all 305 group jobs; filter locally by ParentOrganizationName) | Global chain |
| ✅ 6 | StandardAero | Oracle HCM Cloud (NOT Workday — standardaero.com/careers redirects directly to cva.fa.us1.oraclecloud.com; same API as Etihad but different data centre, site=CX_3, description in ExternalDescriptionStr) | US/Canada/Singapore |
| 6 | MTU Maintenance | Custom | Germany/Canada/Serbia |
| 6 | AFI KLM E&M | Custom French | Global chain |
