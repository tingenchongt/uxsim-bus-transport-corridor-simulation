"""
Field corridor: Robinsons Pala-Pala — Waltermart Dasmariñas (Emilio Aguinaldo Hwy).

Chainage and GPS from field notes (May 2026). Formal vs informal classification follows
the survey legend: formal = Robinsons, Waltermart, Vista Mall; informal = 7-Eleven,
Villa Verde, RCBC Bank (informal curbside loading).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# --- Highway physics (shared) ---
FREE_FLOW_MPS = 16.67  # ~60 km/h
LANES_MAIN = 2
STOP_LINK_LENGTH_M = 25.0
STOP_LANES = 1
DEFAULT_DWELL_S = 40.0

# Total corridor length (terminal to terminal along mainline chainage).
CORRIDOR_LENGTH_M = 3049.0

# Main signal at chainage 2495 m (forward direction); 45 s + 45 s.
SIGNAL_CHAINAGE_M = 2495.0
SIGNAL_GREEN_EB_S = 45.0
SIGNAL_GREEN_WB_S = 45.0
SIGNAL_CYCLE_S = SIGNAL_GREEN_EB_S + SIGNAL_GREEN_WB_S

# GPS reference (documentation / maps; not used in 1D UXsim layout).
GPS_STOPS = {
    "robinsons": (14.3002, 120.9529),
    "informal_robinsons": (14.3002, 120.9529),
    "seven_eleven": (14.3019, 120.9523),
    "villa_verde": (14.3149, 120.9450),
    "vista_mall": (14.31687, 120.94415),
    "signal": None,
    "rcbc": (14.3236, 120.9415),
    "waltermart": (14.3250, 120.9410),
}

StopKind = Literal["terminal_formal", "formal", "informal", "signal"]


@dataclass(frozen=True)
class CorridorStop:
    chainage_m: float
    key: str
    label: str
    kind: StopKind
    direction: Literal["rb_to_wm", "wm_to_rb", "both"]


# Forward (Robinsons → Waltermart): chainage from Robinsons terminal origin.
STOPS_RB_TO_WM: tuple[CorridorStop, ...] = (
    CorridorStop(0, "robinsons", "Robinsons terminal", "terminal_formal", "both"),
    CorridorStop(50, "informal_robinsons", "In front of Robinsons [pre-signal]", "informal", "rb_to_wm"),
    CorridorStop(200, "seven_eleven", "7-Eleven Pala Pala", "informal", "rb_to_wm"),
    CorridorStop(1845, "villa_verde", "Villa Verde", "informal", "rb_to_wm"),
    CorridorStop(2083, "vista_mall", "Vista Mall", "formal", "rb_to_wm"),
    CorridorStop(SIGNAL_CHAINAGE_M, "signal", "Signal intersection", "signal", "both"),
    CorridorStop(2884, "rcbc", "RCBC Bank [post-signal]", "informal", "rb_to_wm"),
    CorridorStop(CORRIDOR_LENGTH_M, "waltermart", "Waltermart terminal", "terminal_formal", "both"),
)

# Reverse (Waltermart → Robinsons): chainage from Waltermart terminal origin.
STOPS_WM_TO_RB: tuple[CorridorStop, ...] = (
    CorridorStop(0, "waltermart", "Waltermart terminal", "terminal_formal", "both"),
    CorridorStop(165, "rcbc", "RCBC Bank", "informal", "wm_to_rb"),
    CorridorStop(966, "vista_mall", "Vista Mall", "formal", "wm_to_rb"),
    CorridorStop(1203, "villa_verde", "Villa Verde", "informal", "wm_to_rb"),
    CorridorStop(CORRIDOR_LENGTH_M, "robinsons", "Robinsons terminal", "terminal_formal", "both"),
)

# First signal encounter = RB→WM at main node (EB / group 0).
# Second encounter = WM→RB return through same node (WB / group 1).
# Four labeled scenarios: initial EB phase × shift of WM→RB demand to target WB phase at t≈0.
@dataclass(frozen=True)
class SignalEncounterScenario:
    scenario_id: str
    first_signal_green_eb: bool
    second_signal_green_wb: bool
    signal_offset_s: float
    wm_to_rb_demand_shift_s: float


def _signal_offset_for_eb_initial(green: bool) -> float:
    """UXsim signal_offset: 0 => EB (group 0) starts in green at t=0."""
    return 0.0 if green else SIGNAL_GREEN_EB_S


SIGNAL_ENCOUNTER_SCENARIOS: tuple[SignalEncounterScenario, ...] = (
    SignalEncounterScenario(
        "sig1_G_sig2_G", True, True, _signal_offset_for_eb_initial(True), 0.0
    ),
    SignalEncounterScenario(
        "sig1_G_sig2_R", True, False, _signal_offset_for_eb_initial(True), SIGNAL_GREEN_WB_S
    ),
    SignalEncounterScenario(
        "sig1_R_sig2_G", False, True, _signal_offset_for_eb_initial(False), 0.0
    ),
    SignalEncounterScenario(
        "sig1_R_sig2_R", False, False, _signal_offset_for_eb_initial(False), SIGNAL_GREEN_WB_S
    ),
)

# Mixed traffic: relative demand multipliers vs bus sheet row-count volume (tune as needed).
@dataclass(frozen=True)
class VehicleClass:
    key: str
    label: str
    volume_multiplier: float
    uses_bus_stops: bool


VEHICLE_CLASSES: tuple[VehicleClass, ...] = (
    VehicleClass("bus", "Bus", 1.0, True),
    VehicleClass("private_car", "Private car", 2.5, False),
    VehicleClass("jeepney", "Jeepney", 1.8, False),
    VehicleClass("truck", "Truck", 0.6, False),
    VehicleClass("motorcycle", "Motorcycle", 1.2, False),
    VehicleClass("van", "Van", 0.9, False),
)

POLICY_BASELINE = "baseline_all_stops"
POLICY_OPTIMIZED = "optimized_formal_only"

OPTIMIZED_SHORT_DWELL_SCALE = 0.55
