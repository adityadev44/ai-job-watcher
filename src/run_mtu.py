import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import mtu_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_mtu.json"
NEAR_MISS_PATH = ROOT / "near_misses_mtu.json"


def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(seen_path=None, near_miss_path=None):
    """Full MTU Maintenance pipeline: fetch → pre-filter → match → dedup → alert → persist."""
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()
    cfg = config.get("mtu_search", {})
    max_listings = cfg.get("max_listings", 300)
    inter_page_delay = cfg.get("inter_page_delay", 0.3)

    print("[mtu] ── MTU Maintenance pipeline starting ──")
    print(f"[mtu] Config: seen={seen_path.name}, near_misses={near_miss_path.name}")

    raw_jobs = mtu_fetcher.fetch_jobs(max_listings=max_listings, inter_page_delay=inter_page_delay)
    total_fetched = len(raw_jobs)

    # Pre-filter: MTU Maintenance subsidiaries only (excludes MTU Aero Engines manufacturing)
    maintenance_jobs = [j for j in raw_jobs if "MTU Maintenance" in j.get("company", "")]
    print(f"[mtu] {total_fetched} total → {len(maintenance_jobs)} MTU Maintenance jobs (pre-filter)")

    matched, near_misses = filter_jobs(maintenance_jobs, mtu_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g4_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate4")
    g1_pass = len(maintenance_jobs) - g1_fail
    g3_pass = g1_pass - g3_fail
    g4_pass = g3_pass - g4_fail
    total_matched = len(matched)

    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    alert_sent = False
    if new_matches:
        print(f"[mtu] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True
        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[mtu] No new matches — nothing to alert")

    if near_misses:
        existing = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing.extend(near_misses)
        _save_json(near_miss_path, existing)
        print(f"[mtu] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    print()
    print("[mtu] ── Run summary ──────────────────────────────")
    print(f"[mtu]  Total fetched     : {total_fetched}")
    print(f"[mtu]  MTU Maintenance   : {len(maintenance_jobs)}  (pre-filter)")
    print(f"[mtu]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[mtu]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[mtu]  Passed Gate 4     : {g4_pass}  (description exclusion clear)")
    print(f"[mtu]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[mtu]  New (not seen)    : {len(new_matches)}")
    print(f"[mtu]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[mtu] ────────────────────────────────────────────")

    return {
        "total_fetched": total_fetched,
        "maintenance_count": len(maintenance_jobs),
        "g1_pass": g1_pass,
        "g3_pass": g3_pass,
        "g4_pass": g4_pass,
        "total_matched": total_matched,
        "new_matches": new_matches,
        "near_misses": near_misses,
        "alert_sent": alert_sent,
    }


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"[mtu] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        raise
