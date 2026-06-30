import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path

import yaml

from src import sanad_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_sanad.json"


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
    Full Sanad pipeline: fetch → filter → dedup → alert → persist.

    """
    seen_path = Path(seen_path) if seen_path else SEEN_PATH

    config = _load_config()
    sanad_cfg = config.get("sanad_search", {})
    max_listings = sanad_cfg.get("max_listings", 200)
    inter_page_delay = sanad_cfg.get("inter_page_delay", 0.3)

    print("[sanad] ── Sanad pipeline starting ──")
    print(f"[sanad] Config: seen_path={seen_path.name}")

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    raw_jobs = sanad_fetcher.fetch_jobs(max_listings=max_listings, inter_page_delay=inter_page_delay)
    # Sanad portal includes Sanad Capital (engine leasing/finance) — keep only Sanad Aerotech (engine MRO)
    raw_jobs = [j for j in raw_jobs if "capital" not in j.get("company", "").lower()]
    total_fetched = len(raw_jobs)
    print(f"[sanad] Fetched {total_fetched} unique listings (Sanad Aerotech only)")

    # ── 2. Filter through 3-gate matcher ─────────────────────────────────────
    matched, near_misses = filter_jobs(raw_jobs, sanad_fetcher, config=config)

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
        print(f"[sanad] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_urls.add(job["url"])
        _save_json(seen_path, sorted(seen_urls))
    else:
        print("[sanad] No new matches — nothing to alert")


    # ── 6. Run summary ────────────────────────────────────────────────────────
    print()
    print("[sanad] ── Run summary ──────────────────────────────")
    print(f"[sanad]  Total fetched     : {total_fetched}")
    print(f"[sanad]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[sanad]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[sanad]  Passed Gate 2     : {total_matched}  (engine domain match)")
    print(f"[sanad]  New (not seen)    : {len(new_matches)}")
    print(f"[sanad]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[sanad] ────────────────────────────────────────────")

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
        notifier.reset_failure_count("sanad")
    except Exception as exc:
        print(f"[sanad] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error("sanad", exc)
