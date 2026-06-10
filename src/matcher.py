import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import yaml
from pathlib import Path


def _load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ci(text):
    """Return lowercase version of text for case-insensitive matching."""
    return text.lower() if text else ""


def filter_jobs(jobs, fetcher, config=None):
    """
    Filter a list of job dicts through 3 gates.

    Each job dict must have at minimum: title, url, location.
    The fetcher object must export:
        fetch_job_description(url) -> str
        RateLimitError (exception class)

    Returns (matched, near_misses) where both are lists of dicts.
    near_misses have extra keys: gate_failed, reason.
    """
    if config is None:
        config = _load_config()

    m = config["matching"]
    title_family = [_ci(t) for t in m["title_family"]]
    exclude_terms = [_ci(t) for t in m["exclude_terms"]]
    engine_terms = [_ci(t) for t in m["engine_specific_terms"]]
    domain_terms = [_ci(t) for t in m["domain_terms"]]

    matched = []
    near_misses = []

    for job in jobs:
        title = job.get("title", "")
        title_lc = _ci(title)
        url = job.get("url", "")

        # Gate 1 — title family
        gate1_hit = next((t for t in title_family if t in title_lc), None)
        if gate1_hit is None:
            reason = f"no title-family term found in title"
            print(f"[gate1] {title} ({reason})")
            near_misses.append({**job, "gate_failed": "gate1", "reason": reason})
            continue

        # Gate 3 — exclude terms
        gate3_hit = next((t for t in exclude_terms if t in title_lc), None)
        if gate3_hit is not None:
            reason = f"excluded term '{gate3_hit}' in title"
            print(f"[gate3] {title} ({reason})")
            near_misses.append({**job, "gate_failed": "gate3", "reason": reason})
            continue

        # Fetch description only if Gates 1 and 3 passed
        description = ""
        fetch_failed = False
        try:
            raw = fetcher.fetch_job_description(url)
            if isinstance(raw, tuple):
                description = raw[0] if raw[0] else ""
            else:
                description = raw if raw else ""
        except fetcher.RateLimitError:
            raise
        except Exception:
            fetch_failed = True

        desc_lc = _ci(description)

        # Keep unconditionally if fetch failed or description too short
        if fetch_failed or len(description) < 100:
            print(f"[kept-no-desc] {title} (description unavailable — kept unconditionally)")
            matched.append(job)
            continue

        # Gate 2 — engine domain
        engine_hits = sum(1 for t in engine_terms if t in desc_lc)
        domain_hits = sum(1 for t in domain_terms if t in desc_lc)
        total_hits = engine_hits + domain_hits

        if engine_hits < 1 or total_hits < 2:
            reason = f"engine_hits={engine_hits}, domain_hits={domain_hits}, needed 1 engine + 2 total"
            print(f"[gate2] {title} ({reason})")
            near_misses.append({**job, "gate_failed": "gate2", "reason": reason})
            continue

        matched.append(job)

    return matched, near_misses


def build_weekly_digest(near_misses):
    """
    Build a plain-text weekly digest from a list of near-miss dicts.
    Each dict must have: title, location, url, gate_failed, reason.
    Returns a formatted string suitable for email body.
    """
    if not near_misses:
        return "No near-misses this week."

    lines = [
        "Aviation MRO Job Watcher — Weekly Near-Miss Digest",
        "=" * 52,
        f"Total near-misses: {len(near_misses)}",
        "",
    ]

    by_gate = {}
    for nm in near_misses:
        gate = nm.get("gate_failed", "unknown")
        by_gate.setdefault(gate, []).append(nm)

    gate_labels = {
        "gate1": "Gate 1 failures (title family mismatch)",
        "gate2": "Gate 2 failures (engine domain mismatch)",
        "gate3": "Gate 3 failures (excluded term in title)",
    }

    for gate in ("gate1", "gate3", "gate2"):
        items = by_gate.get(gate, [])
        if not items:
            continue
        lines.append(gate_labels.get(gate, gate))
        lines.append("-" * 40)
        for nm in items:
            lines.append(f"  {nm.get('title', 'N/A')}")
            lines.append(f"  Location : {nm.get('location', 'N/A')}")
            lines.append(f"  Reason   : {nm.get('reason', 'N/A')}")
            lines.append(f"  URL      : {nm.get('url', 'N/A')}")
            lines.append("")

    return "\n".join(lines)
