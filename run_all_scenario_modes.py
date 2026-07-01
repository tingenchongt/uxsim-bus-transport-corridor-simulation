"""
Run each simulation_per_vehicle.py scenario mode into its own output folder.

Each mode writes under results_by_mode/<slug>/:
  results_per_bus.csv
  results_per_bus_clean.csv
  results_per_bus_stop_detail.csv
  results_per_bus_stop_detail_clean.csv
  results_per_bus.xlsx (if openpyxl available)
  results_per_bus_clean.xlsx

Usage:
  python run_all_scenario_modes.py --manifest          # list modes + paths (no sim)
  python run_all_scenario_modes.py --tier small        # 36–180 row modes (~504 runs)
  python run_all_scenario_modes.py --tier medium       # 288–1,116 row modes
  python run_all_scenario_modes.py --tier large        # 2,304–5,724 row modes
  python run_all_scenario_modes.py --tier mega         # --all-possible (41,472 rows)
  python run_all_scenario_modes.py --mode transit-only # one mode
  python run_all_scenario_modes.py                     # ALL modes (~66k UXsim runs, days)
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent
SIM = _PROJECT / "simulation_per_vehicle.py"
OUT_ROOT = _PROJECT / "results_by_mode"
MANIFEST_CSV = OUT_ROOT / "scenario_modes_manifest.csv"

OUTPUT_FILES = (
    "results_per_bus.csv",
    "results_per_bus_clean.csv",
    "results_per_bus_stop_detail.csv",
    "results_per_bus_stop_detail_clean.csv",
    "results_per_bus.xlsx",
    "results_per_bus_clean.xlsx",
    "results_per_bus_stop_detail.xlsx",
)


@dataclass(frozen=True)
class ScenarioMode:
    slug: str
    cli_flag: str
    description: str
    expected_rows: int
    tier: str  # small | medium | large | mega


MODES: tuple[ScenarioMode, ...] = (
    ScenarioMode("transit_only", "--transit-only", "A — all stops, 100% dwell", 36, "small"),
    ScenarioMode("informal_only", "--informal-only", "B — informal curbs only", 36, "small"),
    ScenarioMode("formal_only", "--formal-only", "C — formal mids only", 36, "small"),
    ScenarioMode("optimized_only", "--optimized-only", "D — formal only, 55% dwell", 36, "small"),
    ScenarioMode("optimized_transit_only", "--optimized-transit-only", "E — all stops, 55% dwell", 36, "small"),
    ScenarioMode("unlisted_stop_only", "--unlisted-stop-only", "All stops + 1 unlisted curb", 36, "small"),
    ScenarioMode("optimized", "--optimized", "A + E + D (3 policies)", 108, "small"),
    ScenarioMode("policies_only", "--policies-only", "A–E named policies", 180, "small"),
    ScenarioMode("unlisted_stop_all", "--unlisted-stop-all", "U0, U1, U2 unlisted", 108, "small"),
    ScenarioMode("optimized_unlisted_stop_all", "--optimized-unlisted-stop-all", "U0–U2 @ 55%", 108, "small"),
    ScenarioMode("partial_informal_only", "--partial-informal-only", "6 partial informal masks", 216, "small"),
    ScenarioMode("driver_service_only", "--driver-service-only", "Drop-off / brief stop / unlisted", 180, "small"),
    ScenarioMode("optimized_informal_all", "--optimized-informal-all", "8 informal @ 55%", 288, "medium"),
    ScenarioMode("optimized_formal_all", "--optimized-formal-all", "8 formal @ 55%", 288, "medium"),
    ScenarioMode("informal_all", "--informal-all", "16 informal subsets", 576, "medium"),
    ScenarioMode("formal_all", "--formal-all", "16 formal subsets", 576, "medium"),
    ScenarioMode("relocation_all", "--relocation-all", "31 relocation (+5 m)", 1116, "medium"),
    ScenarioMode("optimized_relocation_all", "--optimized-relocation-all", "31 relocation @ 55%", 1116, "medium"),
    ScenarioMode("optimized_transit_all", "--optimized-transit-all", "64 combos @ 55% dwell", 2304, "large"),
    ScenarioMode("optimized_all", "--optimized-all", "Same 64 @ 55%", 2304, "large"),
    ScenarioMode("transit_all", "--transit-all", "All 128 stop combos", 4608, "large"),
    ScenarioMode("full_encounter_only", "--full-encounter-only", "128 X_* masks", 4608, "large"),
    ScenarioMode("all_scenarios", "--all-scenarios", "128 encounter + 31 relocation", 5724, "large"),
    ScenarioMode("all_possible", "--all-possible", "Full grid (1,152 policies)", 41472, "mega"),
)


def output_dir_for(mode: ScenarioMode) -> Path:
    return OUT_ROOT / mode.slug


def write_manifest() -> Path:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with MANIFEST_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "slug",
                "cli_flag",
                "description",
                "expected_rows",
                "tier",
                "output_dir",
                "main_csv",
                "stops_csv",
            ]
        )
        for m in MODES:
            d = output_dir_for(m)
            w.writerow(
                [
                    m.slug,
                    m.cli_flag,
                    m.description,
                    m.expected_rows,
                    m.tier,
                    str(d),
                    str(d / "results_per_bus.csv"),
                    str(d / "results_per_bus_stop_detail.csv"),
                ]
            )
    return MANIFEST_CSV


def print_manifest() -> None:
    path = write_manifest()
    print(f"Manifest: {path}\n")
    print(f"{'slug':<28} {'rows':>7}  {'tier':<6}  main output file")
    print("-" * 90)
    for m in MODES:
        d = output_dir_for(m)
        print(
            f"{m.slug:<28} {m.expected_rows:>7}  {m.tier:<6}  {d / 'results_per_bus.csv'}"
        )
    total = sum(m.expected_rows for m in MODES)
    print("-" * 90)
    print(f"{'TOTAL if all modes run separately':<28} {total:>7}  UXsim runs (9 buses x 4 signals x policies)")


def run_mode(mode: ScenarioMode, *, extra_args: list[str] | None = None) -> int:
    out = output_dir_for(mode)
    cmd = [
        sys.executable,
        str(SIM),
        mode.cli_flag,
        "--no-resume",
        "--output-dir",
        str(out),
        *(extra_args or []),
    ]
    print(f"\n{'=' * 72}")
    print(f"MODE: {mode.slug}  ({mode.description})")
    print(f"Expected rows: {mode.expected_rows}  ->  {out / 'results_per_bus.csv'}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 72)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=_PROJECT)
    elapsed = time.time() - t0
    trip = out / "results_per_bus.csv"
    n = 0
    if trip.is_file():
        with trip.open(encoding="utf-8") as f:
            n = sum(1 for _ in csv.DictReader(f))
    print(f"Finished {mode.slug} in {elapsed / 60:.1f} min  exit={proc.returncode}  rows={n}")
    return proc.returncode


def main() -> None:
    p = argparse.ArgumentParser(description="Batch-run scenario modes into results_by_mode/")
    p.add_argument("--manifest", action="store_true", help="Write manifest CSV and exit")
    p.add_argument(
        "--tier",
        choices=("small", "medium", "large", "mega"),
        help="Run only modes in this size tier",
    )
    p.add_argument("--mode", metavar="SLUG", help="Run one mode by slug (e.g. transit_only)")
    p.add_argument(
        "--single-signal",
        action="store_true",
        help="Pass --single-signal to each run (4x faster, 9 rows per 1-policy mode)",
    )
    p.add_argument("--limit", type=int, default=0, help="Pass --limit N to each run (0=all buses)")
    args = p.parse_args()

    if args.manifest and not args.mode and not args.tier:
        print_manifest()
        return

    extra: list[str] = []
    if args.single_signal:
        extra.append("--single-signal")
    if args.limit > 0:
        extra.extend(["--limit", str(args.limit)])

    if args.mode:
        match = [m for m in MODES if m.slug == args.mode.replace("-", "_")]
        if not match:
            slugs = ", ".join(m.slug for m in MODES)
            raise SystemExit(f"Unknown mode {args.mode!r}. Choose: {slugs}")
        write_manifest()
        raise SystemExit(run_mode(match[0], extra_args=extra))

    selected = list(MODES)
    if args.tier:
        selected = [m for m in MODES if m.tier == args.tier]

    write_manifest()
    print_manifest()
    total_rows = sum(m.expected_rows for m in selected)
    print(f"\nWill run {len(selected)} mode(s), ~{total_rows} planned rows total.")
    if total_rows > 5000:
        print("WARNING: This may take many hours. Consider --tier small first.")

    failed: list[str] = []
    for mode in selected:
        if run_mode(mode, extra_args=extra) != 0:
            failed.append(mode.slug)

    if failed:
        raise SystemExit(f"Failed modes: {', '.join(failed)}")
    print("\nAll selected modes completed.")


if __name__ == "__main__":
    main()
