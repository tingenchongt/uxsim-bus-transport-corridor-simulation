"""
Vissim-style 1-hour corridor runs per session (Morning / Lunch / Afternoon).

Scenario mode (pick at most one; default = ALL: A–D + R_*):

  --all                  same as default
  --transit-only        A_transit
  --informal-only        B_informal_only
  --formal-only          C_formal_only
  --optimized-only       D_optimized
  --relocation-only      R_* masks only
  --policies-only        A–D, no relocation
  --optimized            A_transit + E_optimized_transit + D_optimized

Examples:
  python simulation_session_hour.py --session "Morning Session"
  python simulation_session_hour.py --session "Lunch" --transit-only
  python simulation_session_hour.py --session "Afternoon Session" --relocation-only
  python simulation_session_hour.py --jan18-targets --session "Morning Session" --transit-only
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bus_calibration import SESSION_SHEETS, configure_field_workbook_calibration
import corridor_config as corridor_config
from corridor_config import (
    MIXED_CORRIDOR_DEMAND_WINDOW_S,
    SESSION_BUS_PER_HOUR_BY_DIRECTION,
    SESSION_HOUR_CLEARANCE_S,
    SESSION_ONBOARD_JAN18,
)
from scenario_catalog import (
    ScenarioSpec,
    chainage_overrides_for_scenario,
    default_session_hour_scenarios,
    effective_corridor_length_m,
    scenarios_for_session_hour_mode,
    select_scenarios,
)
from signal_scenarios import all_signal_scenarios, trip_direction_for_data_origin
from session_bus_trips import (
    SESSION_HOUR_PER_BUS_COLUMNS,
    build_session_hour_per_bus_rows,
    write_session_bus_trips_csv,
    write_session_hour_per_bus_csv,
)
from simulation_extended import (
    _append_checkpoint,
    _write_comparison_csv,
    _write_results_csv,
    run_one,
)

_PROJECT = Path(__file__).resolve().parent
RESULTS_SESSION_HOUR_CSV = _PROJECT / "results_session_hour.csv"
RESULTS_SESSION_HOUR_COMPARISON_CSV = _PROJECT / "results_baseline_vs_optimized_session_hour.csv"
RESULTS_SESSION_HOUR_BUS_TRIPS_CSV = _PROJECT / "results_session_hour_bus_trips.csv"
CHECKPOINT_SESSION_HOUR_CSV = _PROJECT / "results_session_hour.checkpoint.csv"
CHECKPOINT_SESSION_HOUR_BUS_CSV = _PROJECT / "results_session_hour_bus_trips.checkpoint.csv"
RESULTS_SESSION_HOUR_PER_BUS_CSV = _PROJECT / "results_session_hour_per_bus.csv"
CHECKPOINT_SESSION_HOUR_PER_BUS_CSV = _PROJECT / "results_session_hour_per_bus.checkpoint.csv"


def _describe_scenario_plan(scenarios: tuple[ScenarioSpec, ...], mode_label: str) -> str:
    if len(scenarios) <= 8:
        return ", ".join(s.scenario_id for s in scenarios)
    return (
        f"{mode_label} ({len(scenarios)} scenarios: "
        f"{scenarios[0].scenario_id} … {scenarios[-1].scenario_id})"
    )


def _resolve_session_hour_scenarios(args: argparse.Namespace) -> tuple[tuple[ScenarioSpec, ...], str]:
    from scenario_catalog import default_session_hour_scenarios, resolve_scenario_mode_from_args

    return resolve_scenario_mode_from_args(
        args,
        default=default_session_hour_scenarios(),
        default_label="all (default)",
    )


def main() -> None:
    os.chdir(_PROJECT)
    p = argparse.ArgumentParser(
        description="1-hour mixed-traffic UXsim per session (visual + bus-only metrics)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--visual", action="store_true", help="Open UXsim animation window")
    p.add_argument("--session", choices=SESSION_SHEETS, help="One session (default: all three)")
    p.add_argument("--scenarios", metavar="IDS", help="Comma-separated scenario ids (overrides mode flags)")
    p.add_argument("--scenario-groups", metavar="GROUPS", help="Comma-separated: policies, relocation")
    p.add_argument("--single-signal", action="store_true", help="G-G only (4x faster)")
    p.add_argument(
        "--schedule-field-buses",
        action="store_true",
        help="Inject Data_Collection buses at observed times (on by default with per-vehicle output)",
    )
    p.add_argument(
        "--no-per-vehicle-results",
        action="store_true",
        help="Only 8/280 session summary rows; skip results_session_hour_per_bus.csv",
    )
    p.add_argument("--figures", action="store_true", help="Save network_average PNGs")
    p.add_argument("--leg-bus-only", action="store_true", help="Short leg buses only (underestimates time)")
    p.add_argument(
        "--jan18-targets",
        action="store_true",
        help="Calibrate to Jan 18 on-board times (11/15/19 min); default uses June 2026 San Agustin on-board",
    )
    p.add_argument("--list-scenarios", action="store_true", help="Print scenario catalog and exit")

    mode = p.add_argument_group(
        "scenario mode (pick at most one; default = ALL: A–D + relocation)"
    )
    mode.add_argument(
        "--all",
        "--all-scenarios",
        dest="all_scenarios",
        action="store_true",
        help="A–D + all R_* (280 runs per session, 4 signals)",
    )
    mode.add_argument(
        "--transit-only",
        dest="transit_only",
        action="store_true",
        help="A_transit (8 runs/session)",
    )
    mode.add_argument(
        "--baseline-only",
        dest="transit_only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument("--informal-only", action="store_true", help="B_informal_only")
    mode.add_argument("--formal-only", action="store_true", help="C_formal_only")
    mode.add_argument("--optimized-only", action="store_true", help="D_optimized")
    mode.add_argument(
        "--optimized-transit-only",
        dest="optimized_transit_only",
        action="store_true",
        help="E_optimized_transit (all stops, 0.55 dwell)",
    )
    mode.add_argument(
        "--optimized-baseline-only",
        dest="optimized_transit_only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--full-encounter-only",
        action="store_true",
        help="All 128 X_* encounter scenarios",
    )
    mode.add_argument("--policies-only", action="store_true", help="A–E, no R_*")
    mode.add_argument(
        "--optimized",
        action="store_true",
        help="A_transit + E_optimized_transit + D_optimized",
    )

    args = p.parse_args()
    configure_field_workbook_calibration()
    if args.jan18_targets:
        corridor_config.FIELD_ONBOARD_PROFILE = "jan18"

    if args.list_scenarios:
        from scenario_catalog import print_scenario_catalog

        print_scenario_catalog()
        print("\nSession-hour: --all (default), --transit-only, --informal-only,")
        print("  --formal-only, --optimized-only, --relocation-only, --policies-only, --optimized")
        return

    sessions = [args.session] if args.session else list(SESSION_SHEETS)
    scenarios, mode_label = _resolve_session_hour_scenarios(args)
    per_vehicle_results = not args.no_per_vehicle_results
    schedule_field = args.schedule_field_buses or per_vehicle_results

    n_sig = 1 if args.single_signal else 4
    plan: list[tuple] = []
    for sh in sessions:
        for origin in ("robinsons", "waltermart"):
            direction = trip_direction_for_data_origin(origin)
            signals = all_signal_scenarios(2, sh, direction)
            if args.single_signal:
                signals = (signals[0],)
            for scen in scenarios:
                for sig in signals:
                    plan.append((sh, origin, scen, sig))

    print("Vissim-style session-hour simulation")
    print(f"  Sessions: {', '.join(sessions)}")
    print(f"  Scenario mode: {mode_label}")
    print(f"  Scenarios: {_describe_scenario_plan(scenarios, mode_label)}")
    print(f"  Demand injection: {MIXED_CORRIDOR_DEMAND_WINDOW_S:.0f} s (1 hour)")
    print(f"  Sim horizon: {MIXED_CORRIDOR_DEMAND_WINDOW_S + SESSION_HOUR_CLEARANCE_S:.0f} s")
    print(
        f"  Visual: {args.visual}  |  Buses only in metrics  |  "
        f"Path: {'short legs' if args.leg_bus_only else 'full corridor'}"
    )
    print(f"  Signal patterns: {n_sig}  |  UXsim runs planned: {len(plan)}")
    print(f"  Calibration profile: {corridor_config.FIELD_ONBOARD_PROFILE}")
    if args.jan18_targets:
        for sess in sessions:
            row = SESSION_ONBOARD_JAN18.get(sess, {})
            t_s = row.get("travel_s")
            if t_s:
                print(f"    {sess}: onboard target {float(t_s) / 60:.0f} min (Jan 18)")
    if per_vehicle_results:
        print(
            "  Output: session-hour 1h mixed traffic + one results_per_bus-style row "
            "per Data_Collection bus (obs_id, company, sim travel time)"
        )
    else:
        print("  Output: session averages + anonymous bus_trips CSV only")
    if schedule_field:
        print("  Field buses depart at observed clock times inside the hour")
    for sess in sessions:
        by_dir = SESSION_BUS_PER_HOUR_BY_DIRECTION[sess]
        print(f"    {sess}: buses/h RB->WM {by_dir['rb_to_wm']} | WM->RB {by_dir['wm_to_rb']}")

    rows: list[dict[str, object]] = []
    bus_rows: list[dict[str, object]] = []
    per_bus_rows: list[dict[str, object]] = []
    for i, (sh, origin, scen, sig) in enumerate(plan, start=1):
        print(f"\n[{i}/{len(plan)}] {sh} | {origin} | {scen.scenario_id} | {sig.encounter_pattern}")
        n_bus_before = len(bus_rows)
        length_m = effective_corridor_length_m(scen)
        run_one(
            sh,
            data_origin=origin,  # type: ignore[arg-type]
            include_informal=scen.include_informal,
            informal_keys=scen.informal_keys,
            formal_keys=scen.formal_keys,
            policy_tag=scen.policy_tag,
            short_dwell_scale=scen.dwell_scale,
            sig=sig,
            mixed_traffic=True,
            replicate_field=False,
            results_rows=rows,
            save_figures=args.figures,
            quiet=not args.visual,
            scenario_id=scen.scenario_id,
            scenario_group=scen.group,
            relocate_mask=scen.relocate_mask,
            chainage_overrides=chainage_overrides_for_scenario(scen),
            corridor_length_m=effective_corridor_length_m(scen),
            session_hour=True,
            show_mode=1 if args.visual else 0,
            record_bus_only=True,
            schedule_field_buses=schedule_field,
            bus_full_corridor=not args.leg_bus_only,
            bus_trip_rows=bus_rows,
        )
        if rows:
            _append_checkpoint(rows[-1], CHECKPOINT_SESSION_HOUR_CSV)
        for br in bus_rows[n_bus_before:]:
            _append_checkpoint(br, CHECKPOINT_SESSION_HOUR_BUS_CSV)
        if per_vehicle_results:
            new_trips = bus_rows[n_bus_before:]
            pv = build_session_hour_per_bus_rows(
                sh,
                origin,
                scen,
                sig,
                new_trips,
                corridor_length_m=length_m,
            )
            per_bus_rows.extend(pv)
            for pr in pv:
                _append_checkpoint(pr, CHECKPOINT_SESSION_HOUR_PER_BUS_CSV)
            print(f"  Per-vehicle rows this run: {len(pv)} (obs_id from Data_Collection)")

    print(f"\n  Checkpoints (safe if Excel blocks final CSV): {CHECKPOINT_SESSION_HOUR_CSV}")
    print(f"    Per-bus checkpoint: {CHECKPOINT_SESSION_HOUR_BUS_CSV}")

    try:
        out = _write_results_csv(rows, RESULTS_SESSION_HOUR_CSV)
        _write_comparison_csv(rows, RESULTS_SESSION_HOUR_COMPARISON_CSV)
        bus_out = write_session_bus_trips_csv(bus_rows, RESULTS_SESSION_HOUR_BUS_TRIPS_CSV)
        pv_out = (
            write_session_hour_per_bus_csv(per_bus_rows, RESULTS_SESSION_HOUR_PER_BUS_CSV)
            if per_vehicle_results
            else RESULTS_SESSION_HOUR_PER_BUS_CSV
        )
    except PermissionError as e:
        print(f"\n{e}")
        print("  Check .checkpoint.csv files for saved rows.")
        out = CHECKPOINT_SESSION_HOUR_CSV
        bus_out = CHECKPOINT_SESSION_HOUR_BUS_CSV
        pv_out = CHECKPOINT_SESSION_HOUR_PER_BUS_CSV

    print(f"\nDone.")
    print(f"  Session summary ({len(rows)} UXsim runs) -> {out}")
    if per_vehicle_results:
        print(
            f"  Per-bus all scenarios×signals ({len(per_bus_rows)} rows, completed time first) -> {pv_out}"
        )
        print(f"    Columns start with: {', '.join(SESSION_HOUR_PER_BUS_COLUMNS[:6])} …")
    print(f"  Bus trip log (optional detail) -> {bus_out}  ({len(bus_rows)} rows)")


if __name__ == "__main__":
    main()
