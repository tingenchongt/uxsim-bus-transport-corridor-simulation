"""
Stop-policy and formal-stop relocation scenarios for corridor UXsim simulations.

Each unique combination of bus × stop encounter policy × signal pattern is one
**scenario** (not a generic "run"). Policies A–E use surveyed stop positions (E = transit stops with optimized dwell).
Partial informal scenarios I_<mask> serve formal stops plus a subset of informal
curbs (e.g. Korean grocery yes, 7-Eleven no). Relocation scenarios R_<5-bit>
move selected formal stops +5 m on a formal-only layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from corridor_config import (
    ALL_FORMAL_MID_STOP_KEYS,
    ALL_INFORMAL_STOP_KEYS,
    CORRIDOR_LENGTH_M,
    FORMAL_MID_STOP_KEYS,
    FORMAL_MID_STOP_LABELS,
    INFORMAL_STOP_KEYS,
    INFORMAL_STOP_LABELS,
    OPTIMIZED_SHORT_DWELL_SCALE,
    POLICY_TRANSIT,
    POLICY_OPTIMIZED,
    POLICY_OPTIMIZED_TRANSIT,
    SERVICE_MODES,
    SERVICE_MODE_CODES,
    SERVICE_MODE_LABELS,
    STOPS_RB_TO_WM,
    STOPS_WM_TO_RB,
    chainage_from_robinsons,
    stop_encounter_active,
)

# Formal stops that may be shifted (+5 m toward Waltermart on the Robinsons chainage).
RELOCATABLE_STOP_KEYS: tuple[str, ...] = (
    "robinsons",
    "rkp_trading",
    "villa_verde",
    "vista_mall",
    "waltermart",
)

RELOC_SHIFT_M = 5.0

RELOCATABLE_LABELS: dict[str, str] = {
    "robinsons": "S1 Robinsons terminal",
    "rkp_trading": "S2 RKP Trading (rb→wm only)",
    "villa_verde": "S3 Villa Verde (rb→wm only)",
    "vista_mall": "S4 Vista Mall (rb→wm only)",
    "waltermart": "S5 Waltermart terminal",
}


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    group: str  # "policy" | "full_encounter" | "partial_informal" | "relocation"
    label: str
    policy_tag: str
    formal_keys: frozenset[str]
    informal_keys: frozenset[str]
    dwell_scale: float
    shift_keys: frozenset[str]
    service_mode: str = "full"
    adhoc_informal_count: int = 0

    @property
    def service_mode_code(self) -> str:
        from corridor_config import SERVICE_MODE_CODES
        return SERVICE_MODE_CODES.get(self.service_mode, "F")

    @property
    def use_formal(self) -> bool:
        return bool(self.formal_keys)

    @property
    def use_informal(self) -> bool:
        return bool(self.informal_keys)

    @property
    def include_informal(self) -> bool:
        return bool(self.informal_keys)

    @property
    def formal_mask(self) -> str:
        return "".join("1" if k in self.formal_keys else "0" for k in FORMAL_MID_STOP_KEYS)

    @property
    def informal_mask(self) -> str:
        return "".join("1" if k in self.informal_keys else "0" for k in INFORMAL_STOP_KEYS)

    @property
    def encounter_mask(self) -> str:
        return f"{self.formal_mask}{self.informal_mask}"

    @property
    def relocate_mask(self) -> str:
        return "".join(
            "1" if k in self.shift_keys else "0"
            for k in RELOCATABLE_STOP_KEYS
        )

    def includes_stop(self, stop) -> bool:
        return stop_encounter_active(
            stop,
            formal_keys=self.formal_keys,
            informal_keys=self.informal_keys,
        )


def _keys_from_mask(keys: tuple[str, ...], mask: int) -> frozenset[str]:
    return frozenset(keys[i] for i in range(len(keys)) if mask & (1 << i))


def _mask_label(keys: tuple[str, ...], active: frozenset[str]) -> str:
    return "".join("1" if k in active else "0" for k in keys)


def _encounter_spec(
    formal_mask: int,
    informal_mask: int,
    dwell_scale: float,
    *,
    scenario_id: str,
    group: str,
    label: str,
    policy_tag: str,
    shift_keys: frozenset[str] | None = None,
    service_mode: str = "full",
    adhoc_informal_count: int = 0,
) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id,
        group,
        label,
        policy_tag,
        _keys_from_mask(FORMAL_MID_STOP_KEYS, formal_mask),
        _keys_from_mask(INFORMAL_STOP_KEYS, informal_mask),
        dwell_scale,
        shift_keys or frozenset(),
        service_mode,
        adhoc_informal_count,
    )


def full_encounter_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    All 128 mid-route stop × dwell combinations (terminals always on).

    X_<RKP|Villa|Vista>_<grocery|7-11|RCBC>[_d55]
    """
    out: list[ScenarioSpec] = []
    for fmask in range(8):
        fl = _mask_label(FORMAL_MID_STOP_KEYS, _keys_from_mask(FORMAL_MID_STOP_KEYS, fmask))
        f_names = ", ".join(FORMAL_MID_STOP_LABELS[k] for k in FORMAL_MID_STOP_KEYS if k in _keys_from_mask(FORMAL_MID_STOP_KEYS, fmask)) or "no mid-formal"
        for imask in range(8):
            il = _mask_label(INFORMAL_STOP_KEYS, _keys_from_mask(INFORMAL_STOP_KEYS, imask))
            i_names = ", ".join(INFORMAL_STOP_LABELS[k] for k in INFORMAL_STOP_KEYS if k in _keys_from_mask(INFORMAL_STOP_KEYS, imask)) or "no informal"
            for dwell in (1.0, OPTIMIZED_SHORT_DWELL_SCALE):
                suffix = "_d55" if dwell < 1.0 else ""
                dwell_lbl = "100%" if dwell >= 1.0 else "55%"
                out.append(
                    _encounter_spec(
                        fmask,
                        imask,
                        dwell,
                        scenario_id=f"X_{fl}_{il}{suffix}",
                        group="full_encounter",
                        label=f"F={fl} I={il} dwell={dwell_lbl} ({f_names}; {i_names})",
                        policy_tag="full_encounter",
                    )
                )
    return tuple(out)


