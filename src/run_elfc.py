import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path

import yaml

from src import elfc_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_elfc.json"


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
    """
    Full ELFC pipeline: fetch -> filter -> dedup -> alert -> persist.

    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH

    config = _load_config()

    print("[elfc] ── ELFC pipeline starting ──")
    print(f"[elfc] Config: seen_path={seen_path.name}")

    # ── 1. Fetch ─────────────────────────────────────────────────────────────
    raw_jobs = elfc_fetcher.fetch_jobs()
    total_fetched = len(raw_jobs)
    print(f"[elfc] Fetched {total_fetched} unique listings")

    # ── 2. Filter through 3-gate matcher ────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, elfc_fetcher, config=config)

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
        print(f"[elfc] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        # Persist new URLs to seen_jobs
        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[elfc] No new matches — nothing to alert")


    # ── 6. Run summary ───────────────────────────────────────────────────────
    print()
    print("[elfc] ── Run summary ──────────────────────────────")
    print(f"[elfc]  Total fetched     : {total_fetched}")
    print(f"[elfc]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[elfc]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[elfc]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[elfc]  New (not seen)    : {len(new_matches)}")
    print(f"[elfc]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[elfc] ────────────────────────────────────────────")

    return {
        "total_fetched": total_fetched,
        "g1_pass": g1_pass,
        "g3_pass": g3_pass,
        "total_matched": total_matched,
        "new_matches": new_matches,
        "alert_sent": alert_sent,
    }


if __name__ == "__main__":
    try:
        run_pipeline()
        notifier.reset_failure_count("elfc")
    except Exception as exc:
        print(f"[elfc] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("elfc", exc)
