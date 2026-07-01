"""
Field corridor: Robinsons Pala-Pala — Waltermart Dasmariñas (Emilio Aguinaldo Hwy).

Chainage from Robinsons terminal (Dec 2025 field survey). GPS and segment distances
from observation flows (Robinsons-origin and Waltermart-origin).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_PROJECT_DIR = Path(__file__).resolve().parent
FIELD_STATIONARY_CSV = _PROJECT_DIR / "field_stationary_observations.csv"

# --- Highway physics (shared) ---
# Maximum mid-block cruise for general traffic when field traffic is Light (not a fixed speed).
GENERAL_VEHICLE_SPEED_KMH = 60.0
GENERAL_VEHICLE_SPEED_MPS = GENERAL_VEHICLE_SPEED_KMH / 3.6  # 16.667 m/s
# Thesis caps: buses never exceed 50 km/h on corridor links; cars/jeeps/etc. up to 60 km/h.
BUS_MAX_SPEED_KMH = 50.0
BUS_MAX_SPEED_MPS = BUS_MAX_SPEED_KMH / 3.6
FREE_FLOW_MPS = GENERAL_VEHICLE_SPEED_MPS  # upper bound; actual cap uses TRAFFIC_CRUISE_MULT
# Variable cruise (thesis): 60 mid-block max (Light only); 40 near stops/signals; 30 close spacing; 25 if Heavy.
CRUISE_SPEED_NEAR_KMH = 40.0
CRUISE_SPEED_CLOSE_KMH = 30.0
CRUISE_SPEED_CLOSE_HEAVY_KMH = 25.0
CRUISE_SPEED_NEAR_MPS = CRUISE_SPEED_NEAR_KMH / 3.6
CRUISE_SPEED_CLOSE_MPS = CRUISE_SPEED_CLOSE_KMH / 3.6
CRUISE_SPEED_CLOSE_HEAVY_MPS = CRUISE_SPEED_CLOSE_HEAVY_KMH / 3.6
NEAR_FEATURE_M = 150.0
CLOSE_MILESTONE_SPACING_M = 450.0
LANES_MAIN = 2
STOP_LINK_LENGTH_M = 25.0
STOP_LANES = 1
DEFAULT_DWELL_S = 40.0

# Terminal-to-terminal: field segment sum from Korean-grocery start (3178 m) + ~77 m to Robinsons.
CORRIDOR_LENGTH_M = 3255.0

# --- Main-road lane geometry (field, Dec 2025) ---
# Robinsons -> Waltermart: 3 lanes Korean grocery through Pala-Pala intersection line (~140 m),
# then 2 lanes to 7-Eleven and Waltermart.
# Waltermart -> Robinsons: 2 lanes for 2.9 km from Waltermart, then 3 lanes through Pala-Pala to Robinsons.
GPS_PALA_INTERSECTION_LINE = (14.301985926313263, 120.95414914479397)
GPS_WM_RB_LANE_EXPAND = (14.31226463406824, 120.94793128291685)
KOREAN_GROCERY_CHAINAGE_M = 77.0
KOREAN_TO_PALA_INTERSECTION_LINE_M = 140.0
RB_TO_WM_THREE_LANE_END_M = KOREAN_GROCERY_CHAINAGE_M + KOREAN_TO_PALA_INTERSECTION_LINE_M  # 217 m
WM_TO_RB_TWO_LANE_FROM_WM_M = 2900.0
WM_TO_RB_THREE_LANE_END_M = CORRIDOR_LENGTH_M - WM_TO_RB_TWO_LANE_FROM_WM_M  # 355 m from Robinsons
LANES_MAIN_MAX = 3
LANES_MAIN_MIN = 2

# GPS (field coordinates).
GPS_ROBINSONS_TERMINAL = (14.300037, 120.954412)
GPS_KOREAN_GROCERY = (14.300720, 120.954320)
GPS_PALA_PALA_SIGNAL = (14.302125, 120.954055)
GPS_SEVEN_ELEVEN = (14.301972, 120.954139)
GPS_RKP_TRADING = (14.303230, 120.954053)
GPS_VISTA_MALL = (14.31687, 120.94415)
GPS_WALTERMART_INT_SIGNAL = (14.322364, 120.941649)
GPS_RCBC = (14.322737, 120.941631)
GPS_WALTERMART_TERMINAL = (14.324939, 120.940955)
GPS_WALTERMART_START = (14.325265, 120.940696)
GPS_VILLA_VERDE = (14.3149, 120.9450)

GPS_STOPS = {
    "robinsons": GPS_ROBINSONS_TERMINAL,
    "korean_grocery": GPS_KOREAN_GROCERY,
    "seven_eleven": GPS_SEVEN_ELEVEN,
    "rkp_trading": GPS_RKP_TRADING,
    "villa_verde": GPS_VILLA_VERDE,
    "vista_mall": GPS_VISTA_MALL,
    "rcbc": GPS_RCBC,
    "waltermart": GPS_WALTERMART_TERMINAL,
    "pala_pala": GPS_PALA_PALA_SIGNAL,
    "waltermart_int": GPS_WALTERMART_INT_SIGNAL,
}

# Legacy alias
GPS_ORIGIN_RB = GPS_ROBINSONS_TERMINAL


def format_gps_coordinates(lat: float, lon: float) -> str:
    """WGS84 as 'latitude, longitude' for CSV / thesis tables."""
    return f"{lat:.6f}, {lon:.6f}"


def coordinates_for_corridor_key(key: str) -> str:
    """GPS string for a corridor stop or signal key (empty if unknown)."""
    pair = GPS_STOPS.get(str(key or "").strip().lower())
    if not pair:
        return ""
    return format_gps_coordinates(pair[0], pair[1])


def observation_coordinates(*, data_origin: str = "", location: str = "") -> str:
    """GPS of the stationary observation terminal (Robinsons or Waltermart)."""
    loc = str(location or "").strip().lower()
    origin = str(data_origin or "").strip().lower()
    if "walter" in loc or "waltermart" in origin:
        return coordinates_for_corridor_key("waltermart")
    if "robinson" in loc or "robinsons" in origin:
        return coordinates_for_corridor_key("robinsons")
    return ""


@dataclass(frozen=True)
class SignalPhaseTiming:
    """Field signal phase durations (seconds)."""

    main_green_s: float
    side_green_s: float
    yellow_s: float = 3.0
    all_red_s: float = 2.0

    @property
    def cycle_s(self) -> float:
        return self.main_green_s + self.side_green_s + 2.0 * self.yellow_s + self.all_red_s


# Pala-Pala intersection (Robinsons end) — field Aguinaldo GREEN (main) / cross RED (side).
# Green: Morning ~55 s, Lunch ~65 s, Afternoon ~75 s. Cross red: 145 s (AM/Lunch), 175 s (PM).
SIGNAL_PHASE_PALA_PALA: dict[str, SignalPhaseTiming] = {
    "Morning Session": SignalPhaseTiming(55.0, 145.0, 3.0, 2.0),
    "Lunch": SignalPhaseTiming(65.0, 145.0, 3.0, 2.0),
    "Afternoon Session": SignalPhaseTiming(75.0, 175.0, 3.0, 2.0),
}

# Waltermart intersection — Dec field timings (all-red 1 s per phase table).
SIGNAL_PHASE_WALTERMART: dict[str, SignalPhaseTiming] = {
    "Morning Session": SignalPhaseTiming(40.0, 25.0, 3.0, 1.0),
    "Lunch": SignalPhaseTiming(33.0, 20.0, 3.0, 1.0),
    "Afternoon Session": SignalPhaseTiming(50.0, 30.0, 3.0, 1.0),
}

# Published total cycle lengths (field tables; used for UXsim cycle).
SESSION_SIGNAL_CYCLE_ROBINSONS: dict[str, float] = {
    "Morning Session": 208.0,  # 55 + 145 + yellow/all-red
    "Lunch": 218.0,  # 65 + 145 + yellow/all-red
    "Afternoon Session": 258.0,  # 75 + 175 + yellow/all-red
}
SESSION_SIGNAL_CYCLE_WALTERMART: dict[str, float] = {
    "Morning Session": 73.0,
    "Lunch": 61.0,
    "Afternoon Session": 88.0,
}

SIGNAL_CYCLE_PROFILE: dict[str, str] = {
    "pala_pala": "robinsons",
    "waltermart_int": "waltermart",
}

# Legacy defaults
SIGNAL_CYCLE_S = 180.0
SIGNAL_GREEN_EB_S = 90.0
SIGNAL_GREEN_WB_S = 90.0


def _phase_table(signal_key: str) -> dict[str, SignalPhaseTiming]:
    if signal_key == "pala_pala":
        return SIGNAL_PHASE_PALA_PALA
    if signal_key == "waltermart_int":
        return SIGNAL_PHASE_WALTERMART
    return SIGNAL_PHASE_PALA_PALA


def signal_cycle_seconds(session: str, signal_key: str) -> float:
    """Total cycle length (s): main + side + yellow + all-red from phase table."""
    return signal_phase_timing(session, signal_key).cycle_s


def signal_green_times(session: str, signal_key: str) -> tuple[float, float]:
    """
    (EB green s, WB green s) for UXsim two-phase signal.

    Main-road green serves Aguinaldo through traffic (EB on Robinsons→Waltermart);
  side-road green is the cross-street phase.
    """
    ph = _phase_table(signal_key)[session]
    return ph.main_green_s, ph.side_green_s


def signal_phase_timing(session: str, signal_key: str) -> SignalPhaseTiming:
    return _phase_table(signal_key)[session]


@dataclass(frozen=True)
class CorridorSignal:
    key: str
    label: str
    chainage_m: float
    gps: tuple[float, float]
    green_eb_s: float = SIGNAL_GREEN_EB_S

    @property
    def green_wb_s(self) -> float:
        return self.green_eb_s

    def cycle_s(self, session: str = "Afternoon Session") -> float:
        return signal_cycle_seconds(session, self.key)

    def greens(self, session: str) -> tuple[float, float]:
        return signal_green_times(session, self.key)


CORRIDOR_SIGNALS: tuple[CorridorSignal, ...] = (
    CorridorSignal("pala_pala", "Pala-Pala Intersection Signal", 237.0, GPS_PALA_PALA_SIGNAL),
    CorridorSignal(
        "waltermart_int",
        "Waltermart Dasmariñas Intersection Signal",
        2955.0,
        GPS_WALTERMART_INT_SIGNAL,
    ),
)

SIGNAL_ENCOUNTERS_ONE_WAY = len(CORRIDOR_SIGNALS)
SIGNAL_ENCOUNTERS_PER_ROUND_TRIP = SIGNAL_ENCOUNTERS_ONE_WAY

StopKind = Literal["terminal_formal", "formal", "informal", "signal"]


@dataclass(frozen=True)
class CorridorStop:
    chainage_m: float
    key: str
    label: str
    kind: StopKind
    direction: Literal["rb_to_wm", "wm_to_rb", "both"]


# Forward (Robinsons → Waltermart): chainage from Robinsons anchor (0 m).
# rb→wm field trips do NOT stop at Robinsons/Pala-Pala — buses enter at the first
# informal curb (Korean grocery ~77 m) or first formal mid (RKP ~355 m). The
# robinsons row here is chainage reference only on this leg.
STOPS_RB_TO_WM: tuple[CorridorStop, ...] = (
    CorridorStop(0, "robinsons", "Robinson Place Dasmariñas (formal bus stop)", "terminal_formal", "both"),
    CorridorStop(77, "korean_grocery", "Informal stop (Korean grocery)", "informal", "rb_to_wm"),
    CorridorStop(277, "seven_eleven", "7-Eleven Pala Pala (informal)", "informal", "rb_to_wm"),
    CorridorStop(355, "rkp_trading", "RKP Trading Corporation (formal)", "formal", "rb_to_wm"),
    CorridorStop(2180, "villa_verde", "Villa Verde (formal)", "formal", "rb_to_wm"),
    CorridorStop(2255, "vista_mall", "Vista Mall Dasmariñas (formal)", "formal", "rb_to_wm"),
    CorridorStop(2995, "rcbc", "RCBC Bank (informal)", "informal", "rb_to_wm"),
    CorridorStop(CORRIDOR_LENGTH_M, "waltermart", "Waltermart Dasmariñas (formal bus stop)", "terminal_formal", "both"),
)

# Reverse (Waltermart → Robinsons): chainage from Waltermart observation start.
# Field on-board notes: ~4 mid-route stops (RCBC, Vista Mall, Villa Verde, RKP / market stops).
# Informal curb stops (bit order matches scenario I_<mask> in scenario_catalog).
INFORMAL_STOP_KEYS: tuple[str, ...] = ("korean_grocery", "seven_eleven", "rcbc")
ALL_INFORMAL_STOP_KEYS: frozenset[str] = frozenset(INFORMAL_STOP_KEYS)

INFORMAL_STOP_LABELS: dict[str, str] = {
    "korean_grocery": "Korean grocery",
    "seven_eleven": "7-Eleven",
    "rcbc": "RCBC",
}

# Mid-route formal stops (Robinsons/Waltermart bus stops are leg-specific — see terminal_stop_served).
FORMAL_MID_STOP_KEYS: tuple[str, ...] = ("rkp_trading", "villa_verde", "vista_mall")
ALL_FORMAL_MID_STOP_KEYS: frozenset[str] = frozenset(FORMAL_MID_STOP_KEYS)

FORMAL_MID_STOP_LABELS: dict[str, str] = {
    "rkp_trading": "RKP Trading",
    "villa_verde": "Villa Verde",
    "vista_mall": "Vista Mall",
}

# Unlisted / flag-down informal curbs (not in field GPS map). Chainage from Robinsons (rb→wm).
# U1 = near Robinsons; U2 adds mid-corridor; U3 adds downstream before Waltermart.
ADHOC_INFORMAL_CHAINAGES_M: tuple[float, ...] = (
    520.0,
    CORRIDOR_LENGTH_M * 0.5,
    2350.0,
)

# Driver service at curb (drop-off only, brief full stop, unlisted informals).
SERVICE_MODES: tuple[str, ...] = ("full", "alight_only", "drive_through")
SERVICE_MODE_LABELS: dict[str, str] = {
    "full": "Full board + alight (field dwell)",
    "alight_only": "Drop-off only — no pick-up, shortened dwell",
    "drive_through": "Brief curb stop — pick-up/drop-off/wait, ~55% field dwell",
}
SERVICE_MODE_CODES: dict[str, str] = {"full": "F", "alight_only": "A", "drive_through": "D"}
ALIGHT_ONLY_DWELL_MULT = 0.35
DRIVE_THROUGH_DWELL_MULT = 0.55
DRIVE_THROUGH_DWELL_MIN_S = 12.0

STOPS_WM_TO_RB: tuple[CorridorStop, ...] = (
    CorridorStop(0, "waltermart", "Waltermart Dasmariñas (formal bus stop)", "terminal_formal", "both"),
    CorridorStop(260, "rcbc", "RCBC Bank (informal)", "informal", "wm_to_rb"),
    CorridorStop(1000, "vista_mall", "Vista Mall Dasmariñas (formal)", "formal", "wm_to_rb"),
    CorridorStop(1075, "villa_verde", "Villa Verde (formal)", "formal", "wm_to_rb"),
    CorridorStop(2900, "rkp_trading", "RKP Trading Corporation (formal)", "formal", "wm_to_rb"),
    CorridorStop(CORRIDOR_LENGTH_M, "robinsons", "Robinson Place Dasmariñas (formal bus stop)", "terminal_formal", "both"),
)

# On-board session travel-time means (seconds) — filled from June 2026 San Agustin on-board sheet.
SESSION_ONBOARD_TRAVEL_S: dict[str, float] = {}
SESSION_ONBOARD_DEC_TRAVEL_S = SESSION_ONBOARD_TRAVEL_S  # deprecated alias

# Scale session on-board target by stationary traffic tier.
TRAFFIC_ONBOARD_TRAVEL_MULT: dict[str, float] = {
    "Light": 0.95,
    "Moderate": 1.0,
    "Heavy": 1.18,
}

# On-board 'traffic signal delay' scales more with congestion than total travel time.
TRAFFIC_ONBOARD_SIGNAL_MULT: dict[str, float] = {
    "Light": 0.92,
    "Moderate": 1.0,
    "Heavy": 1.32,
}

# Villa Verde / Vista Mall: formal mid-route stops on Robinsons -> Waltermart only (field route).
VILLA_VERDE_CHAINAGE_FROM_ROBINSONS_M = 2180.0


def terminal_stop_served(
    stop_key: str,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
) -> bool:
    """
    Terminal bus stops modeled on each corridor leg.

    rb→wm: Waltermart destination only (no Robinsons stop — field entry is upstream at informal/formal mids).
    wm→rb: Waltermart origin + Robinsons destination bus stop.
    """
    if stop_key == "robinsons":
        return trip_direction == "wm_to_rb"
    if stop_key == "waltermart":
        return True
    return False


def stop_encounter_active(
    stop: CorridorStop,
    *,
    formal_keys: frozenset[str],
    informal_keys: frozenset[str],
    trip_direction: Literal["rb_to_wm", "wm_to_rb"] | None = None,
) -> bool:
    """Whether a modeled stop is served under a scenario encounter policy."""
    if stop.key.startswith("adhoc_unlisted_"):
        return True
    if stop.kind == "terminal_formal":
        if trip_direction is not None:
            return terminal_stop_served(stop.key, trip_direction)
        return True
    if stop.kind == "formal":
        return stop.key in formal_keys
    if stop.kind == "informal":
        return stop.key in informal_keys
    return True


def trip_origin_stop(
    path: tuple[CorridorStop, ...],
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
    *,
    formal_keys: frozenset[str],
    informal_keys: frozenset[str],
) -> CorridorStop:
    """First stop where the bus is modeled as boarding on this leg."""
    if trip_direction == "wm_to_rb":
        return next(s for s in path if s.key == "waltermart")
    dest_key = "waltermart"
    for s in path:
        if s.key == dest_key:
            continue
        if stop_encounter_active(
            s,
            formal_keys=formal_keys,
            informal_keys=informal_keys,
            trip_direction=trip_direction,
        ):
            return s
    # rb→wm: field boarding is upstream (Korean grocery / Pala-Pala), even when no mids are served.
    for s in path:
        if s.kind == "informal" and s.trip_direction in ("rb_to_wm", "both"):
            return s
    raise ValueError(f"No origin stop on {trip_direction} path for encounter policy")


def adhoc_informal_stops(
    n: int,
    *,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
) -> tuple[CorridorStop, ...]:
    """Synthetic unlisted informal bays (not among the 3 surveyed curbs)."""
    if n <= 0:
        return ()
    labels = (
        "Unlisted informal curb #1 (near Robinsons)",
        f"Unlisted informal curb #2 (mid-corridor ~{CORRIDOR_LENGTH_M * 0.5 / 1000:.2f} km)",
        "Unlisted informal curb #3 (downstream toward Waltermart)",
    )
    out: list[CorridorStop] = []
    for i, chain_rb in enumerate(ADHOC_INFORMAL_CHAINAGES_M[:n]):
        out.append(
            CorridorStop(
                chain_rb,
                f"adhoc_unlisted_{i + 1}",
                labels[i] if i < len(labels) else f"Unlisted informal curb #{i + 1}",
                "informal",
                trip_direction,  # type: ignore[arg-type]
            )
        )
    return tuple(out)


def corridor_stop_path_for_trip(
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
    *,
    adhoc_informal_count: int = 0,
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
) -> tuple[CorridorStop, ...]:
    """Terminals + mid-route stops + optional ad-hoc informals, sorted along trip."""
    length = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    base = list(STOPS_RB_TO_WM if trip_direction == "rb_to_wm" else STOPS_WM_TO_RB)
    if adhoc_informal_count > 0:
        base.extend(
            adhoc_informal_stops(adhoc_informal_count, trip_direction=trip_direction)
        )

    def sort_key(s: CorridorStop) -> float:
        return _stop_chainage_from_robinsons(
            s,
            trip_direction=trip_direction,
            corridor_length_m=length,
            chainage_overrides=chainage_overrides,
        )

    return tuple(sorted(base, key=sort_key))


def chainage_from_robinsons(stop: CorridorStop) -> float:
    """Map a corridor stop to chainage (m) from Robinsons terminal."""
    if stop.key == "robinsons":
        return 0.0
    if stop.key == "waltermart":
        return CORRIDOR_LENGTH_M
    rb = next((s for s in STOPS_RB_TO_WM if s.key == stop.key), None)
    if rb is not None:
        return rb.chainage_m
    return CORRIDOR_LENGTH_M - stop.chainage_m


def _stop_chainage_from_robinsons(
    stop: CorridorStop,
    *,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
    corridor_length_m: float,
    chainage_overrides: dict[str, float] | None,
) -> float:
    if chainage_overrides and stop.key in chainage_overrides:
        return float(chainage_overrides[stop.key])
    if trip_direction == "rb_to_wm":
        return stop.chainage_m
    return corridor_length_m - stop.chainage_m


def main_road_lanes_at_chainage(
    chainage_from_robinsons_m: float,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
) -> int:
    """Lane count on Emilio Aguinaldo mainline at chainage (from Robinsons terminal)."""
    if trip_direction == "rb_to_wm":
        return LANES_MAIN_MAX if chainage_from_robinsons_m <= RB_TO_WM_THREE_LANE_END_M else LANES_MAIN_MIN
    return LANES_MAIN_MIN if chainage_from_robinsons_m >= WM_TO_RB_THREE_LANE_END_M else LANES_MAIN_MAX


def main_road_lanes_for_segment(
    chainage_start_m: float,
    chainage_end_m: float,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
) -> int:
    """Lanes for a link using midpoint chainage (stable when segment does not cross a taper)."""
    mid = 0.5 * (chainage_start_m + chainage_end_m)
    return main_road_lanes_at_chainage(mid, trip_direction)


def iter_main_road_lane_segments(
    chainage_start_m: float,
    chainage_end_m: float,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
):
    """
    Yield (sub_start, sub_end, lanes) when a link crosses a 3-lane / 2-lane boundary.
    Chainage always increases along Robinsons -> Waltermart axis.
    """
    lo = min(chainage_start_m, chainage_end_m)
    hi = max(chainage_start_m, chainage_end_m)
    bound = RB_TO_WM_THREE_LANE_END_M if trip_direction == "rb_to_wm" else WM_TO_RB_THREE_LANE_END_M
    lanes_lo = main_road_lanes_at_chainage(lo, trip_direction)
    lanes_hi = main_road_lanes_at_chainage(hi, trip_direction)
    if lanes_lo == lanes_hi:
        yield lo, hi, lanes_lo
        return
    if lo < bound < hi:
        yield lo, bound, main_road_lanes_at_chainage(lo, trip_direction)
        yield bound, hi, main_road_lanes_at_chainage(hi, trip_direction)
    else:
        mid = 0.5 * (lo + hi)
        yield lo, hi, main_road_lanes_at_chainage(mid, trip_direction)


def network_milestone_stops(
    *,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
    chainage_overrides: dict[str, float] | None = None,
    corridor_length_m: float | None = None,
    adhoc_informal_count: int = 0,
) -> dict[float, CorridorStop]:
    """Stops placed on the corridor for this trip direction (chainage from Robinsons)."""
    length = corridor_length_m if corridor_length_m is not None else CORRIDOR_LENGTH_M
    by_chain: dict[float, CorridorStop] = {}
    for s in corridor_stop_path_for_trip(
        trip_direction,
        adhoc_informal_count=adhoc_informal_count,
        chainage_overrides=chainage_overrides,
        corridor_length_m=length,
    ):
        if s.key in ("robinsons", "waltermart"):
            continue
        ch = _stop_chainage_from_robinsons(
            s,
            trip_direction=trip_direction,
            corridor_length_m=length,
            chainage_overrides=chainage_overrides,
        )
        by_chain[ch] = s
    return by_chain

@dataclass(frozen=True)
class SessionBusField:
    """On-board average bus speed band and conditions (field book)."""

    speed_min_kmh: float
    speed_max_kmh: float
    crowding: str
    traffic: str

    @property
    def speed_mid_mps(self) -> float:
        return (self.speed_min_kmh + self.speed_max_kmh) / 2.0 / 3.6

    @property
    def speed_cap_mps(self) -> float:
        """Cruise cap: field buses do not exceed the observed average-speed maximum."""
        return self.speed_max_kmh / 3.6


# Field on-board bus speed bands by traffic condition (Dec workbook / thesis).
TRAFFIC_FIELD_SPEED_BAND_KMH: dict[str, tuple[float, float]] = {
    "Light": (29.18, 45.44),
    "Moderate": (25.18, 31.20),
    "Heavy": (24.56, 31.24),
}

# Labels for results CSV (Jan 18 on-board sheet: crowding + traffic per session).
SESSION_BUS_FIELD: dict[str, SessionBusField] = {
    "Morning Session": SessionBusField(27.48, 37.5, "Low", "Light"),
    "Lunch": SessionBusField(31.59, 39.31, "Medium", "Moderate"),
    "Afternoon Session": SessionBusField(32.78, 42.31, "High", "Heavy"),
}

# Legacy session rows (crowding labels only); speeds come from TRAFFIC_FIELD_SPEED_BAND_KMH.
SESSION_BUS_FIELD_SIM: dict[str, SessionBusField] = {
    "Morning Session": SessionBusField(*TRAFFIC_FIELD_SPEED_BAND_KMH["Light"], "Low", "Light"),
    "Lunch": SessionBusField(*TRAFFIC_FIELD_SPEED_BAND_KMH["Moderate"], "Medium", "Moderate"),
    "Afternoon Session": SessionBusField(*TRAFFIC_FIELD_SPEED_BAND_KMH["Heavy"], "High", "Heavy"),
}

SESSION_BUS_FIELD_DEC = SESSION_BUS_FIELD_SIM  # deprecated alias

# Jan 18 on-board: travel time to destination, dwell, total signal wait at stops.
SESSION_ONBOARD_JAN18: dict[str, dict[str, float]] = {
    "Morning Session": {
        "travel_s": 660.0,
        "dwell_s": 44.0,
        "signal_s": 180.0,
        "signal_extra_s": 0.0,
    },
    "Lunch": {
        "travel_s": 900.0,
        "dwell_s": 19.0,
        "signal_s": 271.0,
        "signal_extra_s": 91.0,
    },
    "Afternoon Session": {
        "travel_s": 1140.0,
        "dwell_s": 73.0,
        "signal_s": 289.0,
        "signal_extra_s": 109.0,
    },
}

# Crowding → dwell at formal stops (field + thesis rules).
# Low: bus waits longer (~43 s) to collect passengers.
# High: longer if busy boarding/alighting; shorter if quick turnover.
CROWDING_FORMAL_LOW_DWELL_S = 43.0
CROWDING_DWELL_MULT: dict[str, float] = {
    "Low": 1.12,
    "Medium": 1.0,
    "High": 1.0,
}

# On-board mean dwell at each bus stop during corridor trip (Dec On-Board sheets).
# Stationary obs medians are ~35-44s at origin; mid-route formal stops use these (~1-1.5 min).
SESSION_ONBOARD_FORMAL_DWELL_S: dict[str, float] = {
    "Morning Session": 83.3,
    "Lunch": 89.0,
    "Afternoon Session": 62.2,
}

# Share of stationary obs with 1-2 min dwell at the observation stop (field book).
STATIONARY_DWELL_60_120S_PCT: dict[str, float] = {
    "Morning Session": 15.3,
    "Lunch": 19.2,
    "Afternoon Session": 19.8,
}


def normalize_traffic_label(raw: str) -> str:
    """Canonical traffic: Light | Moderate | Heavy only."""
    key = str(raw or "").strip().lower()
    return TRAFFIC_LABEL_ALIASES.get(key, "Light")


def normalize_crowding_label(raw: str) -> str:
    """Canonical crowding: Low | Medium | High only."""
    s = str(raw or "").strip()
    if not s:
        return "Medium"
    low = s.lower()
    if low in ("low", "light"):
        return "Low"
    if low in ("medium", "moderate"):
        return "Medium"
    if low in ("high", "heavy"):
        return "High"
    return "Medium"


def crowding_dwell_multiplier(
    field_crowding: str | None,
    *,
    boarding: float | None = None,
    alighting: float | None = None,
) -> float:
    """Dwell scale from crowding and passenger activity at the stop."""
    label = normalize_crowding_label(str(field_crowding or "Medium"))
    if label == "Low":
        return CROWDING_DWELL_MULT["Low"]
    if label == "High":
        activity = float(boarding or 0) + float(alighting or 0)
        if activity >= 7:
            return 1.35
        if activity <= 2:
            return 0.88
        return 1.12
    return CROWDING_DWELL_MULT["Medium"]


_LIGHT_MID_KMH = sum(TRAFFIC_FIELD_SPEED_BAND_KMH["Light"]) / 2.0

TRAFFIC_CRUISE_MULT: dict[str, float] = {
    "Light": 1.0,
    "Moderate": round(sum(TRAFFIC_FIELD_SPEED_BAND_KMH["Moderate"]) / 2.0 / _LIGHT_MID_KMH, 3),
    "Heavy": round(sum(TRAFFIC_FIELD_SPEED_BAND_KMH["Heavy"]) / 2.0 / _LIGHT_MID_KMH, 3),
}


def traffic_speed_band_kmh(field_traffic: str | None) -> tuple[float, float]:
    """Observed on-board bus speed range (km/h) for this traffic tier."""
    label = normalize_traffic_label(str(field_traffic or "Light"))
    return TRAFFIC_FIELD_SPEED_BAND_KMH.get(label, TRAFFIC_FIELD_SPEED_BAND_KMH["Light"])


def traffic_speed_band_label(field_traffic: str | None) -> str:
    lo, hi = traffic_speed_band_kmh(field_traffic)
    return f"{lo:.2f}-{hi:.2f}"


def traffic_speed_mid_kmh(field_traffic: str | None) -> float:
    lo, hi = traffic_speed_band_kmh(field_traffic)
    return round((lo + hi) / 2.0, 2)


def traffic_speed_min_kmh(field_traffic: str | None) -> float:
    return traffic_speed_band_kmh(field_traffic)[0]


def traffic_cruise_multiplier(field_traffic: str | None) -> float:
    """Speed scale vs Light traffic (Heavy → slower cruise caps)."""
    label = normalize_traffic_label(str(field_traffic or "Light"))
    return TRAFFIC_CRUISE_MULT.get(label, TRAFFIC_CRUISE_MULT["Light"])


def bus_cruise_cap_kmh(field_traffic: str | None = "Light") -> float:
    """Field bus cruise ceiling for this traffic tier (on-board speed band maximum)."""
    lo, hi = traffic_speed_band_kmh(field_traffic)
    return min(BUS_MAX_SPEED_KMH, round(hi, 2))


def align_moving_speed_kmh(speed_kmh: float | None, field_traffic: str | None) -> float:
    """
    Reported / UXsim moving speed aligned to field on-board band.

    Uses measured speed when inside the band; otherwise band midpoint (field buses
    do not cruise below the observed minimum while moving).
    """
    lo, hi = traffic_speed_band_kmh(field_traffic)
    mid = (lo + hi) / 2.0
    if speed_kmh is None or float(speed_kmh) <= 0:
        return round(mid, 2)
    v = float(speed_kmh)
    if v < lo:
        return round(lo, 2)
    if v > hi:
        return round(hi, 2)
    return round(v, 2)


def general_cruise_cap_kmh(field_traffic: str | None = "Light") -> float:
    """Absolute general-traffic ceiling (never above 60 km/h)."""
    mult = traffic_cruise_multiplier(field_traffic)
    return min(GENERAL_VEHICLE_SPEED_KMH, round(GENERAL_VEHICLE_SPEED_KMH * mult, 2))


def clamp_bus_speed_kmh(speed_kmh: float) -> float:
    """Hard ceiling: buses never exceed 50 km/h in results."""
    return min(float(speed_kmh), BUS_MAX_SPEED_KMH)


def clamp_bus_speed_for_traffic(speed_kmh: float, field_traffic: str | None) -> float:
    """Cap bus moving speed at the field band maximum for this traffic tier."""
    return min(clamp_bus_speed_kmh(speed_kmh), bus_cruise_cap_kmh(field_traffic))


# Scales hourly demand injection (more vehicles when Light, fewer effective free-flow slots when Heavy).
TRAFFIC_FLOW_MULT: dict[str, float] = {
    "Light": 1.0,
    "Moderate": 0.90,
    "Heavy": 0.72,
}

# Extra queue delay at signals from vehicles lagging behind (seconds).
TRAFFIC_SIGNAL_QUEUE_S: dict[str, float] = {
    "Light": 20.0,
    "Moderate": 45.0,
    "Heavy": 75.0,
}

# UXsim LWR jam density (veh/m/lane): lower = easier congestion / lower capacity.
TRAFFIC_JAM_DENSITY: dict[str, float] = {
    "Light": 0.16,
    "Moderate": 0.24,
    "Heavy": 0.36,
}


def general_traffic_speed_limits_kmh(field_traffic: str) -> dict[str, float]:
    """
    Documented speed tiers for mixed traffic (km/h), matching limitations text.
    Realized UXsim speeds can be lower under congestion.
    """
    label = normalize_traffic_label(str(field_traffic or "Light"))
    mult = traffic_cruise_multiplier(label)
    mid = GENERAL_VEHICLE_SPEED_KMH * mult
    heavy = label == "Heavy"
    close = CRUISE_SPEED_CLOSE_HEAVY_KMH if heavy else CRUISE_SPEED_CLOSE_KMH
    return {
        "mid_block_kmh": round(min(mid, GENERAL_VEHICLE_SPEED_KMH), 1),
        "near_stop_signal_kmh": round(min(CRUISE_SPEED_NEAR_KMH, mid), 1),
        "close_spacing_kmh": round(min(close, mid), 1),
    }


def bus_traffic_speed_limits_kmh(field_traffic: str) -> dict[str, float]:
    """Bus link speed tiers for a traffic condition (field on-board band)."""
    lo, cap = traffic_speed_band_kmh(field_traffic)
    mid = traffic_speed_mid_kmh(field_traffic)
    heavy = normalize_traffic_label(str(field_traffic or "Light")) == "Heavy"
    close = CRUISE_SPEED_CLOSE_HEAVY_KMH if heavy else CRUISE_SPEED_CLOSE_KMH
    return {
        "mid_block_kmh": round(min(cap, mid * 1.05), 1),
        "near_stop_signal_kmh": round(min(max(lo, CRUISE_SPEED_NEAR_KMH * 0.85), cap), 1),
        "close_spacing_kmh": round(min(max(lo, close), cap), 1),
    }


# Stationary sheet uses Low/Moderate/Heavy; on-board sheets use Light/Moderate/Heavy.
TRAFFIC_LABEL_ALIASES: dict[str, str] = {
    "low": "Light",
    "light": "Light",
    "moderate": "Moderate",
    "medium": "Moderate",
    "heavy": "Heavy",
    "high": "Heavy",
}

CROWDING_SEVERITY: dict[str, float] = {
    "Low": 1.0,
    "Medium": 2.0,
    "High": 3.0,
}
TRAFFIC_SEVERITY: dict[str, float] = {
    "Light": 1.0,
    "Moderate": 2.0,
    "Heavy": 3.0,
}

# june2026 = June 2026 San Agustin on-board rows (default). jan18 = optional Sunday targets.
FIELD_ONBOARD_PROFILE: str = "june2026"

# Terminal dwell medians from stationary sheets (observation at origin stop).
SESSION_DWELL: dict[str, dict[str, float]] = {
    "Morning Session": {"robinsons": 44.0, "waltermart": 34.0},
    "Lunch": {"robinsons": 48.0, "waltermart": 30.0},
    "Afternoon Session": {"robinsons": 44.0, "waltermart": 38.0},
}


def session_formal_mid_route_dwell_s(session: str, onboard_stop_dwell_s: float | None = None) -> float:
    """Dwell (s) at formal mid-route stops — from on-board data (~1-1.5 min), not origin terminal."""
    if onboard_stop_dwell_s and onboard_stop_dwell_s > 0:
        return float(onboard_stop_dwell_s)
    return SESSION_ONBOARD_FORMAL_DWELL_S.get(session, DEFAULT_DWELL_S)

SESSIONS: tuple[str, ...] = ("Morning Session", "Lunch", "Afternoon Session")
ORIGINS: tuple[str, ...] = ("robinsons_location", "waltermart_location")

MIN_FULL_MATRIX_RUNS = len(SESSIONS) * 4 * (2**SIGNAL_ENCOUNTERS_PER_ROUND_TRIP)

# UXsim adddemand: use flow= (veh/s). volume= is total vehicles only (values < 1 inject nothing).
# Peak rates scaled from June 2026 stationary sheets (San Agustin + background mix).
PEAK_DEMAND_CAR = 0.105
PEAK_DEMAND_JEEPNEY = 0.045
PEAK_DEMAND_BUS = 0.013


def _normalize_field_traffic_label(raw: str) -> str:
    return normalize_traffic_label(raw)


def _normalize_field_crowding_label(raw: str) -> str:
    return normalize_crowding_label(raw)


def signal_red_phase_wait_s(session: str, signal_key: str) -> float:
    """Seconds waiting when bus arrives on red (cross-street / side phase)."""
    ph = signal_phase_timing(session, signal_key)
    return float(ph.side_green_s + ph.yellow_s)


def traffic_signal_queue_extra_s(field_traffic: str | None) -> float:
    """Extra signal delay from queued vehicles (Heavy → longer backlog)."""
    label = normalize_traffic_label(str(field_traffic or "Light"))
    return TRAFFIC_SIGNAL_QUEUE_S.get(label, TRAFFIC_SIGNAL_QUEUE_S["Light"])


def corridor_travel_floor_s(
    session: str,
    signal_pattern: str,
    field_traffic: str | None,
    *,
    trip_direction: str = "rb_to_wm",
    n_mid_stops: int = 3,
) -> float:
    """
    Minimum plausible corridor time (s). R-first patterns include full side-red
    phase (~145 s AM/Lunch, ~175 s PM at Pala-Pala) — never < ~5 min total.
    """
    from signal_scenarios import _encounter_signal_key

    pattern = str(signal_pattern or "G-G").strip().upper()
    parts = pattern.split("-")
    first_red = len(parts) > 0 and parts[0] == "R"
    traffic = normalize_traffic_label(str(field_traffic or "Light"))
    direction = trip_direction if trip_direction in ("rb_to_wm", "wm_to_rb") else "rb_to_wm"

    if first_red:
        key = _encounter_signal_key(0, direction)  # type: ignore[arg-type]
        signal_wait = signal_red_phase_wait_s(session, key)
    else:
        signal_wait = 55.0

    queue = traffic_signal_queue_extra_s(traffic)
    dwell = max(1, n_mid_stops) * 42.0
    drive = 160.0
    return signal_wait + queue + dwell + drive


def field_traffic_crowding_index(session: str, rows: list[dict[str, str]]) -> float:
    """
    Combined severity index (1=low … 3=high) from stationary field rows.
    Traffic 55% + crowding 45% — matches mixed Low/Medium/High sheets.
    """
    sub = [r for r in rows if r.get("session") == session]
    if not sub:
        return 2.0
    total = 0.0
    for r in sub:
        t = _normalize_field_traffic_label(r.get("traffic_condition", ""))
        c = _normalize_field_crowding_label(r.get("crowding_level", ""))
        total += 0.55 * TRAFFIC_SEVERITY.get(t, 2.0) + 0.45 * CROWDING_SEVERITY.get(c, 2.0)
    return total / len(sub)


def load_field_stationary_rows(path: Path | None = None) -> list[dict[str, str]]:
    p = path or FIELD_STATIONARY_CSV
    if not p.is_file():
        return []
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def field_session_traffic_mix(session: str, rows: list[dict[str, str]] | None = None) -> dict[str, int]:
    """Count traffic_condition labels per session (for logging / thesis)."""
    rows = rows if rows is not None else load_field_stationary_rows()
    from collections import Counter

    c: Counter[str] = Counter()
    for r in rows:
        if r.get("session") == session:
            c[_normalize_field_traffic_label(r.get("traffic_condition", ""))] += 1
    return dict(c)


def calibrate_session_demand_from_field(
    rows: list[dict[str, str]] | None = None,
    *,
    peak_car: float = PEAK_DEMAND_CAR,
    peak_jeepney: float = PEAK_DEMAND_JEEPNEY,
    peak_bus: float = PEAK_DEMAND_BUS,
) -> dict[str, dict[str, float]]:
    """
    Scale car/jeepney/bus flows by field traffic+crowding index per session.
    Afternoon = peak (most Heavy/High in Excel); Morning = low–medium; Lunch = medium mix.
    """
    rows = rows if rows is not None else load_field_stationary_rows()
    indices = {s: field_traffic_crowding_index(s, rows) for s in SESSIONS}
    peak_idx = max(indices.values()) if indices else 2.0
    out: dict[str, dict[str, float]] = {}
    for s in SESSIONS:
        ratio = indices[s] / peak_idx if peak_idx > 0 else 1.0
        out[s] = {
            "bus": round(peak_bus * ratio, 4),
            "car": round(peak_car * ratio, 4),
            "jeepney": round(peak_jeepney * ratio, 4),
        }
    return out


def session_demand_field_indices(rows: list[dict[str, str]] | None = None) -> dict[str, float]:
    rows = rows if rows is not None else load_field_stationary_rows()
    return {s: field_traffic_crowding_index(s, rows) for s in SESSIONS}


# One-hour mixed-traffic injection window (all classes).
MIXED_CORRIDOR_DEMAND_WINDOW_S = 3600.0
# Extra sim time after the hour so queued vehicles can finish (Vissim-style hour run).
SESSION_HOUR_CLEARANCE_S = 2400.0

# Clock anchor (seconds) for mapping field observation time into a 1-hour session window.
SESSION_CLOCK_START_S: dict[str, int] = {
    "Morning Session": 5 * 3600,
    "Lunch": 11 * 3600,
    "Afternoon Session": 15 * 3600,
}

# Field bus volumes per 1-hour window by direction (Dec 2025 corridor counts).
# Used for session-hour mixed traffic and as the demand anchor for other vehicle classes.
SESSION_BUS_PER_HOUR_BY_DIRECTION: dict[str, dict[Literal["rb_to_wm", "wm_to_rb"], int]] = {
    "Morning Session": {"rb_to_wm": 138, "wm_to_rb": 57},
    "Lunch": {"rb_to_wm": 44, "wm_to_rb": 83},
    "Afternoon Session": {"rb_to_wm": 106, "wm_to_rb": 101},
}

# Totals per session (sum of both directions); not the 513 stationary observation rows.
SESSION_BUS_COUNT_PER_HOUR: dict[str, int] = {
    s: SESSION_BUS_PER_HOUR_BY_DIRECTION[s]["rb_to_wm"] + SESSION_BUS_PER_HOUR_BY_DIRECTION[s]["wm_to_rb"]
    for s in SESSION_BUS_PER_HOUR_BY_DIRECTION
}


def session_bus_count_per_hour(
    session: str,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"],
) -> int:
    """Buses on the corridor in one hour for this session and travel direction."""
    return int(SESSION_BUS_PER_HOUR_BY_DIRECTION[session][trip_direction])

# Typical Philippine arterial traffic composition (shares of hourly volume).
PH_ARTERIAL_VEHICLE_SHARE: dict[str, float] = {
    "bus": 0.08,
    "jeepney": 0.20,
    "car": 0.45,
    "motorcycle": 0.22,
    "truck": 0.025,
    "van": 0.025,
}


def hourly_vehicle_counts_from_bus_anchor(
    session: str,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"] | None = None,
) -> dict[str, int]:
    """
    Derive 1-hour volumes from field bus count and PH_ARTERIAL_VEHICLE_SHARE.

    When trip_direction is set, anchor on that direction's hourly bus count only
    (e.g. Morning rb_to_wm: 138 buses -> scale jeepneys/cars/motorcycles for that run).
    """
    if trip_direction:
        n_bus = session_bus_count_per_hour(session, trip_direction)
    else:
        n_bus = SESSION_BUS_COUNT_PER_HOUR[session]
    total = n_bus / PH_ARTERIAL_VEHICLE_SHARE["bus"]
    return {
        "bus": n_bus,
        "jeepney": round(total * PH_ARTERIAL_VEHICLE_SHARE["jeepney"]),
        "car": round(total * PH_ARTERIAL_VEHICLE_SHARE["car"]),
        "motorcycle": round(total * PH_ARTERIAL_VEHICLE_SHARE["motorcycle"]),
        "truck": round(total * PH_ARTERIAL_VEHICLE_SHARE["truck"]),
        "van": round(total * PH_ARTERIAL_VEHICLE_SHARE["van"]),
    }


def session_demand_flow_rates(
    session: str,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"] | None = None,
) -> dict[str, float]:
    """UXsim flow rates (veh/s) per class for MIXED_CORRIDOR_DEMAND_WINDOW_S."""
    w = MIXED_CORRIDOR_DEMAND_WINDOW_S
    counts = hourly_vehicle_counts_from_bus_anchor(session, trip_direction)
    return {k: round(v / w, 6) if w > 0 else 0.0 for k, v in counts.items()}


def build_session_demand_from_ph_composition() -> dict[str, dict[str, float]]:
    """Session-total flows (both directions combined); prefer session_demand_flow_rates(..., direction)."""
    return {s: session_demand_flow_rates(s) for s in SESSIONS}


SESSION_DEMAND: dict[str, dict[str, float]] = build_session_demand_from_ph_composition()

# Map UXsim VehicleClass.key -> SESSION_DEMAND key.
MIXED_FLOW_KEY: dict[str, str] = {
    "bus": "bus",
    "private_car": "car",
    "jeepney": "jeepney",
    "truck": "truck",
    "motorcycle": "motorcycle",
    "van": "van",
}


def mixed_flow_rate(
    session: str,
    vehicle_key: str,
    *,
    traffic_condition: str | None = None,
    trip_direction: Literal["rb_to_wm", "wm_to_rb"] | None = None,
) -> float:
    """Vehicles per second for adddemand(flow=...), scaled by field traffic when given."""
    sd_key = MIXED_FLOW_KEY.get(vehicle_key, vehicle_key)
    flows = (
        session_demand_flow_rates(session, trip_direction)
        if trip_direction
        else SESSION_DEMAND[session]
    )
    base = float(flows[sd_key])
    if not traffic_condition:
        return base
    label = str(traffic_condition).strip()
    mult = TRAFFIC_FLOW_MULT.get(label, TRAFFIC_FLOW_MULT.get("Light", 1.0))
    return base * mult


def traffic_jam_density(traffic_condition: str | None) -> float:
    label = normalize_traffic_label(str(traffic_condition or "Light"))
    return float(TRAFFIC_JAM_DENSITY.get(label, TRAFFIC_JAM_DENSITY["Light"]))


def mixed_corridor_demand_window_s(raw_span_s: float) -> float:
    if MIXED_CORRIDOR_DEMAND_WINDOW_S <= 0:
        return raw_span_s
    return min(raw_span_s, MIXED_CORRIDOR_DEMAND_WINDOW_S)


def estimated_vehicles_in_window(flow_per_s: float, window_s: float) -> float:
    """Approximate vehicles injected over demand window (one OD)."""
    return flow_per_s * max(window_s, 0.0)

HEADWAYS: dict[str, int | None] = {
    "headway_observed": None,
    "headway_10min": 600,
    "headway_15min": 900,
    "headway_20min": 1200,
}

STOP_CONFIGS: dict[str, dict[str, bool | float]] = {
    "transit_all_stops": {"use_formal": True, "use_informal": True, "dwell_scale": 1.00},
    "transit_all_informal": {"use_formal": False, "use_informal": True, "dwell_scale": 1.00},
    "transit_mixed": {"use_formal": True, "use_informal": True, "dwell_scale": 1.00},
    "optimized_formal_only": {"use_formal": True, "use_informal": False, "dwell_scale": 1.00},
    "optimized_short_dwell": {"use_formal": True, "use_informal": False, "dwell_scale": 0.55},
    "optimized_transit": {"use_formal": True, "use_informal": True, "dwell_scale": 0.55},
    "optimized_two_formal": {"use_formal": True, "use_informal": False, "dwell_scale": 0.75},
    # Legacy keys (thesis CSVs before transit rename)
    "baseline_all_stops": {"use_formal": True, "use_informal": True, "dwell_scale": 1.00},
    "baseline_all_informal": {"use_formal": False, "use_informal": True, "dwell_scale": 1.00},
    "baseline_mixed": {"use_formal": True, "use_informal": True, "dwell_scale": 1.00},
    "optimized_baseline": {"use_formal": True, "use_informal": True, "dwell_scale": 0.55},
}

TOTAL_LENGTH_M = CORRIDOR_LENGTH_M
FREE_FLOW_SPEED = FREE_FLOW_MPS
NUM_LANES = LANES_MAIN
SIGNAL_POS = CORRIDOR_SIGNALS[0].chainage_m
TMAX = 3600


def _stop_dict_entry(stop: CorridorStop) -> dict[str, float | str]:
    return {"pos": stop.chainage_m, "kind": stop.kind, "label": stop.label}


def stops_by_kind(
    stops: tuple[CorridorStop, ...],
    *,
    direction: Literal["rb_to_wm", "wm_to_rb"],
    kinds: tuple[StopKind, ...],
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in stops:
        if s.direction not in (direction, "both"):
            continue
        if s.kind not in kinds or s.kind == "signal":
            continue
        if s.key in ("robinsons", "waltermart"):
            continue
        out[s.key] = _stop_dict_entry(s)
    return out


def formal_stops_fwd() -> dict[str, dict]:
    return stops_by_kind(STOPS_RB_TO_WM, direction="rb_to_wm", kinds=("formal",))


def informal_stops_fwd() -> dict[str, dict]:
    return stops_by_kind(STOPS_RB_TO_WM, direction="rb_to_wm", kinds=("informal",))


def formal_stops_rev() -> dict[str, dict]:
    return stops_by_kind(STOPS_WM_TO_RB, direction="wm_to_rb", kinds=("formal",))


def informal_stops_rev() -> dict[str, dict]:
    return stops_by_kind(STOPS_WM_TO_RB, direction="wm_to_rb", kinds=("informal",))


def dwell_for_stop(session: str, stop_key: str, dwell_scale: float = 1.0) -> float:
    """Session-based dwell (seconds) aligned with corridor_network.py logic."""
    sess = SESSION_DWELL[session]
    rb, wm = sess["robinsons"], sess["waltermart"]
    stop = next((s for s in STOPS_RB_TO_WM + STOPS_WM_TO_RB if s.key == stop_key), None)
    if stop is None:
        return DEFAULT_DWELL_S
    kind = stop.kind
    if kind == "terminal_formal":
        base = (rb + wm) / 2.0
    elif kind == "formal":
        base = session_formal_mid_route_dwell_s(session)
    elif kind == "informal":
        base = max(rb * 1.12, 45.0)
        if stop_key == "rcbc":
            base = max(wm * 1.05, 35.0)
        if stop_key in ("korean_grocery", "seven_eleven"):
            base = max(rb * 1.12, 45.0)
    else:
        base = DEFAULT_DWELL_S
    if dwell_scale < 1.0:
        return max(8.0, base * dwell_scale)
    return base


def active_stops_for_config(
    session: str,
    stop_cfg: dict,
) -> tuple[dict[str, dict], dict[str, dict]]:
    scale = float(stop_cfg.get("dwell_scale", 1.0))
    use_formal = bool(stop_cfg.get("use_formal", True))
    use_informal = bool(stop_cfg.get("use_informal", True))
    fwd: dict[str, dict] = {}
    rev: dict[str, dict] = {}
    if use_informal:
        for k, v in informal_stops_fwd().items():
            fwd[k] = {"pos": v["pos"], "dwell": dwell_for_stop(session, k, scale)}
        for k, v in informal_stops_rev().items():
            rev[k] = {"pos": v["pos"], "dwell": dwell_for_stop(session, k, scale)}
    if use_formal:
        for k, v in formal_stops_fwd().items():
            fwd[k] = {"pos": v["pos"], "dwell": dwell_for_stop(session, k, scale)}
        for k, v in formal_stops_rev().items():
            rev[k] = {"pos": v["pos"], "dwell": dwell_for_stop(session, k, scale)}
    return fwd, rev


FORMAL_STOPS_FWD = formal_stops_fwd()
INFORMAL_STOPS_FWD = informal_stops_fwd()
FORMAL_STOPS_REV = formal_stops_rev()
INFORMAL_STOPS_REV = informal_stops_rev()


def print_corridor_legend() -> None:
    print(
        "Main-road lanes (field): "
        f"RB->WM 3 lanes 0–{RB_TO_WM_THREE_LANE_END_M:.0f} m then 2 lanes; "
        f"WM->RB 2 lanes {WM_TO_RB_THREE_LANE_END_M:.0f}–{CORRIDOR_LENGTH_M:.0f} m "
        f"({WM_TO_RB_TWO_LANE_FROM_WM_M:.0f} m from Waltermart) then 3 lanes to Robinsons."
    )
    print(f"  Pala-Pala intersection line GPS {GPS_PALA_INTERSECTION_LINE}")
    print(f"  WM->RB widen GPS {GPS_WM_RB_LANE_EXPAND}")
    print("Signals (field main/side green per session):")
    for sig in CORRIDOR_SIGNALS:
        ph = signal_phase_timing("Afternoon Session", sig.key)
        print(
            f"  {sig.chainage_m:4.0f}m  {sig.label}  "
            f"GPS {sig.gps}  (main {ph.main_green_s:.0f}s / side {ph.side_green_s:.0f}s)"
        )
    print("Forward (Robinsons -> Waltermart) stops:")
    for s in STOPS_RB_TO_WM:
        if s.kind != "signal":
            print(f"  {s.chainage_m:4.0f}m  [{s.kind:16s}]  {s.label}")
    print("Reverse (Waltermart -> Robinsons) stops:")
    for s in STOPS_WM_TO_RB:
        if s.kind != "signal":
            print(f"  {s.chainage_m:4.0f}m  [{s.kind:16s}]  {s.label}")


@dataclass(frozen=True)
class VehicleClass:
    key: str
    label: str
    volume_multiplier: float
    uses_bus_stops: bool
    max_speed_kmh: float | None = None  # None = use session/field bus cap on stop legs


VEHICLE_CLASSES: tuple[VehicleClass, ...] = (
    VehicleClass("bus", "Bus", 1.0, True, None),
    VehicleClass("private_car", "Private car", 1.2, False, GENERAL_VEHICLE_SPEED_KMH),
    VehicleClass("jeepney", "Jeepney", 1.0, False, GENERAL_VEHICLE_SPEED_KMH),
    VehicleClass("truck", "Truck", 0.5, False, GENERAL_VEHICLE_SPEED_KMH),
    VehicleClass("motorcycle", "Motorcycle", 0.8, False, GENERAL_VEHICLE_SPEED_KMH),
    VehicleClass("van", "Van", 0.5, False, GENERAL_VEHICLE_SPEED_KMH),
)

# Cap bus legs when not using mixed traffic (avoid 100+ buses/leg from stationary counts).
BUS_VOLUME_CAP_PER_LEG = 12

# Field replication: one observed bus, one corridor trip (matches on-board sheets).
# Low volume on chained legs ≈ one bus corridor trip (vol 1 does not complete in UXsim).
FIELD_TRIP_VOLUME = 5
FIELD_TRIP_DEMAND_S = 3600.0
FIELD_SIM_TMAX_S = 7200.0

POLICY_TRANSIT = "transit_all_stops"
POLICY_OPTIMIZED_TRANSIT = "optimized_transit"
POLICY_OPTIMIZED = "optimized_formal_only"
# Legacy aliases
POLICY_BASELINE = POLICY_TRANSIT
POLICY_OPTIMIZED_BASELINE = POLICY_OPTIMIZED_TRANSIT
TRANSIT_POLICY_TAGS: tuple[str, ...] = ("transit_all_stops", "baseline_all_stops")
OPTIMIZED_TRANSIT_POLICY_TAGS: tuple[str, ...] = ("optimized_transit", "optimized_baseline")
OPTIMIZED_SHORT_DWELL_SCALE = 0.55