def transit_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    Transit corridor (formal + informal stops modeled): all 128 encounter × dwell combos.

    Bus may serve any subset of formal/informal mids — not only all-on (A_transit).
    Same masks as X_* / --full-encounter-only; grouped for --transit-all.
    """
    return tuple(
        ScenarioSpec(
            s.scenario_id,
            "transit_all",
            s.label,
            POLICY_TRANSIT,
            s.formal_keys,
            s.informal_keys,
            s.dwell_scale,
            frozenset(),
            s.service_mode,
            s.adhoc_informal_count,
        )
        for s in full_encounter_scenarios()
    )


def baseline_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """Legacy alias for transit_all_scenarios()."""
    return transit_all_scenarios()


def informal_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    Policy B family: no formal mids; all 8 informal encounter masks × 2 dwell = 16.

    X_000_<I3> — bus may stop at any subset of informal curbs (or none).
    """
    out: list[ScenarioSpec] = []
    for imask in range(8):
        il = _mask_label(INFORMAL_STOP_KEYS, _keys_from_mask(INFORMAL_STOP_KEYS, imask))
        i_names = ", ".join(
            INFORMAL_STOP_LABELS[k] for k in INFORMAL_STOP_KEYS if k in _keys_from_mask(INFORMAL_STOP_KEYS, imask)
        ) or "no informal"
        for dwell in (1.0, OPTIMIZED_SHORT_DWELL_SCALE):
            suffix = "_d55" if dwell < 1.0 else ""
            dwell_lbl = "100%" if dwell >= 1.0 else "55%"
            out.append(
                _encounter_spec(
                    0,
                    imask,
                    dwell,
                    scenario_id=f"X_000_{il}{suffix}",
                    group="informal_all",
                    label=f"Informal-only F=000 I={il} dwell={dwell_lbl} ({i_names})",
                    policy_tag="informal_only",
                )
            )
    return tuple(out)


def formal_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    Policy C family: no informal curbs; all 8 formal mid masks × 2 dwell = 16.

    X_<F3>_000 — bus may stop at any subset of formal mids (or none).
    """
    out: list[ScenarioSpec] = []
    for fmask in range(8):
        fl = _mask_label(FORMAL_MID_STOP_KEYS, _keys_from_mask(FORMAL_MID_STOP_KEYS, fmask))
        f_names = ", ".join(
            FORMAL_MID_STOP_LABELS[k] for k in FORMAL_MID_STOP_KEYS if k in _keys_from_mask(FORMAL_MID_STOP_KEYS, fmask)
        ) or "no mid-formal"
        for dwell in (1.0, OPTIMIZED_SHORT_DWELL_SCALE):
            suffix = "_d55" if dwell < 1.0 else ""
            dwell_lbl = "100%" if dwell >= 1.0 else "55%"
            out.append(
                _encounter_spec(
                    fmask,
                    0,
                    dwell,
                    scenario_id=f"X_{fl}_000{suffix}",
                    group="formal_all",
                    label=f"Formal-only F={fl} I=000 dwell={dwell_lbl} ({f_names})",
                    policy_tag="formal_only",
                )
            )
    return tuple(out)


def optimized_transit_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """All 64 formal×informal encounter masks at 55% dwell (E-style, every stop combo)."""
    return tuple(
        ScenarioSpec(
            s.scenario_id,
            "optimized_transit_all",
            s.label,
            POLICY_OPTIMIZED_TRANSIT,
            s.formal_keys,
            s.informal_keys,
            s.dwell_scale,
            frozenset(),
        )
        for s in full_encounter_scenarios()
        if s.dwell_scale < 1.0
    )


def optimized_baseline_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """Legacy alias for optimized_transit_all_scenarios()."""
    return optimized_transit_all_scenarios()


def optimized_informal_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """Informal-only: 8 informal masks at 55% dwell."""
    return tuple(
        ScenarioSpec(
            s.scenario_id,
            "optimized_informal_all",
            s.label,
            "informal_only",
            s.formal_keys,
            s.informal_keys,
            s.dwell_scale,
            frozenset(),
        )
        for s in informal_all_scenarios()
        if s.dwell_scale < 1.0
    )


def optimized_formal_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """Formal-only: 8 formal masks at 55% dwell (D-style, every formal subset)."""
    return tuple(
        ScenarioSpec(
            s.scenario_id,
            "optimized_formal_all",
            s.label,
            POLICY_OPTIMIZED,
            s.formal_keys,
            s.informal_keys,
            s.dwell_scale,
            frozenset(),
        )
        for s in formal_all_scenarios()
        if s.dwell_scale < 1.0
    )


def optimized_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """All 64 encounter combos at 55% dwell (alias grid for --optimized-all)."""
    return tuple(
        ScenarioSpec(
            s.scenario_id,
            "optimized_all",
            s.label,
            "optimized_encounter",
            s.formal_keys,
            s.informal_keys,
            s.dwell_scale,
            frozenset(),
        )
        for s in full_encounter_scenarios()
        if s.dwell_scale < 1.0
    )


def unlisted_stop_scenarios(
    *,
    dwell_scale: float = 1.0,
    u_only: int | None = None,
) -> tuple[ScenarioSpec, ...]:
    """Transit all stops + 0/1/2 unlisted informals (or U1 only)."""
    counts = (u_only,) if u_only is not None else (0, 1, 2)
    if u_only is not None:
        group = "unlisted_only"
    elif dwell_scale < 1.0:
        group = "optimized_unlisted_all"
    else:
        group = "unlisted_all"
    tag = "unlisted_informal" if dwell_scale >= 1.0 else "optimized_unlisted"
    out: list[ScenarioSpec] = []
    for u in counts:
        suffix = "_d55" if dwell_scale < 1.0 else ""
        sid = f"A_transit__U{u}{suffix}"
        if u_only is not None:
            sid = f"A_transit__U{u}_only{suffix}"
        dwell_lbl = "55%" if dwell_scale < 1.0 else "100%"
        out.append(
            _encounter_spec(
                0b111,
                0b111,
                dwell_scale,
                scenario_id=sid,
                group=group,
                label=f"All mapped stops + {u} unlisted informal(s), dwell={dwell_lbl}",
                policy_tag=tag,
                adhoc_informal_count=u,
            )
        )
    return tuple(out)


def unlisted_stop_only_scenario() -> tuple[ScenarioSpec, ...]:
    return unlisted_stop_scenarios(dwell_scale=1.0, u_only=1)


def unlisted_stop_all_scenarios() -> tuple[ScenarioSpec, ...]:
    return unlisted_stop_scenarios(dwell_scale=1.0)


def optimized_unlisted_stop_all_scenarios() -> tuple[ScenarioSpec, ...]:
    return unlisted_stop_scenarios(dwell_scale=OPTIMIZED_SHORT_DWELL_SCALE)


def complete_encounter_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    Full grid: 128 stop masks × 3 service modes × 3 ad-hoc informal counts = 1,152.

    ID pattern: X_111_111__F__U0  (F/A/D = full / alight-only / drive-through; U0–U2 unlisted curbs)
    """
    out: list[ScenarioSpec] = []
    for base in full_encounter_scenarios():
        for sm in SERVICE_MODES:
            code = SERVICE_MODE_CODES[sm]
            for u in range(3):
                out.append(
                    ScenarioSpec(
                        f"{base.scenario_id}__{code}__U{u}",
                        "complete_encounter",
                        f"{base.label} | {SERVICE_MODE_LABELS[sm]} | unlisted informals={u}",
                        "complete_encounter",
                        base.formal_keys,
                        base.informal_keys,
                        base.dwell_scale,
                        frozenset(),
                        sm,
                        u,
                    )
                )
    return tuple(out)


