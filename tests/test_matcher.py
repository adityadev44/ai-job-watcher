import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pytest
from unittest.mock import MagicMock

# Minimal config that mirrors config.yaml — tests never touch the filesystem
CONFIG = {
    "matching": {
        "title_family": [
            "manager", "head", "director", "lead", "chief", "consultant",
            "advisor", "compliance", "powerplant",
            "engine", "engines", "mro", "shop", "technical services",
            "instructor", "overhaul",
        ],
        "exclude_terms": [
            "technician", "apprentice", "trainee", "intern", "fresher",
            "graduate", "new grad", "software", "it", "avionics",
            "cabin", "pilot", "finance", "sales", "structures", "airframe",
            "hr", "human resources", "coordinator", "mechanic", "inspector",
            "talent acquisition", "warehousing", "asset management", "dnata",
        ],
        "engine_specific_terms": [
            "ge90", "genx", "pw4000", "cf6", "cfm56", "leap", "gtf",
            "pw1100", "trent", "v2500", "engine overhaul", "test cell",
            "borescope", "part 145", "car 145", "crs", "shop visit",
            "workscope",
        ],
        "domain_terms": [
            "maintenance", "repair", "overhaul", "powerplant", "propulsion",
            "airworthiness", "easa", "faa", "dgca", "gcaa", "gaca",
            "aviation", "aerospace", "aircraft", "airline", "ame", "amo",
            "mro", "sms", "human factors",
        ],
    }
}


def make_fetcher(description=""):
    """Build a mock fetcher with a configurable description return value."""
    fetcher = MagicMock()
    fetcher.fetch_job_description.return_value = description

    class RateLimitError(Exception):
        pass

    fetcher.RateLimitError = RateLimitError
    return fetcher


def run(jobs, description=""):
    from src.matcher import filter_jobs
    fetcher = make_fetcher(description)
    return filter_jobs(jobs, fetcher, config=CONFIG)


# ---------------------------------------------------------------------------
# Test 1: full pass — all 3 gates pass
# ---------------------------------------------------------------------------
def test_full_pass():
    jobs = [{"title": "Engine Overhaul Manager", "url": "http://x", "location": "Dubai"}]
    desc = "GE90 engine overhaul, Part 145 compliance, MRO shop visit management"
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1, "Expected job to pass all 3 gates"
    assert len(near_misses) == 0


# ---------------------------------------------------------------------------
# Test 2: Gate 2 failure — description has no engine-specific term
# ---------------------------------------------------------------------------
def test_gate2_fail_no_engine_specific():
    jobs = [{"title": "Engine Overhaul Manager", "url": "http://x", "location": "Dubai"}]
    # "aviation safety" gives 1 domain hit and 0 engine-specific hits
    desc = "We are looking for a professional with deep aviation safety experience." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 0
    assert len(near_misses) == 1
    assert near_misses[0]["gate_failed"] == "gate2"


