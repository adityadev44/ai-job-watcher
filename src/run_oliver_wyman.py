import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import oliver_wyman_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_oliver_wyman.json"
NEAR_MISS_PATH = ROOT / "near_misses_oliver_wyman.json"


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


def _is_oliver_wyman_job(job: dict) -> bool:
    """
    Return True if this job belongs to Oliver Wyman (not Marsh, Mercer, or Guy Carpenter).

    The MAMCGLOBAL portal mixes all Marsh McLennan Companies brands. Oliver Wyman job titles
    consistently include "Oliver Wyman" as a prefix (e.g. "Oliver Wyman - Principal, Aviation").
    The company/businessUnit field may also identify Oliver Wyman roles.

    CAVOK (Oliver Wyman's aviation MRO consulting brand) is integrated into Oliver Wyman and
    appears under "Oliver Wyman" titles, not as a separate "CAVOK" entity in the portal.
    """
    title = job.get("title", "").lower()
    company = job.get("company", "").lower()
    return "oliver wyman" in title or "oliver wyman" in company


def run_pipeline(seen_path=None, near_miss_path=None):
    """
    Full Oliver Wyman / CAVOK pipeline: fetch → pre-filter → gate-filter → dedup → alert → persist.

    The MAMCGLOBAL Phenom portal returns all Marsh McLennan companies. This pipeline
    pre-filters to Oliver Wyman roles before passing to the 3-gate matcher, which then
    further filters to aviation MRO consulting roles via domain_terms + engine_specific_terms.
    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH
    near_miss_path = Path(near_miss_path) if near_miss_path else NEAR_MISS_PATH

    config = _load_config()

    print("[oliver_wyman] ── Oliver Wyman / CAVOK pipeline starting ──")
    print(f"[oliver_wyman] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    # ── 1. Fetch ─────────────────────────────────────────────────────────────
    raw_jobs = oliver_wyman_fetcher.fetch_jobs()

    # Pre-filter: Marsh McLennan portal mixes all brands — keep only Oliver Wyman
    raw_jobs = [j for j in raw_jobs if _is_oliver_wyman_job(j)]
    total_fetched = len(raw_jobs)
    print(f"[oliver_wyman] Fetched {total_fetched} unique listings (Oliver Wyman only)")

    # ── 2. Filter through 3-gate matcher ────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, oliver_wyman_fetcher, config=config)

    # Derive gate-pass counts from near_misses for the summary
    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g2_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate2")
    g1_pass = total_fetched - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    # ── 3. Deduplicate against seen_jobs ────────────────────────────────────
    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    # ── 4. Alert if new matches found ───────────────────────────────────────
    alert_sent = False
    if new_matches:
        print(f"[oliver_wyman] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[oliver_wyman] No new matches — nothing to alert")

    # ── 5. Persist near-misses with timestamp ───────────────────────────────
    if near_misses:
        existing_near_misses = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing_near_misses.extend(near_misses)
        _save_json(near_miss_path, existing_near_misses)
        print(f"[oliver_wyman] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    # ── 6. Run summary ───────────────────────────────────────────────────────
    print()
    print("[oliver_wyman] ── Run summary ──────────────────────────────")
    print(f"[oliver_wyman]  Total fetched     : {total_fetched}")
    print(f"[oliver_wyman]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[oliver_wyman]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[oliver_wyman]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[oliver_wyman]  New (not seen)    : {len(new_matches)}")
    print(f"[oliver_wyman]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[oliver_wyman] ────────────────────────────────────────────")

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
        notifier.reset_failure_count("oliver_wyman")
    except Exception as exc:
        print(f"[oliver_wyman] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("oliver_wyman", exc)
