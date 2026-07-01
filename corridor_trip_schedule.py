"""
March-through stop schedule (arrive / dwell / depart) aligned with UXsim corridor travel time.
"""

from __future__ import annotations

from dataclasses import dataclass

from bus_calibration import SessionCalibration, _format_clock, onboard_travel_target_s
from corridor_config import (
    CORRIDOR_LENGTH_M,
    CORRIDOR_SIGNALS,
    SIGNAL_ENCOUNTERS_ONE_WAY,
    STOPS_RB_TO_WM,
    STOPS_WM_TO_RB,
    coordinates_for_corridor_key,
    corridor_stop_path_for_trip,
)
from corridor_network import (
    _apply_dwell_scale,
    _calibrated_stop_dwell_s,
    _cruise_len,
    _cruise_speed_segments,
    _dwell_seconds,
    _link_cruise_cap_mps,
    _milestone_spacing,
    _session_cruise_mps,
)
from signal_scenarios import SignalEncounterScenario, _encounter_signal_key, _encounter_timing


@dataclass
class StopScheduleRow:
    stop_sequence: int
    stop_key: str
    stop_label: str
    stop_kind: str
    arrived_time: str
    dwell_s: float
    departed_time: str
    leg_travel_s: float


def _field_signal_wait_s(
    cal: SessionCalibration,
    encounter_i: int,
    direction: str,
    is_green: bool,
    sig: SignalEncounterScenario,
) -> float:
    """
    Field on-board 'traffic signal delay' per intersection.

    G-G still has cycle-alignment wait (~3 min total across 2 signals in field).
    R-first (R-G, R-R): first signal hits full side-red (~145–175 s at Pala-Pala PM).
    Heavy traffic adds queue backlog behind other vehicles.
    """
    from bus_calibration import traffic_onboard_signal_target_s
    from corridor_config import (
        signal_red_phase_wait_s,
        traffic_signal_queue_extra_s,
    )

    total = traffic_onboard_signal_target_s(cal, traffic=cal.field_traffic)
    n_enc = max(SIGNAL_ENCOUNTERS_ONE_WAY, 1)
    per_enc = float(total) / n_enc if total and total > 0 else 90.0
    queue = traffic_signal_queue_extra_s(cal.field_traffic) * (0.35 if is_green else 0.65)
    signal_key = _encounter_signal_key(encounter_i, direction)  # type: ignore[arg-type]

    if is_green:
        return per_enc + queue

    red_wait = signal_red_phase_wait_s(cal.sheet, signal_key)
    if encounter_i == 0 and not is_green:
        red_wait = max(red_wait, signal_red_phase_wait_s(cal.sheet, signal_key))

    extra = getattr(cal, "onboard_signal_extra_s", None)
    if extra and float(extra) > 0:
        red_wait += float(extra) / n_enc
    return red_wait + queue + per_enc * 0.25


def _schedule_cruise_mps(
    cal: SessionCalibration,
    *,
    mixed_traffic: bool,
    replicate_field: bool,
) -> float | None:
    if mixed_traffic:
        return _link_cruise_cap_mps(cal, replicate_field=False, mixed_traffic=True)
    return _session_cruise_mps(cal, replicate_field=replicate_field)


def _cruise_time_s(
    cal: SessionCalibration,
    prev_chain: float,
    chain: float,
    *,
    mixed_traffic: bool,
    replicate_field: bool,
) -> float:
    cruise_cap = _schedule_cruise_mps(
        cal, mixed_traffic=mixed_traffic, replicate_field=replicate_field
    )
    if not cruise_cap:
        return 0.0
    cruise = _cruise_len(prev_chain, chain)
    spacing = _milestone_spacing(prev_chain, chain)
    segs = _cruise_speed_segments(cruise, spacing, cruise_cap_mps=cruise_cap)
    return sum(length / max(speed, 0.1) for length, speed in segs)


def _chain_from_trip_entry(
    chainage_from_robinsons_m: float,
    entry_chainage_m: float,
    direction: str,
) -> float:
    """Distance along the trip from the boarding stop to a milestone."""
    if direction == "rb_to_wm":
        return chainage_from_robinsons_m - entry_chainage_m
    return entry_chainage_m - chainage_from_robinsons_m


