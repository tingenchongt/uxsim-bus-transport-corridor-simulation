"""Analyze stationary dwell times from field workbooks."""

from __future__ import annotations

import statistics as st
from collections import defaultdict

import openpyxl

from bus_calibration import (
    JUNE_2026_DATA_PATH,
    load_all_stationary_vehicles,
    load_onboard_session_stats,
    parse_dwell_seconds,
)
from corridor_config import SESSION_ONBOARD_FORMAL_DWELL_S, STATIONARY_DWELL_60_120S_PCT


def stats(vals: list[float]) -> dict | None:
    if not vals:
        return None
    vals = sorted(vals)
    n = len(vals)
    return {
        "n": n,
        "min": vals[0],
        "p25": vals[n // 4],
        "med": st.median(vals),
        "mean": st.mean(vals),
        "p75": vals[(3 * n) // 4],
        "max": vals[-1],
        "pct_60_120": sum(1 for v in vals if 60 <= v <= 120) / n * 100,
        "pct_ge_60": sum(1 for v in vals if v >= 60) / n * 100,
    }


def main() -> None:
    all_obs = load_all_stationary_vehicles()
    dwells = [o.dwell_s for o in all_obs if o.dwell_s and o.dwell_s > 0]
    print(f"=== June 2026 stationary ({JUNE_2026_DATA_PATH.name}, n={len(all_obs)} obs) ===")
    s = stats(dwells)
    assert s
    print(
        f"  n={s['n']} min={s['min']:.0f}s med={s['med']:.0f}s mean={s['mean']:.1f}s "
        f"max={s['max']:.0f}s"
    )
    print(f"  1-2 min (60-120s): {s['pct_60_120']:.1f}%  |  >=60s: {s['pct_ge_60']:.1f}%")

    by_sess: dict[str, list[float]] = defaultdict(list)
    by_loc: dict[str, list[float]] = defaultdict(list)
    by_crowd: dict[str, list[float]] = defaultdict(list)
    for o in all_obs:
        if not o.dwell_s or o.dwell_s <= 0:
            continue
        by_sess[o.session].append(o.dwell_s)
        by_loc[o.data_origin].append(o.dwell_s)
        by_crowd[o.crowding or "Medium"].append(o.dwell_s)

    print("\nBy session (stationary at observation stop):")
    for sess in ("Morning Session", "Lunch", "Afternoon Session"):
        stt = stats(by_sess[sess])
        if stt:
            print(
                f"  {sess}: med={stt['med']:.0f}s mean={stt['mean']:.1f}s "
                f"1-2min={stt['pct_60_120']:.1f}%"
            )

    print("\nBy crowding (stationary):")
    for crowd in ("Low", "Medium", "High"):
        stt = stats(by_crowd.get(crowd, []))
        if stt:
            print(f"  {crowd}: med={stt['med']:.0f}s mean={stt['mean']:.1f}s")

    long_dwell = [o for o in all_obs if o.dwell_s and 60 <= o.dwell_s <= 120]
    print(f"\nBuses with 1-2 min dwell at origin (n={len(long_dwell)}):")
    for o in long_dwell[:8]:
        print(
            f"  obs {o.obs_id} {o.session} {o.data_origin} "
            f"{o.dwell_s:.0f}s crowd={o.crowding} traffic={o.traffic}"
        )
    if len(long_dwell) > 8:
        print(f"  ... and {len(long_dwell) - 8} more")

    print("\n=== On-board per-stop dwell (corridor trip) ===")
    for sess in ("Morning Session", "Lunch", "Afternoon Session"):
        ob = load_onboard_session_stats(sess)
        d = ob.get("onboard_stop_dwell_s")
        sim = SESSION_ONBOARD_FORMAL_DWELL_S.get(sess)
        print(f"  {sess}: field={d:.1f}s  sim_config={sim}s  ({sim / 60:.1f} min)")

    print("\n=== Simulation mapping ===")
    print("  Terminal (origin): stationary median per session/location")
    print("  Formal mid-route:  SESSION_ONBOARD_FORMAL_DWELL_S (~1-1.5 min)")
    print("  Per-bus origin:    obs.dwell_s when scheduled (includes 1-2 min buses)")
    print("  Crowding:          Low x0.84, High x1.45 (from stationary distribution)")


if __name__ == "__main__":
    main()
