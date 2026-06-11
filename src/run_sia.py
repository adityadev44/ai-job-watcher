import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import sia_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_sia.json"
NEAR_MISS_PATH = ROOT / "near_misses_sia.json"


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
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()
    sia_cfg = config.get("sia_search", {})
    max_listings = sia_cfg.get("max_listings", 200)
    inter_page_delay = sia_cfg.get("inter_page_delay", 0.3)

    print("[sia] ── SIA Engineering pipeline starting ──")
    print(f"[sia] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    raw_jobs = sia_fetcher.fetch_jobs(max_listings=max_listings, inter_page_delay=inter_page_delay)
    total_fetched = len(raw_jobs)
    print(f"[sia] Fetched {total_fetched} unique listings")

    matched, near_misses = filter_jobs(raw_jobs, sia_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g1_pass = total_fetched - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    alert_sent = False
    if new_matches:
        print(f"[sia] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[sia] No new matches — nothing to alert")

    if near_misses:
        existing = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing.extend(near_misses)
        _save_json(near_miss_path, existing)
        print(f"[sia] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    print()
    print("[sia] ── Run summary ──────────────────────────────")
    print(f"[sia]  Total fetched     : {total_fetched}")
    print(f"[sia]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[sia]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[sia]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[sia]  New (not seen)    : {len(new_matches)}")
    print(f"[sia]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[sia] ────────────────────────────────────────────")

    return {
        "total_fetched": total_fetched,
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
    except Exception as exc:
        print(f"[sia] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        raise