_NAMED_DRIVER_SERVICE: tuple[tuple[str, int, int, float, str, str, str, int], ...] = (
    (
        "P_alight_only",
        0b111,
        0b111,
        1.0,
        "alight_only",
        "Drop-off only at all mapped stops (no pick-up)",
        "alight_only",
        0,
    ),
    (
        "P_drive_through",
        0b111,
        0b111,
        1.0,
        "drive_through",
        "Brief curb stop — pick-up/drop-off/wait (~55% field dwell)",
        "drive_through",
        0,
    ),
    (
        "U1_unlisted_informal",
        0b111,
        0b111,
        1.0,
        "unlisted_informal",
        "Baseline stops + 1 unlisted informal curb (~520 m from Robinsons)",
        "full",
        1,
    ),
    (
        "U2_unlisted_informal",
        0b111,
        0b111,
        1.0,
        "unlisted_informal",
        "Baseline stops + 2 unlisted informal curbs (~520 m + mid-corridor ~1.63 km)",
        "full",
        2,
    ),
    (
        "P_alight_U1",
        0b111,
        0b111,
        1.0,
        "alight_unlisted",
        "Drop-off only + 1 unlisted informal stop",
        "alight_only",
        1,
    ),
)


def driver_service_scenarios() -> tuple[ScenarioSpec, ...]:
    """Named scenarios: drop-off only, drive-through, and unlisted informal curbs."""
    return tuple(
        _encounter_spec(
            fm,
            im,
            dwell,
            scenario_id=sid,
            group="driver_service",
            label=label,
            policy_tag=tag,
            service_mode=sm,
            adhoc_informal_count=u,
        )
        for sid, fm, im, dwell, tag, label, sm, u in _NAMED_DRIVER_SERVICE
    )


_NAMED_POLICY_SPECS: tuple[tuple[str, int, int, float, str, str], ...] = (
    ("A_transit", 0b111, 0b111, 1.0, POLICY_TRANSIT, "Transit — all stops, 100% dwell"),
    ("B_informal_only", 0b000, 0b111, 1.0, "informal_only", "Informal only, 100% dwell"),
    ("C_formal_only", 0b111, 0b000, 1.0, "formal_only", "Formal only, 100% dwell"),
    ("E_optimized_transit", 0b111, 0b111, OPTIMIZED_SHORT_DWELL_SCALE, POLICY_OPTIMIZED_TRANSIT, "All stops, 55% dwell"),
    ("D_optimized", 0b111, 0b000, OPTIMIZED_SHORT_DWELL_SCALE, POLICY_OPTIMIZED, "Formal only, 55% dwell"),
)


def _stop_by_key(key: str):
    for s in STOPS_RB_TO_WM + STOPS_WM_TO_RB:
        if s.key == key:
            return s
    raise KeyError(key)


def chainage_overrides_for_scenario(spec: ScenarioSpec) -> dict[str, float] | None:
    """Absolute chainage (m from Robinsons) per stop key; None if no shifts."""
    if not spec.shift_keys:
        return None
    out: dict[str, float] = {}
    for key in RELOCATABLE_STOP_KEYS:
        base = chainage_from_robinsons(_stop_by_key(key))
        if key in spec.shift_keys:
            out[key] = base + RELOC_SHIFT_M
        else:
            out[key] = base
    return out


