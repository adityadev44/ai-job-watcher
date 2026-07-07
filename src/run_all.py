import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

PIPELINES = [
    "safran",
    "ge",
    "sanad",
    "emirates",
    "gmr",
    "rtx",
    "indigo",
    "etihad",
    "sia",
    "ste",
    "standardaero",
    "saudia_technic",
    "lht",
    "qatar",
    "ethiopian",
    "gatelesis",
    "fltechnics",
    "magnetic",
    "air_india",
    "dgca",
    "saesl",
    "oman_air",
    "gulf_air",
    "kuwait_airways",
    "ammroc",
    "wlfc",
    "elfc",
    "rolls_royce",
    "honeywell",
    "mtu",
    "boeing",
    "aar",
    "icf",
    "oliver_wyman",
    "smbc_aviation",
    "aercap",
    "avolon",
    "boc_aviation",
    "acg",
]


def _run_one(source: str, timeout_seconds: int) -> tuple[str, int]:
    cmd = [sys.executable, "-u", "-m", f"src.run_{source}"]
    try:
        proc = subprocess.run(cmd, timeout=timeout_seconds)
        return source, proc.returncode
    except subprocess.TimeoutExpired:
        print(f"[{source}] Timed out after {timeout_seconds}s")
        return source, 124


def main() -> int:
    timeout_seconds = 300
    failures: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=len(PIPELINES)) as executor:
        futures = {executor.submit(_run_one, source, timeout_seconds): source for source in PIPELINES}
        for future in as_completed(futures):
            source, code = future.result()
            if code:
                failures[source] = code
                print(f"[run_all] {source}: exit {code}")
            else:
                print(f"[run_all] {source}: ok")

    if failures:
        print(f"[run_all] Failed pipelines: {failures}")
        return 1
    print("[run_all] All pipelines completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
