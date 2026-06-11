import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import ste_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_ste.json"
NEAR_MISS_PATH = ROOT / "near_misses_ste.json"


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
    """
    Full ST Engineering Aerospace pipeline: fetch → filter → dedup → alert → persist.

    seen_path / near_miss_path let tests inject temp files without
    touching the real ones on disk.
    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()
    ste_cfg = config.get("ste_search", {})
    max_listings = ste_cfg.get("max_listings", 200)
    inter_page_delay = ste_cfg.get("inter_page_delay", 0.3)

    print("[ste] ── ST Engineering Aerospace pipeline starting ──")
    print(f"[ste] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    raw_jobs = ste_fetcher.fetch_jobs(max_listings=max_listings, inter_page_delay=inter_page_delay)

    # ST Engineering portal serves all divisions — keep only Commercial Aerospace.
    # Other divisions: Defence Aerospace, Group HQ, Urban Solutions, Marine, Land Systems, Digital Systems.
    raw_jobs = [j for j in raw_jobs if j.get("facility", "").lower() == "commercial aerospace"]
    total_fetched = len(raw_jobs)
    print(f"[ste] Fetched {total_fetched} unique listings (Commercial Aerospace only)")

    # ── 2. Filter through 3-gate matcher ─────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, ste_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g1_pass = total_fetched - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    # ── 3. Deduplicate against seen_jobs ──────────────────────────────────────
    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    # ── 4. Alert if new matches found ─────────────────────────────────────────
    alert_sent = False
    if new_matches:
        print(f"[ste] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[ste] No new matches — nothing to alert")

    # ── 5. Persist near-misses with timestamp ─────────────────────────────────
    if near_misses:
        existing_near_misses = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing_near_misses.extend(near_misses)
        _save_json(near_miss_path, existing_near_misses)
        print(f"[ste] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    # ── 6. Run summary ────────────────────────────────────────────────────────
    print()
    print("[ste] ── Run summary ──────────────────────────────")
    print(f"[ste]  Total fetched     : {total_fetched}")
    print(f"[ste]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[ste]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[ste]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[ste]  New (not seen)    : {len(new_matches)}")
    print(f"[ste]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[ste] ────────────────────────────────────────────")

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
        print(f"[ste] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        raise