def effective_corridor_length_m(spec: ScenarioSpec) -> float:
    """Extend corridor when Waltermart terminal is shifted downstream."""
    length = CORRIDOR_LENGTH_M
    if not spec.shift_keys:
        return length
    ov = chainage_overrides_for_scenario(spec)
    if ov and "waltermart" in ov:
        length = max(length, ov["waltermart"])
    return length


def policy_scenarios() -> tuple[ScenarioSpec, ...]:
    return tuple(
        _encounter_spec(fm, im, dwell, scenario_id=sid, group="policy", label=label, policy_tag=tag)
        for sid, fm, im, dwell, tag, label in _NAMED_POLICY_SPECS
    )


def partial_informal_scenarios() -> tuple[ScenarioSpec, ...]:
    """
    Formal stops + selective informal encounter (100% dwell).

    Mask bits in scenario id I_<grocery><7-11><rcbc>: 1 = bus stops at that informal curb.
    Example: I_100 = Korean grocery only (skips 7-Eleven and RCBC on rb→wm).
  """
    out: list[ScenarioSpec] = []
    all_mask = (1 << len(INFORMAL_STOP_KEYS)) - 1
    for mask in range(1, 1 << len(INFORMAL_STOP_KEYS)):
        if mask == all_mask:
            continue  # same encounter set as A_transit
        keys = frozenset(
            INFORMAL_STOP_KEYS[i] for i in range(len(INFORMAL_STOP_KEYS)) if mask & (1 << i)
        )
        mask_label = "".join("1" if k in keys else "0" for k in INFORMAL_STOP_KEYS)
        names = ", ".join(INFORMAL_STOP_LABELS[k] for k in INFORMAL_STOP_KEYS if k in keys)
        skipped = ", ".join(
            INFORMAL_STOP_LABELS[k] for k in INFORMAL_STOP_KEYS if k not in keys
        )
        out.append(
            _encounter_spec(
                0b111,
                mask,
                1.0,
                scenario_id=f"I_{mask_label}",
                group="partial_informal",
                label=f"Formal + informal subset ({names}); skip {skipped}",
                policy_tag="partial_informal",
            )
        )
    return tuple(out)


def relocation_scenarios(*, dwell_scale: float = 1.0) -> tuple[ScenarioSpec, ...]:
    """Formal-only + 5 m shifts; 31 non-zero relocation masks."""
    suffix = "_d55" if dwell_scale < 1.0 else ""
    group = "optimized_relocation_all" if dwell_scale < 1.0 else "relocation"
    tag = "formal_reloc_opt" if dwell_scale < 1.0 else "formal_reloc"
    dwell_lbl = "55%" if dwell_scale < 1.0 else "100%"
    out: list[ScenarioSpec] = []
    keys = RELOCATABLE_STOP_KEYS
    for mask in range(1, 1 << len(keys)):
        shifted = frozenset(keys[i] for i in range(len(keys)) if mask & (1 << i))
        names = ", ".join(RELOCATABLE_LABELS[k].split()[-1] for k in keys if k in shifted)
        out.append(
            ScenarioSpec(
                f"R_{mask:05b}{suffix}",
                group,
                f"Formal only; +5 m: {names}; dwell={dwell_lbl}",
                tag,
                ALL_FORMAL_MID_STOP_KEYS,
                frozenset(),
                dwell_scale,
                shifted,
            )
        )
    return tuple(out)


def relocation_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """Alias for all 31 relocation masks (--relocation-all)."""
    return relocation_scenarios()


def optimized_relocation_all_scenarios() -> tuple[ScenarioSpec, ...]:
    """All relocation masks at 55% dwell."""
    return relocation_scenarios(dwell_scale=OPTIMIZED_SHORT_DWELL_SCALE)


def scenario_registry() -> dict[str, ScenarioSpec]:
    """Named policies + X_* grid + partial informal + relocation + driver-service named scenarios."""
    reg: dict[str, ScenarioSpec] = {}
    for s in full_encounter_scenarios():
        reg[s.scenario_id] = s
    for s in policy_scenarios():
        reg[s.scenario_id] = s
    for s in partial_informal_scenarios():
        reg[s.scenario_id] = s
    for s in relocation_scenarios():
        reg[s.scenario_id] = s
    for s in driver_service_scenarios():
        reg[s.scenario_id] = s
    for s in unlisted_stop_all_scenarios():
        reg[s.scenario_id] = s
    for s in unlisted_stop_only_scenario():
        reg[s.scenario_id] = s
    for s in optimized_unlisted_stop_all_scenarios():
        reg[s.scenario_id] = s
    # Legacy scenario id aliases (baseline → transit rename)
    _legacy_ids = {
        "A_baseline": "A_transit",
        "E_optimized_baseline": "E_optimized_transit",
    }
    for old, new in _legacy_ids.items():
        if new in reg:
            reg[old] = reg[new]
    for u in (0, 1, 2):
        for suffix in ("", "_d55"):
            for only in ("", "_only"):
                old = f"A_baseline__U{u}{only}{suffix}"
                new = f"A_transit__U{u}{only}{suffix}"
                if new in reg:
                    reg[old] = reg[new]
    return reg


def complete_scenario_registry() -> dict[str, ScenarioSpec]:
    """scenario_registry() plus all 1,152 complete-encounter variants."""
    reg = scenario_registry()
    for s in complete_encounter_scenarios():
        reg[s.scenario_id] = s
    return reg


def all_scenario_specs(
    *,
    include_policies: bool = False,
    include_partial_informal: bool = False,
    include_full_encounter: bool = False,
    include_relocation: bool = False,
    include_complete_encounter: bool = False,
    include_driver_service: bool = False,
) -> tuple[ScenarioSpec, ...]:
    parts: list[ScenarioSpec] = []
    if include_complete_encounter:
        parts.extend(complete_encounter_scenarios())
    if include_full_encounter:
        parts.extend(full_encounter_scenarios())
    if include_policies:
        parts.extend(policy_scenarios())
    if include_partial_informal:
        parts.extend(partial_informal_scenarios())
    if include_relocation:
        parts.extend(relocation_scenarios())
    if include_driver_service:
        parts.extend(driver_service_scenarios())
    return tuple(parts)