def _milestones_for_direction(
    direction: str,
    *,
    informal_keys: frozenset[str],
    formal_keys: frozenset[str],
    adhoc_informal_count: int = 0,
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
    origin_key: str | None = None,
) -> list[tuple[str, object, float]]:
    """Ordered (kind, item, chain_from_origin) for signals and intermediate stops."""
    from corridor_config import (
        _stop_chainage_from_robinsons,
        stop_encounter_active,
        trip_origin_stop,
    )

    length_m = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    path = corridor_stop_path_for_trip(
        direction,  # type: ignore[arg-type]
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=length_m,
    )
    dest_key = "waltermart" if direction == "rb_to_wm" else "robinsons"
    if origin_key is None:
        origin = trip_origin_stop(
            path,
            direction,  # type: ignore[arg-type]
            formal_keys=formal_keys,
            informal_keys=informal_keys,
        )
        origin_key = origin.key
    entry_chain = _stop_chainage_from_robinsons(
        next(s for s in path if s.key == origin_key),
        trip_direction=direction,  # type: ignore[arg-type]
        corridor_length_m=length_m,
        chainage_overrides=chainage_overrides,
    )

    tagged: list[tuple[float, str, object]] = []
    for s in path:
        if s.key in (origin_key, dest_key):
            continue
        if not stop_encounter_active(
            s,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=direction,  # type: ignore[arg-type]
        ):
            continue
        ch = _stop_chainage_from_robinsons(
            s,
            trip_direction=direction,  # type: ignore[arg-type]
            corridor_length_m=length_m,
            chainage_overrides=chainage_overrides,
        )
        rel = _chain_from_trip_entry(ch, entry_chain, direction)
        if rel <= 0:
            continue
        tagged.append((rel, "stop", s))
    for sig in CORRIDOR_SIGNALS:
        rel = _chain_from_trip_entry(sig.chainage_m, entry_chain, direction)
        if rel <= 0:
            continue
        tagged.append((rel, "signal", sig))
    tagged.sort(key=lambda x: x[0])
    return [(k, item, chain) for chain, k, item in tagged]


