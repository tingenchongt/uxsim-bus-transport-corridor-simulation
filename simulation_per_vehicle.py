"""
Per-bus corridor simulation — primary entry point for thesis tables.

Primary source: Bus_Data_Collection_June 2026.xlsx (San Agustin only; June 2026 permissioned study).

One UXsim run per field bus x scenario x signal pattern (June 2026 default: ~9 San Agustin x scenario x 4).
Each row follows the field timeline: arrived_at_stop -> dwell -> departed -> corridor -> reached_destination.

Calibration (shared with simulation_session_hour.py / corridor_network.py):
  - Mixed traffic by default (PH vehicle mix anchored on hourly bus counts).
  - Speed caps: bus 50 km/h, other vehicles 60 km/h; traffic tier slows cruise (Heavy < Light).
  - Dwell: origin from field obs; formal mid-route from on-board data (~1–1.5 min);
    crowding Low x0.84 / High x1.45 vs session median.
  - Travel time: sum of UXsim leg durations (not wall-clock first-dep to last-arr).
  - Default onboard reference: June 2026 San Agustin on-board sheet. Use --jan18-targets for Jan 18 Sunday rows.

Outputs (reached_destination_time first for Excel):
  results_per_bus.csv, results_per_bus_stop_detail.csv (+ _clean variants)

Scenario mode (pick at most one; default = A_transit only):
  --transit-only, --informal-only, --formal-only, --optimized-only,
  --relocation-only, --policies-only, --optimized (A+E+D), --all-scenarios

Examples:
  python simulation_per_vehicle.py --export-only
  python simulation_per_vehicle.py
  python simulation_per_vehicle.py --transit-only
  python simulation_per_vehicle.py --formal-only --session "Lunch" --limit 20
  python simulation_per_vehicle.py --relocation-only --single-signal
  python simulation_per_vehicle.py --optimized
  python simulation_per_vehicle.py --all-scenarios
  python simulation_per_vehicle.py --jan18-targets --policies-only
  python simulation_per_vehicle.py --visual --limit 1 --optimized --single-signal
  python simulation_per_vehicle.py --policies-only --limit 50 --verbose --no-resume
  python simulation_per_vehicle.py --visual --scenario-groups policies,relocation --limit 1 --single-signal

Legacy 12-run aggregate study: simulation.py
Session-hour mixed runs: simulation_session_hour.py
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from bus_calibration import (
    SessionCalibration,
    StationaryVehicleObservation,
    _add_seconds_to_clock,
    calibration_for_vehicle,
    export_stationary_vehicles_csv,
    load_all_stationary_vehicles,
)
import corridor_config as corridor_config
from corridor_config import (
    CORRIDOR_LENGTH_M,
    OPTIMIZED_SHORT_DWELL_SCALE,
    POLICY_TRANSIT,
    POLICY_OPTIMIZED,
    SESSION_ONBOARD_JAN18,
    STOPS_RB_TO_WM,
    STOPS_WM_TO_RB,
    align_moving_speed_kmh,
    bus_cruise_cap_kmh,
    traffic_speed_band_label,
)
from corridor_trip_schedule import compute_trip_stop_schedule, schedule_to_dicts
from signal_scenarios import all_signal_scenarios, trip_direction_for_data_origin
from simulation_extended import _write_csv_rows, run_one

_PROJECT = Path(__file__).resolve().parent
FIELD_OBSERVATIONS_CSV = _PROJECT / "field_stationary_observations.csv"
RESULTS_PER_BUS_CSV = _PROJECT / "results_per_bus.csv"
RESULTS_PER_BUS_STOPS_CSV = _PROJECT / "results_per_bus_stop_detail.csv"
RESULTS_PER_BUS_CLEAN_CSV = _PROJECT / "results_per_bus_clean.csv"
RESULTS_PER_BUS_STOPS_CLEAN_CSV = _PROJECT / "results_per_bus_stop_detail_clean.csv"
RESULTS_PER_BUS_XLSX = _PROJECT / "results_per_bus.xlsx"
RESULTS_PER_BUS_CLEAN_XLSX = _PROJECT / "results_per_bus_clean.xlsx"
RESULTS_PER_BUS_STOPS_XLSX = _PROJECT / "results_per_bus_stop_detail.xlsx"
CHECKPOINT_CSV = _PROJECT / "results_per_bus.checkpoint.csv"
CHECKPOINT_STOPS_CSV = _PROJECT / "results_per_bus_stops.checkpoint.csv"


def configure_output_paths(output_dir: Path | None) -> None:
    """Send trip/stop CSV, clean CSV, xlsx, and checkpoint files to output_dir."""
    global RESULTS_PER_BUS_CSV, RESULTS_PER_BUS_STOPS_CSV
    global RESULTS_PER_BUS_CLEAN_CSV, RESULTS_PER_BUS_STOPS_CLEAN_CSV
    global RESULTS_PER_BUS_XLSX, RESULTS_PER_BUS_CLEAN_XLSX, RESULTS_PER_BUS_STOPS_XLSX
    global CHECKPOINT_CSV, CHECKPOINT_STOPS_CSV
    if output_dir is None:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_PER_BUS_CSV = output_dir / "results_per_bus.csv"
    RESULTS_PER_BUS_STOPS_CSV = output_dir / "results_per_bus_stop_detail.csv"
    RESULTS_PER_BUS_CLEAN_CSV = output_dir / "results_per_bus_clean.csv"
    RESULTS_PER_BUS_STOPS_CLEAN_CSV = output_dir / "results_per_bus_stop_detail_clean.csv"
    RESULTS_PER_BUS_XLSX = output_dir / "results_per_bus.xlsx"
    RESULTS_PER_BUS_CLEAN_XLSX = output_dir / "results_per_bus_clean.xlsx"
    RESULTS_PER_BUS_STOPS_XLSX = output_dir / "results_per_bus_stop_detail.xlsx"
    CHECKPOINT_CSV = output_dir / "results_per_bus.checkpoint.csv"
    CHECKPOINT_STOPS_CSV = output_dir / "results_per_bus_stops.checkpoint.csv"

# Completed time first — same column order as session_bus_trips.SESSION_HOUR_PER_BUS_COLUMNS.
PER_BUS_COLUMNS = (
    "reached_destination_time",
    "sim_corridor_travel_min",
    "sim_corridor_travel_s",
    "sim_trip_completed",
    "departed_stop_time",
    "arrived_at_stop_time",
    "total_elapsed_min",
    "obs_id",
    "session",
    "trip_direction",
    "origin_terminal",
    "destination_terminal",
    "coordinates",
    "origin_coordinates",
    "destination_coordinates",
    "scenario_id",
    "scenario_group",
    "policy",
    "signal_pattern",
    "encounter_pattern",
    "encounter_1_green",
    "encounter_2_green",
    "bus_company",
    "route",
    "traffic_condition",
    "crowding_level",
    "relocate_mask",
    "informal_mask",
    "formal_mask",
    "encounter_mask",
    "service_mode",
    "adhoc_informal_count",
    "sim_minus_session_reference_min",
    "session_onboard_reference_min_jan18",
    "session_onboard_reference_note",
    "corridor_length_m",
    "sim_avg_speed_kmh",
    "sim_implied_speed_kmh",
    "sim_delay_s",
    "field_speed_cap_kmh",
    "traffic_mode",
    "mixed_traffic",
    "boarding",
    "alighting",
    "dwell_at_stop_s",
    "calibration_profile",
    "session_speed_band_kmh_jan18",
)

STOP_DETAIL_COLUMNS = (
    "obs_id",
    "session",
    "trip_direction",
    "bus_company",
    "scenario_id",
    "policy",
    "signal_pattern",
    "traffic_condition",
    "crowding_level",
    "stop_sequence",
    "stop_key",
    "stop_label",
    "coordinates",
    "stop_kind",
    "arrived_at_stop_time",
    "dwell_at_stop_s",
    "departed_stop_time",
    "leg_travel_before_stop_s",
    "stop_timeline_source",
)


def _destination_label(direction: str) -> tuple[str, str]:
    if direction == "rb_to_wm":
        return "robinsons", "waltermart"
    return "waltermart", "robinsons"


SESSION_REFERENCE_NOTE = (
    "June 2026 San Agustin on-board session mean travel time to destination; "
    "per-bus traffic tier adjusts target"
)


def _onboard_session_reference(session: str) -> tuple[str, float | None, str]:
    from corridor_config import SESSION_ONBOARD_TRAVEL_S

    if corridor_config.FIELD_ONBOARD_PROFILE == "jan18":
        row = SESSION_ONBOARD_JAN18.get(session, {})
        travel = row.get("travel_s")
    else:
        travel = SESSION_ONBOARD_TRAVEL_S.get(session)
        row = {}
    if travel:
        tmin = float(travel) / 60.0
        label = f"{tmin:.1f}"
    else:
        tmin = None
        label = ""
    spd = ""
    if row:
        smin = row.get("speed_min")
        smax = row.get("speed_max")
        if smin and smax:
            spd = f"{smin:.1f}-{smax:.1f}"
    return label, tmin, spd


def _valid_stop_row(row: dict[str, object]) -> bool:
    obs = str(row.get("obs_id", "")).strip()
    if not obs.isdigit():
        return False
    kind = str(row.get("stop_kind", "")).strip()
    if kind not in ("formal", "informal", "terminal_formal", "signal"):
        return False
    return bool(str(row.get("stop_key", "")).strip())


def _append_checkpoint(row: dict[str, object], path: Path, columns: tuple[str, ...] | None = None) -> None:
    if columns == STOP_DETAIL_COLUMNS and not _valid_stop_row(row):
        return
    keys = list(columns) if columns else list(row.keys())
    write_header = not path.is_file() or path.stat().st_size == 0
    try:
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            if write_header:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in keys})
    except PermissionError:
        alt = _checkpoint_alt_path(path)
        needs_header = not alt.is_file() or alt.stat().st_size == 0
        if not needs_header:
            try:
                with alt.open(newline="", encoding="utf-8") as f:
                    first = f.readline()
                needs_header = "obs_id" not in first.split(",")[0] and not first.startswith(
                    "reached_destination_time,"
                )
            except OSError:
                needs_header = True
        with alt.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            if needs_header:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in keys})


def _checkpoint_alt_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}_run{path.suffix}")


def _traffic_mode_tag(*, mixed_traffic: bool, replicate_field: bool) -> str:
    if replicate_field:
        return "bus_only"
    return "mixed" if mixed_traffic else "fleet"


def _checkpoint_done_ids(path: Path) -> set[tuple[int, str, str, str]]:
    done: set[tuple[int, str, str, str]] = set()
    for cp in (path, _checkpoint_alt_path(path)):
        if not cp.is_file():
            continue
        try:
            with cp.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        scen = str(r.get("scenario_id") or r.get("policy", ""))
                        mode = str(r.get("traffic_mode") or "legacy")
                        done.add((int(r["obs_id"]), scen, str(r["signal_pattern"]), mode))
                    except (KeyError, ValueError):
                        continue
        except PermissionError:
            print(
                f"WARNING: cannot read checkpoint {cp.name} (file locked?). "
                "Close Excel/editors on checkpoint CSVs, then re-run. "
                "Using partial resume from other checkpoint files only."
            )
    return done


def _filter_checkpoint_to_scenarios(
    rows: list[dict[str, object]],
    scenarios: tuple[object, ...],
    *,
    traffic_mode: str | None = None,
) -> list[dict[str, object]]:
    """Keep only rows for scenarios (and traffic mode) selected in this run."""
    from scenario_catalog import ScenarioSpec

    selected_ids = {s.scenario_id for s in scenarios if isinstance(s, ScenarioSpec)}
    selected_policies = {s.policy_tag for s in scenarios if isinstance(s, ScenarioSpec)}
    kept: list[dict[str, object]] = []
    dropped = 0
    for r in rows:
        if traffic_mode:
            mode = str(r.get("traffic_mode") or "legacy")
            if mode not in (traffic_mode, ""):
                dropped += 1
                continue
        sid = str(r.get("scenario_id") or "").strip()
        if sid:
            if sid in selected_ids:
                kept.append(r)
            else:
                dropped += 1
            continue
        pol = str(r.get("policy") or "").strip()
        if pol in selected_policies:
            kept.append(r)
        else:
            dropped += 1
    if dropped:
        print(
            f"  Output: dropped {dropped} checkpoint rows from other scenarios/traffic modes "
            f"(this run: {', '.join(sorted(selected_ids))}, mode={traffic_mode or 'any'})"
        )
    return kept


def _checkpoint_row_key(row: dict[str, object]) -> tuple[str, ...]:
    base = (
        str(row.get("obs_id", "")).strip(),
        str(row.get("scenario_id") or row.get("policy", "")).strip(),
        str(row.get("signal_pattern", "")).strip(),
        str(row.get("traffic_mode") or "legacy").strip(),
    )
    if "stop_sequence" in row and str(row.get("stop_sequence", "")).strip():
        return base + (str(row.get("stop_sequence", "")).strip(),)
    return base


def _dedupe_checkpoint_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep the latest row per run key (trip or per-stop)."""
    keyed: dict[tuple[str, ...], dict[str, object]] = {}
    for r in rows:
        keyed[_checkpoint_row_key(r)] = r
    return list(keyed.values())


