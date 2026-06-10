import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Minimal HTML fixtures — represent real Safran portal structure
# ---------------------------------------------------------------------------

SEARCH_PAGE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Safran - Job openings</title></head>
<body>
<div class="ts-ol-pagination__title resultat">
  Number of results
  <span class="gras" id="ctl00_ctl00_corpsRoot_corps_Pagination_TotalOffers">42 job opening(s)</span>
</div>
<ul>
  <li class="ts-offer-list-item offerlist-item" title="">
    <h3 class="ts-offer-list-item__title styleh3">
      <a class="ts-offer-list-item__title-link" href="/job/job-engine-overhaul-manager_100001.aspx"
         title="Engine Overhaul Manager (Ref. : 2026-100001)">
        Engine Overhaul Manager
      </a>
    </h3>
    <ul class="ts-offer-list-item__description">
      <li>Ref. : 2026-100001</li>
      <li>6/10/2026</li>
      <li>Permanent</li>
      <li class="noBorder">Hyderabad, India</li>
    </ul>
  </li>
  <li class="ts-offer-list-item offerlist-item" title="">
    <h3 class="ts-offer-list-item__title styleh3">
      <a class="ts-offer-list-item__title-link" href="/job/job-mro-production-director_100002.aspx"
         title="MRO Production Director (Ref. : 2026-100002)">
        MRO Production Director
      </a>
    </h3>
    <ul class="ts-offer-list-item__description">
      <li>Ref. : 2026-100002</li>
      <li>6/9/2026</li>
      <li>Permanent</li>
      <li class="noBorder">Singapore</li>
    </ul>
  </li>
  <li class="ts-offer-list-item offerlist-item" title="">
    <h3 class="ts-offer-list-item__title styleh3">
      <a class="ts-offer-list-item__title-link" href="/job/job-quality-team-leader_100003.aspx"
         title="Quality Team Leader (Ref. : 2026-100003)">
        Quality Team Leader
      </a>
    </h3>
    <ul class="ts-offer-list-item__description">
      <li>Ref. : 2026-100003</li>
      <li>6/8/2026</li>
      <li>Permanent</li>
      <li class="noBorder">Brussels, Belgium</li>
    </ul>
  </li>
</ul>
</body>
</html>
"""

DETAIL_PAGE_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>Safran - Engine Overhaul Manager</title>
  <meta name="Description"
        content="Job Safran Aircraft Engines Services India of 'Engine Overhaul Manager'.
                 Location: Hyderabad, India. Date: 6/10/2026. Ref.: 2026-100001." />
</head>
<body>
<div id="contenu-ficheoffre">
  <h2>General information</h2>
  <p>Safran Aircraft Engines Services India (SAESI) MRO facility.</p>
  <h2 class="JobDescription">Job details</h2>
  <p id="fldjobdescription_description1">
    Oversee GE90 and CFM56 engine overhaul shop. Responsible for Part 145 compliance,
    workscope planning and shop visit management. Coordinate with MRO quality team on
    airworthiness and EASA regulations. Ensure FAA and DGCA alignment for all maintenance
    activities. Manage borescope inspection scheduling and test cell operations.
  </p>
  <p id="fldjobdescription_description2">
    10+ years in aviation MRO management required. SMS and human factors experience preferred.
  </p>
</div>
</body>
</html>
"""

EMPTY_RESULTS_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Safran - Job openings</title></head>
<body>
<div class="ts-ol-pagination__title resultat">
  Number of results
  <span class="gras" id="ctl00_ctl00_corpsRoot_corps_Pagination_TotalOffers">0 job opening(s)</span>
