import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline_registry import SPECS
from src.run_all import PIPELINES


def test_run_all_and_registry_have_same_sources():
    assert sorted(PIPELINES) == sorted(SPECS)


def test_every_registered_source_has_seen_file_and_dedupe_key():
    for source, spec in SPECS.items():
        assert spec.source == source
        assert spec.seen_filename == f"seen_jobs_{source}.json"
        assert spec.dedupe_key in {"url", "id"}


def test_known_id_dedupe_sources_are_explicit():
    assert SPECS["indigo"].dedupe_key == "id"
    assert SPECS["rolls_royce"].dedupe_key == "id"