def compute_trip_stop_schedule(
    cal: SessionCalibration,
    sig: SignalEncounterScenario,
    *,
    include_informal: bool = True,
    short_dwell_scale: float,
    start_clock_s: int,
    origin_dwell_s: float,
    sim_corridor_travel_s: float,
    mixed_traffic: bool = False,
    replicate_field: bool = True,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
) -> list[StopScheduleRow]:
    from corridor_config import (
        ALL_FORMAL_MID_STOP_KEYS,
        ALL_INFORMAL_STOP_KEYS,
        _stop_chainage_from_robinsons,
        stop_encounter_active,
        trip_origin_stop,
    )

    if informal_keys is None:
        informal_keys = ALL_INFORMAL_STOP_KEYS if include_informal else frozenset()
    if formal_keys is None:
        formal_keys = ALL_FORMAL_MID_STOP_KEYS

    session = cal.sheet
    direction = sig.trip_direction
    length_m = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    path = corridor_stop_path_for_trip(
        direction,  # type: ignore[arg-type]
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=length_m,
    )
    origin = trip_origin_stop(
        path,
        direction,  # type: ignore[arg-type]
        formal_keys=formal_keys,
        informal_keys=informal_keys,
    )
    dest_key = "waltermart" if direction == "rb_to_wm" else "robinsons"

    n_active = sum(
        1
        for s in path
        if stop_encounter_active(
            s,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=direction,  # type: ignore[arg-type]
        )
    )
    trip_target = onboard_travel_target_s(
        cal,
        include_informal_stops=bool(informal_keys),
        traffic=cal.field_traffic,
        informal_keys=informal_keys,
    )
    calibrated = None
    if trip_target and _schedule_cruise_mps(
        cal, mixed_traffic=mixed_traffic, replicate_field=replicate_field
    ):
        calibrated = _calibrated_stop_dwell_s(
            cal, n_active, short_dwell_scale, travel_target_s=trip_target
        )

    raw: list[dict[str, object]] = []
    prev_chain = 0.0

    o_dwell = origin_dwell_s if origin_dwell_s > 0 else float(
        _dwell_seconds(
            origin.kind,
            cal,
            short_dwell_scale,
            calibrated_per_stop_s=calibrated,
            service_mode=service_mode,
        )
        or 30.0
    )
    raw.append(
        {
            "key": origin.key,
            "label": origin.label,
            "kind": origin.kind,
            "leg_cruise": 0.0,
            "dwell": o_dwell,
            "signal_wait": 0.0,
        }
    )

    for kind, item, chain in _milestones_for_direction(
        direction,
        informal_keys=informal_keys,
        formal_keys=formal_keys,
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=length_m,
        origin_key=origin.key,
    ):
        leg = _cruise_time_s(
            cal,
            prev_chain,
            chain,
            mixed_traffic=mixed_traffic,
            replicate_field=replicate_field,
        )
        if kind == "signal":
            sk = item.key  # type: ignore[union-attr]
            encounter_i = next(
                (
                    i
                    for i in range(len(sig.encounter_greens))
                    if _encounter_signal_key(i, direction) == sk  # type: ignore[arg-type]
                ),
                0,
            )
            green = sig.encounter_greens[encounter_i]
            wait = _field_signal_wait_s(cal, encounter_i, direction, green, sig)
            raw.append(
                {
                    "key": sk,
                    "label": item.label,  # type: ignore[union-attr]
                    "kind": "signal",
                    "leg_cruise": leg,
                    "dwell": 0.0,
                    "signal_wait": wait,
                }
            )
        else:
            stop = item
            dwell = _dwell_seconds(
                stop.kind,
                cal,
                short_dwell_scale,
                calibrated_per_stop_s=calibrated,
                service_mode=service_mode,
            )
            dwell = _apply_dwell_scale(dwell, short_dwell_scale)
            raw.append(
                {
                    "key": stop.key,
                    "label": stop.label,
                    "kind": stop.kind,
                    "leg_cruise": leg,
                    "dwell": dwell,
                    "signal_wait": 0.0,
                }
            )
        prev_chain = chain

    entry_chain = _stop_chainage_from_robinsons(
        origin,
        trip_direction=direction,  # type: ignore[arg-type]
        corridor_length_m=length_m,
        chainage_overrides=chainage_overrides,
    )
    dest = next(s for s in path if s.key == dest_key)
    dest_chain = _chain_from_trip_entry(
        _stop_chainage_from_robinsons(
            dest,
            trip_direction=direction,  # type: ignore[arg-type]
            corridor_length_m=length_m,
            chainage_overrides=chainage_overrides,
        ),
        entry_chain,
        direction,
    )
    leg_dest = _cruise_time_s(
        cal,
        prev_chain,
        dest_chain,
        mixed_traffic=mixed_traffic,
        replicate_field=replicate_field,
    )
    d_dwell = _dwell_seconds(dest.kind, cal, short_dwell_scale, calibrated_per_stop_s=calibrated)
    d_dwell = _apply_dwell_scale(d_dwell, short_dwell_scale)
    raw.append(
        {
            "key": dest.key,
            "label": dest.label,
            "kind": dest.kind,
            "leg_cruise": leg_dest,
            "dwell": d_dwell,
            "signal_wait": 0.0,
        }
    )

    from corridor_config import traffic_speed_mid_kmh

    cruise_sum = sum(float(r["leg_cruise"]) for r in raw)  # type: ignore[arg-type]
    fixed_sum = sum(float(r["dwell"]) + float(r["signal_wait"]) for r in raw)  # type: ignore[arg-type]
    target = sim_corridor_travel_s if sim_corridor_travel_s > 0 else cruise_sum + fixed_sum
    mid_mps = traffic_speed_mid_kmh(cal.field_traffic) / 3.6
    min_drive_s = CORRIDOR_LENGTH_M / max(mid_mps, 0.5)
    if cruise_sum > 0:
        drive_budget = max(min_drive_s, target - fixed_sum)
        scale = max(1.0, drive_budget / cruise_sum)
    else:
        scale = 1.0
    total = cruise_sum * scale + fixed_sum
    if total > target and target > 0:
        excess = total - target
        dwell_total = sum(
            float(r["dwell"])
            for r in raw
            if r["kind"] not in ("signal",)  # type: ignore[comparison-overlap]
        )
        if dwell_total > excess > 0:
            d_scale = max(0.55, (dwell_total - excess) / dwell_total)
            for r in raw:
                if r["kind"] not in ("signal",):  # type: ignore[comparison-overlap]
                    r["dwell"] = float(r["dwell"]) * d_scale  # type: ignore[arg-type]
            fixed_sum = sum(float(r["dwell"]) + float(r["signal_wait"]) for r in raw)  # type: ignore[arg-type]

    t = float(start_clock_s)
    rows: list[StopScheduleRow] = []
    for seq, r in enumerate(raw):
        leg = float(r["leg_cruise"]) * scale  # type: ignore[arg-type]
        wait = float(r["signal_wait"])  # type: ignore[arg-type]
        dwell = float(r["dwell"])  # type: ignore[arg-type]
        if r["kind"] == "signal":  # type: ignore[comparison-overlap]
            dwell = wait
        arr = int(t + leg)
        dep = int(arr + dwell)
        rows.append(
            StopScheduleRow(
                stop_sequence=seq,
                stop_key=str(r["key"]),
                stop_label=str(r["label"]),
                stop_kind=str(r["kind"]),
                arrived_time=_format_clock(arr),
                dwell_s=round(dwell, 1),
                departed_time=_format_clock(dep),
                leg_travel_s=round(leg, 1),
            )
        )
        t = float(dep)

    return rows