def optimized_comparison_scenarios() -> tuple[ScenarioSpec, ...]:
    """A (full dwell) + E (all stops, short dwell) + D (formal only, short dwell)."""
    by_id = {s.scenario_id: s for s in policy_scenarios()}
    return (
        by_id["A_transit"],
        by_id["E_optimized_transit"],
        by_id["D_optimized"],
    )


def default_per_bus_scenarios(*, optimized: bool) -> tuple[ScenarioSpec, ...]:
    """Default: A only, or A + E + D (decompose dwell vs informal removal)."""
    if not optimized:
        return (policy_scenarios()[0],)
    return optimized_comparison_scenarios()


def default_extended_scenarios() -> tuple[ScenarioSpec, ...]:
    """Extended default: A + E + D."""
    return optimized_comparison_scenarios()


def default_session_hour_scenarios() -> tuple[ScenarioSpec, ...]:
    """Full encounter grid (128) + relocation (31)."""
    return all_scenario_specs(include_full_encounter=True, include_relocation=True)


def policy_scenario_by_tag(tag: str) -> ScenarioSpec:
    """One of: transit, informal_only, formal_only, optimized_transit, optimized (or A–E)."""
    key = {
        "a": "A_transit",
        "transit": "A_transit",
        "baseline": "A_transit",
        "b": "B_informal_only",
        "informal_only": "B_informal_only",
        "informal": "B_informal_only",
        "c": "C_formal_only",
        "formal_only": "C_formal_only",
        "formal": "C_formal_only",
        "e": "E_optimized_transit",
        "optimized_transit": "E_optimized_transit",
        "optimized_baseline": "E_optimized_transit",
        "baseline_optimized": "E_optimized_transit",
        "d": "D_optimized",
        "optimized": "D_optimized",
    }.get(tag.strip().lower())
    if not key:
        raise ValueError(f"Unknown policy tag {tag!r}")
    for s in policy_scenarios():
        if s.scenario_id == key:
            return s
    raise KeyError(key)


# Mid-route stops that may be removed via --policy + --remove (terminals always on).
REMOVABLE_MID_STOP_KEYS: frozenset[str] = frozenset(FORMAL_MID_STOP_KEYS) | frozenset(
    INFORMAL_STOP_KEYS
)

STOP_REMOVE_ALIASES: dict[str, str] = {
    "rkp": "rkp_trading",
    "rkp_trading": "rkp_trading",
    "trading": "rkp_trading",
    "villa": "villa_verde",
    "villa_verde": "villa_verde",
    "vista": "vista_mall",
    "vista_mall": "vista_mall",
    "grocery": "korean_grocery",
    "korean": "korean_grocery",
    "korean_grocery": "korean_grocery",
    "7_11": "seven_eleven",
    "711": "seven_eleven",
    "seven_eleven": "seven_eleven",
    "7-11": "seven_eleven",
    "rcbc": "rcbc",
}

STOP_REMOVE_SHORT: dict[str, str] = {
    "rkp_trading": "rkp",
    "villa_verde": "villa",
    "vista_mall": "vista",
    "korean_grocery": "grocery",
    "seven_eleven": "7-11",
    "rcbc": "rcbc",
}

STOP_REMOVE_HELP = (
    "Formal: rkp, villa, vista  |  Informal: grocery, 7-11, rcbc  "
    "(prefix optional: informal--7-11, formal--vista)"
)


