import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import dgca_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_dgca.json"
NEAR_MISS_PATH = ROOT / "near_misses_dgca.json"


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
    Full DGCA pipeline: fetch → filter → dedup → alert → persist.

    seen_path / near_miss_path let tests inject temp files without
    touching the real ones on disk.
    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()
    dgca_cfg = config.get("dgca_search", {})
    max_listings = dgca_cfg.get("max_listings", 50)

    print("[dgca] ── DGCA pipeline starting ──")
    print(f"[dgca] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    raw_jobs = dgca_fetcher.fetch_jobs(max_listings=max_listings)
    total_fetched = len(raw_jobs)
    print(f"[dgca] Fetched {total_fetched} vacancy circulars")

    # ── 2. Filter through gates ───────────────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, dgca_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g1_pass = total_fetched - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    # ── 3. Deduplicate against seen_jobs ──────────────────────────────────────
    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    # On first run: seed seen_urls with ALL fetched URLs to avoid bulk alert
    if not seen_urls and raw_jobs:
        print(f"[dgca] First run — seeding seen list with all {total_fetched} circulars (no alert)")
        all_urls = [j["url"] for j in raw_jobs]
        _save_json(seen_path, sorted(set(all_urls)))
        new_matches = []

    # ── 4. Alert if new matches found ─────────────────────────────────────────
    alert_sent = False
    if new_matches:
        print(f"[dgca] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        seen_urls = set(_load_json(seen_path))
        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[dgca] No new matches — nothing to alert")

    # ── 5. Persist near-misses with timestamp ─────────────────────────────────
    if near_misses:
        existing_near_misses = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing_near_misses.extend(near_misses)
        _save_json(near_miss_path, existing_near_misses)
        print(f"[dgca] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    # ── 6. Run summary ────────────────────────────────────────────────────────
    print()
    print("[dgca] ── Run summary ──────────────────────────────")
    print(f"[dgca]  Total fetched     : {total_fetched}")
    print(f"[dgca]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[dgca]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[dgca]  Passed Gate 2     : {total_matched}  (kept — Gate 2 bypassed for PDFs)")
    print(f"[dgca]  New (not seen)    : {len(new_matches)}")
    print(f"[dgca]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[dgca] ────────────────────────────────────────────")

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
        notifier.reset_failure_count("dgca")
    except Exception as exc:
        print(f"[dgca] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("dgca", exc)