</div>
<ul></ul>
</body>
</html>
"""


def _mock_response(html, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Tests for _parse_list_page
# ---------------------------------------------------------------------------

def test_parse_list_page_returns_correct_count():
    from src.safran_fetcher import _parse_list_page
    jobs = _parse_list_page(SEARCH_PAGE_HTML)
    assert len(jobs) == 3


def test_parse_list_page_fields():
    from src.safran_fetcher import _parse_list_page
    jobs = _parse_list_page(SEARCH_PAGE_HTML)
    j = jobs[0]
    assert j["title"] == "Engine Overhaul Manager"
    assert j["url"] == "https://careers.safran-group.com/job/job-engine-overhaul-manager_100001.aspx"
    assert j["date"] == "6/10/2026"
    assert j["location"] == "Hyderabad, India"
    assert j["contract"] == "Permanent"
    assert j["source"] == "safran"


def test_parse_list_page_empty():
    from src.safran_fetcher import _parse_list_page
    jobs = _parse_list_page(EMPTY_RESULTS_HTML)
    assert jobs == []


def test_parse_list_page_all_locations():
    from src.safran_fetcher import _parse_list_page
    jobs = _parse_list_page(SEARCH_PAGE_HTML)
    locations = [j["location"] for j in jobs]
    assert "Hyderabad, India" in locations
    assert "Singapore" in locations
    assert "Brussels, Belgium" in locations


# ---------------------------------------------------------------------------
# Tests for _total_pages
# ---------------------------------------------------------------------------

def test_total_pages_calculation():
    from src.safran_fetcher import _total_pages
    # 42 results / 20 per page = 3 pages (ceil)
    assert _total_pages(SEARCH_PAGE_HTML) == 3


def test_total_pages_zero():
    from src.safran_fetcher import _total_pages
    assert _total_pages(EMPTY_RESULTS_HTML) == 1


# ---------------------------------------------------------------------------
# Tests for fetch_job_description
# ---------------------------------------------------------------------------

def test_fetch_job_description_returns_text():
    from src.safran_fetcher import fetch_job_description
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.return_value = _mock_response(DETAIL_PAGE_HTML)
        desc = fetch_job_description("https://careers.safran-group.com/job/job-engine-overhaul-manager_100001.aspx")
    assert "GE90" in desc
    assert "Part 145" in desc
    assert "SAESI" in desc or "Safran Aircraft Engines Services India" in desc


def test_fetch_job_description_fallback_on_error():
    from src.safran_fetcher import fetch_job_description
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.side_effect = Exception("connection timeout")
        desc = fetch_job_description("https://careers.safran-group.com/job/job-bad_999.aspx")
    assert desc == ""


def test_fetch_job_description_appends_lcid():
    """URL without LCID param should get LCID appended before request."""
    from src.safran_fetcher import fetch_job_description
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.return_value = _mock_response(DETAIL_PAGE_HTML)
        fetch_job_description("https://careers.safran-group.com/job/job-engine-overhaul-manager_100001.aspx")
    called_url = mock_get.call_args[0][0]
    assert "LCID=1033" in called_url


# ---------------------------------------------------------------------------
# Tests for fetch_jobs (mocked HTTP)
# ---------------------------------------------------------------------------

def test_fetch_jobs_deduplicates():
    """Same URL from two different keyword searches must appear only once."""
    from src.safran_fetcher import fetch_jobs, SEARCH_KEYWORDS
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.return_value = _mock_response(SEARCH_PAGE_HTML)
        jobs = fetch_jobs()
    urls = [j["url"] for j in jobs]
    assert len(urls) == len(set(urls)), "Duplicate URLs found in results"


def test_fetch_jobs_stops_on_empty_page():
    """When a page returns no items, pagination stops for that keyword."""
    from src.safran_fetcher import fetch_jobs
    responses = [
        _mock_response(SEARCH_PAGE_HTML),   # page 1: 3 items
        _mock_response(EMPTY_RESULTS_HTML), # page 2: 0 items -> stop
    ]
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.side_effect = responses * 20  # enough for all keywords
        with patch("src.safran_fetcher.time") as mock_time:
            mock_time.sleep = MagicMock()
            jobs = fetch_jobs()
    # Should have 3 unique jobs (SEARCH_PAGE_HTML always returns the same 3 URLs)
    assert len(jobs) == 3


def test_fetch_jobs_rate_limit_propagates():
    """RateLimitError from _get must propagate out of fetch_jobs."""
    from src.safran_fetcher import fetch_jobs, RateLimitError
    with patch("src.safran_fetcher._get") as mock_get:
        mock_get.side_effect = RateLimitError("too many requests")
        with pytest.raises(RateLimitError):
            fetch_jobs()


# ---------------------------------------------------------------------------
# Integration: fetch_jobs + matcher (no live API)
# ---------------------------------------------------------------------------

def test_matcher_accepts_safran_fetcher_interface():
    """
    Verify safran_fetcher exports the exact interface contract expected by matcher.
    """
    import src.safran_fetcher as sf
    assert callable(sf.fetch_jobs)
    assert callable(sf.fetch_job_description)
    assert issubclass(sf.RateLimitError, Exception)
