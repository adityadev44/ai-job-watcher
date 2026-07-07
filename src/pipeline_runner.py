import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import yaml

from src.matcher import filter_jobs
from src import notifier

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
HEALTH_PATH = ROOT / "pipeline_health.json"

DedupKey = Literal["url", "id"]
FetchMode = Literal["default", "config", "search_params"]


@dataclass(frozen=True)
class PipelineSpec:
    source: str
    display_name: str
    fetcher: object
    seen_filename: str
    config_section: str | None = None
    fetch_mode: FetchMode = "default"
    dedupe_key: DedupKey = "url"
    pre_filter: Callable[[dict], bool] | None = None
    pre_filter_label: str = "Pre-filter"
    pre_filter_pass_label: str = "Filtered titles"
    log_pre_filter_skips: bool = False
    seed_seen_on_first_run: bool = False
    populate_company: Callable[[dict], None] | None = None
    total_note: str = ""
    matched_label: str = "Passed Gate 2"
    matched_note: str = "engine domain match"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def load_json(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[WARNING] {path.name}: JSON parse error ({exc}) - returning empty list (check for file corruption)")
            return []
    return data if isinstance(data, list) else []


def save_json(path: Path, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _atomic_write_json(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, path)


def _read_health() -> dict:
    try:
        data = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _update_health(source: str, total_fetched: int) -> None:
    """Track suspicious zero-fetch streaks without failing the pipeline."""
    try:
        data = _read_health()
        item = data.get(source, {})
        counts = list(item.get("recent_counts", []))
        counts.append(total_fetched)
        counts = counts[-10:]
        previous_zero_streak = int(item.get("zero_streak", 0) or 0)
        zero_streak = previous_zero_streak + 1 if total_fetched == 0 else 0
        item.update({
            "recent_counts": counts,
            "last_fetched": total_fetched,
            "zero_streak": zero_streak,
        })
        data[source] = item
        _atomic_write_json(HEALTH_PATH, data)

        if zero_streak == 3:
            notifier.send_email(
                subject=f"[{source}] possible silent source failure - Aviation MRO Watcher",
                body=(
                    f"The [{source}] pipeline fetched 0 jobs for 3 consecutive successful runs.\n\n"
                    "This may be normal for a tiny portal, but it can also mean the source changed "
                    "without raising a hard pipeline error."
                ),
            )
            print(f"[{source}] Health warning sent after 3 consecutive zero-fetch runs.")
    except Exception as exc:
        print(f"[{source}] Health tracking skipped (non-fatal): {exc}")


def _fetch_jobs(spec: PipelineSpec, config: dict) -> list[dict]:
    if spec.fetch_mode == "config":
        return spec.fetcher.fetch_jobs(config=config)
    if spec.fetch_mode == "search_params":
        section = config.get(spec.config_section or f"{spec.source}_search", {})
        kwargs = {}
        if "max_listings" in section:
            kwargs["max_listings"] = section["max_listings"]
        if "inter_page_delay" in section:
            kwargs["inter_page_delay"] = section["inter_page_delay"]
        return spec.fetcher.fetch_jobs(**kwargs)
    return spec.fetcher.fetch_jobs()


def _dedupe_value(job: dict, key: DedupKey) -> str:
    return str(job.get(key, "") or "")


def _summarize_gates(total_filtered: int, matched: list[dict], near_misses: list[dict]) -> dict:
    g1_fail = sum(1 for nm in near_misses if nm.get("gate_failed") == "gate1")
    g3_fail = sum(1 for nm in near_misses if nm.get("gate_failed") == "gate3")
    g4_fail = sum(1 for nm in near_misses if nm.get("gate_failed") == "gate4")
    g1_pass = total_filtered - g1_fail
    g3_pass = g1_pass - g3_fail
    g4_pass = g3_pass - g4_fail
    return {
        "g1_pass": g1_pass,
        "g3_pass": g3_pass,
        "g4_pass": g4_pass,
        "total_matched": len(matched),
    }


def run_pipeline(spec: PipelineSpec, seen_path: str | Path | None = None) -> dict:
    seen_path = Path(seen_path) if seen_path else ROOT / spec.seen_filename
    config = load_config()

    print(f"[{spec.source}] -- {spec.display_name} pipeline starting --")
    print(f"[{spec.source}] Config: seen_path={seen_path.name}, dedupe_key={spec.dedupe_key}")

    raw_jobs = _fetch_jobs(spec, config)
    total_fetched = len(raw_jobs)
    print(f"[{spec.source}] Fetched {total_fetched} unique listings")
    _update_health(spec.source, total_fetched)

    filter_input = raw_jobs
    pre_filter_dropped = 0
    if spec.pre_filter is not None:
        filter_input = [job for job in raw_jobs if spec.pre_filter(job)]
        pre_filter_dropped = total_fetched - len(filter_input)
        if pre_filter_dropped:
            print(f"[{spec.source}] {spec.pre_filter_label}: dropped {pre_filter_dropped} title(s)")
            if spec.log_pre_filter_skips:
                for job in raw_jobs:
                    if not spec.pre_filter(job):
                        print(f"[{spec.source}]   skipped: {job.get('title', 'N/A')}")

    matched, near_misses = filter_jobs(filter_input, spec.fetcher, config=config)
    gate_counts = _summarize_gates(len(filter_input), matched, near_misses)

    seen_values = set(load_json(seen_path))
    if spec.seed_seen_on_first_run and not seen_values and raw_jobs:
        print(f"[{spec.source}] First run detected - seeding seen_jobs with all fetched URLs (no alerts)")
        save_json(seen_path, sorted({str(j.get("url", "") or "") for j in raw_jobs if j.get("url")}))
        seen_values = set(load_json(seen_path))

    new_matches = [j for j in matched if _dedupe_value(j, spec.dedupe_key) not in seen_values]

    if spec.populate_company:
        for job in new_matches:
            spec.populate_company(job)

    alert_sent = False
    if new_matches:
        print(f"[{spec.source}] {len(new_matches)} new match(es) - sending alert")
        notifier.notify_matches(new_matches)
        alert_sent = True

        for job in new_matches:
            value = _dedupe_value(job, spec.dedupe_key)
            if value:
                seen_values.add(value)
        save_json(seen_path, sorted(seen_values))
    else:
        print(f"[{spec.source}] No new matches - nothing to alert")

    print()
    print(f"[{spec.source}] -- Run summary ------------------------------")
    total_line = f"[{spec.source}]  Total fetched     : {total_fetched}"
    if spec.total_note:
        total_line += f"  ({spec.total_note})"
    print(total_line)
    if spec.pre_filter is not None:
        print(
            f"[{spec.source}]  {spec.pre_filter_pass_label:<17}: "
            f"{len(filter_input)}  (pre-filter: {pre_filter_dropped} dropped)"
        )
    print(f"[{spec.source}]  Passed Gate 1     : {gate_counts['g1_pass']}  (title family match)")
    print(f"[{spec.source}]  Passed Gate 3     : {gate_counts['g3_pass']}  (exclude filter clear)")
    print(f"[{spec.source}]  Passed Gate 4     : {gate_counts['g4_pass']}  (description exclusion clear)")
    print(f"[{spec.source}]  {spec.matched_label:<17}: {gate_counts['total_matched']}  ({spec.matched_note})")
    print(f"[{spec.source}]  New (not seen)    : {len(new_matches)}")
    print(f"[{spec.source}]  Alert sent        : {'YES' if alert_sent else 'no'}")
    print(f"[{spec.source}] --------------------------------------------")

    return {
        "total_fetched": total_fetched,
        "pre_filter_dropped": pre_filter_dropped,
        **gate_counts,
        "new_matches": new_matches,
        "alert_sent": alert_sent,
    }


def run_cli(spec: PipelineSpec) -> None:
    try:
        run_pipeline(spec)
        notifier.reset_failure_count(spec.source)
    except Exception as exc:
        print(f"[{spec.source}] PIPELINE ERROR (non-fatal to outer scheduler): {exc}")
        notifier.notify_pipeline_error(spec.source, exc)
