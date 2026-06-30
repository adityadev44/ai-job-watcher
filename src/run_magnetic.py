import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path

import yaml

from src import magnetic_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_magnetic.json"


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


def run_pipeline(seen_path=None):
    seen_path = Path(seen_path) if seen_path else SEEN_PATH

    config = _load_config()

    print("[magnetic] ── Magnetic MRO pipeline starting ──")
    print(f"[magnetic] Config: seen_path={seen_path.name}")
    print("[magnetic] NOTE: BambooHR SPA — descriptions unavailable, Gate 2 bypassed")

    # ── 1. Fetch ─────────────────────────────────────────────────────────────
    raw_jobs = magnetic_fetcher.fetch_jobs()
    total_fetched = len(raw_jobs)
    print(f"[magnetic] Fetched {total_fetched} unique listings")

    # ── 2. Filter through 4-gate matcher ────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, magnetic_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g4_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate4")
    g1_pass = total_fetched - g1_fail
    g3_pass = g1_pass - g3_fail
    g4_pass = g3_pass - g4_fail
    total_matched = len(matched)

    # ── 3. Deduplicate against seen_jobs ────────────────────────────────────
    seen_urls = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["url"] not in seen_urls]

    # ── 4. Alert if new matches found ───────────────────────────────────────
    alert_sent = False
    if new_matches:
        print(f"[magnetic] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[magnetic] No new matches — nothing to alert")


    # ── 6. Run summary ───────────────────────────────────────────────────────
    print()
    print("[magnetic] ── Run summary ──────────────────────────────")
    print(f"[magnetic]  Total fetched     : {total_fetched}")
    print(f"[magnetic]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[magnetic]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[magnetic]  Passed Gate 4     : {g4_pass}  (description exclusion clear)")
    print(f"[magnetic]  Passed Gate 2     : {total_matched}  (bypassed — no descriptions)")
    print(f"[magnetic]  New (not seen)    : {len(new_matches)}")
    print(f"[magnetic]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[magnetic] ────────────────────────────────────────────")

    return {
        "total_fetched": total_fetched,
        "g1_pass": g1_pass,
        "g3_pass": g3_pass,
        "g4_pass": g4_pass,
        "total_matched": total_matched,
        "new_matches": new_matches,
        "alert_sent": alert_sent,
    }


if __name__ == "__main__":
    try:
        run_pipeline()
        notifier.reset_failure_count("magnetic")
    except Exception as exc:
        print(f"[magnetic] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("magnetic", exc)
