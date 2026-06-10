import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import datetime
from pathlib import Path

import yaml

from src import indigo_fetcher
from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SEEN_PATH = ROOT / "seen_jobs_indigo.json"
NEAR_MISS_PATH = ROOT / "near_misses_indigo.json"

# IndiGo is a full-service airline — descriptions are inaccessible (Gate 2 is
# bypassed), and their portal is domain-diverse (finance, HR, IT, etc.).
# Gate 1 alone (broad title_family terms like "manager", "consultant") produces
# too many non-aviation matches.  This pre-filter requires at least one
# aviation-domain term in the title before handing off to filter_jobs().
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


def _is_aviation_title(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in _AVIATION_TITLE_TERMS)


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

    print("[indigo] ── IndiGo pipeline starting ──")
    print(f"[indigo] Config: seen_path={seen_path.name}, near_miss_path={near_miss_path.name}")

    raw_jobs = indigo_fetcher.fetch_jobs()
    total_fetched = len(raw_jobs)
    print(f"[indigo] Fetched {total_fetched} listings")

    # Pre-filter: drop non-aviation titles before handing off to Gates 1-3.
    # Necessary because descriptions are unavailable (Gate 2 bypassed) and
    # IndiGo hires across all functions — generic Gate 1 terms catch admin/finance.
    aviation_jobs = [j for j in raw_jobs if _is_aviation_title(j["title"])]
    skipped = total_fetched - len(aviation_jobs)
    if skipped:
        print(f"[indigo] Pre-filter: dropped {skipped} non-aviation title(s)")
        for j in raw_jobs:
            if not _is_aviation_title(j["title"]):
                print(f"[indigo]   skipped: {j['title']}")

    matched, near_misses = filter_jobs(aviation_jobs, indigo_fetcher, config=config)

    g1_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm["gate_failed"] == "gate3")
    g1_pass = len(aviation_jobs) - g1_fail
    g3_pass = g1_pass - g3_fail
    total_matched = len(matched)

    # Deduplicate by job id (not url) — jobReqSecKey in the URL is session-scoped
    # and changes every DWR session, making URL-based dedup unreliable.
    seen_ids = set(_load_json(seen_path))
    new_matches = [j for j in matched if j["id"] not in seen_ids]

    alert_sent = False
    if new_matches:
        print(f"[indigo] {len(new_matches)} new match(es) — sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            seen_ids.add(job["id"])
        _save_json(seen_path, sorted(seen_ids))
    else:
        print("[indigo] No new matches — nothing to alert")

    if near_misses:
        existing = _load_json(near_miss_path)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for nm in near_misses:
            nm["run_timestamp"] = timestamp
        existing.extend(near_misses)
        _save_json(near_miss_path, existing)
        print(f"[indigo] {len(near_misses)} near-miss(es) appended to {near_miss_path.name}")

    print()
    print("[indigo] ── Run summary ──────────────────────────────")
    print(f"[indigo]  Total fetched     : {total_fetched}  (page 1 of ~3; pagination unavailable)")
    print(f"[indigo]  Aviation pre-filter: {len(aviation_jobs)} passed, {skipped} dropped")
    print(f"[indigo]  Passed Gate 1     : {g1_pass}  (title family match)")
    print(f"[indigo]  Passed Gate 3     : {g3_pass}  (exclude filter clear)")
    print(f"[indigo]  Matched           : {total_matched}  (kept; no description gate — see fetcher)")
    print(f"[indigo]  New (not seen)    : {len(new_matches)}")
    print(f"[indigo]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print("[indigo] ────────────────────────────────────────────")

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
        print(f"[indigo] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        raise
