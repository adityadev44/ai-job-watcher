import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline_runner import PipelineSpec

from src import aar_fetcher
from src import acg_fetcher
from src import aercap_fetcher
from src import air_india_fetcher
from src import ammroc_fetcher
from src import avolon_fetcher
from src import boc_aviation_fetcher
from src import boeing_fetcher
from src import delta_fetcher
from src import dgca_fetcher
from src import elfc_fetcher
from src import emirates_fetcher
from src import ethiopian_fetcher
from src import etihad_fetcher
from src import fltechnics_fetcher
from src import gatelesis_fetcher
from src import ge_fetcher
from src import gmr_fetcher
from src import gulf_air_fetcher
from src import honeywell_fetcher
from src import icf_fetcher
from src import indigo_fetcher
from src import kuwait_airways_fetcher
from src import lht_fetcher
from src import magnetic_fetcher
from src import mtu_fetcher
from src import oliver_wyman_fetcher
from src import oman_air_fetcher
from src import qatar_fetcher
from src import rolls_royce_fetcher
from src import rtx_fetcher
from src import saesl_fetcher
from src import safran_fetcher
from src import sanad_fetcher
from src import saudia_technic_fetcher
from src import sia_fetcher
from src import smbc_aviation_fetcher
from src import standardaero_fetcher
from src import ste_fetcher
from src import wlfc_fetcher


def _title_has_any(job: dict, terms: list[str]) -> bool:
    title = str(job.get("title", "") or "").lower()
    return any(term in title for term in terms)


_AVIATION_TITLE_TERMS = [
    "engineer", "engineering",
    "aircraft", "engine", "powerplant",
    "maintenance", "airworthiness",
    "mro", "overhaul", "shop",
    "technical services", "technical manager",
    "quality", "safety", "compliance",
    "instructor", "ame", "dgca",
    "aviation", "propulsion",
]

_AEROSPACE_TITLE_TERMS = [
    "aerospace", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power",
    "overhaul", "mro", "maintenance", "airworthiness", "aviation",
    "avionics",
]

_FLTECHNICS_TITLE_TERMS = [
    "aerospace", "aircraft", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power", "overhaul", "mro", "maintenance",
    "airworthiness", "aviation", "avionics", "airframe", "inspector", "camo",
]

# Delta: Gate 2 is NOT bypassed (real descriptions are available) — this
# pre-filter exists purely to bound the number of expensive per-job
# Playwright renders fetch_job_description() needs (see delta_fetcher.py),
# not to compensate for a missing Gate 2 the way the lists above do.
_DELTA_TITLE_TERMS = [
    "aerospace", "aircraft", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power", "overhaul", "mro", "maintenance",
    "airworthiness", "aviation", "avionics", "techops", "tech ops",
]


def _aviation_title(job: dict) -> bool:
    return _title_has_any(job, _AVIATION_TITLE_TERMS)


def _aerospace_title(job: dict) -> bool:
    return _title_has_any(job, _AEROSPACE_TITLE_TERMS)


def _fltechnics_title(job: dict) -> bool:
    return _title_has_any(job, _FLTECHNICS_TITLE_TERMS)


def _delta_title(job: dict) -> bool:
    return _title_has_any(job, _DELTA_TITLE_TERMS)


def _ammroc_entity(job: dict) -> bool:
    return "ammroc" in str(job.get("entity", "") or "").lower()


def _ste_commercial_aerospace(job: dict) -> bool:
    return str(job.get("facility", "") or "").lower() == "commercial aerospace"


def _rtx_pratt(job: dict) -> bool:
    return "pratt" in str(job.get("company", "") or "").lower()


def _sanad_aerotech(job: dict) -> bool:
    return "capital" not in str(job.get("company", "") or "").lower()


def _oliver_wyman(job: dict) -> bool:
    title = str(job.get("title", "") or "").lower()
    company = str(job.get("company", "") or "").lower()
    return "oliver wyman" in title or "oliver wyman" in company


def _populate_company_from(fetcher):
    def _inner(job: dict) -> None:
        if not job.get("company"):
            job["company"] = fetcher.get_company(job.get("url", ""))
    return _inner


