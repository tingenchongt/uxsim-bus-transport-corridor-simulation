"""
Per-bus corridor trip records for 1-hour session runs (Vissim-style output).

Groups completed UXsim bus legs by trip_id (field schedule) or departure-time bin
(hourly volume) into one corridor trip per bus with depart/arrive clocks and
Data_Collection on-board reference times.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from bus_calibration import onboard_travel_target_s
from corridor_config import (
    CORRIDOR_LENGTH_M,
    MIXED_CORRIDOR_DEMAND_WINDOW_S,
    SESSION_CLOCK_START_S,
    align_moving_speed_kmh,
    bus_cruise_cap_kmh,
    session_bus_count_per_hour,
)
if TYPE_CHECKING:
    from uxsim import World

# One row per bus × scenario × signal; completed time first for Excel / thesis tables.
SESSION_HOUR_PER_BUS_COLUMNS: tuple[str, ...] = (
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
)

_SESSION_ORDER = {"Morning Session": 0, "Lunch": 1, "Afternoon Session": 2}
_SIGNAL_ORDER = {"G-G": 0, "G-R": 1, "R-G": 2, "R-R": 3}


def _sort_session_hour_per_bus_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    def key(r: dict[str, object]) -> tuple:
        sess = str(r.get("session", ""))
        completed = str(r.get("reached_destination_time", "")) or "99:99:99"
        return (
            _SESSION_ORDER.get(sess, 9),
            str(r.get("scenario_id", "")),
            _SIGNAL_ORDER.get(str(r.get("signal_pattern", "")), 9),
            str(r.get("trip_direction", "")),
            completed,
            int(str(r.get("obs_id", "0")) or "0"),
        )

    return sorted(rows, key=key)


def write_session_hour_per_bus_csv(rows: list[dict[str, object]], path) -> Path:
    from pathlib import Path

    from simulation_extended import _write_csv_safe_path

    p = Path(path)
    if not rows:
        return p
    ordered = _sort_session_hour_per_bus_rows(rows)
    return _write_csv_safe_path(
        ordered,
        p,
        fieldnames=SESSION_HOUR_PER_BUS_COLUMNS,
        label="Per-bus results (all scenarios × signals)",
    )


SESSION_BUS_TRIP_COLUMNS: tuple[str, ...] = (
    "bus_trip_id",
    "session",
    "trip_direction",
    "origin_terminal",
    "destination_terminal",
    "scenario_id",
    "scenario_group",
    "policy",
    "signal_pattern",
    "encounter_pattern",
    "departed_origin_sim_s",
    "arrived_destination_sim_s",
    "corridor_travel_s",
    "corridor_travel_min",
    "departed_origin_clock",
    "arrived_destination_clock",
    "n_legs_completed",
    "n_legs_expected",
    "trip_completed",
    "field_onboard_reference_s",
    "field_onboard_reference_min",
    "field_observed_dec_travel_s",
    "sim_minus_field_reference_s",
    "sim_minus_field_reference_min",
    "avg_speed_kmh",
    "field_speed_cap_kmh",
    "corridor_length_m",
    "relocate_mask",
    "data_origin",
    "field_obs_id",
    "bus_company",
    "route",
    "traffic_condition",
    "crowding_level",
)


def bus_demand_attribute(
    vehicle_key: str = "bus",
    *,
    trip_id: str | int | None = None,
    field_obs_id: str | int | None = None,
) -> dict[str, str]:
    attr: dict[str, str] = {"vehicle_class": vehicle_key}
    if trip_id is not None:
        attr["trip_id"] = str(trip_id)
    if field_obs_id is not None:
        attr["field_obs_id"] = str(field_obs_id)
    return attr


def _sim_to_clock(session: str, sim_s: float) -> str:
    anchor = float(SESSION_CLOCK_START_S.get(session, 0))
    total = int(anchor + sim_s) % 86400
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _completed_bus_legs(W: World) -> list:
    legs = []
    for v in W.VEHICLES.values():
        attr = v.attribute if isinstance(v.attribute, dict) else {}
        if attr.get("vehicle_class") != "bus":
            continue
        if v.state != "end":
            continue
        dep, arr = v.departure_time, v.arrival_time
        if dep is None or arr is None:
            continue
        if float(arr) - float(dep) <= 0:
            continue
        legs.append(v)
    return legs


def _cluster_legs_into_trips(
    legs: list,
    *,
    demand_shift_s: float,
    session: str,
    trip_direction: str,
    max_gap_s: float = 600.0,
) -> dict[str, list]:
    """
    Group bus legs into corridor trips.

    - trip_id from field schedule: all legs with same id
    - otherwise: greedy merge consecutive legs when gap between legs < max_gap_s
    - then assign trip ids Mor_rb_to_wm_0001, ...
    """
    by_tid: dict[str, list] = defaultdict(list)
    orphans: list = []
    for v in legs:
        attr = v.attribute if isinstance(v.attribute, dict) else {}
        tid = attr.get("trip_id")
        if tid:
            by_tid[str(tid)].append(v)
        else:
            orphans.append(v)

    if orphans:
        n_hourly = session_bus_count_per_hour(session, trip_direction)  # type: ignore[arg-type]
        slot = float(MIXED_CORRIDOR_DEMAND_WINDOW_S) / max(n_hourly, 1)
        bins: dict[int, list] = defaultdict(list)
        for v in orphans:
            dep = float(v.departure_time)
            bins[int((dep - demand_shift_s) / max(slot, 1.0))].append(v)
        prefix = f"{session[:3]}_{trip_direction}"
        for bin_idx, bin_legs in sorted(bins.items()):
            bin_legs.sort(key=lambda v: float(v.departure_time))
            chains: list[list] = []
            current: list = [bin_legs[0]]
            for v in bin_legs[1:]:
                gap = float(v.departure_time) - float(current[-1].arrival_time)
                if gap <= max_gap_s:
                    current.append(v)
                else:
                    chains.append(current)
                    current = [v]
            chains.append(current)
            for j, chain in enumerate(chains):
                tid = f"{prefix}_{bin_idx:04d}" if len(chains) == 1 else f"{prefix}_{bin_idx:04d}_{j}"
                by_tid[tid] = chain

    return by_tid


def enrich_rows_from_field_observations(
    rows: list[dict[str, object]],
    *,
    session: str,
) -> None:
    from bus_calibration import load_all_stationary_vehicles

    by_id = {str(o.obs_id): o for o in load_all_stationary_vehicles(session=session)}
    for r in rows:
        oid = str(r.get("field_obs_id", "")).strip()
        if not oid or oid not in by_id:
            continue
        o = by_id[oid]
        r["bus_company"] = o.bus_company
        r["route"] = o.route
        r["traffic_condition"] = o.traffic
        r["crowding_level"] = o.crowding
        r["field_speed_cap_kmh"] = bus_cruise_cap_kmh(o.traffic)
        raw = float(r["avg_speed_kmh"]) if r.get("avg_speed_kmh") else 0.0
        r["avg_speed_kmh"] = align_moving_speed_kmh(raw if raw > 0 else None, o.traffic)


def extract_session_bus_trip_rows(
    W: World,
    *,
    session: str,
    trip_direction: str,
    scenario_id: str,
    scenario_group: str,
    policy: str,
    signal_pattern: str,
    encounter_pattern: str,
    include_informal: bool = True,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    data_origin: str,
    cal,
    demand_shift_s: float = 0.0,
    relocate_mask: str = "",
    field_observed_dec_travel_s: float | str = "",
    n_legs_expected: int | None = None,
    corridor_length_m: float | None = None,
) -> list[dict[str, object]]:
    """One row per bus corridor trip (Vissim-style: start time, end time, travel duration)."""
    origin, dest = (
        ("robinsons", "waltermart")
        if trip_direction == "rb_to_wm"
        else ("waltermart", "robinsons")
    )
    ref_s = onboard_travel_target_s(
        cal,
        include_informal_stops=include_informal,
        traffic=cal.field_traffic,
        informal_keys=informal_keys,
    )
    ref_min = round(ref_s / 60.0, 2) if ref_s else ""
    n_exp = n_legs_expected if n_legs_expected else 1
    length_m = float(corridor_length_m) if corridor_length_m else CORRIDOR_LENGTH_M
    session_traffic = cal.field_traffic or "Light"
    session_speed_cap = bus_cruise_cap_kmh(session_traffic)

    by_trip = _cluster_legs_into_trips(
        _completed_bus_legs(W),
        demand_shift_s=demand_shift_s,
        session=session,
        trip_direction=trip_direction,
    )

    rows: list[dict[str, object]] = []
    for trip_id, legs in sorted(
        by_trip.items(),
        key=lambda x: min(float(v.departure_time) for v in x[1]),
    ):
        legs.sort(key=lambda v: float(v.departure_time))
        dep_s = float(legs[0].departure_time)
        arr_s = float(legs[-1].arrival_time)
        leg_durations = [
            max(0.0, float(v.arrival_time) - float(v.departure_time))
            for v in legs
            if v.departure_time is not None and v.arrival_time is not None
        ]
        # UXsim injects each stop leg as separate demand; legs overlap in sim time.
        # Wall-clock (last arr − first dep) ≈ one leg (~20 s); sum legs ≈ corridor minutes.
        travel_s = sum(leg_durations) if leg_durations else max(0.0, arr_s - dep_s)
        completed = len(legs) >= max(1, n_exp)
        leg_dist = sum(float(getattr(v, "distance_traveled", 0.0) or 0.0) for v in legs)
        # UXsim sometimes attributes full OD distance to every leg; cap at corridor length.
        dist_m = leg_dist
        if dist_m > length_m * 1.05:
            dist_m = length_m
        elif dist_m <= 0 and completed:
            dist_m = length_m
        raw_speed = (dist_m / travel_s * 3.6) if travel_s > 0 and dist_m > 0 else 0.0
        speed = (
            align_moving_speed_kmh(raw_speed, session_traffic)
            if raw_speed > 0
            else align_moving_speed_kmh(None, session_traffic)
        )
        delta_s = round(travel_s - ref_s, 1) if ref_s and travel_s > 0 else ""
        delta_min = round(delta_s / 60.0, 2) if delta_s != "" else ""
        attr0 = legs[0].attribute if isinstance(legs[0].attribute, dict) else {}
        obs_id = attr0.get("field_obs_id", "")

        rows.append(
            {
                "bus_trip_id": trip_id,
                "session": session,
                "trip_direction": trip_direction,
                "origin_terminal": origin,
                "destination_terminal": dest,
                "scenario_id": scenario_id,
                "scenario_group": scenario_group,
                "policy": policy,
                "signal_pattern": signal_pattern,
                "encounter_pattern": encounter_pattern,
                "departed_origin_sim_s": round(dep_s, 1),
                "arrived_destination_sim_s": round(arr_s, 1),
                "corridor_travel_s": round(travel_s, 1),
                "corridor_travel_min": round(travel_s / 60.0, 2),
                "departed_origin_clock": _sim_to_clock(session, dep_s),
                "arrived_destination_clock": _sim_to_clock(session, arr_s),
                "n_legs_completed": len(legs),
                "n_legs_expected": n_exp,
                "trip_completed": completed,
                "field_onboard_reference_s": round(ref_s, 1) if ref_s else "",
                "field_onboard_reference_min": ref_min,
                "field_observed_dec_travel_s": field_observed_dec_travel_s,
                "sim_minus_field_reference_s": delta_s,
                "sim_minus_field_reference_min": delta_min,
                "avg_speed_kmh": speed,
                "field_speed_cap_kmh": session_speed_cap,
                "corridor_length_m": round(length_m, 1),
                "relocate_mask": relocate_mask,
                "data_origin": data_origin,
                "field_obs_id": obs_id,
                "bus_company": "",
                "route": "",
                "traffic_condition": "",
                "crowding_level": "",
            }
        )
    return rows


def build_session_hour_per_bus_rows(
    session: str,
    data_origin: str,
    scen,
    sig,
    bus_trip_rows: list[dict[str, object]],
    *,
    corridor_length_m: float,
) -> list[dict[str, object]]:
    """
    One row per Data_Collection bus for this session-hour run (same columns as results_per_bus.csv).
    Matches completed UXsim trips by field_obs_id; missing trips get sim_trip_completed=False.
    """
    from bus_calibration import calibration_for_vehicle, load_all_stationary_vehicles
    from signal_scenarios import trip_direction_for_data_origin
    from simulation_per_vehicle import _simple_row

    direction = sig.trip_direction
    origin_key: str = "robinsons" if data_origin == "robinsons_location" else "waltermart"
    by_obs = {
        str(r.get("field_obs_id", "")).strip(): r
        for r in bus_trip_rows
        if str(r.get("field_obs_id", "")).strip()
    }

    out: list[dict[str, object]] = []
    for obs in load_all_stationary_vehicles(session=session):
        if obs.data_origin != data_origin:
            continue
        if trip_direction_for_data_origin(origin_key) != direction:
            continue
        trip = by_obs.get(str(obs.obs_id), {})
        travel_s = float(trip["corridor_travel_s"]) if trip.get("corridor_travel_s") else 0.0
        speed = float(trip["avg_speed_kmh"]) if trip.get("avg_speed_kmh") else None
        cal = calibration_for_vehicle(obs, data_origin=origin_key)  # type: ignore[arg-type]
        out.append(
            _simple_row(
                obs,
                cal,
                traffic_mode="session_hour_mixed",
                mixed_traffic=True,
                policy=scen.policy_tag,
                scenario_id=scen.scenario_id,
                scenario_group=scen.group,
                relocate_mask=scen.relocate_mask,
                corridor_length_m=corridor_length_m,
                signal_pattern=sig.encounter_pattern,
                direction=direction,
                travel_s=travel_s,
                delay_s=0.0,
                speed_kmh=speed,
                sig=sig,
            )
        )
    return out


def write_session_bus_trips_csv(rows: list[dict[str, object]], path) -> Path:
    from pathlib import Path

    from simulation_extended import _write_csv_safe_path

    p = Path(path)
    if not rows:
        return p
    return _write_csv_safe_path(
        rows,
        p,
        fieldnames=SESSION_BUS_TRIP_COLUMNS,
        label="Per-bus trips",
    )