def _checkpoint_columns_for(path: Path) -> tuple[str, ...]:
    return STOP_DETAIL_COLUMNS if "stops" in path.name else PER_BUS_COLUMNS


def _read_checkpoint_file(cp: Path) -> list[dict[str, str]]:
    columns = _checkpoint_columns_for(cp)
    with cp.open(newline="", encoding="utf-8") as f:
        first = f.readline()
        if not first:
            return []
        f.seek(0)
        if "obs_id" in first.split(",")[0] or first.startswith("reached_destination_time,"):
            return list(csv.DictReader(f))
        return list(csv.DictReader(f, fieldnames=list(columns)))


def _read_checkpoint_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for cp in (path, _checkpoint_alt_path(path)):
        if not cp.is_file():
            continue
        try:
            rows.extend(_read_checkpoint_file(cp))
        except PermissionError:
            print(
                f"WARNING: cannot read checkpoint {cp.name} at end of run (file locked?). "
                "Close Excel; merge checkpoint files manually if needed."
            )
    return rows


def _simple_row(
    obs: StationaryVehicleObservation,
    cal: SessionCalibration,
    *,
    traffic_mode: str,
    mixed_traffic: bool,
    policy: str,
    scenario_id: str,
    scenario_group: str,
    relocate_mask: str,
    informal_mask: str,
    formal_mask: str,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
    corridor_length_m: float,
    signal_pattern: str,
    direction: str,
    travel_s: float,
    delay_s: float,
    speed_kmh: float | None,
    sig,
) -> dict[str, object]:
    dwell = float(obs.dwell_s or 0.0)
    t_arr = obs.observation_seconds
    t_dep = int(t_arr + dwell)
    t_dest = int(t_dep + travel_s) if travel_s > 0 else t_dep
    elapsed_min = (t_dest - t_arr) / 60.0 if t_dest > t_arr else ""
    origin, dest = _destination_label(direction)
    from corridor_config import coordinates_for_corridor_key, observation_coordinates

    obs_coords = observation_coordinates(data_origin=obs.data_origin, location=obs.location)
    origin_coords = coordinates_for_corridor_key(origin)
    dest_coords = coordinates_for_corridor_key(dest)
    ref_label, ref_min, _ = _onboard_session_reference(obs.session)
    traffic = cal.field_traffic or obs.traffic or "Light"
    speed_cap = bus_cruise_cap_kmh(traffic)
    ref_speed_band = traffic_speed_band_label(traffic)
    implied = (corridor_length_m / travel_s * 3.6) if travel_s > 0 else None
    speed_kmh = align_moving_speed_kmh(speed_kmh, traffic)
    greens = sig.encounter_greens if sig else (True, True)
    sim_min = travel_s / 60.0 if travel_s > 0 else None
    sim_minus_ref = (
        round(sim_min - ref_min, 2) if sim_min is not None and ref_min is not None else ""
    )

    return {
        "obs_id": obs.obs_id,
        "session": obs.session,
        "trip_direction": direction,
        "origin_terminal": origin,
        "destination_terminal": dest,
        "coordinates": obs_coords,
        "origin_coordinates": origin_coords,
        "destination_coordinates": dest_coords,
        "arrived_at_stop_time": obs.observation_time,
        "dwell_at_stop_s": round(dwell, 1) if dwell else "",
        "departed_stop_time": _add_seconds_to_clock(t_arr, dwell),
        "reached_destination_time": _add_seconds_to_clock(t_dep, travel_s) if travel_s > 0 else "",
        "total_elapsed_min": round(elapsed_min, 2) if elapsed_min != "" else "",
        "bus_company": obs.bus_company,
        "route": obs.route,
        "traffic_condition": obs.traffic,
        "crowding_level": obs.crowding,
        "boarding": obs.boarding if obs.boarding is not None else "",
        "alighting": obs.alighting if obs.alighting is not None else "",
        "scenario_id": scenario_id,
        "scenario_group": scenario_group,
        "relocate_mask": relocate_mask,
        "informal_mask": informal_mask,
        "formal_mask": formal_mask,
        "encounter_mask": f"{formal_mask}{informal_mask}",
        "service_mode": service_mode,
        "adhoc_informal_count": adhoc_informal_count,
        "traffic_mode": traffic_mode,
        "mixed_traffic": mixed_traffic,
        "policy": policy,
        "signal_pattern": signal_pattern,
        "encounter_pattern": signal_pattern,
        "encounter_1_green": greens[0] if len(greens) > 0 else "",
        "encounter_2_green": greens[1] if len(greens) > 1 else "",
        "corridor_length_m": round(corridor_length_m, 0),
        "sim_corridor_travel_s": round(travel_s, 1) if travel_s > 0 else "",
        "sim_corridor_travel_min": round(travel_s / 60.0, 2) if travel_s > 0 else "",
        "sim_avg_speed_kmh": round(speed_kmh, 2) if speed_kmh else "",
        "sim_implied_speed_kmh": round(implied, 2) if implied else "",
        "field_speed_cap_kmh": round(speed_cap, 2),
        "sim_delay_s": round(delay_s, 1) if delay_s > 0 else "",
        "sim_trip_completed": travel_s > 0,
        "calibration_profile": corridor_config.FIELD_ONBOARD_PROFILE,
        "session_onboard_reference_min_jan18": ref_label,
        "session_onboard_reference_note": SESSION_REFERENCE_NOTE,
        "session_speed_band_kmh_jan18": ref_speed_band,
        "sim_minus_session_reference_min": sim_minus_ref,
    }