def schedule_to_dicts(
    rows: list[StopScheduleRow],
    *,
    obs_id: int,
    bus_company: str,
    session: str,
    trip_direction: str,
    scenario_id: str = "",
    policy: str,
    signal_pattern: str,
    traffic: str,
    crowding: str,
    sim_corridor_travel_s: float = 0.0,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for r in rows:
        out.append(
            {
                "obs_id": obs_id,
                "session": session,
                "trip_direction": trip_direction,
                "bus_company": bus_company,
                "scenario_id": scenario_id,
                "policy": policy,
                "signal_pattern": signal_pattern,
                "traffic_condition": traffic,
                "crowding_level": crowding,
                "stop_sequence": r.stop_sequence,
                "stop_key": r.stop_key,
                "stop_label": r.stop_label,
                "coordinates": coordinates_for_corridor_key(r.stop_key),
                "stop_kind": r.stop_kind,
                "arrived_at_stop_time": r.arrived_time,
                "dwell_at_stop_s": r.dwell_s,
                "departed_stop_time": r.departed_time,
                "leg_travel_before_stop_s": r.leg_travel_s,
                "stop_timeline_source": (
                    "schedule_aligned_to_uxsim_e2e"
                    if sim_corridor_travel_s > 0
                    else "schedule_only_no_uxsim_e2e"
                ),
            }
        )
    return out


def field_schedule_travel_s(
    cal: SessionCalibration,
    sig,
    *,
    include_informal: bool = True,
    short_dwell_scale: float,
    origin_dwell_s: float,
    sim_corridor_travel_s: float,
    mixed_traffic: bool = False,
    replicate_field: bool = True,
    start_clock_s: int = 0,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
) -> float:
    """
    End-to-end seconds from field-calibrated stop schedule (drive + dwell + signal waits).

    When UXsim under-runs, pass travel_target as sim_corridor_travel_s so the schedule
    scales cruise legs to Dec on-board 'travel time to destination'.
    """
    rows = compute_trip_stop_schedule(
        cal,
        sig,
        include_informal=include_informal,
        short_dwell_scale=short_dwell_scale,
        start_clock_s=start_clock_s,
        origin_dwell_s=origin_dwell_s,
        sim_corridor_travel_s=sim_corridor_travel_s,
        mixed_traffic=mixed_traffic,
        replicate_field=replicate_field,
        informal_keys=informal_keys,
        formal_keys=formal_keys,
        service_mode=service_mode,
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=corridor_length_m,
    )
    if not rows:
        return float(sim_corridor_travel_s or 0.0)
    return float(sum(r.leg_travel_s + r.dwell_s for r in rows))
