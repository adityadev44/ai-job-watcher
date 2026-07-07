import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline_registry import SPECS
from src.run_all import PIPELINES


def test_run_all_and_registry_have_same_sources():
    assert sorted(PIPELINES) == sorted(SPECS)


def test_every_registered_source_has_seen_file_and_dedupe_key():
    for source, spec in SPECS.items():
        assert spec.source == source
        assert spec.seen_filename == f"seen_jobs_{source}.json"
        assert spec.dedupe_key in {"url", "id"}


def test_known_id_dedupe_sources_are_explicit():
    assert SPECS["indigo"].dedupe_key == "id"
    assert SPECS["rolls_royce"].dedupe_key == "id"


def test_fltechnics_pre_filter_keeps_camo_titles():
    # Regression: a copy/paste of the Honeywell term list once dropped "camo"
    # from FL Technics' pre-filter, silently hiding CAMO roles from Gate 1-4.
    pre_filter = SPECS["fltechnics"].pre_filter
    assert pre_filter({"title": "CAMO Engineer"}) is True
    assert pre_filter({"title": "Head of Legal"}) is False


def test_honeywell_pre_filter_keeps_aerospace_titles():
    pre_filter = SPECS["honeywell"].pre_filter
    assert pre_filter({"title": "Aerospace Engine Overhaul Manager"}) is True
    assert pre_filter({"title": "HBS Projects General Manager"}) is False


def test_indigo_pre_filter_keeps_aviation_titles():
    pre_filter = SPECS["indigo"].pre_filter
    assert pre_filter({"title": "Aircraft Maintenance Engineer"}) is True
    assert pre_filter({"title": "Finance Manager"}) is False


def test_ammroc_pre_filter_matches_entity_field():
    pre_filter = SPECS["ammroc"].pre_filter
    assert pre_filter({"entity": "AMMROC"}) is True
    assert pre_filter({"entity": "POWERTECH"}) is False


def test_ste_pre_filter_matches_commercial_aerospace_only():
    pre_filter = SPECS["ste"].pre_filter
    assert pre_filter({"facility": "Commercial Aerospace"}) is True
    assert pre_filter({"facility": "Defence Aerospace"}) is False


def test_sanad_pre_filter_excludes_capital_division():
    pre_filter = SPECS["sanad"].pre_filter
    assert pre_filter({"company": "Sanad Aerotech"}) is True
    assert pre_filter({"company": "Sanad Capital"}) is False


def test_rtx_pre_filter_keeps_pratt_whitney_only():
    pre_filter = SPECS["rtx"].pre_filter
    assert pre_filter({"company": "Pratt & Whitney"}) is True
    assert pre_filter({"company": "Collins Aerospace"}) is False


def test_oliver_wyman_pre_filter_matches_brand():
    pre_filter = SPECS["oliver_wyman"].pre_filter
    assert pre_filter({"title": "Oliver Wyman - Principal, Aviation", "company": ""}) is True
    assert pre_filter({"title": "Actuarial Analyst", "company": "Mercer"}) is False


def test_delta_pre_filter_keeps_engine_mro_titles():
    # Delta's Gate 2 is NOT bypassed (real descriptions available) — this
    # pre-filter exists only to bound expensive per-job Playwright renders,
    # not to compensate for a missing gate. Still must not silently narrow
    # what Gate 1-4 would otherwise catch.
    pre_filter = SPECS["delta"].pre_filter
    assert pre_filter({"title": "Manager, Engine Overhaul Shop"}) is True
    assert pre_filter({"title": "Director, TechOps Line Maintenance"}) is True
    assert pre_filter({"title": "Senior Manager, Finance"}) is False


def test_delta_dedupe_key_is_id():
    # Job detail URLs embed a title-derived slug that can drift if a
    # requisition's title is edited — dedupe on the stable numeric jobId
    # instead, same reasoning as Rolls-Royce and IndiGo.
    assert SPECS["delta"].dedupe_key == "id"