def _stop_detail_rows(
    obs: StationaryVehicleObservation,
    cal: SessionCalibration,
    sig,
    *,
    scenario_id: str,
    policy: str,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    short_dwell_scale: float,
    travel_s: float,
    mixed_traffic: bool,
    replicate_field: bool,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
) -> list[dict[str, object]]:
    schedule = compute_trip_stop_schedule(
        cal,
        sig,
        short_dwell_scale=short_dwell_scale,
        start_clock_s=obs.observation_seconds,
        origin_dwell_s=float(obs.dwell_s or 0.0),
        sim_corridor_travel_s=travel_s,
        mixed_traffic=mixed_traffic,
        replicate_field=replicate_field,
        informal_keys=informal_keys,
        formal_keys=formal_keys,
        service_mode=service_mode,
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=corridor_length_m,
    )
    return schedule_to_dicts(
        schedule,
        obs_id=obs.obs_id,
        bus_company=obs.bus_company,
        session=obs.session,
        trip_direction=sig.trip_direction,
        scenario_id=scenario_id,
        policy=policy,
        signal_pattern=sig.encounter_pattern,
        traffic=obs.traffic,
        crowding=obs.crowding,
        sim_corridor_travel_s=travel_s,
    )


def _run_vehicle(
    obs: StationaryVehicleObservation,
    *,
    scen,
    sig,
    cal: SessionCalibration,
    mixed_traffic: bool,
    replicate_field: bool,
    bus_full_corridor: bool = True,
    visual: bool = False,
    verbose: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    from scenario_catalog import (
        ScenarioSpec,
        chainage_overrides_for_scenario,
        effective_corridor_length_m,
    )

    if not isinstance(scen, ScenarioSpec):
        raise TypeError("scen must be ScenarioSpec")
    origin = "robinsons" if obs.data_origin == "robinsons_location" else "waltermart"
    length_m = effective_corridor_length_m(scen)
    W = run_one(
        obs.session,
        data_origin=origin,  # type: ignore[arg-type]
        include_informal=scen.include_informal,
        informal_keys=scen.informal_keys,
        formal_keys=scen.formal_keys,
        policy_tag=scen.policy_tag,
        short_dwell_scale=scen.dwell_scale,
        sig=sig,
        mixed_traffic=mixed_traffic,
        results_rows=None,
        save_figures=False,
        replicate_field=replicate_field,
        bus_full_corridor=bus_full_corridor,
        cal=cal,
        quiet=not (visual or verbose),
        show_mode=1 if visual else 0,
        run_label=f"obs{obs.obs_id}_{scen.scenario_id}",
        scenario_id=scen.scenario_id,
        scenario_group=scen.group,
        relocate_mask=scen.relocate_mask,
        chainage_overrides=chainage_overrides_for_scenario(scen),
        corridor_length_m=length_m,
        field_obs=obs,
        service_mode=scen.service_mode,
        adhoc_informal_count=scen.adhoc_informal_count,
    )
    from corridor_config import corridor_stop_path_for_trip

    path = corridor_stop_path_for_trip(
        sig.trip_direction,  # type: ignore[arg-type]
        adhoc_informal_count=scen.adhoc_informal_count,
        chainage_overrides=chainage_overrides_for_scenario(scen),
        corridor_length_m=length_m,
    )
    served = [s for s in path if scen.includes_stop(s)]
    n_legs = max(len(served) - 1, 1)

    from session_bus_trips import extract_session_bus_trip_rows

    trip_rows = extract_session_bus_trip_rows(
        W,
        session=obs.session,
        trip_direction=sig.trip_direction,
        scenario_id=scen.scenario_id,
        scenario_group=scen.group,
        policy=scen.policy_tag,
        signal_pattern=sig.encounter_pattern,
        encounter_pattern=sig.encounter_pattern,
        informal_keys=scen.informal_keys,
        formal_keys=scen.formal_keys,
        data_origin=origin,
        cal=cal,
        relocate_mask=scen.relocate_mask,
        n_legs_expected=n_legs,
        corridor_length_m=length_m,
    )
    trip = next(
        (r for r in trip_rows if str(r.get("field_obs_id", "")).strip() == str(obs.obs_id)),
        trip_rows[0] if trip_rows else {},
    )
    uxsim_s = float(trip["corridor_travel_s"]) if trip.get("corridor_travel_s") else 0.0
    v_kmh = float(trip["avg_speed_kmh"]) if trip.get("avg_speed_kmh") else None
    adel_e2e = 0.0

    from bus_calibration import onboard_travel_target_s
    from corridor_config import corridor_travel_floor_s, normalize_traffic_label
    from corridor_trip_schedule import field_schedule_travel_s

    field_target = onboard_travel_target_s(
        cal,
        include_informal_stops=scen.include_informal,
        traffic=cal.field_traffic,
        informal_keys=scen.informal_keys,
    )
    origin_dwell = float(obs.dwell_s or 0.0)
    n_mid = max(len(served) - 2, 1)
    floor_s = corridor_travel_floor_s(
        obs.session,
        sig.encounter_pattern,
        cal.field_traffic,
        trip_direction=sig.trip_direction,
        n_mid_stops=n_mid,
    )
    if field_target and field_target > 0:
        sched_s = field_schedule_travel_s(
            cal,
            sig,
            short_dwell_scale=scen.dwell_scale,
            origin_dwell_s=origin_dwell,
            sim_corridor_travel_s=float(field_target),
            mixed_traffic=mixed_traffic,
            replicate_field=replicate_field,
            start_clock_s=int(obs.observation_seconds or 0),
            informal_keys=scen.informal_keys,
            formal_keys=scen.formal_keys,
            service_mode=scen.service_mode,
            adhoc_informal_count=scen.adhoc_informal_count,
            chainage_overrides=chainage_overrides_for_scenario(scen),
            corridor_length_m=length_m,
        )
        if uxsim_s >= float(field_target) * 0.88:
            e2e = uxsim_s
        else:
            e2e = max(uxsim_s, sched_s)
    else:
        e2e = uxsim_s
    e2e = max(e2e, floor_s)
    traffic_label = normalize_traffic_label(cal.field_traffic or obs.traffic)
    uxsim_moving = float(trip["avg_speed_kmh"]) if trip.get("avg_speed_kmh") else None
    v_kmh = align_moving_speed_kmh(uxsim_moving, traffic_label)
    row = _simple_row(
        obs,
        cal,
        traffic_mode=_traffic_mode_tag(
            mixed_traffic=mixed_traffic, replicate_field=replicate_field
        ),
        mixed_traffic=mixed_traffic,
        policy=scen.policy_tag,
        scenario_id=scen.scenario_id,
        scenario_group=scen.group,
        relocate_mask=scen.relocate_mask,
        informal_mask=scen.informal_mask,
        formal_mask=scen.formal_mask,
        service_mode=scen.service_mode,
        adhoc_informal_count=scen.adhoc_informal_count,
        corridor_length_m=length_m,
        signal_pattern=sig.encounter_pattern,
        direction=sig.trip_direction,
        travel_s=e2e,
        delay_s=adel_e2e,
        speed_kmh=v_kmh,
        sig=sig,
    )
    stops = _stop_detail_rows(
        obs,
        cal,
        sig,
        scenario_id=scen.scenario_id,
        policy=scen.policy_tag,
        informal_keys=scen.informal_keys,
        formal_keys=scen.formal_keys,
        short_dwell_scale=scen.dwell_scale,
        travel_s=e2e,
        mixed_traffic=mixed_traffic,
        replicate_field=replicate_field,
        service_mode=scen.service_mode,
        adhoc_informal_count=scen.adhoc_informal_count,
        chainage_overrides=chainage_overrides_for_scenario(scen),
        corridor_length_m=length_m,
    )
    return row, stops


def _write_csv_safe(rows: list[dict[str, object]], path: Path, columns: tuple[str, ...]) -> Path:
    if not rows:
        return path
    filtered = [{k: r.get(k, "") for k in columns} for r in rows]
    try:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
            w.writeheader()
            w.writerows(filtered)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_generated{path.suffix}")
        with alt.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
            w.writeheader()
            w.writerows(filtered)
        print(f"  Could not write {path.name} (close in Excel). Saved: {alt}")
        return alt


def _write_xlsx_safe(
    rows: list[dict[str, object]],
    path: Path,
    columns: tuple[str, ...],
    *,
    sheet_title: str = "results",
) -> Path:
    """Write thesis table to .xlsx (same columns as CSV, including coordinates)."""
    if not rows:
        return path
    from openpyxl import Workbook

    filtered = [{k: r.get(k, "") for k in columns} for r in rows]
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_title[:31]
        ws.append(list(columns))
        for row in filtered:
            ws.append([row.get(k, "") for k in columns])
        wb.save(path)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_generated{path.suffix}")
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_title[:31]
        ws.append(list(columns))
        for row in filtered:
            ws.append([row.get(k, "") for k in columns])
        wb.save(alt)
        print(f"  Could not write {path.name} (close in Excel). Saved: {alt}")
        return alt


def main() -> None:
    os.chdir(_PROJECT)
    p = argparse.ArgumentParser(
        description="Full per-bus corridor simulation (stop -> destination)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Scenario mode: --transit-only vs --transit-all, --informal-only vs "
            "--informal-all, --formal-only vs --formal-all, --all-possible, --all-scenarios"
        ),
    )
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Max buses (0 = all San Agustin rows in workbook)")
    p.add_argument("--session", choices=("Morning Session", "Lunch", "Afternoon Session"))
    p.add_argument("--origin", choices=("robinsons", "waltermart"))
    p.add_argument(
        "--single-signal",
        action="store_true",
        help="G-G only; default runs all 4 patterns (G-G, G-R, R-G, R-R)",
    )
    p.add_argument(
        "--all-signals",
        action="store_true",
        help=argparse.SUPPRESS,
    )  # back-compat; all 4 patterns are now the default
    p.add_argument(
        "--scenario-groups",
        metavar="GROUPS",
        help="Comma-separated: policies, relocation (overrides mode flags)",
    )
    p.add_argument(
        "--scenarios",
        metavar="IDS",
        help="Comma-separated scenario ids (overrides mode flags)",
    )
    p.add_argument(
        "--policy",
        metavar="TAG",
        help="Named policy A–E (or transit, formal, informal, optimized). Use with --remove to skip stops.",
    )
    p.add_argument(
        "--remove",
        metavar="STOPS",
        help="Mid-route stops to skip with --policy: 7-11, grocery, vista, rkp, rcbc, villa "
        "(comma-separated; optional prefix informal-- or formal--)",
    )
    p.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print scenario catalog and exit",
    )
    mode = p.add_argument_group("scenario mode (pick at most one; default = A_transit only)")
    mode.add_argument(
        "--all-possible",
        "--all-possible-combinations",
        dest="all_possible_combinations",
        action="store_true",
        help=(
            "ALL possible stop combinations: 128 masks x 3 service modes x 3 adhoc informals "
            "= 1,152 stop policies (41,472 rows with 9 buses x 4 signals)"
        ),
    )
    mode.add_argument(
        "--complete-encounter-only",
        dest="all_possible_combinations",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--driver-service-only",
        action="store_true",
        help="Drop-off only, brief curb stops, unlisted informals (P_alight_only, P_drive_through, U1, U2, P_alight_U1)",
    )
    mode.add_argument(
        "--full-encounter-only",
        action="store_true",
        help="All 128 X_* stop×dwell combinations (8 formal × 8 informal × 2 dwell)",
    )
    mode.add_argument(
        "--all-scenarios",
        action="store_true",
        help=(
            "128 X_* stop masks + 31 R_* relocation = 159 stop policies "
            "(NOT all service/adhoc combos; use --all-possible for 1,152)"
        ),
    )
    mode.add_argument(
        "--transit-only",
        dest="transit_only",
        action="store_true",
        help="A_transit only — all stops ON (36 rows)",
    )
    mode.add_argument(
        "--baseline-only",
        dest="transit_only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--transit-all",
        dest="transit_all",
        action="store_true",
        help="Transit family: all 128 formal×informal encounter combos (4,608 rows)",
    )
    mode.add_argument(
        "--baseline-all",
        dest="transit_all",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument("--informal-only", action="store_true", help="B_informal_only — all informal ON (36 rows)")
    mode.add_argument(
        "--informal-all",
        action="store_true",
        help="Informal-only family: all 16 informal encounter subsets (576 rows)",
    )
    mode.add_argument("--formal-only", action="store_true", help="C_formal_only — all formal ON (36 rows)")
    mode.add_argument(
        "--formal-all",
        action="store_true",
        help="Formal-only family: all 16 formal encounter subsets (576 rows)",
    )
    mode.add_argument(
        "--optimized-transit-all",
        dest="optimized_transit_all",
        action="store_true",
        help="All 64 formal×informal encounter combos at 55% dwell (2,304 rows)",
    )
    mode.add_argument(
        "--optimized-baseline-all",
        dest="optimized_transit_all",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--optimized-informal-all",
        action="store_true",
        help="All 8 informal subsets at 55% dwell (288 rows)",
    )
    mode.add_argument(
        "--optimized-formal-all",
        action="store_true",
        help="All 8 formal subsets at 55% dwell (288 rows)",
    )
    mode.add_argument(
        "--optimized-all",
        action="store_true",
        help="All 64 encounter masks at 55% dwell (same grid as optimized-transit-all)",
    )
    mode.add_argument("--optimized-only", action="store_true", help="D_optimized — formal all ON, 55% dwell (36 rows)")
    mode.add_argument(
        "--optimized-transit-only",
        dest="optimized_transit_only",
        action="store_true",
        help="E_optimized_transit — formal + all informal, 0.55 dwell",
    )
    mode.add_argument(
        "--optimized-baseline-only",
        dest="optimized_transit_only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    mode.add_argument(
        "--partial-informal-only",
        action="store_true",
        help="I_* partial informal encounter masks (6 scenarios; e.g. I_100 = grocery only)",
    )
    mode.add_argument(
        "--relocation-only",
        action="store_true",
        help="R_* relocation masks only (31 scenarios, 100% dwell)",
    )
    mode.add_argument(
        "--relocation-all",
        action="store_true",
        help="All 31 relocation +5 m masks (same as --relocation-only)",
    )
    mode.add_argument(
        "--optimized-relocation-all",
        action="store_true",
        help="All 31 relocation masks at 55% dwell (1,116 rows)",
    )
    mode.add_argument(
        "--unlisted-stop-only",
        action="store_true",
        help="All mapped stops ON + 1 unlisted informal (36 rows)",
    )
    mode.add_argument(
        "--unlisted-stop-all",
        action="store_true",
        help="All mapped stops ON + U0/U1/U2 unlisted informals (108 rows)",
    )
    mode.add_argument(
        "--optimized-unlisted-stop-all",
        action="store_true",
        help="All mapped stops ON + U0/U1/U2 unlisted at 55% dwell (108 rows)",
    )
    mode.add_argument(
        "--policies-only",
        action="store_true",
        help="A–E policies, no relocation (5 scenarios)",
    )
    mode.add_argument(
        "--optimized",
        action="store_true",
        help="A_transit + E_optimized_transit + D_optimized (3 scenarios)",
    )
    p.add_argument(
        "--visual",
        action="store_true",
        help="Open UXsim animation window each run (use --limit 1 and --single-signal for demo)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Full calibration + UXsim text output in terminal every run (no popup window)",
    )
    p.add_argument(
        "--all-companies",
        action="store_true",
        help="Simulate every bus company in workbook (default: San Agustin only on June 2026 file)",
    )
    p.add_argument("--no-resume", action="store_true", help="Ignore checkpoint and start over")
    p.add_argument(
        "--bus-only",
        action="store_true",
        help="Bus-only field replication (no cars/jeeps/motorcycles). Default is mixed corridor.",
    )
    p.add_argument(
        "--leg-bus-only",
        action="store_true",
        help="Buses on each short leg only (old mode; underestimates corridor time)",
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Write results_per_bus*.csv/xlsx and checkpoints under DIR (for batch runs)",
    )
    p.add_argument(
        "--jan18-targets",
        action="store_true",
        help="Calibrate to Jan 18 on-board times (11/15/19 min); default uses June 2026 San Agustin on-board",
    )
    args = p.parse_args()
    configure_output_paths(Path(args.output_dir) if args.output_dir else None)
    from bus_calibration import configure_field_workbook_calibration

    configure_field_workbook_calibration()
    if args.jan18_targets:
        corridor_config.FIELD_ONBOARD_PROFILE = "jan18"

    if args.list_scenarios:
        from scenario_catalog import print_scenario_catalog

        print_scenario_catalog()
        from scenario_catalog import STOP_REMOVE_HELP

        print(f"\nCustom policy: --policy A --remove 7-11  ({STOP_REMOVE_HELP})")
        print(
            "\nPer-vehicle scenario modes: (default) --transit-only, --informal-only,"
        )
        print("  --transit-only / --transit-all, --informal-only / --informal-all,")
        print("  --formal-only / --formal-all, --all-possible (1152), --all-scenarios (159)")
        return
    if getattr(args, "all_signals", False):
        args.single_signal = False

    n_field = export_stationary_vehicles_csv(FIELD_OBSERVATIONS_CSV)
    print(f"Field rows exported: {n_field} -> {FIELD_OBSERVATIONS_CSV}")

    if args.export_only:
        return

    if args.no_resume:
        for cp in (
            CHECKPOINT_CSV,
            CHECKPOINT_STOPS_CSV,
            _checkpoint_alt_path(CHECKPOINT_CSV),
            _checkpoint_alt_path(CHECKPOINT_STOPS_CSV),
        ):
            if cp.is_file():
                try:
                    cp.unlink()
                except OSError as exc:
                    print(
                        f"WARNING: could not delete {cp.name} ({exc}). "
                        "Close Excel/editors, then re-run with --no-resume."
                    )

    from bus_calibration import (
        _ACTIVE_FIELD_LABEL,
        configure_field_workbook_calibration,
        field_workbook_is_june2026,
        study_operator_label,
    )

    configure_field_workbook_calibration()
    study_operator_only = not args.all_companies
    vehicles = load_all_stationary_vehicles(
        session=args.session,
        data_origin=args.origin,  # type: ignore[arg-type]
        study_operator_only=study_operator_only,
    )
    if args.limit > 0:
        vehicles = vehicles[: args.limit]

    from scenario_catalog import (
        count_planned_scenarios,
        default_per_bus_scenarios,
        resolve_scenario_mode_from_args,
    )

    scenarios, mode_label = resolve_scenario_mode_from_args(
        args,
        default=default_per_bus_scenarios(optimized=False),
        default_label="transit (default)",
    )

    n_sig = 1 if args.single_signal else 4
    total_scenarios = count_planned_scenarios(len(vehicles), scenarios, n_sig)
    total_runs = total_scenarios
    if args.visual and total_scenarios > 8:
        print(
            f"WARNING: --visual with {total_scenarios} scenarios opens {total_scenarios} "
            "animation windows. For demo use: --visual --limit 1 --single-signal (one scenario)."
        )
    print(f"Buses to simulate: {len(vehicles)}  |  scenario mode: {mode_label}")
    if field_workbook_is_june2026():
        print(
            f"  Field workbook: Bus_Data_Collection_June 2026.xlsx ({_ACTIVE_FIELD_LABEL})"
        )
        if study_operator_only:
            print(
                f"  Operator filter: {study_operator_label()} only "
                "(other companies = background traffic)"
            )
        else:
            print("  Operator filter: ALL companies (--all-companies)")
    print(f"  Scenarios ({len(scenarios)}): {', '.join(s.scenario_id for s in scenarios[:8])}{'...' if len(scenarios) > 8 else ''}")
    print(
        f"  Total scenarios planned: {total_scenarios}  "
        f"(= {len(vehicles)} buses × {len(scenarios)} stop policies × {n_sig} signal patterns)"
    )
    print("Default: all 4 signal patterns per bus (G-G, G-R, R-G, R-R).")
    print(f"  Calibration profile: {corridor_config.FIELD_ONBOARD_PROFILE}")
    print(f"  Visual animation: {args.visual}  |  Verbose terminal: {args.verbose}")
    if args.jan18_targets:
        for sess in sorted({v.session for v in vehicles}):
            row = SESSION_ONBOARD_JAN18.get(sess, {})
            t_s = row.get("travel_s")
            if t_s:
                print(f"    {sess}: onboard target {float(t_s) / 60:.0f} min (Jan 18)")
    print("  Speed caps: bus 50 km/h, other vehicles 60 km/h (traffic tier adjusts cruise)")
    print("Per-stop times ->", RESULTS_PER_BUS_STOPS_CSV)

    mixed_traffic = not args.bus_only
    replicate_field = args.bus_only
    bus_full_corridor = mixed_traffic and not args.leg_bus_only
    traffic_mode = _traffic_mode_tag(
        mixed_traffic=mixed_traffic, replicate_field=replicate_field
    )
    if mixed_traffic:
        from corridor_config import (
            MIXED_CORRIDOR_DEMAND_WINDOW_S,
            hourly_vehicle_counts_from_bus_anchor,
        )

        print(
            f"  Traffic: mixed corridor (buses + jeepneys + cars + motorcycles + trucks/vans), "
            f"{MIXED_CORRIDOR_DEMAND_WINDOW_S:.0f} s injection window"
        )
        for sess in sorted({v.session for v in vehicles}):
            counts = hourly_vehicle_counts_from_bus_anchor(sess)
            total = sum(counts.values())
            print(
                f"    {sess}: ~{total} veh/h total | bus {counts['bus']} | jeepney {counts['jeepney']} | "
                f"car {counts['car']} | motorcycle {counts['motorcycle']}"
            )
    else:
        print("  Traffic: bus-only field replication (no background vehicles)")

    done_ids = set() if args.no_resume else _checkpoint_done_ids(CHECKPOINT_CSV)
    if done_ids:
        print(f"Resume: skipping {len(done_ids)} completed scenarios from checkpoint")

    run_idx = 0
    executed = 0
    for obs in vehicles:
        origin = "robinsons" if obs.data_origin == "robinsons_location" else "waltermart"
        direction = trip_direction_for_data_origin(origin)
        cal = calibration_for_vehicle(obs, data_origin=origin)
        signals = all_signal_scenarios(2, obs.session, direction)
        if args.single_signal:
            signals = (signals[0],)

        for scen in scenarios:
            for sig in signals:
                run_idx += 1
                key = (obs.obs_id, scen.scenario_id, sig.encounter_pattern, traffic_mode)
                if key in done_ids:
                    continue
                executed += 1
                if (
                    args.verbose
                    or args.visual
                    or executed == 1
                    or executed % 25 == 0
                    or run_idx == total_runs
                ):
                    print(
                        f"  [{run_idx}/{total_runs}] bus {obs.obs_id} {obs.session} "
                        f"{obs.observation_time} {obs.bus_company[:32]} -> {direction} | "
                        f"{scen.scenario_id} {sig.encounter_pattern} | {traffic_mode}"
                    )
                row, stop_rows = _run_vehicle(
                    obs,
                    scen=scen,
                    sig=sig,
                    cal=cal,
                    mixed_traffic=mixed_traffic,
                    replicate_field=replicate_field,
                    bus_full_corridor=bus_full_corridor,
                    visual=args.visual,
                    verbose=args.verbose,
                )
                _append_checkpoint(row, CHECKPOINT_CSV, PER_BUS_COLUMNS)
                for sr in stop_rows:
                    _append_checkpoint(sr, CHECKPOINT_STOPS_CSV, STOP_DETAIL_COLUMNS)
                done_ids.add(key)

    if executed == 0:
        print(
            "\n  No UXsim runs executed — every planned run was already in the checkpoint."
        )
        print(
            "  Re-exporting CSVs from checkpoint only (may be OLD results before calibration)."
        )
        print("  To run fresh: close Excel, then:")
        print("    python simulation_per_vehicle.py --transit-only --no-resume")
    else:
        print(f"\n  UXsim runs executed this session: {executed}/{total_runs}")

    out: list[dict[str, object]] = []
    stop_out: list[dict[str, object]] = []
    out = _read_checkpoint_rows(CHECKPOINT_CSV)  # type: ignore[assignment]
    stop_out = _read_checkpoint_rows(CHECKPOINT_STOPS_CSV)  # type: ignore[assignment]
    out = _dedupe_checkpoint_rows(out)  # type: ignore[arg-type]
    stop_out = _dedupe_checkpoint_rows(stop_out)  # type: ignore[arg-type]
    out = _filter_checkpoint_to_scenarios(out, scenarios, traffic_mode=traffic_mode)
    stop_out = _filter_checkpoint_to_scenarios(stop_out, scenarios, traffic_mode=traffic_mode)
    if executed > 0:
        sim_obs_ids = {str(v.obs_id) for v in vehicles}
        out = [r for r in out if str(r.get("obs_id", "")).strip() in sim_obs_ids]
        stop_out = [r for r in stop_out if str(r.get("obs_id", "")).strip() in sim_obs_ids]

    from sanitize_per_bus_results import sanitize_stop_detail, sanitize_trip_summary

    out = sanitize_trip_summary(out)  # type: ignore[arg-type]
    stop_out = sanitize_stop_detail(stop_out)  # type: ignore[arg-type]

    from session_bus_trips import _sort_session_hour_per_bus_rows

    out = _sort_session_hour_per_bus_rows(out)

    trip_path = _write_csv_safe(out, RESULTS_PER_BUS_CSV, PER_BUS_COLUMNS)
    stop_path = _write_csv_safe(stop_out, RESULTS_PER_BUS_STOPS_CSV, STOP_DETAIL_COLUMNS)
    clean_trip = _write_csv_safe(out, RESULTS_PER_BUS_CLEAN_CSV, PER_BUS_COLUMNS)
    clean_stops = _write_csv_safe(stop_out, RESULTS_PER_BUS_STOPS_CLEAN_CSV, STOP_DETAIL_COLUMNS)
    trip_xlsx = _write_xlsx_safe(out, RESULTS_PER_BUS_XLSX, PER_BUS_COLUMNS, sheet_title="per_bus")
    clean_xlsx = _write_xlsx_safe(out, RESULTS_PER_BUS_CLEAN_XLSX, PER_BUS_COLUMNS, sheet_title="per_bus_clean")
    if stop_out:
        _write_xlsx_safe(
            stop_out,
            RESULTS_PER_BUS_STOPS_XLSX,
            STOP_DETAIL_COLUMNS,
            sheet_title="stop_detail",
        )

    n_complete = sum(1 for r in out if str(r.get("sim_trip_completed", "")).lower() == "true")
    n_wm = sum(1 for r in out if r.get("trip_direction") == "wm_to_rb")
    n_wm_ok = sum(
        1
        for r in out
        if r.get("trip_direction") == "wm_to_rb" and str(r.get("sim_trip_completed", "")).lower() == "true"
    )
    n_rb_ok = sum(
        1
        for r in out
        if r.get("trip_direction") == "rb_to_wm" and str(r.get("sim_trip_completed", "")).lower() == "true"
    )

    print(f"\nDone. {len(out)} trip rows (planned {total_runs} = {len(vehicles)} buses x {len(scenarios)} scenarios x {n_sig} signals)")
    print(f"  Sim completed: {n_complete}/{len(out)}  |  rb_to_wm: {n_rb_ok}  |  wm_to_rb: {n_wm_ok}/{n_wm}")
    print(f"  Trips -> {trip_path}")
    print(f"  Stops -> {stop_path}")
    print(f"  Use in Excel/thesis -> {clean_trip}")
    print(f"                      -> {clean_stops}")
    print(f"  Excel workbook -> {trip_xlsx}")
    print(f"                 -> {clean_xlsx}")


if __name__ == "__main__":
    main()
