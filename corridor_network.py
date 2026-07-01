"""
Build the Robinsons–Waltermart corridor in UXsim (field chainage, stops, session-timed signals).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from corridor_config import (
    BUS_MAX_SPEED_MPS,
    CLOSE_MILESTONE_SPACING_M,
    CORRIDOR_LENGTH_M,
    CORRIDOR_SIGNALS,
    CRUISE_SPEED_CLOSE_HEAVY_MPS,
    CRUISE_SPEED_CLOSE_MPS,
    CRUISE_SPEED_NEAR_MPS,
    DEFAULT_DWELL_S,
    FREE_FLOW_MPS,
    GENERAL_VEHICLE_SPEED_KMH,
    GENERAL_VEHICLE_SPEED_MPS,
    bus_cruise_cap_kmh,
    bus_traffic_speed_limits_kmh,
    crowding_dwell_multiplier,
    general_cruise_cap_kmh,
    general_traffic_speed_limits_kmh,
    session_formal_mid_route_dwell_s,
    iter_main_road_lane_segments,
    main_road_lanes_for_segment,
    NEAR_FEATURE_M,
    STOP_LANES,
    STOP_LINK_LENGTH_M,
    STOPS_RB_TO_WM,
    STOPS_WM_TO_RB,
    StopKind,
    traffic_cruise_multiplier,
    traffic_jam_density,
    corridor_stop_path_for_trip,
    network_milestone_stops,
    signal_green_times,
)

from bus_calibration import SessionCalibration, onboard_travel_target_s

if TYPE_CHECKING:
    from uxsim import World


def _crowding_dwell_mult(cal: SessionCalibration) -> float:
    return crowding_dwell_multiplier(
        cal.field_crowding,
        boarding=cal.mean_boarding_at_origin_s,
        alighting=cal.mean_alighting_at_origin_s,
    )


def _formal_dwell_s(base_s: float, cal: SessionCalibration, short_dwell_scale: float) -> float:
    """Dwell at formal / terminal stops, scaled by crowding then policy (optimized) scale."""
    scaled = base_s * _crowding_dwell_mult(cal)
    return _apply_dwell_scale(scaled, short_dwell_scale)


def _traffic_cruise_mult(cal: SessionCalibration) -> float:
    return traffic_cruise_multiplier(cal.field_traffic)


def _clamp_mps(speed_mps: float, cap_mps: float) -> float:
    return min(max(float(speed_mps), 0.12), float(cap_mps))


def _apply_dwell_scale(seconds: float, scale: float) -> float:
    if scale >= 1.0:
        return seconds
    return max(8.0, seconds * scale)


def _apply_service_mode_dwell(dwell_s: float, service_mode: str) -> float:
    from corridor_config import (
        ALIGHT_ONLY_DWELL_MULT,
        DRIVE_THROUGH_DWELL_MIN_S,
        DRIVE_THROUGH_DWELL_MULT,
    )

    if service_mode == "drive_through":
        return max(DRIVE_THROUGH_DWELL_MIN_S, dwell_s * DRIVE_THROUGH_DWELL_MULT)
    if service_mode == "alight_only":
        return max(DRIVE_THROUGH_DWELL_MIN_S, dwell_s * ALIGHT_ONLY_DWELL_MULT)
    return dwell_s


def _field_dwell_base_s(kind: StopKind, cal: SessionCalibration) -> float:
    """Base dwell before crowding / optimized scale."""
    base_rb = float(cal.mean_dwell_rb_s or DEFAULT_DWELL_S)
    base_wm = float(cal.mean_dwell_wm_s or DEFAULT_DWELL_S)
    if kind == "terminal_formal":
        return (base_rb + base_wm) / 2.0
    if kind == "formal":
        from corridor_config import CROWDING_FORMAL_LOW_DWELL_S, normalize_crowding_label

        base = session_formal_mid_route_dwell_s(cal.sheet, cal.onboard_stop_dwell_s)
        if normalize_crowding_label(cal.field_crowding) == "Low":
            return max(base, CROWDING_FORMAL_LOW_DWELL_S)
        return base
    if kind == "informal":
        return max(base_rb * 1.12, 45.0)
    return DEFAULT_DWELL_S


def _dwell_seconds(
    kind: StopKind,
    cal: SessionCalibration,
    short_dwell_scale: float,
    *,
    calibrated_per_stop_s: float | None = None,
    service_mode: str = "full",
) -> float:
    crowd = _crowding_dwell_mult(cal) if kind in ("formal", "terminal_formal") else 1.0
    if calibrated_per_stop_s is not None:
        dwell = float(calibrated_per_stop_s) * crowd
        if kind == "terminal_formal":
            dwell = max(
                dwell,
                float(cal.mean_dwell_rb_s or dwell),
                float(cal.mean_dwell_wm_s or dwell),
            )
        return _apply_service_mode_dwell(dwell, service_mode)
    base = _field_dwell_base_s(kind, cal)
    if kind in ("formal", "terminal_formal"):
        dwell = _formal_dwell_s(base, cal, short_dwell_scale)
    elif kind == "informal":
        dwell = _apply_dwell_scale(base, short_dwell_scale)
    else:
        dwell = DEFAULT_DWELL_S
    return _apply_service_mode_dwell(dwell, service_mode)


def _session_cruise_mps(cal: SessionCalibration, *, replicate_field: bool = False) -> float | None:
    if cal.field_speed_max_kmh and cal.field_speed_max_kmh > 0:
        cap = float(cal.field_speed_max_kmh) / 3.6
        if replicate_field:
            return min(cap * _traffic_cruise_mult(cal), FREE_FLOW_MPS)
        return cap
    if cal.onboard_cruise_mps and cal.onboard_cruise_mps > 0:
        return min(float(cal.onboard_cruise_mps), FREE_FLOW_MPS)
    return None


def _link_cruise_cap_mps(
    cal: SessionCalibration,
    *,
    replicate_field: bool = False,
    mixed_traffic: bool = False,
) -> float | None:
    """
    Cruise speed cap for bypass / general traffic (cars, jeepneys, etc.) on main road.

    Up to 60 km/h when Light; lower when Moderate or Heavy.
    """
    if mixed_traffic:
        return general_cruise_cap_kmh(cal.field_traffic) / 3.6
    cap = _session_cruise_mps(cal, replicate_field=replicate_field)
    if cap:
        return min(cap, GENERAL_VEHICLE_SPEED_MPS)
    return GENERAL_VEHICLE_SPEED_MPS * _traffic_cruise_mult(cal)


def _bus_link_cruise_cap_mps(
    cal: SessionCalibration,
    *,
    replicate_field: bool = False,
    mixed_traffic: bool = False,
) -> float:
    """
    Cruise cap on bus stop chain and terminal links.

    Never above 50 km/h; Heavy/High traffic uses a lower cap than Light.
    """
    tier_cap = bus_cruise_cap_kmh(cal.field_traffic) / 3.6
    if replicate_field:
        field_cap = _session_cruise_mps(cal, replicate_field=True)
        if field_cap:
            return min(BUS_MAX_SPEED_MPS, field_cap, tier_cap)
    return min(BUS_MAX_SPEED_MPS, tier_cap)


def _session_cruise_mid_mps(cal: SessionCalibration) -> float | None:
    if cal.field_speed_min_kmh and cal.field_speed_max_kmh:
        return (float(cal.field_speed_min_kmh) + float(cal.field_speed_max_kmh)) / 2.0 / 3.6
    return cal.onboard_cruise_mps


def _field_bus_cruise_scale(
    cal: SessionCalibration,
    *,
    n_active_stops: int,
    travel_target_s: float | None,
    corridor_length_m: float,
    calibrated_dwell_s: float | None,
) -> float:
    """
    Scale bus main-road cruise down so drive + dwell + signals can reach Dec on-board target.

    UXsim 1D legs often finish faster than field; values < 1.0 slow buses toward workbook times.
    """
    if not travel_target_s or travel_target_s <= 0:
        return 1.0
    cruise = _session_cruise_mid_mps(cal) or 7.5
    ff_s = corridor_length_m / cruise
    dwell_each = float(calibrated_dwell_s or session_formal_mid_route_dwell_s(cal.sheet, cal.onboard_stop_dwell_s))
    bay_s = 2.0 * STOP_LINK_LENGTH_M / max(_speed_from_dwell(dwell_each), 0.12)
    mid_stops = max(0, n_active_stops - 2)
    dwell_total = mid_stops * (dwell_each + bay_s)
    signal_total = float(cal.onboard_signal_delay_s or 0.0)
    est_s = ff_s + dwell_total + signal_total
    if est_s <= travel_target_s:
        # Keep field cruise speeds; dwell + signals absorb extra end-to-end time.
        return 1.0
    return 1.0


def _calibrated_stop_dwell_s(
    cal: SessionCalibration,
    n_stops: int,
    short_dwell_scale: float,
    *,
    travel_target_s: float | None = None,
) -> float:
    """
    Per-stop dwell aligned with on-board 'Travel Time to Destination'.

    Buses are simulated leg-by-leg between stops; budget per leg ≈ field trip / (n_stops - 1).
    """
    cruise = _session_cruise_mid_mps(cal)
    target = travel_target_s or cal.onboard_travel_time_s
    if not target or not cruise or n_stops < 2:
        return DEFAULT_DWELL_S
    n_legs = n_stops - 1
    target_leg_s = float(target) / n_legs
    drive_leg_s = (CORRIDOR_LENGTH_M / n_legs) / cruise
    signal_leg_s = 0.0
    extra = getattr(cal, "onboard_signal_extra_s", None)
    if extra is not None and extra > 0:
        signal_leg_s = float(extra) / len(CORRIDOR_SIGNALS) / 2.0
    elif cal.onboard_signal_delay_s:
        signal_leg_s = float(cal.onboard_signal_delay_s) / len(CORRIDOR_SIGNALS) / 2.0
    per_stop = max(15.0, target_leg_s - drive_leg_s - signal_leg_s)
    onboard_floor = session_formal_mid_route_dwell_s(cal.sheet, cal.onboard_stop_dwell_s)
    per_stop = max(per_stop, onboard_floor)
    return _apply_dwell_scale(per_stop, short_dwell_scale)


def _speed_from_dwell(dwell_s: float, *, max_mps: float = BUS_MAX_SPEED_MPS) -> float:
    raw = max(STOP_LINK_LENGTH_M / max(dwell_s, 5.0), 0.12)
    return min(raw, max_mps)


def _cruise_len(chain_a: float, chain_b: float) -> float:
    return max(chain_b - chain_a - 2.0 * STOP_LINK_LENGTH_M, 50.0)


def _milestone_spacing(chain_a: float, chain_b: float) -> float:
    return max(chain_b - chain_a, 1.0)


def _is_heavy_field_traffic(field_traffic: str | None) -> bool:
    from corridor_config import normalize_traffic_label

    return normalize_traffic_label(str(field_traffic or "Light")) == "Heavy"


def _cruise_speed_segments(
    cruise_len: float,
    milestone_spacing_m: float,
    *,
    cruise_cap_mps: float | None = None,
    field_traffic: str | None = None,
    for_bus: bool = False,
) -> list[tuple[float, float]]:
    """
    Variable cruise speeds (m/s) on main-road links.

    Bus links: never above 50 km/h; Heavy uses lower near/close/mid than Light.
    General traffic: up to 60 km/h when Light.
    """
    cap = cruise_cap_mps if cruise_cap_mps else FREE_FLOW_MPS
    cap = _clamp_mps(cap, cap)
    ft = field_traffic or "Light"
    if for_bus or cap <= BUS_MAX_SPEED_MPS + 0.2:
        limits = bus_traffic_speed_limits_kmh(ft)
        mid = limits["mid_block_kmh"] / 3.6
        near = limits["near_stop_signal_kmh"] / 3.6
        close = limits["close_spacing_kmh"] / 3.6
    else:
        mid = min(cap, GENERAL_VEHICLE_SPEED_MPS)
        near = min(CRUISE_SPEED_NEAR_MPS, cap)
        close_mps = (
            CRUISE_SPEED_CLOSE_HEAVY_MPS
            if _is_heavy_field_traffic(ft)
            else CRUISE_SPEED_CLOSE_MPS
        )
        close = min(close_mps, cap)

    if milestone_spacing_m < CLOSE_MILESTONE_SPACING_M:
        segs = [(cruise_len, close)]
    else:
        near_len = min(NEAR_FEATURE_M, cruise_len / 3.0)
        mid_len = cruise_len - 2.0 * near_len
        if mid_len < 80.0:
            segs = [(cruise_len, near)]
        else:
            segs = [
                (near_len, near),
                (mid_len, mid),
                (near_len, near),
            ]
    return [(length, _clamp_mps(speed, cap)) for length, speed in segs]


def build_corridor_network(
    W: World,
    cal: SessionCalibration,
    *,
    include_informal_stops: bool,
    short_dwell_scale: float = 1.0,
    signal_offset_s: float = 0.0,
    session: str = "Afternoon Session",
    replicate_field: bool = False,
    mixed_traffic: bool = False,
    trip_direction: str = "rb_to_wm",
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
    quiet: bool = False,
    informal_keys: frozenset[str] | None = None,
    formal_keys: frozenset[str] | None = None,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
) -> dict[str, object]:
    """Returns rb_bus_stop, wm_bus_stop, rb_road, wm_road, mid-route *_Stop nodes, and signals."""
    from corridor_config import ALL_FORMAL_MID_STOP_KEYS, ALL_INFORMAL_STOP_KEYS, stop_encounter_active

    if informal_keys is None:
        informal_keys = ALL_INFORMAL_STOP_KEYS if include_informal_stops else frozenset()
    if formal_keys is None:
        formal_keys = ALL_FORMAL_MID_STOP_KEYS

    def _stop_active(stop) -> bool:
        return stop_encounter_active(
            stop,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=trip_direction,  # type: ignore[arg-type]
        )

    signal_nodes: dict[str, object] = {}
    mid_stop_nodes: dict[str, object] = {}
    cruise_cap = _link_cruise_cap_mps(
        cal, replicate_field=replicate_field, mixed_traffic=mixed_traffic
    )
    bus_cruise_cap = _bus_link_cruise_cap_mps(
        cal, replicate_field=replicate_field, mixed_traffic=mixed_traffic
    )
    path_stops = list(
        corridor_stop_path_for_trip(
            trip_direction,  # type: ignore[arg-type]
            adhoc_informal_count=adhoc_informal_count,
            chainage_overrides=chainage_overrides,
            corridor_length_m=corridor_length_m,
        )
    )
    route_stops = [s for s in path_stops if s.key not in ("robinsons", "waltermart")]
    n_active_stops = sum(1 for s in path_stops if _stop_active(s))
    trip_target = onboard_travel_target_s(
        cal,
        include_informal_stops=bool(informal_keys),
        traffic=cal.field_traffic,
        informal_keys=informal_keys,
    )
    if trip_target and (_session_cruise_mid_mps(cal) or cal.onboard_cruise_mps):
        calibrated_dwell = _calibrated_stop_dwell_s(
            cal,
            n_active_stops,
            short_dwell_scale,
            travel_target_s=trip_target,
        )
    else:
        calibrated_dwell = None

    bus_cruise_scale = _field_bus_cruise_scale(
        cal,
        n_active_stops=n_active_stops,
        travel_target_s=trip_target,
        corridor_length_m=corridor_length_m or CORRIDOR_LENGTH_M,
        calibrated_dwell_s=calibrated_dwell,
    )

    jam = traffic_jam_density(cal.field_traffic if mixed_traffic else cal.field_traffic)
    cap_in = None
    from corridor_config import normalize_traffic_label

    traffic_tier = normalize_traffic_label(cal.field_traffic or "Light")
    if mixed_traffic and traffic_tier == "Heavy":
        cap_in = 0.50
    elif mixed_traffic and traffic_tier == "Moderate":
        cap_in = 0.72

    def _main_link_kwargs(
        chain_start_m: float,
        chain_end_m: float,
        *,
        forward_rb_to_wm: bool,
    ) -> dict:
        direction = "rb_to_wm" if forward_rb_to_wm else "wm_to_rb"
        lanes = main_road_lanes_for_segment(chain_start_m, chain_end_m, direction)  # type: ignore[arg-type]
        kw: dict = {"number_of_lanes": lanes, "jam_density": jam}
        if cap_in is not None:
            kw["capacity_in"] = cap_in
        return kw

    def _cruise_lane_splits(
        chain_start_m: float, chain_end_m: float, cruise_len_m: float
    ) -> list[tuple[float, float, float]]:
        """(sub_cruise_len, chain_lo, chain_hi) along Robinsons -> Waltermart axis."""
        lo = min(chain_start_m, chain_end_m)
        hi = max(chain_start_m, chain_end_m)
        span = hi - lo
        parts = list(iter_main_road_lane_segments(lo, hi, "rb_to_wm"))  # type: ignore[arg-type]
        if span <= 0 or len(parts) == 1:
            return [(cruise_len_m, lo, hi)]
        return [
            (cruise_len_m * (sub_hi - sub_lo) / span, sub_lo, sub_hi) for sub_lo, sub_hi, _ in parts
        ]

    def link_cruise(
        name: str,
        a: object,
        b: object,
        cruise_len: float,
        milestone_spacing_m: float,
        group: int,
        chain_start_m: float,
        chain_end_m: float,
    ) -> None:
        """Variable speed by field traffic; lane count from field 3-lane / 2-lane profile."""
        ft = cal.field_traffic or "Light"
        lane_splits = _cruise_lane_splits(chain_start_m, chain_end_m, cruise_len)
        current = a
        for lane_i, (lane_len, ch_lo, ch_hi) in enumerate(lane_splits):
            lane_name = name if len(lane_splits) == 1 else f"{name}_L{lane_i}"
            fwd_kw = _main_link_kwargs(ch_lo, ch_hi, forward_rb_to_wm=True)
            rev_kw = _main_link_kwargs(ch_lo, ch_hi, forward_rb_to_wm=False)
            segs = _cruise_speed_segments(
                lane_len,
                milestone_spacing_m,
                cruise_cap_mps=bus_cruise_cap * bus_cruise_scale,
                field_traffic=ft,
                for_bus=True,
            )
            if len(segs) == 1:
                seg_len, speed = segs[0]
                if lane_i == len(lane_splits) - 1:
                    nxt = b
                else:
                    x = float(getattr(current, "x", 0.0)) + seg_len
                    nxt = W.addNode(f"{lane_name}_join", x, 0.0)
                W.addLink(lane_name, current, nxt, seg_len, speed, signal_group=[group], **fwd_kw)
                W.addLink(
                    f"{lane_name}_rev",
                    nxt,
                    current,
                    seg_len,
                    speed,
                    signal_group=[1 - group],
                    **rev_kw,
                )
                current = nxt
                continue
            sub_current = current
            x = float(getattr(sub_current, "x", 0.0))
            for i, (seg_len, speed) in enumerate(segs):
                is_last_speed = i == len(segs) - 1
                is_last_lane = lane_i == len(lane_splits) - 1
                if is_last_speed and is_last_lane:
                    nxt = b
                else:
                    x += seg_len
                    nxt = W.addNode(f"{lane_name}_z{i}", x, 0.0)
                W.addLink(
                    f"{lane_name}_p{i}",
                    sub_current,
                    nxt,
                    seg_len,
                    speed,
                    signal_group=[group],
                    **fwd_kw,
                )
                W.addLink(
                    f"{lane_name}_p{i}_rev",
                    nxt,
                    sub_current,
                    seg_len,
                    speed,
                    signal_group=[1 - group],
                    **rev_kw,
                )
                sub_current = nxt
            current = sub_current

    rb_stop = W.addNode("Robinsons_BusStop", 0.0, 0.0)
    rb_road = W.addNode("Robinsons_Road", STOP_LINK_LENGTH_M, 0.0)
    dwell_rb = _dwell_seconds(
        "terminal_formal",
        cal,
        short_dwell_scale,
        calibrated_per_stop_s=calibrated_dwell,
        service_mode=service_mode,
    )
    u_rb = _speed_from_dwell(dwell_rb, max_mps=bus_cruise_cap)
    W.addLink("RB_Stop_in", rb_road, rb_stop, STOP_LINK_LENGTH_M, u_rb, number_of_lanes=STOP_LANES)
    W.addLink("RB_Stop_out", rb_stop, rb_road, STOP_LINK_LENGTH_M, u_rb, number_of_lanes=STOP_LANES)

    prev = rb_road
    prev_chain = 0.0

    length_m = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    stop_by_chain = network_milestone_stops(
        trip_direction=trip_direction,  # type: ignore[arg-type]
        chainage_overrides=chainage_overrides,
        corridor_length_m=length_m,
        adhoc_informal_count=adhoc_informal_count,
    )
    sig_by_chain = {s.chainage_m: s for s in CORRIDOR_SIGNALS}
    milestones = sorted(set(stop_by_chain) | set(sig_by_chain))

    for chain in milestones:
        cruise = _cruise_len(prev_chain, chain)
        spacing = _milestone_spacing(prev_chain, chain)
        if chain in sig_by_chain:
            sig = sig_by_chain[chain]
            g_eb, g_wb = signal_green_times(session, sig.key)
            node = W.addNode(
                sig.key,
                prev.x + cruise,
                0.0,
                signal=[g_eb, g_wb],
                signal_offset=signal_offset_s,
            )
            link_cruise(f"to_{sig.key}", prev, node, cruise, spacing, 0, prev_chain, chain)
            signal_nodes[sig.key] = node
            prev = node
        else:
            stop = stop_by_chain[chain]
            if not _stop_active(stop):
                next_road = W.addNode(f"Road_{stop.key}", prev.x + cruise, 0.0)
                link_cruise(f"skip_{stop.key}", prev, next_road, cruise, spacing, 0, prev_chain, chain)
                prev = next_road
            else:
                entry = W.addNode(f"{stop.key}_Entry", prev.x + cruise, 0.0)
                stop_n = W.addNode(f"{stop.key}_Stop", entry.x + STOP_LINK_LENGTH_M, 0.0)
                exit_n = W.addNode(f"{stop.key}_Exit", stop_n.x + STOP_LINK_LENGTH_M, 0.0)
                dwell = _dwell_seconds(
                    stop.kind,
                    cal,
                    short_dwell_scale,
                    calibrated_per_stop_s=calibrated_dwell,
                    service_mode=service_mode,
                )
                us = _speed_from_dwell(dwell, max_mps=bus_cruise_cap)
                W.addLink(f"{stop.key}_bay_in", entry, stop_n, STOP_LINK_LENGTH_M, us, number_of_lanes=STOP_LANES)
                W.addLink(f"{stop.key}_bay_out", stop_n, exit_n, STOP_LINK_LENGTH_M, us, number_of_lanes=STOP_LANES)
                mid_stop_nodes[stop.key] = stop_n
                link_cruise(f"to_{stop.key}", prev, entry, cruise, spacing, 0, prev_chain, chain)
                if not replicate_field:
                    bypass_len = cruise + 2.0 * STOP_LINK_LENGTH_M
                    bypass_segs = _cruise_speed_segments(
                        bypass_len,
                        spacing,
                        cruise_cap_mps=cruise_cap,
                        field_traffic=cal.field_traffic or "Light",
                        for_bus=False,
                    )
                    u_bypass = min(s for _, s in bypass_segs)
                    W.addLink(
                        f"bypass_{stop.key}",
                        prev,
                        exit_n,
                        bypass_len,
                        u_bypass,
                        signal_group=[0],
                        **_main_link_kwargs(prev_chain, chain, forward_rb_to_wm=True),
                    )
                    W.addLink(
                        f"bypass_{stop.key}_rev",
                        exit_n,
                        prev,
                        bypass_len,
                        u_bypass,
                        signal_group=[1],
                        **_main_link_kwargs(prev_chain, chain, forward_rb_to_wm=False),
                    )
                prev = exit_n
        prev_chain = chain

    cruise_wm = _cruise_len(prev_chain, length_m)
    spacing_wm = _milestone_spacing(prev_chain, length_m)
    wm_road = W.addNode("Waltermart_Road", prev.x + cruise_wm, 0.0)
    link_cruise("to_wm_road", prev, wm_road, cruise_wm, spacing_wm, 0, prev_chain, length_m)
    wm_stop = W.addNode("Waltermart_BusStop", wm_road.x + STOP_LINK_LENGTH_M, 0.0)
    dwell_wm = _dwell_seconds(
        "terminal_formal",
        cal,
        short_dwell_scale,
        calibrated_per_stop_s=calibrated_dwell,
        service_mode=service_mode,
    )
    u_wm = _speed_from_dwell(dwell_wm, max_mps=bus_cruise_cap)
    W.addLink("WM_Stop_in", wm_road, wm_stop, STOP_LINK_LENGTH_M, u_wm, number_of_lanes=STOP_LANES)
    W.addLink("WM_Stop_out", wm_stop, wm_road, STOP_LINK_LENGTH_M, u_wm, number_of_lanes=STOP_LANES)

    if replicate_field:
        policy = "FIELD REPLICATION (one bus, all stops, no bypass)"
    elif informal_keys == ALL_INFORMAL_STOP_KEYS and formal_keys == ALL_FORMAL_MID_STOP_KEYS:
        policy = "transit (formal + all informal)"
    elif informal_keys and formal_keys:
        policy = f"encounter F={''.join('1' if k in formal_keys else '0' for k in ('rkp_trading', 'villa_verde', 'vista_mall'))} I={''.join('1' if k in informal_keys else '0' for k in ('korean_grocery', 'seven_eleven', 'rcbc'))}"
    elif not informal_keys and formal_keys:
        policy = "formal only (informal bypassed)"
    elif informal_keys and not formal_keys:
        policy = "informal curbs only"
    else:
        policy = "optimized (formal + Vista; informal removed)"
    from corridor_config import signal_cycle_seconds

    sig_line = ", ".join(
        f"{s.key}@{s.chainage_m:.0f}m ({signal_cycle_seconds(session, s.key):.0f}s)"
        for s in CORRIDOR_SIGNALS
    )
    if not quiet:
        print(f"  Extended corridor: {policy}")
        print(f"  Length {CORRIDOR_LENGTH_M:.0f} m | session={session!r} | signals: {sig_line}")
        print(f"  Synchronized offset {signal_offset_s:.0f} s on all signals")
        if mixed_traffic and cruise_cap:
            bus_lim = bus_traffic_speed_limits_kmh(cal.field_traffic or "Light")
            lim = general_traffic_speed_limits_kmh(cal.field_traffic or "Light")
            print(
                f"  Bus speeds (traffic={cal.field_traffic!r}; max 50 km/h): "
                f"mid {bus_lim['mid_block_kmh']:.0f}, near stop {bus_lim['near_stop_signal_kmh']:.0f}, "
                f"close {bus_lim['close_spacing_kmh']:.0f} km/h"
            )
            print(
                f"  General traffic (max {GENERAL_VEHICLE_SPEED_KMH:.0f} km/h): "
                f"mid {lim['mid_block_kmh']:.0f}, near {lim['near_stop_signal_kmh']:.0f}, "
                f"close {lim['close_spacing_kmh']:.0f} km/h"
            )
        crowd_mult = _crowding_dwell_mult(cal)
        if cal.field_crowding:
            print(
                f"  Formal-stop dwell × crowding ({cal.field_crowding!r}): "
                f"{crowd_mult:.2f} (field data: Low=shorter, High=longer)"
            )
        ob = cal.onboard_stop_dwell_s
        if ob:
            print(
                f"  On-board formal stop dwell (session mean): {ob:.0f} s "
                f"({ob / 60:.1f} min) | terminal stationary med ~"
                f"{(float(cal.mean_dwell_rb_s or 0) + float(cal.mean_dwell_wm_s or 0)) / 2:.0f} s"
            )
        elif cruise_cap and cal.field_speed_max_kmh and replicate_field:
            print(
                f"  Cruise cap (field mid × traffic): {cruise_cap * 3.6:.2f} km/h "
                f"[band {cal.field_speed_min_kmh:.2f}–{cal.field_speed_max_kmh:.2f}; "
                f"traffic={cal.field_traffic!r}]"
            )
        elif cruise_cap and cal.field_speed_max_kmh:
            print(
                f"  Cruise cap (field bus avg speed max): {cal.field_speed_max_kmh:.2f} km/h "
                f"[band {cal.field_speed_min_kmh:.2f}–{cal.field_speed_max_kmh:.2f}]"
            )
        elif cruise_cap:
            print(f"  Cruise cap from on-board avg speed: {cruise_cap * 3.6:.1f} km/h")
        else:
            print(
                "  Cruise speeds: 60 km/h mid-block, 40 km/h near stops/signals, "
                "30 km/h when milestones < {:.0f} m apart".format(CLOSE_MILESTONE_SPACING_M)
            )
        if calibrated_dwell:
            print(
                f"  Calibrated dwell per stop: {calibrated_dwell:.0f} s "
                f"(targets on-board {cal.onboard_travel_time_s / 60:.1f} min trip)"
            )
        elif trip_target:
            label = "transit" if informal_keys == ALL_INFORMAL_STOP_KEYS else "partial/formal encounter"
            print(f"  On-board target travel time ({label}): {trip_target / 60:.1f} min")

    return {
        "rb_bus_stop": rb_stop,
        "wm_bus_stop": wm_stop,
        "rb_road": rb_road,
        "wm_road": wm_road,
        "mid_stops": mid_stop_nodes,
        "signal": signal_nodes.get("pala_pala"),
        "signals": signal_nodes,
        "path_ctx": {
            "adhoc_informal_count": adhoc_informal_count,
            "chainage_overrides": chainage_overrides,
            "corridor_length_m": corridor_length_m,
        },
    }