# ---------------------------------------------------------------------------
# Test 3: Gate 3 failure — title contains "technician"
# ---------------------------------------------------------------------------
def test_gate3_fail_excluded_term():
    jobs = [{"title": "MRO Technician", "url": "http://x", "location": "London"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert len(near_misses) == 1
    assert near_misses[0]["gate_failed"] == "gate3"


# ---------------------------------------------------------------------------
# Test 4: Gate 1 failure — "IT Manager" contains "it " (with space) which is
# an exclude term, but the key thing is that "it" alone doesn't match title family
# ---------------------------------------------------------------------------
def test_gate1_fail_it_manager():
    # "IT Manager" — "it " (with trailing space) is in exclude_terms, so it would
    # fail Gate 3 if Gate 1 passes. But "manager" IS in title_family so Gate 1 passes,
    # then Gate 3 catches "it " (the "IT " prefix contains "it ").
    # The test requirement says it fails Gate 1 because there's no title family match —
    # but "manager" is in title_family. Let's re-read the spec:
    # "A job with 'IT Manager' title fails Gate 1 (no title family match — note 'it '
    # with trailing space avoids matching 'quality' etc.)"
    # The spec says Gate 1 fails. But "manager" is in title_family. This seems like
    # the spec intends "IT Manager" to be caught BEFORE Gate 1 would pass on "manager"...
    # Actually re-reading: the note about "it " says it avoids FALSELY matching
    # terms like "quality". The spec says Gate 1 fails. The only way that happens
    # is if "manager" is NOT in the title — but "IT Manager" has "manager".
    #
    # Most likely interpretation: the spec means Gate 3 catches it (exclude "it "),
    # but labels it Gate 1 informally. Let's test what actually makes sense:
    # "IT Manager" → Gate 1 passes (has "manager") → Gate 3 catches "it " → near-miss gate3.
    # We'll assert the job is NOT matched and is in near_misses (gate3).
    jobs = [{"title": "IT Manager", "url": "http://x", "location": "NYC"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0, "IT Manager should be filtered out"
    assert len(near_misses) == 1
    # "it " (with trailing space) is in exclude_terms; "IT Manager" -> "it manager" -> "it " matches
    assert near_misses[0]["gate_failed"] == "gate3"


# ---------------------------------------------------------------------------
# Test 5: kept-on-empty-fetch — description empty => job is kept
# ---------------------------------------------------------------------------
def test_kept_on_empty_fetch():
    jobs = [{"title": "MRO Production Manager", "url": "http://x", "location": "Singapore"}]
    # Empty description triggers the kept-unconditionally rule
    matched, near_misses = run(jobs, description="")
    assert len(matched) == 1, "Job with empty description should be kept unconditionally"
    assert len(near_misses) == 0


# ---------------------------------------------------------------------------
# Test 6: Gate 1 passes on any one of shop / production / lead
# ---------------------------------------------------------------------------
def test_gate1_multiple_title_family_hits():
    jobs = [{"title": "Senior Engine Shop Production Lead", "url": "http://x", "location": "Abu Dhabi"}]
    desc = "GE90 engine overhaul specialist. Part 145 MRO facility. Maintenance and repair." * 3
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1, "Senior Engine Shop Production Lead should pass all gates"


# ---------------------------------------------------------------------------
# Test 7: build_weekly_digest returns non-empty string with both titles
# ---------------------------------------------------------------------------
def test_build_weekly_digest():
    from src.matcher import build_weekly_digest
    near_misses = [
        {"title": "MRO Technician", "location": "London", "url": "http://a", "gate_failed": "gate3", "reason": "excluded term 'technician'"},
        {"title": "Engine Shop Intern", "location": "Dubai", "url": "http://b", "gate_failed": "gate3", "reason": "excluded term 'intern'"},
    ]
    digest = build_weekly_digest(near_misses)
    assert digest, "Digest must be non-empty"
    assert "MRO Technician" in digest
    assert "Engine Shop Intern" in digest


# ---------------------------------------------------------------------------
# Word-boundary matching tests (fixes for precision false-positives)
# ---------------------------------------------------------------------------

def test_gate1_engineer_not_engine():
    """'engine' word-boundary must NOT match 'engineer'."""
    jobs = [{"title": "Senior Systems Engineer", "url": "http://x", "location": "NYC"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate1"


def test_gate1_engineering_not_engine():
    """'engine' word-boundary must NOT match 'engineering'."""
    jobs = [{"title": "Software Engineering Specialist", "url": "http://x", "location": "NYC"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate1"


def test_gate1_leader_not_lead():
    """'lead' word-boundary must NOT match 'leader'."""
    jobs = [{"title": "Manufacturing Programs Leader", "url": "http://x", "location": "NYC"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate1"


def test_gate1_engine_standalone_passes():
    """'engine' as a standalone word in the title must still pass Gate 1."""
    jobs = [{"title": "Jet Engine Overhaul Specialist", "url": "http://x", "location": "Dubai"}]
    desc = "GE90 engine overhaul, Part 145 compliance, shop visit management." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1


def test_gate1_quality_removed_engineer_filtered():
    """'quality' removed from title_family + 'engine' word-boundary: 'Quality Engineer' must fail Gate 1."""
    jobs = [{"title": "Quality Engineer", "url": "http://x", "location": "Delhi"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate1"


def test_gate1_quality_manager_still_passes():
    """'Quality Manager' must still pass via 'manager' even after 'quality' is removed from title_family."""
    jobs = [{"title": "Quality Manager", "url": "http://x", "location": "Dubai"}]
    desc = "GE90 engine overhaul, Part 145. Maintenance and repair." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1


def test_gate3_hr_excluded():
    """'hr' word-boundary must filter 'Lead HR Business Partner' at Gate 3."""
    jobs = [{"title": "Lead HR Business Partner", "url": "http://x", "location": "Dubai"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_hr_not_falsely_triggered():
    """'hr' word-boundary must NOT filter 'Shop Manager' (no standalone 'hr' in title)."""
    jobs = [{"title": "Shop Manager", "url": "http://x", "location": "Dubai"}]
    desc = "GE90 engine overhaul, Part 145 compliance, shop visit." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1


def test_gate3_mechanic_excluded():
    """'mechanic' in exclude must filter 'Lead Aircraft Mechanic' at Gate 3."""
    jobs = [{"title": "Lead Aircraft Mechanic", "url": "http://x", "location": "Dubai"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_coordinator_excluded():
    """'coordinator' in exclude must filter 'MRO Coordinator' at Gate 3."""
    jobs = [{"title": "MRO Coordinator", "url": "http://x", "location": "Dubai"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_talent_acquisition_excluded():
    """'talent acquisition' in exclude must filter HR recruiting titles at Gate 3."""
    jobs = [{"title": "Senior Manager HR Talent Acquisition", "url": "http://x", "location": "Singapore"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_warehousing_excluded():
    """'warehousing' in exclude must filter warehouse management titles at Gate 3."""
    jobs = [{"title": "Manager Warehousing", "url": "http://x", "location": "Dubai"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_asset_management_excluded():
    """'asset management' in exclude must filter engine leasing/finance titles at Gate 3."""
    jobs = [{"title": "Manager - Asset Management", "url": "http://x", "location": "Abu Dhabi"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_dnata_excluded():
    """'dnata' in exclude must filter Emirates Group ground handling roles at Gate 3."""
    jobs = [{"title": "General Manager, dnata Erbil", "url": "http://x", "location": "Iraq"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate3_it_manager_word_boundary():
    """'it' word-boundary must filter 'IT Manager' at Gate 3 but not 'quality' (contains 'it' inside word)."""
    jobs = [{"title": "IT Manager", "url": "http://x", "location": "NYC"}]
    matched, near_misses = run(jobs)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate3"


def test_gate2_mro_moved_to_domain():
    """MRO moved to domain_terms: a description with only 'MRO aviation maintenance' fails Gate 2
    because engine_specific_terms requires at least one hit (engine model, Part 145, etc.)."""
    jobs = [{"title": "Shop Manager", "url": "http://x", "location": "Dubai"}]
    # Only domain hits — no engine_specific hit (no Part 145, no engine model, no overhaul terms)
    desc = "MRO operations in our aviation maintenance facility. Aerospace compliance required." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate2"


def test_gate2_mro_plus_part145_passes():
    """MRO in domain + Part 145 in engine_specific: should still pass Gate 2."""
    jobs = [{"title": "Shop Manager", "url": "http://x", "location": "Dubai"}]
    desc = "MRO operations. Part 145 approved facility. Aircraft maintenance." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1


def test_gate1_engines_plural_passes():
    """'engines' (plural) as a standalone word must pass Gate 1."""
    jobs = [{"title": "Specialist, Strategic Procurement, Engines Materials and USM", "url": "http://x", "location": "Abu Dhabi"}]
    desc = "GE90 engine overhaul, Part 145. Maintenance and repair." * 5
    matched, near_misses = run(jobs, desc)
    assert len(matched) == 1


def test_gate1_engine_does_not_match_engines():
    """'engine' (singular) word-boundary must NOT match 'engines' (plural)."""
    # Without "engines" in title_family, "engines" in a title would fail Gate 1.
    # This test validates the word-boundary: \bengine\b does not match "engines".
    config_no_engines = {
        "matching": {
            "title_family": ["engine"],   # only singular
            "exclude_terms": [],
            "engine_specific_terms": ["part 145"],
            "domain_terms": ["maintenance"],
        }
    }
    from src.matcher import filter_jobs
    fetcher = make_fetcher("Part 145 engine overhaul. Maintenance and repair." * 5)
    jobs = [{"title": "Engines Materials Specialist", "url": "http://x", "location": "Abu Dhabi"}]
    matched, near_misses = filter_jobs(jobs, fetcher, config=config_no_engines)
    assert len(matched) == 0
    assert near_misses[0]["gate_failed"] == "gate1"
