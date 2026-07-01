"""
Extended UXsim study: Robinsons–Waltermart corridor (field Dec 2025), session-timed signals, G/R scenarios.

Signals (GPS): Pala-Pala (Robinsons end), Waltermart intersection.
One-way trip (field): 2 signal encounters -> 2^2 = 4 G/R patterns (e.g. G-G).
Full matrix: 3 sessions x 4 policies x 4 = 48 runs (WM->RB or RB->WM per data origin).

Examples:
  python simulation_extended.py
  python simulation_extended.py --quick
  python simulation_extended.py --list-signals
  python simulation_extended.py --figures
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from pathlib import Path

from uxsim import World

from bus_calibration import (
    SESSION_SHEETS,
    DataOrigin,
    SessionCalibration,
    load_session_stats,
    onboard_travel_target_s,
    print_calibration,
)
from corridor_config import (
    FIELD_ONBOARD_PROFILE,
    MIN_FULL_MATRIX_RUNS,
    OPTIMIZED_SHORT_DWELL_SCALE,
    POLICY_TRANSIT,
    POLICY_OPTIMIZED,
    SESSION_BUS_COUNT_PER_HOUR,
    SESSION_CLOCK_START_S,
    SESSION_DEMAND,
    SESSIONS,
    MIXED_CORRIDOR_DEMAND_WINDOW_S,
    SESSION_HOUR_CLEARANCE_S,
    hourly_vehicle_counts_from_bus_anchor,
    session_bus_count_per_hour,
    PH_ARTERIAL_VEHICLE_SHARE,
    field_session_traffic_mix,
    session_demand_field_indices,
    signal_cycle_seconds,
    signal_green_times,
    SESSION_ONBOARD_JAN18,
    SIGNAL_ENCOUNTERS_PER_ROUND_TRIP,
    STOPS_RB_TO_WM,
    STOPS_WM_TO_RB,
    VEHICLE_CLASSES,
    BUS_VOLUME_CAP_PER_LEG,
    FIELD_SIM_TMAX_S,
    FIELD_TRIP_DEMAND_S,
    FIELD_TRIP_VOLUME,
    estimated_vehicles_in_window,
    mixed_corridor_demand_window_s,
    mixed_flow_rate,
    signal_phase_timing,
)
from corridor_config import ALL_FORMAL_MID_STOP_KEYS, ALL_INFORMAL_STOP_KEYS, stop_encounter_active


def resolve_encounter_policy(
    include_informal: bool,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    *,
    use_formal: bool = True,
) -> tuple[frozenset[str], frozenset[str]]:
    """Map legacy flags or explicit key sets to encounter policy."""
    ik = (
        informal_keys
        if informal_keys is not None
        else (ALL_INFORMAL_STOP_KEYS if include_informal else frozenset())
    )
    fk = (
        formal_keys
        if formal_keys is not None
        else (ALL_FORMAL_MID_STOP_KEYS if use_formal else frozenset())
    )
    return ik, fk


def _jan18_observed_travel_s(session: str) -> float | str:
    row = SESSION_ONBOARD_JAN18.get(session)
    if not row:
        return ""
    return round(float(row["travel_s"]), 1)
from corridor_network import build_corridor_network
from signal_scenarios import (
    SignalEncounterScenario,
    all_signal_scenarios,
    trip_direction_for_data_origin,
)

_PROJECT_DIR = Path(__file__).resolve().parent
FIGURES_OUTPUT_DIR = _PROJECT_DIR / "figures_output"
RESULTS_SUMMARY_CSV = _PROJECT_DIR / "results_summary_extended.csv"
RESULTS_COMPARISON_CSV = _PROJECT_DIR / "results_baseline_vs_optimized_extended.csv"
RESULTS_CHECKPOINT_CSV = _PROJECT_DIR / "results_summary_extended.checkpoint.csv"


def _vehicle_demand_attribute(vehicle_key: str, **extra: str) -> dict[str, str]:
    from session_bus_trips import bus_demand_attribute

    return bus_demand_attribute(vehicle_key, trip_id=extra.get("trip_id"), field_obs_id=extra.get("field_obs_id"))


def bus_only_trip_metrics(
    W: World,
    *,
    n_bus_legs: int = 1,
    field_traffic: str | None = None,
) -> dict[str, object]:
    """Completed UXsim trips tagged as bus (other classes still simulated, not counted)."""
    from corridor_config import clamp_bus_speed_for_traffic

    leg_tt: list[float] = []
    dist_m: list[float] = []
    for v in W.VEHICLES.values():
        attr = v.attribute if isinstance(v.attribute, dict) else {}
        if attr.get("vehicle_class") != "bus":
            continue
        if v.state != "end":
            continue
        dep, arr = v.departure_time, v.arrival_time
        if dep is None or arr is None:
            continue
        tt = float(arr) - float(dep)
        if tt <= 0:
            continue
        leg_tt.append(tt)
        dist_m.append(float(getattr(v, "distance_traveled", 0.0) or 0.0))
    att_leg = sum(leg_tt) / len(leg_tt) if leg_tt else None
    att_e2e = att_leg * n_bus_legs if att_leg and n_bus_legs > 0 else None
    v_kmh = None
    if att_leg and dist_m:
        mean_d = sum(dist_m) / len(dist_m)
        v_kmh = mean_d / att_leg * 3.6 if att_leg > 0 else None
    if v_kmh is not None:
        v_kmh = clamp_bus_speed_for_traffic(v_kmh, field_traffic)
    return {
        "bus_completed_trips": len(leg_tt),
        "bus_avg_travel_time_per_leg_s": round(att_leg, 2) if att_leg else "",
        "bus_avg_travel_time_e2e_s": round(att_e2e, 2) if att_e2e else "",
        "bus_avg_speed_kmh": round(v_kmh, 2) if v_kmh else "",
    }


def _collect_metrics_row(
    W: World,
    cal: SessionCalibration,
    sheet_name: str,
    policy_tag: str,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    short_dwell_scale: float,
    sig: SignalEncounterScenario,
    mixed_traffic: bool,
    replicate_field: bool = False,
    scenario_id: str = "",
    scenario_group: str = "",
    relocate_mask: str = "",
    corridor_length_m: float | None = None,
    session_hour: bool = False,
    record_bus_only: bool = False,
    sim_duration_s: float | None = None,
    bus_full_corridor: bool = True,
) -> dict[str, object]:
    a = W.analyzer
    att = float(getattr(a, "average_travel_time", -1.0))
    adel = float(getattr(a, "average_delay", -1.0))
    path = STOPS_RB_TO_WM if sig.trip_direction == "rb_to_wm" else STOPS_WM_TO_RB
    n_bus_stops = sum(
        1
        for s in path
        if stop_encounter_active(
            s,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=sig.trip_direction,  # type: ignore[arg-type]
        )
    )
    n_bus_legs = max(n_bus_stops - 1, 1)
    chain_trip = replicate_field or (mixed_traffic and bus_full_corridor)
    if chain_trip:
        # Chained stop bays: end-to-end ≈ mean leg time × number of legs.
        att_e2e = att * n_bus_legs if att > 0 else att
        adel_e2e = adel * n_bus_legs if adel > 0 else adel
    else:
        att_e2e = att * n_bus_legs if att > 0 else att
        adel_e2e = adel * n_bus_legs if adel > 0 else adel
    dr = (adel_e2e / att_e2e) if att_e2e > 0 and adel_e2e >= 0 else None
    target_s = onboard_travel_target_s(
        cal,
        include_informal_stops=bool(informal_keys),
        informal_keys=informal_keys,
    )
    err_pct = None
    if replicate_field and target_s and att_e2e > 0:
        err_pct = round((att_e2e - target_s) / target_s * 100.0, 1)
    tc = int(getattr(a, "trip_completed", 0))
    ta = int(getattr(a, "trip_all", 0))
    dist = float(getattr(a, "total_distance_traveled", -1.0))
    ttot = float(getattr(a, "total_travel_time", -1.0))
    vavg = (dist / ttot) if ttot > 0 and dist >= 0 else None
    enc = sig.encounter_greens
    raw_span = max(cal.demand_t1_s - cal.demand_t0_s, 1.0)
    mix_span = mixed_corridor_demand_window_s(raw_span) if mixed_traffic else raw_span
    mixed_est = mixed_traffic_summary(sheet_name, mix_span) if mixed_traffic else {}
    bus_stats = bus_only_trip_metrics(
        W, n_bus_legs=n_bus_legs, field_traffic=cal.field_traffic
    ) if mixed_traffic and record_bus_only else {}
    length_m = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    report_tt = att_e2e
    report_tt_leg = att
    if bus_stats.get("bus_avg_travel_time_e2e_s"):
        report_tt = float(bus_stats["bus_avg_travel_time_e2e_s"])
        if bus_stats.get("bus_avg_travel_time_per_leg_s"):
            report_tt_leg = float(bus_stats["bus_avg_travel_time_per_leg_s"])
    row: dict[str, object] = {
        "session": sheet_name,
        "data_origin": cal.data_origin,
        "scenario_id": scenario_id,
        "scenario_group": scenario_group,
        "relocate_mask": relocate_mask,
        "corridor_length_m": round(length_m, 1),
        "policy": policy_tag,
        "informal_stops": bool(informal_keys),
        "informal_mask": "".join(
            "1" if k in informal_keys else "0"
            for k in ("korean_grocery", "seven_eleven", "rcbc")
        ),
        "short_dwell_scale": short_dwell_scale if short_dwell_scale < 1.0 else "",
        "signal_scenario": sig.scenario_id,
        "n_signal_encounters": sig.n_encounters,
        "encounter_pattern": sig.encounter_pattern,
        "trip_direction": sig.trip_direction,
        "signal_offset_s": sig.signal_offset_s,
        "demand_shift_s": sig.demand_shift_s,
        "wm_to_rb_demand_shift_s": sig.wm_to_rb_demand_shift_s,
        "mixed_traffic": mixed_traffic,
        "session_hour": session_hour,
        "sim_duration_s": round(sim_duration_s, 0) if sim_duration_s else "",
        "bus_full_corridor": bus_full_corridor if mixed_traffic else "",
        "sim_mode": "session_hour_mixed"
        if session_hour
        else (
            "mixed_full_corridor"
            if mixed_traffic and bus_full_corridor
            else (
                "field_replication"
                if replicate_field
                else ("mixed_corridor" if mixed_traffic else "bus_only")
            )
        ),
        "field_replication": replicate_field,
        "record_bus_only": record_bus_only,
        "all_vehicles_avg_travel_time_s": round(att_e2e, 2) if att_e2e >= 0 else "",
        "all_vehicles_avg_travel_time_per_leg_s": round(att, 2) if att >= 0 else "",
        "pct_vs_onboard_target": err_pct if err_pct is not None else "",
        "vol_rb_to_wm": cal.vol_rb_to_wm,
        "vol_wm_to_rb": cal.vol_wm_to_rb,
        "n_rows_calibration_subset": cal.n_rows_calibration_subset,
        "demand_window_s": round(cal.demand_t1_s - cal.demand_t0_s, 1),
        "demand_window_capped": cal.demand_window_capped,
        "avg_travel_time_s": round(report_tt, 2) if report_tt and report_tt >= 0 else "",
        "avg_travel_time_per_leg_s": round(report_tt_leg, 2) if report_tt_leg and report_tt_leg >= 0 else "",
        "n_bus_legs": n_bus_legs,
        "avg_delay_s": round(adel_e2e, 2) if adel_e2e >= 0 else "",
        "onboard_target_travel_s": round(
            onboard_travel_target_s(
                cal, include_informal_stops=bool(informal_keys), informal_keys=informal_keys
            )
            or 0,
            1,
        )
        if onboard_travel_target_s(
            cal, include_informal_stops=bool(informal_keys), informal_keys=informal_keys
        )
        else "",
        "field_speed_min_kmh": cal.field_speed_min_kmh or "",
        "field_speed_max_kmh": cal.field_speed_max_kmh or "",
        "field_crowding": cal.field_crowding,
        "field_traffic": cal.field_traffic,
        "crowding_level_mix": cal.crowding_summary,
        "traffic_condition_mix": cal.traffic_condition_summary,
        "stationary_bus_observations": cal.n_rows_calibration_subset,
        "bus_companies_top": cal.bus_companies_summary,
        "field_observed_travel_s": _jan18_observed_travel_s(sheet_name),
        "delay_ratio": round(dr, 4) if dr is not None else "",
        "completed_trips": tc,
        "total_trips": ta,
        "total_distance_m": round(dist, 1) if dist >= 0 else "",
        "avg_speed_mps": round(vavg, 3) if vavg is not None else "",
        "est_vehicles_bus": mixed_est.get("bus", ""),
        "est_vehicles_private_car": mixed_est.get("private_car", ""),
        "est_vehicles_jeepney": mixed_est.get("jeepney", ""),
        "est_vehicles_truck": mixed_est.get("truck", ""),
        "est_vehicles_motorcycle": mixed_est.get("motorcycle", ""),
        "est_vehicles_van": mixed_est.get("van", ""),
        **bus_stats,
    }
    for i, green in enumerate(enc, start=1):
        row[f"encounter_{i}_green"] = green
    if session_hour:
        row["demand_window_s"] = MIXED_CORRIDOR_DEMAND_WINDOW_S
    if sig.extra_rb_to_wm_shifts:
        row["extra_rb_to_wm_shifts_s"] = ";".join(str(round(s, 1)) for s in sig.extra_rb_to_wm_shifts)
    return row


def _write_csv_rows(rows: list[dict[str, object]], path: Path) -> None:
    _write_csv_safe_path(rows, path, label="CSV")


def _write_csv_safe_path(
    rows: list[dict[str, object]],
    path: Path,
    *,
    fieldnames: tuple[str, ...] | list[str] | None = None,
    label: str = "Results",
) -> Path:
    """Write CSV; if Excel locks the file, try _generated and a timestamped name."""
    from datetime import datetime

    if not rows:
        return path
    keys = list(fieldnames) if fieldnames else list(rows[0].keys())
    filtered = [{k: r.get(k, "") for k in keys} for r in rows]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidates = [
        path,
        path.with_name(f"{path.stem}_generated{path.suffix}"),
        path.with_name(f"{path.stem}_{stamp}{path.suffix}"),
    ]
    seen: set[str] = set()
    for target in candidates:
        key = str(target.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            with target.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(filtered)
            if target != path:
                print(f"  {label}: {target}")
                print(f"    (could not write {path.name} — close it in Excel, then rename or copy)")
            else:
                print(f"  {label}: {target}")
            return target
        except PermissionError:
            continue
    raise PermissionError(
        f"Could not write {label}. Close these in Excel if open: "
        f"{path.name}, {path.stem}_generated{path.suffix}, then re-run."
    )


def _write_results_csv(rows: list[dict[str, object]], path: Path) -> Path:
    if not rows:
        return path
    return _write_csv_safe_path(rows, path, label="Session summary")


def _read_results_csv(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_checkpoint(row: dict[str, object], path: Path) -> None:
    from datetime import datetime

    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(row.keys())
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    targets = [
        path,
        path.with_name(f"{path.stem}_run{path.suffix}"),
        path.with_name(f"{path.stem}_{stamp}{path.suffix}"),
    ]
    for target in targets:
        try:
            write_header = not target.is_file() or target.stat().st_size == 0
            with target.open("a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                if write_header:
                    w.writeheader()
                w.writerow(row)
            return
        except PermissionError:
            continue


def _write_comparison_csv(rows: list[dict[str, object]], path: Path) -> Path:
    by: dict[tuple[str, str, str], dict[str, dict]] = {}
    for r in rows:
        key = (str(r["session"]), str(r.get("data_origin", "")), str(r.get("signal_scenario", "")))
        pol = str(r["policy"])
        by.setdefault(key, {})[pol] = r
    out = []
    for (sess, origin, sig_id), pols in by.items():
        b = pols.get(POLICY_TRANSIT) or pols.get("baseline_all_stops")
        o = pols.get(POLICY_OPTIMIZED)
        if not b or not o:
            continue
        try:
            tt_bf = float(b["avg_travel_time_s"])
            tt_of = float(o["avg_travel_time_s"])
        except (TypeError, ValueError):
            continue
        save = tt_bf - tt_of
        pct = (save / tt_bf * 100.0) if tt_bf else None
        out.append(
            {
                "session": sess,
                "data_origin": origin,
                "field_crowding": b.get("field_crowding", ""),
                "field_traffic": b.get("field_traffic", ""),
                "traffic_condition_mix": b.get("traffic_condition_mix", ""),
                "crowding_level_mix": b.get("crowding_level_mix", ""),
                "stationary_bus_observations": b.get("stationary_bus_observations", ""),
                "bus_companies_top": b.get("bus_companies_top", ""),
                "field_observed_travel_s": b.get("field_observed_travel_s", ""),
                "onboard_target_travel_s": b.get("onboard_target_travel_s", ""),
                "signal_scenario": sig_id,
                "encounter_pattern": b.get("encounter_pattern", ""),
                "baseline_avg_travel_time_s": tt_bf,
                "optimized_avg_travel_time_s": tt_of,
                "time_saved_per_trip_s": round(save, 2),
                "pct_improvement_travel_time": round(pct, 2) if pct is not None else "",
            }
        )
    if not out:
        return path
    try:
        return _write_csv_safe_path(out, path, label="Paired comparison")  # type: ignore[arg-type]
    except PermissionError:
        print(f"  Skipped comparison CSV (close {path.name} in Excel).")
        return path


def _bus_stop_chain(
    nodes: dict[str, object],
    direction: str,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
) -> list[object]:
    """Force buses through each modeled stop bay (matches on-board stop-by-stop trips)."""
    from corridor_config import corridor_stop_path_for_trip

    ctx = nodes.get("path_ctx") or {}
    path = corridor_stop_path_for_trip(
        direction,  # type: ignore[arg-type]
        adhoc_informal_count=int(ctx.get("adhoc_informal_count", 0)),
        chainage_overrides=ctx.get("chainage_overrides"),
        corridor_length_m=ctx.get("corridor_length_m"),
    )
    mid = nodes.get("mid_stops") or {}
    chain: list[object] = []
    for s in path:
        if not stop_encounter_active(
            s,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=direction,  # type: ignore[arg-type]
        ):
            continue
        if s.key == "robinsons":
            chain.append(nodes["rb_bus_stop"])
        elif s.key == "waltermart":
            chain.append(nodes["wm_bus_stop"])
        elif s.key in mid:
            chain.append(mid[s.key])
    if len(chain) < 2:
        import warnings

        warnings.warn(
            f"Bus stop chain for {direction} has {len(chain)} nodes (mid keys: {sorted(mid.keys())})",
            stacklevel=2,
        )
    return chain


def _add_field_bus_schedule_demands(
    W: World,
    nodes: dict[str, object],
    session: str,
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
) -> int:
    """
    Inject one bus trip per field stationary row at its observed clock time (within the 1-hour window).
    Runs on top of hourly background flows; tags trips as bus for metrics.
    """
    from bus_calibration import load_all_stationary_vehicles

    anchor = SESSION_CLOCK_START_S.get(session, 0)
    direction = sig.trip_direction
    chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
    if len(chain) < 2:
        return 0
    injected = 0
    for obs in load_all_stationary_vehicles(session=session, study_operator_only=True):
        origin = "robinsons" if obs.data_origin == "robinsons_location" else "waltermart"
        if trip_direction_for_data_origin(origin) != direction:
            continue
        if obs.observation_seconds is None:
            continue
        t0 = float(obs.observation_seconds) - anchor + sig.demand_shift_s
        if t0 < 0 or t0 >= MIXED_CORRIDOR_DEMAND_WINDOW_S - 120:
            continue
        t_end = min(t0 + 120.0, sig.demand_shift_s + MIXED_CORRIDOR_DEMAND_WINDOW_S)
        pulse = max(t_end - t0, 8.0)
        attr = _vehicle_demand_attribute(
            "bus",
            trip_id=f"obs_{obs.obs_id}",
            field_obs_id=str(obs.obs_id),
        )
        leg_flow = 1.0 / pulse
        for a, b in zip(chain, chain[1:]):
            origin_n, dest_n = _demand_endpoints(a, b, direction)
            W.adddemand(
                origin_n,
                dest_n,
                t0,
                t_end,
                flow=leg_flow,
                attribute=attr,
            )
        injected += 1
    return injected


def _add_single_observation_bus_demand(
    W: World,
    nodes: dict[str, object],
    obs,
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
) -> None:
    """Inject one field bus at its observed clock time (per-vehicle simulation)."""
    anchor = SESSION_CLOCK_START_S.get(obs.session, 0)
    direction = sig.trip_direction
    chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
    if len(chain) < 2:
        return
    origin = "robinsons" if obs.data_origin == "robinsons_location" else "waltermart"
    if trip_direction_for_data_origin(origin) != direction:
        return
    if obs.observation_seconds is None:
        return
    t0 = float(obs.observation_seconds) - anchor + sig.demand_shift_s
    if t0 < 0:
        t0 = sig.demand_shift_s
    t_end = t0 + 120.0
    attr = _vehicle_demand_attribute(
        "bus",
        trip_id=f"obs_{obs.obs_id}",
        field_obs_id=str(obs.obs_id),
    )
    for a, b in zip(chain, chain[1:]):
        origin_n, dest_n = _demand_endpoints(a, b, direction)
        W.adddemand(
            origin_n,
            dest_n,
            t0,
            t_end,
            volume=float(FIELD_TRIP_VOLUME),
            attribute=attr,
        )


def _add_field_trip_demand(
    W: World,
    nodes: dict[str, object],
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
) -> None:
    """
    Replicate on-board trip: bus stops at every modeled stop (chained legs, low volume).

    Single OD rb->wm skips bays when bypass links exist; chaining forces each stop.
    """
    direction = sig.trip_direction
    chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
    t1 = FIELD_TRIP_DEMAND_S + sig.demand_shift_s
    for a, b in zip(chain, chain[1:]):
        ax = float(getattr(a, "x", 0.0))
        bx = float(getattr(b, "x", 0.0))
        # Network spine is built Robinsons (low x) -> Waltermart (high x).
        if direction == "wm_to_rb" and ax > bx:
            origin, dest = b, a
        else:
            origin, dest = a, b
        W.adddemand(
            origin,
            dest,
            sig.demand_shift_s,
            t1,
            volume=float(FIELD_TRIP_VOLUME),
            attribute=_vehicle_demand_attribute("bus"),
        )


def _demand_endpoints(
    a: object,
    b: object,
    direction: str,
) -> tuple[object, object]:
    ax = float(getattr(a, "x", 0.0))
    bx = float(getattr(b, "x", 0.0))
    if direction == "wm_to_rb" and ax > bx:
        return b, a
    return a, b


def _add_bus_full_corridor_demand(
    W: World,
    nodes: dict[str, object],
    cal: SessionCalibration,
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    session_hour: bool = False,
) -> None:
    """
    Buses forced through every modeled stop (chained legs), not a single main-road OD.
    Background cars use bypass links; buses use stop bays (replicate_field topology).
    """
    direction = sig.trip_direction
    chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
    if len(chain) < 2:
        return
    if session_hour:
        t0 = sig.demand_shift_s
        t1 = sig.demand_shift_s + MIXED_CORRIDOR_DEMAND_WINDOW_S
    else:
        raw_span = cal.demand_t1_s - cal.demand_t0_s
        mix_span = mixed_corridor_demand_window_s(raw_span)
        t0 = cal.demand_t0_s + sig.demand_shift_s
        t1 = t0 + mix_span
    hourly = float(session_bus_count_per_hour(cal.sheet, direction))  # type: ignore[arg-type]
    n_legs = max(len(chain) - 1, 1)
    window_h = max((t1 - t0) / 3600.0, 1.0 / 3600.0)
    vol = max(float(FIELD_TRIP_VOLUME), hourly * window_h / n_legs)
    if session_hour:
        # Target ~hourly bus count as full corridor trips (legs share volume per chain).
        vol = max(vol, hourly / n_legs)
    for a, b in zip(chain, chain[1:]):
        origin, dest = _demand_endpoints(a, b, direction)
        W.adddemand(
            origin,
            dest,
            t0,
            t1,
            volume=vol,
            attribute=_vehicle_demand_attribute("bus"),
        )


def _add_other_bus_background_noise(
    W: World,
    nodes: dict[str, object],
    cal: SessionCalibration,
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    session_hour: bool = False,
) -> None:
    """Inject generic non-Erjohn buses as corridor background (permissioned study noise)."""
    from bus_calibration import field_workbook_is_june2026, other_bus_noise_flow_per_s

    if not field_workbook_is_june2026():
        return
    flow = other_bus_noise_flow_per_s(cal.sheet, sig.trip_direction)
    if flow <= 0:
        return
    direction = sig.trip_direction
    chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
    if len(chain) < 2:
        return
    shift = sig.demand_shift_s
    if session_hour:
        t0, t1 = shift, shift + MIXED_CORRIDOR_DEMAND_WINDOW_S
    else:
        raw_span = cal.demand_t1_s - cal.demand_t0_s
        mix_span = mixed_corridor_demand_window_s(raw_span)
        t0 = cal.demand_t0_s + shift
        t1 = t0 + mix_span
    for a, b in zip(chain, chain[1:]):
        origin, dest = _demand_endpoints(a, b, direction)
        W.adddemand(
            origin,
            dest,
            t0,
            t1,
            flow=flow,
            attribute=_vehicle_demand_attribute("bus", trip_id="other_company_noise"),
        )


def _add_mixed_corridor_demands(
    W: World,
    nodes: dict[str, object],
    cal: SessionCalibration,
    sig: SignalEncounterScenario,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    session_hour: bool = False,
    include_buses: bool = True,
) -> None:
    """
    Mixed corridor: buses use stop bays; cars/jeeps/trucks/motorcycles use main-road OD pairs.
    Flow rates (veh/s) from SESSION_DEMAND in corridor_config.py.
    """
    session = cal.sheet
    direction = sig.trip_direction
    shift = sig.demand_shift_s
    if session_hour:
        t0 = shift
        t1 = shift + MIXED_CORRIDOR_DEMAND_WINDOW_S
    else:
        raw_span = cal.demand_t1_s - cal.demand_t0_s
        mix_span = mixed_corridor_demand_window_s(raw_span)
        t0 = cal.demand_t0_s + shift
        t1 = t0 + mix_span
    rb_road = nodes["rb_road"]
    wm_road = nodes["wm_road"]

    traffic = cal.field_traffic or "Light"
    for vc in VEHICLE_CLASSES:
        if vc.uses_bus_stops and not include_buses:
            continue
        flow = mixed_flow_rate(
            session, vc.key, traffic_condition=traffic, trip_direction=direction  # type: ignore[arg-type]
        )
        if flow <= 0:
            continue
        if vc.uses_bus_stops:
            chain = _bus_stop_chain(nodes, direction, informal_keys=informal_keys, formal_keys=formal_keys)
            for a, b in zip(chain, chain[1:]):
                origin, dest = _demand_endpoints(a, b, direction)
                W.adddemand(
                    origin,
                    dest,
                    t0,
                    t1,
                    flow=flow,
                    attribute=_vehicle_demand_attribute(vc.key),
                )
        elif direction == "rb_to_wm":
            W.adddemand(
                rb_road,
                wm_road,
                t0,
                t1,
                flow=flow,
                attribute=_vehicle_demand_attribute(vc.key),
            )
            W.adddemand(
                wm_road,
                rb_road,
                t0,
                t1,
                flow=flow * 0.6,
                attribute=_vehicle_demand_attribute(vc.key),
            )
        else:
            W.adddemand(
                wm_road,
                rb_road,
                t0,
                t1,
                flow=flow,
                attribute=_vehicle_demand_attribute(vc.key),
            )
            W.adddemand(
                rb_road,
                wm_road,
                t0,
                t1,
                flow=flow * 0.6,
                attribute=_vehicle_demand_attribute(vc.key),
            )


def mixed_traffic_summary(session: str, window_s: float) -> dict[str, float]:
    """Approximate vehicles per class over mixed-traffic injection window (main OD)."""
    out: dict[str, float] = {}
    for vc in VEHICLE_CLASSES:
        flow = mixed_flow_rate(session, vc.key)
        out[vc.key] = round(estimated_vehicles_in_window(flow, window_s), 1)
    return out


def _add_demands(
    W: World,
    nodes: dict[str, object],
    cal: SessionCalibration,
    *,
    mixed_traffic: bool,
    sig: SignalEncounterScenario,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    replicate_field: bool = False,
    session_hour: bool = False,
    schedule_field_buses: bool = False,
    bus_full_corridor: bool = True,
    field_obs=None,
) -> None:
    if replicate_field:
        _add_field_trip_demand(W, nodes, sig, informal_keys=informal_keys, formal_keys=formal_keys)
        return
    if mixed_traffic:
        if bus_full_corridor:
            _add_mixed_corridor_demands(
                W,
                nodes,
                cal,
                sig,
                informal_keys=informal_keys,
                formal_keys=formal_keys,
                session_hour=session_hour,
                include_buses=False,
            )
            if session_hour:
                _add_bus_full_corridor_demand(
                    W,
                    nodes,
                    cal,
                    sig,
                    informal_keys=informal_keys,
                    formal_keys=formal_keys,
                    session_hour=True,
                )
                if schedule_field_buses:
                    n = _add_field_bus_schedule_demands(
                        W,
                        nodes,
                        cal.sheet,
                        sig,
                        informal_keys=informal_keys,
                        formal_keys=formal_keys,
                    )
                    if n:
                        print(
                            f"  + {n} field buses at Data_Collection clock times "
                            f"(obs_id in bus_trips CSV)"
                        )
                else:
                    from corridor_config import session_bus_count_per_hour

                    n = session_bus_count_per_hour(cal.sheet, sig.trip_direction)  # type: ignore[arg-type]
                    print(
                        f"  Hourly bus demand: {n} {sig.trip_direction} corridor trips "
                        f"({cal.sheet}); per-bus rows in bus_trips CSV"
                    )
            else:
                if field_obs is not None:
                    _add_single_observation_bus_demand(
                        W,
                        nodes,
                        field_obs,
                        sig,
                        informal_keys=informal_keys,
                        formal_keys=formal_keys,
                    )
                    _add_other_bus_background_noise(
                        W,
                        nodes,
                        cal,
                        sig,
                        informal_keys=informal_keys,
                        formal_keys=formal_keys,
                        session_hour=session_hour,
                    )
                else:
                    _add_bus_full_corridor_demand(
                        W,
                        nodes,
                        cal,
                        sig,
                        informal_keys=informal_keys,
                        formal_keys=formal_keys,
                        session_hour=session_hour,
                    )
        else:
            _add_mixed_corridor_demands(
                W,
                nodes,
                cal,
                sig,
                informal_keys=informal_keys,
                formal_keys=formal_keys,
                session_hour=session_hour,
                include_buses=True,
            )
        if schedule_field_buses and not (bus_full_corridor and session_hour):
            n = _add_field_bus_schedule_demands(
                W,
                nodes,
                cal.sheet,
                sig,
                informal_keys=informal_keys,
                formal_keys=formal_keys,
            )
            if n:
                print(f"  Scheduled {n} field bus departures in 1-hour window")
        return
    rb_bus = nodes["rb_bus_stop"]
    wm_bus = nodes["wm_bus_stop"]
    rb_road = nodes["rb_road"]
    wm_road = nodes["wm_road"]
    t0 = cal.demand_t0_s + sig.demand_shift_s
    t1 = cal.demand_t1_s + sig.demand_shift_s

    classes = [VEHICLE_CLASSES[0]] if not mixed_traffic else VEHICLE_CLASSES
    for vc in classes:
        if sig.trip_direction == "wm_to_rb":
            base_vol = cal.vol_wm_to_rb
            vol = max(1, int(round(base_vol * vc.volume_multiplier)))
            if not mixed_traffic and vc.uses_bus_stops:
                vol = min(vol, BUS_VOLUME_CAP_PER_LEG)
            if vc.uses_bus_stops:
                chain = _bus_stop_chain(
                    nodes, "wm_to_rb", informal_keys=informal_keys, formal_keys=formal_keys
                )
                for a, b in zip(chain, chain[1:]):
                    W.adddemand(
                        a,
                        b,
                        t0,
                        t1,
                        volume=float(vol),
                        attribute=_vehicle_demand_attribute(vc.key),
                    )
            else:
                W.adddemand(
                    wm_road,
                    rb_road,
                    t0,
                    t1,
                    volume=float(vol),
                    attribute=_vehicle_demand_attribute(vc.key),
                )
        else:
            vol = max(1, int(round(cal.vol_rb_to_wm * vc.volume_multiplier)))
            if vc.uses_bus_stops:
                chain = _bus_stop_chain(
                    nodes, "rb_to_wm", informal_keys=informal_keys, formal_keys=formal_keys
                )
                for a, b in zip(chain, chain[1:]):
                    W.adddemand(
                        a,
                        b,
                        t0,
                        t1,
                        volume=float(vol),
                        attribute=_vehicle_demand_attribute(vc.key),
                    )
            else:
                W.adddemand(
                    rb_road,
                    wm_road,
                    t0,
                    t1,
                    volume=float(vol),
                    attribute=_vehicle_demand_attribute(vc.key),
                )


def run_one(
    sheet_name: str,
    *,
    data_origin: DataOrigin,
    include_informal: bool,
    policy_tag: str,
    short_dwell_scale: float,
    sig: SignalEncounterScenario,
    mixed_traffic: bool,
    results_rows: list[dict[str, object]] | None,
    save_figures: bool,
    replicate_field: bool = False,
    cal: SessionCalibration | None = None,
    quiet: bool = False,
    run_label: str | None = None,
    scenario_id: str = "",
    scenario_group: str = "",
    relocate_mask: str = "",
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
    session_hour: bool = False,
    show_mode: int | None = None,
    record_bus_only: bool = False,
    schedule_field_buses: bool = False,
    bus_full_corridor: bool = True,
    bus_trip_rows: list[dict[str, object]] | None = None,
    field_obs=None,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
) -> World:
    if cal is None:
        cal = load_session_stats(sheet_name, data_origin=data_origin)
    enc_keys, enc_formal = resolve_encounter_policy(
        include_informal, informal_keys, formal_keys
    )
    if session_hour and not mixed_traffic:
        raise ValueError("session_hour requires mixed_traffic=True")
    if not quiet:
        print(f"\n{'='*60}")
        scen_lbl = scenario_id or policy_tag
        print(
            f"  {sheet_name} | {cal.data_origin} | {scen_lbl} | "
            f"{sig.scenario_id} ({sig.encounter_pattern}) | mixed={mixed_traffic}"
            f"{' | 1hr session' if session_hour else ''}"
        )
        if relocate_mask and relocate_mask != "00000":
            print(f"  relocate_mask={relocate_mask}")
        if run_label:
            print(f"  {run_label}")
        print(f"{'='*60}")
        print_calibration(cal)

    tag = scenario_id or policy_tag
    safe = run_label or f"{sheet_name.replace(' ', '_')}_{cal.data_origin}_{tag}_{sig.scenario_id}"
    if not mixed_traffic:
        safe += "_bus_only"

    extra_t = sig.demand_shift_s
    if session_hour:
        tmax = MIXED_CORRIDOR_DEMAND_WINDOW_S + SESSION_HOUR_CLEARANCE_S + extra_t
    elif replicate_field:
        tmax = FIELD_SIM_TMAX_S + extra_t
    else:
        tmax = cal.sim_tmax_s + extra_t
    vis = 0 if show_mode is None else int(show_mode)
    W = World(
        name=safe[:80],
        print_mode=0 if quiet else 1,
        tmax=tmax,
        save_mode=1,
        show_mode=vis,
    )
    nodes = build_corridor_network(
        W,
        cal,
        include_informal_stops=bool(enc_keys),
        short_dwell_scale=short_dwell_scale,
        signal_offset_s=sig.signal_offset_s,
        session=sheet_name,
        replicate_field=replicate_field,
        mixed_traffic=mixed_traffic,
        trip_direction=sig.trip_direction,
        chainage_overrides=chainage_overrides,
        corridor_length_m=corridor_length_m,
        quiet=quiet,
        informal_keys=enc_keys,
        formal_keys=enc_formal,
        service_mode=service_mode,
        adhoc_informal_count=adhoc_informal_count,
    )
    _add_demands(
        W,
        nodes,
        cal,
        mixed_traffic=mixed_traffic,
        sig=sig,
        informal_keys=enc_keys,
        formal_keys=enc_formal,
        replicate_field=replicate_field,
        session_hour=session_hour,
        schedule_field_buses=schedule_field_buses,
        bus_full_corridor=bus_full_corridor,
        field_obs=field_obs,
    )
    W.exec_simulation()
    if not quiet:
        W.analyzer.print_simple_stats(force_print=True)

    if results_rows is not None:
        row = _collect_metrics_row(
            W,
            cal,
            sheet_name,
            policy_tag,
            informal_keys=enc_keys,
            formal_keys=enc_formal,
            short_dwell_scale=short_dwell_scale,
            sig=sig,
            mixed_traffic=mixed_traffic,
            replicate_field=replicate_field,
            scenario_id=scenario_id,
            scenario_group=scenario_group,
            relocate_mask=relocate_mask,
            corridor_length_m=corridor_length_m,
            session_hour=session_hour,
            record_bus_only=record_bus_only or session_hour,
            sim_duration_s=tmax,
            bus_full_corridor=bus_full_corridor,
        )
        results_rows.append(row)
        _append_checkpoint(row, RESULTS_CHECKPOINT_CSV)

    if bus_trip_rows is not None and session_hour and mixed_traffic:
        from session_bus_trips import (
            enrich_rows_from_field_observations,
            extract_session_bus_trip_rows,
        )

        from corridor_config import corridor_stop_path_for_trip

        path = corridor_stop_path_for_trip(
            sig.trip_direction,  # type: ignore[arg-type]
            adhoc_informal_count=adhoc_informal_count,
            chainage_overrides=chainage_overrides,
            corridor_length_m=corridor_length_m,
        )
        n_stops = sum(
            1
            for s in path
            if stop_encounter_active(
                s,
                formal_keys=enc_formal,
                informal_keys=enc_keys,
                trip_direction=sig.trip_direction,  # type: ignore[arg-type]
            )
        )
        n_legs = max(n_stops - 1, 1)
        trip_rows = extract_session_bus_trip_rows(
            W,
            session=sheet_name,
            trip_direction=sig.trip_direction,
            scenario_id=scenario_id,
            scenario_group=scenario_group,
            policy=policy_tag,
            signal_pattern=sig.scenario_id,
            encounter_pattern=sig.encounter_pattern,
            informal_keys=enc_keys,
            formal_keys=enc_formal,
            data_origin=cal.data_origin,
            cal=cal,
            relocate_mask=relocate_mask,
            field_observed_dec_travel_s=_jan18_observed_travel_s(sheet_name),
            n_legs_expected=n_legs,
            demand_shift_s=sig.demand_shift_s,
            corridor_length_m=corridor_length_m,
        )
        if schedule_field_buses:
            enrich_rows_from_field_observations(trip_rows, session=sheet_name)
        bus_trip_rows.extend(trip_rows)
        if not quiet:
            n_done = sum(1 for r in trip_rows if r.get("trip_completed"))
            print(f"  Per-bus records: {len(trip_rows)} trips ({n_done} completed corridor)")

    if save_figures:
        FIGURES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            W.analyzer.network_average(left_handed=0, figsize=(12, 4), network_font_size=7)
            png = _PROJECT_DIR / f"out{safe}" / "network_average.png"
            if png.is_file():
                shutil.copy2(png, FIGURES_OUTPUT_DIR / f"{safe}_network_average.png")
        except Exception as exc:
            print(f"  Figure skipped: {exc}")

    return W


def _run_plan(
    sessions: list[str],
    n_encounters: int,
    scenarios: tuple,
    *,
    single_signal: bool = False,
    replicate_field: bool = False,
) -> list[tuple]:
    from scenario_catalog import ScenarioSpec

    plan: list[tuple] = []
    for sh in sessions:
        for origin in ("robinsons", "waltermart"):
            direction = trip_direction_for_data_origin(origin)
            signal_scenarios = all_signal_scenarios(n_encounters, sh, direction)
            if single_signal:
                signal_scenarios = (signal_scenarios[0],)
            for scen in scenarios:
                if not isinstance(scen, ScenarioSpec):
                    raise TypeError("scenarios must be ScenarioSpec tuples from scenario_catalog")
                for sig in signal_scenarios:
                    plan.append((sh, origin, scen, sig, replicate_field))
    return plan


def main() -> None:
    os.chdir(_PROJECT_DIR)
    p = argparse.ArgumentParser(description="Extended corridor UXsim with 2^N signal encounter scenarios")
    p.add_argument("--quick", action="store_true", help="Morning Session only (still runs all 2^N signal cases)")
    p.add_argument(
        "--single-signal",
        action="store_true",
        help="Run only the first signal pattern (fast smoke test)",
    )
    p.add_argument(
        "--encounters",
        type=int,
        default=SIGNAL_ENCOUNTERS_PER_ROUND_TRIP,
        metavar="N",
        help=f"Signal encounters (default {SIGNAL_ENCOUNTERS_PER_ROUND_TRIP}=2 per one-way trip, 4 patterns, 48 runs)",
    )
    p.add_argument(
        "--bus-only",
        action="store_true",
        help="Buses only, one bus end-to-end (field replication). Default is mixed traffic.",
    )
    p.add_argument(
        "--mixed-traffic",
        action="store_true",
        help=argparse.SUPPRESS,
    )  # back-compat; mixed is now default unless --bus-only
    p.add_argument(
        "--replicate-field",
        action="store_true",
        help="Baseline/optimized as ONE bus end-to-end (matches on-board travel time; default ON)",
    )
    p.add_argument(
        "--fleet-mode",
        action="store_true",
        help="Old mode: many buses per leg (leg average x n_legs); do not use for field validation",
    )
    p.add_argument(
        "--figures",
        action="store_true",
        help="Export network PNGs to figures_output/ (off by default for faster runs)",
    )
    p.add_argument(
        "--jan18-targets",
        action="store_true",
        help="Calibrate to Jan 18 on-board times (11/15/19 min); default uses Dec workbook averages",
    )
    p.add_argument(
        "--export-field-vehicles",
        action="store_true",
        help="Write field_stationary_observations.csv (one row per bus in workbook) and exit",
    )
    p.add_argument("--list-signals", action="store_true", help="Print all signal scenario IDs and exit")
    p.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print stop-policy and relocation scenario catalog and exit",
    )
    p.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Run all policy (A-D) and relocation (R_*) scenarios",
    )
    p.add_argument(
        "--scenario-groups",
        metavar="GROUPS",
        help="Comma-separated: policies, relocation (e.g. policies,relocation)",
    )
    p.add_argument(
        "--scenarios",
        metavar="IDS",
        help="Comma-separated scenario ids (e.g. A_transit,D_optimized,R_00100)",
    )
    p.add_argument(
        "--export-only",
        action="store_true",
        help="Write results CSVs from checkpoint (no simulation); use after a run that failed at save",
    )
    args = p.parse_args()

    if args.export_field_vehicles:
        from bus_calibration import export_stationary_vehicles_csv

        n = export_stationary_vehicles_csv(_PROJECT_DIR / "field_stationary_observations.csv")
        print(f"Exported {n} stationary bus observations -> field_stationary_observations.csv")
        return

    if args.export_only:
        rows = _read_results_csv(RESULTS_CHECKPOINT_CSV)
        if not rows:
            print(f"No checkpoint at {RESULTS_CHECKPOINT_CSV}")
            print("  Re-run simulation, or close Excel and copy results_summary_extended_generated.csv if present.")
            return
        print(f"Exporting {len(rows)} rows from checkpoint...")
        _write_results_csv(rows, RESULTS_SUMMARY_CSV)
        _write_comparison_csv(rows, RESULTS_COMPARISON_CSV)
        print("Done.")
        return

    if args.list_scenarios:
        from scenario_catalog import print_scenario_catalog

        print_scenario_catalog()
        return

    if args.list_signals:
        print("Signal cycles by session (field main/side green):\n")
        for sh in SESSIONS:
            print(f"  {sh}:")
            for sk in ("pala_pala", "waltermart_int"):
                c = signal_cycle_seconds(sh, sk)
                main, side = signal_green_times(sh, sk)
                ph = signal_phase_timing(sh, sk)
                print(f"    {sk}: cycle {c:.0f} s  main {main:.0f} s / side {side:.0f} s  (yellow {ph.yellow_s:.0f}s)")
        print()
        print("One-way: 2 signals per trip -> 4 patterns (G-G, G-R, R-G, R-R)\n")
        for origin in ("waltermart", "robinsons"):
            direction = trip_direction_for_data_origin(origin)
            scenarios = all_signal_scenarios(args.encounters, SESSIONS[0], direction)
            print(f"  {origin} ({direction}):")
            for s in scenarios:
                names = ("waltermart_int", "pala_pala") if direction == "wm_to_rb" else ("pala_pala", "waltermart_int")
                detail = " -> ".join(
                    f"{names[i]}:{'G' if s.encounter_greens[i] else 'R'}" for i in range(len(names))
                )
                print(f"    {s.encounter_pattern:7s}  {detail}")
        return

    import corridor_config as _cc
    from bus_calibration import configure_field_workbook_calibration

    configure_field_workbook_calibration()
    if args.jan18_targets:
        _cc.FIELD_ONBOARD_PROFILE = "jan18"

    sessions = [SESSION_SHEETS[0]] if args.quick else list(SESSION_SHEETS)

    from scenario_catalog import (
        default_extended_scenarios,
        select_scenarios,
    )

    groups = [g.strip() for g in args.scenario_groups.split(",")] if args.scenario_groups else None
    ids = [s.strip() for s in args.scenarios.split(",")] if args.scenarios else None
    if args.all_scenarios:
        scenarios = select_scenarios(all_scenarios=True)
    elif ids or groups:
        scenarios = select_scenarios(ids=ids, groups=groups)
    else:
        scenarios = default_extended_scenarios()

    mixed = not args.bus_only or getattr(args, "mixed_traffic", False)
    replicate_field = not args.fleet_mode and not mixed
    plan = _run_plan(
        sessions,
        args.encounters,
        scenarios,
        single_signal=args.single_signal,
        replicate_field=replicate_field,
    )
    n_sig = 1 if args.single_signal else 2**args.encounters
    n = len(plan)
    print(f"Encounters N={args.encounters} -> {n_sig} signal pattern(s)")
    print(f"Planned UXsim runs: {n}")
    print(f"  traffic_mode={'mixed_corridor (buses+cars+jeepneys+...)' if mixed else 'bus_only field_replication'}")
    print(f"  field_replication={replicate_field}")
    print(f"  calibration_profile={_cc.FIELD_ONBOARD_PROFILE}")
    print(f"  stop_scenarios={len(scenarios)} ({', '.join(s.scenario_id for s in scenarios[:6])}{'...' if len(scenarios) > 6 else ''})")
    print(f"  signal_scenarios={'G-G only' if args.single_signal else 'all 4 patterns (G-G, G-R, R-G, R-R)'}")
    print(f"  save_figures={args.figures}")
    if mixed:
        idx = session_demand_field_indices()
        print("  Mixed demand calibrated from Bus_Data_Collection stationary traffic/crowding:")
        for sess in sessions:
            mix = field_session_traffic_mix(sess)
            mix_s = ", ".join(f"{k}:{v}" for k, v in sorted(mix.items(), key=lambda x: -x[1]))
            print(f"    {sess}: field index {idx[sess]:.2f} | traffic mix {{{mix_s}}}")
        print(
            f"  Mixed injection window: {MIXED_CORRIDOR_DEMAND_WINDOW_S:.0f} s (1 hour) for all classes"
        )
        print(
            "  Volumes: Philippine arterial composition "
            f"(bus {PH_ARTERIAL_VEHICLE_SHARE['bus']:.0%}, jeepney {PH_ARTERIAL_VEHICLE_SHARE['jeepney']:.0%}, "
            f"car {PH_ARTERIAL_VEHICLE_SHARE['car']:.0%}, motorcycle {PH_ARTERIAL_VEHICLE_SHARE['motorcycle']:.0%}, "
            f"truck+van {PH_ARTERIAL_VEHICLE_SHARE['truck'] + PH_ARTERIAL_VEHICLE_SHARE['van']:.0%}), "
            "anchored to field buses/hour"
        )
        for sess in sessions:
            counts = hourly_vehicle_counts_from_bus_anchor(sess)
            total = sum(counts.values())
            print(
                f"    {sess}: total ~{total} veh/h | bus {counts['bus']} | jeepney {counts['jeepney']} | "
                f"cars {counts['car']} | motorcycles {counts['motorcycle']} | "
                f"trucks {counts['truck']} | vans {counts['van']}"
            )
        ph = signal_phase_timing("Afternoon Session", "pala_pala")
        print(
            f"  Afternoon Pala-Pala signal: main green {ph.main_green_s:.0f}s, "
            f"red/cross {ph.side_green_s:.0f}s, cycle {ph.cycle_s:.0f}s"
        )
    if not replicate_field and not mixed:
        print("  Warning: --fleet-mode leg×n metrics do not match on-board travel time.")
    if args.bus_only:
        print("  Bus-only mode: no private cars/jeeps in corridor (field replication).")

    for ck in (
        RESULTS_CHECKPOINT_CSV,
        RESULTS_CHECKPOINT_CSV.with_name(f"{RESULTS_CHECKPOINT_CSV.stem}_run{RESULTS_CHECKPOINT_CSV.suffix}"),
    ):
        if ck.is_file():
            try:
                ck.unlink()
                print(f"  Cleared checkpoint: {ck.name}")
            except OSError:
                print(f"  Could not clear {ck.name} (close in Excel if open).")

    rows: list[dict[str, object]] = []
    from scenario_catalog import (
        chainage_overrides_for_scenario,
        effective_corridor_length_m,
    )

    for sh, origin, scen, sig, rep_field in plan:
        run_one(
            sh,
            data_origin=origin,  # type: ignore[arg-type]
            include_informal=scen.include_informal,
            informal_keys=scen.informal_keys,
            formal_keys=scen.formal_keys,
            policy_tag=scen.policy_tag,
            short_dwell_scale=scen.dwell_scale,
            sig=sig,
            mixed_traffic=mixed,
            results_rows=rows,
            save_figures=args.figures,
            replicate_field=rep_field,
            scenario_id=scen.scenario_id,
            scenario_group=scen.group,
            relocate_mask=scen.relocate_mask,
            chainage_overrides=chainage_overrides_for_scenario(scen),
            corridor_length_m=effective_corridor_length_m(scen),
            service_mode=scen.service_mode,
            adhoc_informal_count=scen.adhoc_informal_count,
        )

    out_path = _write_results_csv(rows, RESULTS_SUMMARY_CSV)
    _write_comparison_csv(rows, RESULTS_COMPARISON_CSV)
    if RESULTS_CHECKPOINT_CSV.is_file() and out_path == RESULTS_SUMMARY_CSV:
        try:
            RESULTS_CHECKPOINT_CSV.unlink()
        except OSError:
            pass
    print(f"\nDone. {len(rows)} runs -> {out_path}")
    print(f"  Checkpoint kept on disk if final write used a fallback name.")


if __name__ == "__main__":
    main()