def _populate_delta(job: dict) -> None:
    # Delta's posting date isn't on the listing page — it's only known after
    # fetch_job_description() renders the detail page, so (unlike the other
    # populate_company hooks) this also backfills posting_date from the same
    # per-job cache. matcher.py discards fetch_job_description's own tuple
    # date return (see PLAYBOOK.md "Bugs We Hit"), so this hook is the only
    # path that gets a real date into the alert.
    if not job.get("company"):
        job["company"] = delta_fetcher.get_company(job.get("url", ""))
    posting_date = delta_fetcher.get_posting_date(job.get("url", ""))
    if posting_date:
        job["posting_date"] = posting_date


SPECS = {
    "aar": PipelineSpec("aar", "AAR Corp", aar_fetcher, "seen_jobs_aar.json", fetch_mode="config"),
    "acg": PipelineSpec("acg", "Aviation Capital Group", acg_fetcher, "seen_jobs_acg.json"),
    "aercap": PipelineSpec("aercap", "AerCap", aercap_fetcher, "seen_jobs_aercap.json"),
    "air_india": PipelineSpec("air_india", "Air India", air_india_fetcher, "seen_jobs_air_india.json", fetch_mode="search_params"),
    "ammroc": PipelineSpec(
        "ammroc",
        "AMMROC",
        ammroc_fetcher,
        "seen_jobs_ammroc.json",
        fetch_mode="search_params",
        pre_filter=_ammroc_entity,
        pre_filter_label="AMMROC entity pre-filter",
        pre_filter_pass_label="AMMROC entity",
    ),
    "avolon": PipelineSpec("avolon", "Avolon", avolon_fetcher, "seen_jobs_avolon.json"),
    "boc_aviation": PipelineSpec("boc_aviation", "BOC Aviation", boc_aviation_fetcher, "seen_jobs_boc_aviation.json"),
    "boeing": PipelineSpec(
        "boeing",
        "Boeing Global Services",
        boeing_fetcher,
        "seen_jobs_boeing.json",
        populate_company=_populate_company_from(boeing_fetcher),
    ),
    "delta": PipelineSpec(
        "delta",
        "Delta Air Lines TechOps",
        delta_fetcher,
        "seen_jobs_delta.json",
        fetch_mode="search_params",
        dedupe_key="id",
        pre_filter=_delta_title,
        pre_filter_label="Aviation title pre-filter",
        pre_filter_pass_label="Aviation titles",
        populate_company=_populate_delta,
    ),
    "dgca": PipelineSpec(
        "dgca",
        "DGCA India",
        dgca_fetcher,
        "seen_jobs_dgca.json",
        fetch_mode="search_params",
        seed_seen_on_first_run=True,
    ),
    "elfc": PipelineSpec("elfc", "Engine Lease Finance", elfc_fetcher, "seen_jobs_elfc.json"),
    "emirates": PipelineSpec("emirates", "Emirates Group", emirates_fetcher, "seen_jobs_emirates.json", fetch_mode="search_params"),
    "ethiopian": PipelineSpec("ethiopian", "Ethiopian Airlines", ethiopian_fetcher, "seen_jobs_ethiopian.json"),
    "etihad": PipelineSpec("etihad", "Etihad Engineering", etihad_fetcher, "seen_jobs_etihad.json"),
    "fltechnics": PipelineSpec(
        "fltechnics",
        "FL Technics",
        fltechnics_fetcher,
        "seen_jobs_fltechnics.json",
        pre_filter=_fltechnics_title,
        pre_filter_label="Aviation title pre-filter",
        pre_filter_pass_label="Aviation titles",
    ),
    "gatelesis": PipelineSpec("gatelesis", "GA Telesis", gatelesis_fetcher, "seen_jobs_gatelesis.json"),
    "ge": PipelineSpec("ge", "GE Aerospace", ge_fetcher, "seen_jobs_ge.json", fetch_mode="search_params"),
    "gmr": PipelineSpec("gmr", "GMR Aero Technic", gmr_fetcher, "seen_jobs_gmr.json", fetch_mode="search_params"),
    "gulf_air": PipelineSpec("gulf_air", "Gulf Air", gulf_air_fetcher, "seen_jobs_gulf_air.json", fetch_mode="search_params"),
    "honeywell": PipelineSpec(
        "honeywell",
        "Honeywell Aerospace",
        honeywell_fetcher,
        "seen_jobs_honeywell.json",
        fetch_mode="config",
        pre_filter=_aerospace_title,
        pre_filter_label="Aerospace title pre-filter",
        pre_filter_pass_label="Aerospace titles",
    ),
    "icf": PipelineSpec("icf", "ICF", icf_fetcher, "seen_jobs_icf.json"),
    "indigo": PipelineSpec(
        "indigo",
        "IndiGo",
        indigo_fetcher,
        "seen_jobs_indigo.json",
        dedupe_key="id",
        pre_filter=_aviation_title,
        pre_filter_label="Aviation title pre-filter",
        pre_filter_pass_label="Aviation pre-filter",
        log_pre_filter_skips=True,
        total_note="page 1 of ~3; pagination unavailable",
        matched_label="Matched",
        matched_note="kept; no description gate - see fetcher",
    ),
    "kuwait_airways": PipelineSpec("kuwait_airways", "Kuwait Airways", kuwait_airways_fetcher, "seen_jobs_kuwait_airways.json", fetch_mode="search_params"),
    "lht": PipelineSpec("lht", "Lufthansa Technik", lht_fetcher, "seen_jobs_lht.json", fetch_mode="search_params"),
    "magnetic": PipelineSpec("magnetic", "Magnetic MRO", magnetic_fetcher, "seen_jobs_magnetic.json"),
    "mtu": PipelineSpec("mtu", "MTU Maintenance", mtu_fetcher, "seen_jobs_mtu.json"),
    "oliver_wyman": PipelineSpec(
        "oliver_wyman",
        "Oliver Wyman / CAVOK",
        oliver_wyman_fetcher,
        "seen_jobs_oliver_wyman.json",
        pre_filter=_oliver_wyman,
        pre_filter_label="Oliver Wyman brand pre-filter",
        pre_filter_pass_label="Oliver Wyman jobs",
    ),
    "oman_air": PipelineSpec("oman_air", "Oman Air", oman_air_fetcher, "seen_jobs_oman_air.json", fetch_mode="search_params"),
    "qatar": PipelineSpec("qatar", "Qatar Airways", qatar_fetcher, "seen_jobs_qatar.json", fetch_mode="search_params"),
    "rolls_royce": PipelineSpec(
        "rolls_royce",
        "Rolls-Royce Civil Aerospace",
        rolls_royce_fetcher,
        "seen_jobs_rolls_royce.json",
        dedupe_key="id",
    ),
    "rtx": PipelineSpec(
        "rtx",
        "RTX / Pratt & Whitney",
        rtx_fetcher,
        "seen_jobs_rtx.json",
        pre_filter=_rtx_pratt,
        pre_filter_label="Pratt & Whitney pre-filter",
        pre_filter_pass_label="P&W jobs",
    ),
    "saesl": PipelineSpec("saesl", "SAESL", saesl_fetcher, "seen_jobs_saesl.json", fetch_mode="search_params"),
    "safran": PipelineSpec(
        "safran",
        "Safran",
        safran_fetcher,
        "seen_jobs_safran.json",
        populate_company=_populate_company_from(safran_fetcher),
    ),
    "sanad": PipelineSpec(
        "sanad",
        "Sanad",
        sanad_fetcher,
        "seen_jobs_sanad.json",
        fetch_mode="search_params",
        pre_filter=_sanad_aerotech,
        pre_filter_label="Sanad Aerotech pre-filter",
        pre_filter_pass_label="Aerotech jobs",
    ),
    "saudia_technic": PipelineSpec("saudia_technic", "Saudia Technic", saudia_technic_fetcher, "seen_jobs_saudia_technic.json", fetch_mode="search_params"),
    "sia": PipelineSpec("sia", "SIA Engineering", sia_fetcher, "seen_jobs_sia.json", fetch_mode="search_params"),
    "smbc_aviation": PipelineSpec("smbc_aviation", "SMBC Aviation Capital", smbc_aviation_fetcher, "seen_jobs_smbc_aviation.json", fetch_mode="config"),
    "standardaero": PipelineSpec("standardaero", "StandardAero", standardaero_fetcher, "seen_jobs_standardaero.json", fetch_mode="search_params"),
    "ste": PipelineSpec(
        "ste",
        "ST Engineering Aerospace",
        ste_fetcher,
        "seen_jobs_ste.json",
        fetch_mode="search_params",
        pre_filter=_ste_commercial_aerospace,
        pre_filter_label="Commercial Aerospace pre-filter",
        pre_filter_pass_label="Commercial Aero",
    ),
    "wlfc": PipelineSpec("wlfc", "Willis Lease Finance", wlfc_fetcher, "seen_jobs_wlfc.json"),
}


def get_spec(source: str) -> PipelineSpec:
    return SPECS[source]
