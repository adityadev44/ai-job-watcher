import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline_registry import get_spec
from src.pipeline_runner import run_cli, run_pipeline as _run_pipeline

SPEC = get_spec("honeywell")
_AEROSPACE_TITLE_TERMS = [
    "aerospace", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power",
    "overhaul", "mro", "maintenance", "airworthiness", "aviation",
    "avionics",
]


def _is_aerospace_title(title: str) -> bool:
    text = title.lower()
    return any(term in text for term in _AEROSPACE_TITLE_TERMS)


def run_pipeline(seen_path=None):
    return _run_pipeline(SPEC, seen_path=seen_path)


if __name__ == "__main__":
    run_cli(SPEC)
