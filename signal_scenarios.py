"""
Green/Red encounter patterns for a one-way corridor trip.

Field data: single leg (e.g. Waltermart -> Robinsons), passing 2 traffic signals once each
-> 2^2 = 4 patterns (G-G, G-R, R-G, R-R).

3 sessions x 4 policies x 4 = 48 simulations.

Signal cycle length depends on session (see corridor_config).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

from corridor_config import (
    CORRIDOR_SIGNALS,
    FREE_FLOW_MPS,
    SIGNAL_ENCOUNTERS_ONE_WAY,
    signal_cycle_seconds,
    signal_green_times,
)

N_SIGNALS = len(CORRIDOR_SIGNALS)
TripDirection = Literal["rb_to_wm", "wm_to_rb"]


def _signal_index_for_encounter(encounter_i: int, direction: TripDirection) -> int:
    """Travel-order encounter index -> index in CORRIDOR_SIGNALS (chainage from Robinsons)."""
    if direction == "rb_to_wm":
        return encounter_i
    # wm_to_rb: waltermart_int first, then pala_pala
    return (N_SIGNALS - 1) - encounter_i


def _arrival_t_eb(signal_index: int) -> float:
    return CORRIDOR_SIGNALS[signal_index].chainage_m / FREE_FLOW_MPS


def _arrival_t_wb(signal_index: int) -> float:
    from corridor_config import CORRIDOR_LENGTH_M

    return (CORRIDOR_LENGTH_M - CORRIDOR_SIGNALS[signal_index].chainage_m) / FREE_FLOW_MPS


def _encounter_group_and_base_arrival(
    encounter_i: int,
    direction: TripDirection,
) -> tuple[int, float]:
    sig_idx = _signal_index_for_encounter(encounter_i, direction)
    if direction == "rb_to_wm":
        return 0, _arrival_t_eb(sig_idx)
    return 1, _arrival_t_wb(sig_idx)


def _encounter_signal_key(encounter_i: int, direction: TripDirection) -> str:
    return CORRIDOR_SIGNALS[_signal_index_for_encounter(encounter_i, direction)].key


def _encounter_timing(encounter_i: int, session: str, direction: TripDirection) -> tuple[float, float, float]:
    key = _encounter_signal_key(encounter_i, direction)
    main, side = signal_green_times(session, key)
    # UXsim two-phase cycle = main + side (yellow/all-red folded into side clearance).
    cycle = main + side
    return cycle, main, side


def _group_is_green(
    t: float,
    group: int,
    offset_s: float,
    cycle_s: float,
    main_green_s: float,
    direction: TripDirection,
) -> bool:
    """
    Aguinaldo through traffic (EB and WB) proceeds during the main-road green phase.
    UXsim phase 0 length = main, phase 1 = side (cross-street).
    """
    t_mod = (t + offset_s) % cycle_s
    on_main = t_mod < main_green_s
    if direction == "rb_to_wm":
        return on_main if group == 0 else not on_main
    # wm_to_rb: WB arterial uses main phase (not the side-street phase)
    return on_main if group == 1 else not on_main


def _offset_for_group_at_time(
    want_green: bool,
    group: int,
    arrival_t: float,
    session: str,
    encounter_i: int,
    direction: TripDirection,
) -> float:
    cycle, main_green, side_green = _encounter_timing(encounter_i, session, direction)
    candidates = (0.0, main_green)
    for off in candidates:
        if _group_is_green(arrival_t, group, off, cycle, main_green, direction) == want_green:
            return off
    return candidates[0] if want_green else candidates[1]


def _shift_for_group_at_time(
    want_green: bool,
    group: int,
    offset_s: float,
    base_arrival_t: float,
    session: str,
    encounter_i: int,
    direction: TripDirection,
) -> float:
    cycle, main_green, side_green = _encounter_timing(encounter_i, session, direction)
    step = 5.0
    for shift in range(0, int(cycle), int(step)):
        if _group_is_green(base_arrival_t + float(shift), group, offset_s, cycle, main_green, direction) == want_green:
            return float(shift)
    return 0.0 if want_green else side_green


@dataclass(frozen=True)
class SignalEncounterScenario:
    scenario_id: str
    encounter_greens: tuple[bool, ...]
    session: str
    trip_direction: TripDirection
    signal_offset_s: float
    demand_shift_s: float
    leg_shifts_s: tuple[float, ...]

    @property
    def n_encounters(self) -> int:
        return len(self.encounter_greens)

    @property
    def encounter_pattern(self) -> str:
        return "-".join("G" if g else "R" for g in self.encounter_greens)

    # Back-compat for simulation_extended
    @property
    def wm_to_rb_demand_shift_s(self) -> float:
        return self.demand_shift_s if self.trip_direction == "wm_to_rb" else 0.0

    @property
    def extra_rb_to_wm_shifts(self) -> tuple[float, ...]:
        return ()


def _scenario_id(pattern: tuple[bool, ...]) -> str:
    return "enc_" + "_".join("G" if g else "R" for g in pattern)


def build_signal_scenario(
    pattern: tuple[bool, ...],
    session: str,
    direction: TripDirection,
) -> SignalEncounterScenario:
    if len(pattern) != N_SIGNALS:
        raise ValueError(f"pattern must have {N_SIGNALS} encounters (one per signal), got {len(pattern)}")

    leg_shifts: list[float] = []
    group0, t0 = _encounter_group_and_base_arrival(0, direction)
    offset = _offset_for_group_at_time(pattern[0], group0, t0, session, 0, direction)

    cumulative = 0.0
    for i in range(1, len(pattern)):
        group, base_t = _encounter_group_and_base_arrival(i, direction)
        shift = _shift_for_group_at_time(
            pattern[i], group, offset, base_t + cumulative, session, i, direction
        )
        leg_shifts.append(shift)
        cumulative += shift

    demand_shift = leg_shifts[-1] if leg_shifts else 0.0

    return SignalEncounterScenario(
        scenario_id=_scenario_id(pattern),
        encounter_greens=pattern,
        session=session,
        trip_direction=direction,
        signal_offset_s=offset,
        demand_shift_s=demand_shift,
        leg_shifts_s=tuple(leg_shifts),
    )


def trip_direction_for_data_origin(origin: str) -> TripDirection:
    """Waltermart-origin field rows -> WM to Robinsons; Robinsons-origin -> RB to WM."""
    return "wm_to_rb" if origin == "waltermart" else "rb_to_wm"


def all_signal_scenarios(
    n_encounters: int | None = None,
    session: str = "Afternoon Session",
    direction: TripDirection = "wm_to_rb",
) -> tuple[SignalEncounterScenario, ...]:
    n = n_encounters if n_encounters is not None else SIGNAL_ENCOUNTERS_ONE_WAY
    if n != N_SIGNALS:
        raise ValueError(f"n_encounters must be {N_SIGNALS} (one-way, one pass per signal)")
    patterns = list(itertools.product((True, False), repeat=n))
    return tuple(build_signal_scenario(p, session, direction) for p in patterns)


SIGNAL_ENCOUNTER_SCENARIOS: tuple[SignalEncounterScenario, ...] = all_signal_scenarios()