def _normalize_remove_token(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "")
    for prefix in ("informal--", "informal-", "formal--", "formal-"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return s.replace("-", "_")


def parse_remove_stop_tokens(remove: str) -> frozenset[str]:
    """Parse --remove '7-11,vista' or 'informal--7-11' into canonical stop keys."""
    if not remove or not remove.strip():
        raise ValueError("--remove needs at least one stop name")
    keys: set[str] = set()
    for part in remove.split(","):
        token = _normalize_remove_token(part)
        if not token:
            continue
        key = STOP_REMOVE_ALIASES.get(token)
        if key is None:
            known = ", ".join(sorted(set(STOP_REMOVE_ALIASES.keys())))
            raise ValueError(f"Unknown stop {part!r}. Use: {known}")
        keys.add(key)
    if not keys:
        raise ValueError("--remove needs at least one stop name")
    return frozenset(keys)


def policy_scenario_with_removals(policy: str, remove_keys: frozenset[str]) -> ScenarioSpec:
    """
    Start from a named policy (A–E) and skip selected mid-route stops.

    Example: policy A + remove seven_eleven -> all stops except 7-Eleven.
    """
    base = policy_scenario_by_tag(policy)
    bad = remove_keys - REMOVABLE_MID_STOP_KEYS
    if bad:
        raise ValueError(
            f"Cannot remove terminal or unknown stop(s): {', '.join(sorted(bad))}. "
            f"Mid-route only: {', '.join(sorted(REMOVABLE_MID_STOP_KEYS))}"
        )
    active = base.formal_keys | base.informal_keys
    not_in_policy = remove_keys - active
    if not_in_policy:
        labels = {
            **FORMAL_MID_STOP_LABELS,
            **INFORMAL_STOP_LABELS,
        }
        names = ", ".join(labels.get(k, k) for k in sorted(not_in_policy))
        raise ValueError(
            f"Policy {base.scenario_id} does not serve: {names}. "
            "Pick a policy that includes those stops, or remove different stops."
        )
    formal = base.formal_keys - remove_keys
    informal = base.informal_keys - remove_keys
    short = [STOP_REMOVE_SHORT.get(k, k) for k in sorted(remove_keys)]
    suffix = "__no_" + "_".join(short)
    removed_labels = []
    for k in sorted(remove_keys):
        if k in FORMAL_MID_STOP_LABELS:
            removed_labels.append(FORMAL_MID_STOP_LABELS[k])
        else:
            removed_labels.append(INFORMAL_STOP_LABELS[k])
    label = f"{base.label}; skip {', '.join(removed_labels)}"
    return ScenarioSpec(
        f"{base.scenario_id}{suffix}",
        "policy_custom",
        label,
        base.policy_tag,
        formal,
        informal,
        base.dwell_scale,
        base.shift_keys,
        base.service_mode,
        base.adhoc_informal_count,
    )


def resolve_policy_custom_scenarios(policy: str, remove: str | None) -> tuple[ScenarioSpec, ...]:
    """--policy A [--remove 7-11,...]"""
    if remove:
        return (policy_scenario_with_removals(policy, parse_remove_stop_tokens(remove)),)
    return (policy_scenario_by_tag(policy),)


def scenarios_for_session_hour_mode(mode: str) -> tuple[ScenarioSpec, ...]:
    """
    Scenario sets for simulation_session_hour.py.

    Modes: all, transit, informal, formal, optimized_transit, optimized, relocation,
    policies (A–E), transit_and_optimized (A+E+D).
    """
    m = mode.strip().lower().replace("-", "_")
    if m in ("all", "everything"):
        return default_session_hour_scenarios()
    if m in ("transit", "baseline"):
        return (policy_scenario_by_tag("transit"),)
    if m in ("transit_all", "baseline_all", "baseline_every_encounter"):
        return transit_all_scenarios()
    if m in ("informal", "informal_only"):
        return (policy_scenario_by_tag("informal"),)
    if m in ("informal_all", "informal_every_encounter"):
        return informal_all_scenarios()
    if m in ("formal", "formal_only"):
        return (policy_scenario_by_tag("formal"),)
    if m in ("formal_all", "formal_every_encounter"):
        return formal_all_scenarios()
    if m in ("optimized_transit_all", "optimized_baseline_all"):
        return optimized_transit_all_scenarios()
    if m in ("optimized_informal_all",):
        return optimized_informal_all_scenarios()
    if m in ("optimized_formal_all",):
        return optimized_formal_all_scenarios()
    if m == "optimized_all":
        return optimized_all_scenarios()
    if m in ("optimized_transit", "optimized_baseline", "baseline_optimized", "e"):
        return (policy_scenario_by_tag("optimized_transit"),)
    if m == "optimized":
        return (policy_scenario_by_tag("optimized"),)
    if m in ("full_encounter", "full", "x", "all_stops"):
        return full_encounter_scenarios()
    if m in ("complete_encounter", "complete", "all_possible", "all_possible_combinations"):
        return complete_encounter_scenarios()
    if m in ("driver_service", "service_mode", "curb_behavior", "drop_off", "unlisted_informal"):
        return driver_service_scenarios()
    if m in ("relocation", "reloc", "r", "relocation_all"):
        return relocation_all_scenarios()
    if m in ("optimized_relocation_all",):
        return optimized_relocation_all_scenarios()
    if m in ("unlisted_stop_only", "unlisted_only"):
        return unlisted_stop_only_scenario()
    if m in ("unlisted_stop_all", "unlisted_all"):
        return unlisted_stop_all_scenarios()
    if m in ("optimized_unlisted_stop_all", "optimized_unlisted_all"):
        return optimized_unlisted_stop_all_scenarios()
    if m in ("partial_informal", "partial", "informal_subset", "i"):
        return partial_informal_scenarios()
    if m in ("policies", "policy", "a_d", "abcd"):
        return policy_scenarios()
    if m in ("transit_and_optimized", "baseline_and_optimized", "a_e_d", "a_d_pair"):
        return optimized_comparison_scenarios()
    raise ValueError(
        f"Unknown session-hour mode {mode!r}; use all, transit, informal, formal, "
        "optimized_transit, optimized, partial_informal, relocation, policies, "
        "complete_encounter, driver_service, or transit_and_optimized"
    )


def select_scenarios(
    ids: list[str] | None = None,
    *,
    groups: list[str] | None = None,
    optimized: bool = False,
    all_scenarios: bool = False,
) -> tuple[ScenarioSpec, ...]:
    if all_scenarios:
        return all_scenario_specs(include_full_encounter=True, include_relocation=True)
    if groups:
        gset = {x.strip().lower() for x in groups}
        incl_full = "full_encounter" in gset or "full" in gset or "x" in gset
        incl_pol = "policies" in gset or "policy" in gset
        incl_partial = (
            "partial_informal" in gset
            or "partial" in gset
            or "informal_subset" in gset
        )
        incl_reloc = "relocation" in gset or "reloc" in gset
        if not incl_full and not incl_pol and not incl_partial and not incl_reloc:
            incl_full = True
        return all_scenario_specs(
            include_full_encounter=incl_full,
            include_policies=incl_pol,
            include_partial_informal=incl_partial,
            include_relocation=incl_reloc,
        )
    if ids:
        by_id = complete_scenario_registry()
        out: list[ScenarioSpec] = []
        for raw in ids:
            key = raw.strip()
            if key not in by_id:
                raise SystemExit(f"Unknown scenario id: {key}. Use --list-scenarios.")
            out.append(by_id[key])
        return tuple(out)
    return default_per_bus_scenarios(optimized=optimized)


def count_planned_scenarios(
    n_buses: int,
    scenarios: tuple[ScenarioSpec, ...],
    n_signal_patterns: int,
) -> int:
    """Total result rows: one scenario per bus × stop policy × signal pattern."""
    return n_buses * len(scenarios) * n_signal_patterns


count_planned_runs = count_planned_scenarios  # legacy alias


SCENARIO_MODE_CHOICES_MSG = (
    "Choose only one scenario mode: --transit-only, --transit-all, --informal-all, "
    "--formal-all, --all-scenarios, --all-possible, --full-encounter-only, "
    "--driver-service-only, --informal-only, --formal-only, --optimized, etc."
)


def resolve_scenario_mode_from_args(
    args,
    *,
    default: tuple[ScenarioSpec, ...],
    default_label: str,
) -> tuple[tuple[ScenarioSpec, ...], str]:
    """
    Map CLI scenario flags to ScenarioSpec tuples.

    Shared by simulation_per_vehicle.py and simulation_session_hour.py.
    --scenarios / --scenario-groups override mode flags.
    """
    groups = (
        [g.strip() for g in args.scenario_groups.split(",")]
        if getattr(args, "scenario_groups", None)
        else None
    )
    ids = (
        [s.strip() for s in args.scenarios.split(",")]
        if getattr(args, "scenarios", None)
        else None
    )
    policy = getattr(args, "policy", None)
    remove = getattr(args, "remove", None)
    if policy:
        if ids or groups:
            raise SystemExit("Use either --policy/--remove or --scenarios/--scenario-groups, not both.")
        mode_flags = (
            getattr(args, "all_scenarios", False),
            getattr(args, "transit_only", False),
            getattr(args, "transit_all", False),
            getattr(args, "informal_only", False),
            getattr(args, "informal_all", False),
            getattr(args, "formal_only", False),
            getattr(args, "formal_all", False),
            getattr(args, "optimized_transit_only", False),
            getattr(args, "optimized_only", False),
            getattr(args, "full_encounter_only", False),
            getattr(args, "complete_encounter_only", False)
            or getattr(args, "all_possible_combinations", False),
            getattr(args, "driver_service_only", False),
            getattr(args, "relocation_only", False),
            getattr(args, "partial_informal_only", False),
            getattr(args, "policies_only", False),
            getattr(args, "optimized", False),
        )
        if any(mode_flags):
            raise SystemExit("Use --policy/--remove or one scenario mode flag, not both.")
        try:
            specs = resolve_policy_custom_scenarios(policy, remove)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        label = f"policy {policy}" + (f" minus {remove}" if remove else "")
        return specs, label
    if remove:
        raise SystemExit("--remove requires --policy (e.g. --policy A --remove 7-11)")
    if ids or groups:
        return select_scenarios(ids=ids, groups=groups), "custom"

    mode_flags = (
        ("all", getattr(args, "all_scenarios", False)),
        ("transit", getattr(args, "transit_only", False)),
        ("transit_all", getattr(args, "transit_all", False)),
        ("informal", getattr(args, "informal_only", False)),
        ("informal_all", getattr(args, "informal_all", False)),
        ("formal", getattr(args, "formal_only", False)),
        ("formal_all", getattr(args, "formal_all", False)),
        ("optimized_transit_all", getattr(args, "optimized_transit_all", False)),
        ("optimized_informal_all", getattr(args, "optimized_informal_all", False)),
        ("optimized_formal_all", getattr(args, "optimized_formal_all", False)),
        ("optimized_all", getattr(args, "optimized_all", False)),
        ("optimized_transit", getattr(args, "optimized_transit_only", False)),
        ("optimized", getattr(args, "optimized_only", False)),
        ("full_encounter", getattr(args, "full_encounter_only", False)),
        (
            "complete_encounter",
            getattr(args, "complete_encounter_only", False)
            or getattr(args, "all_possible_combinations", False),
        ),
        ("driver_service", getattr(args, "driver_service_only", False)),
        ("relocation", getattr(args, "relocation_only", False)),
        ("relocation_all", getattr(args, "relocation_all", False)),
        ("optimized_relocation_all", getattr(args, "optimized_relocation_all", False)),
        ("unlisted_only", getattr(args, "unlisted_stop_only", False)),
        ("unlisted_all", getattr(args, "unlisted_stop_all", False)),
        ("optimized_unlisted_all", getattr(args, "optimized_unlisted_stop_all", False)),
        ("partial_informal", getattr(args, "partial_informal_only", False)),
        ("policies", getattr(args, "policies_only", False)),
        ("transit_and_optimized", getattr(args, "optimized", False)),
    )
    chosen = [name for name, on in mode_flags if on]
    if len(chosen) > 1:
        raise SystemExit(SCENARIO_MODE_CHOICES_MSG)
    if chosen:
        label = chosen[0]
        if label == "complete_encounter" and getattr(args, "all_possible_combinations", False):
            label = "all_possible (1152 stop policies)"
        if label == "transit_all":
            label = "transit-all (128 encounter masks)"
        if label == "informal_all":
            label = "informal-all (16 informal encounter masks)"
        if label == "formal_all":
            label = "formal-all (16 formal encounter masks)"
        return scenarios_for_session_hour_mode(chosen[0]), label
    return default, default_label


def print_scenario_catalog() -> None:
    print("=" * 72)
    print("CORRIDOR SCENARIO CATALOG")
    print("=" * 72)
    print(f"Formal mid bits: {' | '.join(f'{k}' for k in FORMAL_MID_STOP_KEYS)}")
    print(f"Informal bits:   {' | '.join(f'{k}' for k in INFORMAL_STOP_KEYS)}")
    print(f"Relocatable (+{RELOC_SHIFT_M:.0f} m): {', '.join(RELOCATABLE_STOP_KEYS)}")
    print()
    n_full = len(full_encounter_scenarios())
    print(f"FULL ENCOUNTER GRID (X_<F3>_<I3>[_d55]): {n_full} scenarios")
    print("  8 formal mid masks × 8 informal masks × 2 dwell (100%, 55%)")
    print("  Terminals (Robinsons, Waltermart) always served.")
    for s in full_encounter_scenarios()[:6]:
        print(f"  {s.scenario_id:22s}  encounter={s.encounter_mask}  dwell={s.dwell_scale:.2f}")
    print(f"  ... ({n_full} total; e.g. X_111_111=A, X_111_111_d55=E, X_111_000=C)")
    print()
    print("NAMED POLICY ALIASES (subset of X_*)")
    for s in policy_scenarios():
        x_id = f"X_{s.formal_mask}_{s.informal_mask}" + ("_d55" if s.dwell_scale < 1.0 else "")
        print(
            f"  {s.scenario_id:22s}  -> {x_id}  encounter={s.encounter_mask}  dwell={s.dwell_scale:.2f}"
        )
        print(f"    {s.label}")
    print()
    n_ba = len(transit_all_scenarios())
    n_ia = len(informal_all_scenarios())
    n_fa = len(formal_all_scenarios())
    print("POLICY -only (all ON in that policy) vs -all (every stop-encounter combo in family)")
    print("  --transit-only      1 policy (A, all stops ON)         -> 36 rows (9 buses x 4 signals)")
    print(f"  --transit-all       {n_ba} policies (formal x informal)       -> {n_ba * 4 * 9} rows")
    print("  --informal-only     1 policy (B, all informal ON)       -> 36 rows")
    print(f"  --informal-all      {n_ia} policies (informal subsets)         -> {n_ia * 4 * 9} rows")
    print("  --formal-only       1 policy (C, all formal ON)        -> 36 rows")
    print(f"  --formal-all        {n_fa} policies (formal subsets)          -> {n_fa * 4 * 9} rows")
    n_ob = len(optimized_transit_all_scenarios())
    n_oi = len(optimized_informal_all_scenarios())
    n_of = len(optimized_formal_all_scenarios())
    n_reloc = len(relocation_all_scenarios())
    n_reloc_opt = len(optimized_relocation_all_scenarios())
    n_u1 = len(unlisted_stop_only_scenario())
    n_ua = len(unlisted_stop_all_scenarios())
    n_uo = len(optimized_unlisted_stop_all_scenarios())
    print()
    print("OPTIMIZED (-all = 55% dwell encounter grids)")
    print(f"  --optimized-transit-only  E (1 policy, all ON)     -> 36 rows")
    print(f"  --optimized-transit-all {n_ob} policies              -> {n_ob * 4 * 9} rows")
    print(f"  --optimized-informal-all {n_oi} policies              -> {n_oi * 4 * 9} rows")
    print(f"  --optimized-formal-all   {n_of} policies              -> {n_of * 4 * 9} rows")
    print(f"  --optimized-only         D (1 policy, formal ON)    -> 36 rows")
    print(f"  --optimized-all          {n_ob} (all masks @ 55%)    -> {n_ob * 4 * 9} rows")
    print()
    print("RELOCATION (+5 m formal/terminal shifts, formal-only)")
    print(f"  --relocation-only / --relocation-all  {n_reloc} policies -> {n_reloc * 4 * 9} rows")
    print(f"  --optimized-relocation-all            {n_reloc_opt} @ 55% -> {n_reloc_opt * 4 * 9} rows")
    print()
    print("UNLISTED INFORMAL (mapped stops all ON + adhoc curbs)")
    print(f"  --unlisted-stop-only  {n_u1} (U1 only)               -> {n_u1 * 4 * 9} rows")
    print(f"  --unlisted-stop-all   {n_ua} (U0,U1,U2)              -> {n_ua * 4 * 9} rows")
    print(f"  --optimized-unlisted-stop-all {n_uo} @ 55%           -> {n_uo * 4 * 9} rows")
    print()
    n_reloc = len(relocation_scenarios())
    n_driver = len(driver_service_scenarios())
    n_complete = len(complete_encounter_scenarios())
    print(f"RELOCATION (R_*): {n_reloc} scenarios — all formal mid on, no informal, +5 m shifts")
    for s in relocation_scenarios()[:4]:
        print(f"  {s.scenario_id:16s}  {s.label}")
    print(f"  ... ({n_reloc} total)")
    print()
    print(f"DRIVER SERVICE & UNLISTED INFORMAL (P_*, U*): {n_driver} named scenarios")
    print("  Drop-off only, brief curb stop (~55% dwell), +0/1/2 unlisted informal curbs")
    for s in driver_service_scenarios():
        print(
            f"  {s.scenario_id:22s}  service={s.service_mode}  adhoc={s.adhoc_informal_count}  "
            f"encounter={s.encounter_mask}"
        )
    print()
    print(
        f"COMPLETE ENCOUNTER GRID (X_*__F|A|D__U0-2): {n_complete} scenarios "
        f"({n_full} masks × 3 service × 3 adhoc)"
    )
    for s in complete_encounter_scenarios()[:4]:
        print(f"  {s.scenario_id}")
    print(f"  ... ({n_complete} total)")
    print()
    n_all = n_full + n_reloc
    print("--all-scenarios: 128 X_* encounter + 31 R_* relocation = 159 stop policies")
    print(f"  x 4 signal patterns x 9 buses = {n_all * 4 * 9} rows")
    print(
        f"--all-possible / --complete-encounter-only: {n_complete} stop policies "
        f"(128 masks x 3 service x 3 adhoc = ALL combinations)"
    )
    print(f"  x 4 x 9 = {n_complete * 4 * 9} rows")
    print(f"--full-encounter-only: {n_full} (masks x dwell only, no service/adhoc) -> {n_full * 4 * 9} rows")
    print(f"--driver-service-only: {n_driver} × 4 × 9 = {n_driver * 4 * 9} rows")
    print(f"--optimized (A+E+D named): 3 × 4 × 9 = 108 rows")


if __name__ == "__main__":
    print_scenario_catalog()
