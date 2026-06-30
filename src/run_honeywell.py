import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import honeywell_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_honeywell.json"
NEAR_MISS_PATH = ROOT / "near_misses_honeywell.json"

# Honeywell has many non-aerospace divisions (HBS = Building Solutions,
# PMT = Performance Materials, SPS = Safety & Productivity, UOP = Process
# Technologies). Gate 2 is bypassed (descriptions unavailable), so without
# this pre-filter all Gate-1+3-passing Honeywell jobs alert — including
# "HBS Projects General Manager" and "Sr Product Manager Building Automation".
# Require at least one aerospace-domain term in the title before handing off.
_AEROSPACE_TITLE_TERMS = [
    "aerospace", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power",
    "overhaul", "mro", "maintenance", "airworthiness", "aviation",
    "avionics",
]


def _is_aerospace_title(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in _AEROSPACE_TITLE_TERMS)


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def _load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as _e:
            print(f"[WARNING] {path.name}: JSON parse error ({_e}) — returning empty list (check for file corruption)")
            return []


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(seen_path=None, near_miss_path=None):
    """
    Full Honeywell Aerospace pipeline: fetch → filter → dedup → alert → persist.

    Honeywell uses Phenom People at careers.honeywell.com. All Honeywell jobs are
    fetched; Gate 1-4 filters downstream to aerospace MRO / engine-specific roles.

    seen_path / near_miss_path let tests inject temp files without
    touching the real ones on disk.
    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()

    print("[honeywell] ── Honeywell Aerospace pipeline starting ──")
    print(f"[honeywell] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    # ── 1. Fetch ─────────────────────────────────────────────────────────────
    raw_jobs = honeywell_fetcher.fetch_jobs(config=config)
    total_fetched = len(raw_jobs)
    print(f"[honeywell] Fetched {total_fetched} unique listings")

    # ── 1.5. Aerospace title pre-filter ─────────────────────────────────────
    # Gate 2 is bypassed for Honeywell (descriptions unavailable), so without
    # this step ALL Gate-1+3-passing jobs alert — including HBS / PMT / SPS
    # business-unit managers that are unrelated to Aerospace.
    aerospace_jobs = [j for j in raw_jobs if _is_aerospace_title(j["title"])]
    pre_filter_dropped = total_fetched - len(aerospace_jobs)
    if pre_filter_dropped:
        print(f"[honeywell] Pre-filter: dropped {pre_filter_dropped} non-aerospace title(s)")

    # ── 2. Filter through 4-gate matcher ────────────────────────────────────
    matched, near_misses = filter_jobs(aerospace_jobs, honeywell_fetcher, config=config)

    # Derive gate-pass counts from near_misses for the summary
    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g1_pass = len(aerospace_jobs) - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    # ── 3. Deduplicate against seen_jobs ────────────────────────────────────
    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    # ── 4. Alert if new matches found ───────────────────────────────────────
    alert_sent = False
    if new_matches:
        print(f"[honeywell] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[honeywell] No new matches — nothing to alert")

    # ── 5. Persist near-misses with timestamp ───────────────────────────────
    if near_misses:
        existing_near_misses = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing_near_misses.extend(near_misses)
        _save_json(near_miss_path, existing_near_misses)
        print(f"[honeywell] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    # ── 6. Run summary ───────────────────────────────────────────────────────
    print()
    print("[honeywell] ── Run summary ──────────────────────────────")
    print(f"[honeywell]  Total fetched     : {total_fetched}")
    print(f"[honeywell]  Aerospace titles  : {len(aerospace_jobs)}  (pre-filter: {pre_filter_dropped} non-aerospace dropped)")
    print(f"[honeywell]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[honeywell]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[honeywell]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[honeywell]  New (not seen)    : {len(new_matches)}")
    print(f"[honeywell]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[honeywell] ────────────────────────────────────────────")

    return {
        "total_fetched": total_fetched,
        "pre_filter_dropped": pre_filter_dropped,
        "g1_pass": g1_pass,
        "g3_pass": g3_pass,
        "total_matched": total_matched,
        "new_matches": new_matches,
        "near_misses": near_misses,
        "alert_sent": alert_sent,
    }


if __name__ == "__main__":
    try:
        run_pipeline()
        notifier.reset_failure_count("honeywell")
    except Exception as exc:
        print(f"[honeywell] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("honeywell", exc)
