import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline_registry import get_spec
from src.pipeline_runner import run_cli, run_pipeline as _run_pipeline

SPEC = get_spec("fltechnics")
_AVIATION_TITLE_TERMS = [
    "aerospace", "aircraft", "engine", "engines", "powerplant", "propulsion",
    "turbine", "apu", "auxiliary power", "overhaul", "mro", "maintenance",
    "airworthiness", "aviation", "avionics", "airframe", "inspector",
]


def _is_aviation_title(title: str) -> bool:
    text = title.lower()
    return any(term in text for term in _AVIATION_TITLE_TERMS)


def run_pipeline(seen_path=None):
    return _run_pipeline(SPEC, seen_path=seen_path)


if __name__ == "__main__":
    run_cli(SPEC)
