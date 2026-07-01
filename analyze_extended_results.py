"""Quick analysis of results_summary_extended.csv — run: python analyze_extended_results.py"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent

from corridor_config import CORRIDOR_LENGTH_M, TRANSIT_POLICY_TAGS  # noqa: E402

ROWS = list(csv.DictReader((ROOT / "results_summary_extended.csv").open(encoding="utf-8")))
COMP = list(csv.DictReader((ROOT / "results_baseline_vs_optimized_extended.csv").open(encoding="utf-8")))


def f(key: str, row: dict) -> float | None:
    try:
        v = row.get(key, "")
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def main() -> None:
    tts = [f("avg_travel_time_s", r) for r in ROWS if f("avg_travel_time_s", r)]
    print("=" * 60)
    print(f"EXTENDED RESULTS ANALYSIS — {len(ROWS)} simulation runs")
    print("=" * 60)
    print(f"Mean travel time: {mean(tts):.1f} s  |  Range: {min(tts):.1f} – {max(tts):.1f} s")
    print(f"Model: 2 signals (session-timed), mixed traffic, {CORRIDOR_LENGTH_M:.0f} m corridor")
    print()

    print("1. POLICY: transit (all stops) vs optimized (formal + Vista only)")
    for pol, label in [
        (TRANSIT_POLICY_TAGS, "Transit"),
        ("optimized_formal_only", "Optimized"),
    ]:
        if isinstance(pol, tuple):
            sub = [
                f("avg_travel_time_s", r)
                for r in ROWS
                if r["policy"] in pol and f("avg_travel_time_s", r)
            ]
            dr = [f("delay_ratio", r) for r in ROWS if r["policy"] in pol and f("delay_ratio", r)]
            sp = [f("avg_speed_mps", r) for r in ROWS if r["policy"] in pol and f("avg_speed_mps", r)]
        else:
            sub = [f("avg_travel_time_s", r) for r in ROWS if r["policy"] == pol and f("avg_travel_time_s", r)]
            dr = [f("delay_ratio", r) for r in ROWS if r["policy"] == pol and f("delay_ratio", r)]
            sp = [f("avg_speed_mps", r) for r in ROWS if r["policy"] == pol and f("avg_speed_mps", r)]
        print(f"   {label:10s}  TT={mean(sub):.1f}s  delay_ratio={mean(dr):.3f}  speed={mean(sp)*3.6:.1f} km/h")
    b = mean([f("avg_travel_time_s", r) for r in ROWS if r["policy"] in TRANSIT_POLICY_TAGS])
    o = mean([f("avg_travel_time_s", r) for r in ROWS if r["policy"] == "optimized_formal_only"])
    print(f"   -> Removing informal stops saves ~{b-o:.1f} s/trip ({(b-o)/b*100:.1f}% on average)")
    print()

    print("2. BY SESSION (mean travel time, all signal patterns)")
    for sess in ("Morning Session", "Lunch", "Afternoon Session"):
        b = mean(
            [
                f("avg_travel_time_s", r)
                for r in ROWS
                if r["session"] == sess and r["policy"] in TRANSIT_POLICY_TAGS
            ]
        )
        o = mean(
            [
                f("avg_travel_time_s", r)
                for r in ROWS
                if r["session"] == sess and r["policy"] == "optimized_formal_only"
            ]
        )
        print(f"   {sess:18s}  transit={b:.1f}s  optimized={o:.1f}s  save={(b-o)/b*100:.1f}%")
    print("   Lunch is fastest overall (lighter effective demand window).")
    print()

    print("3. BY DATA ORIGIN (calibration subset)")
    for origin in ("robinsons_location", "waltermart_location"):
        sub = [f("avg_travel_time_s", r) for r in ROWS if r["data_origin"] == origin]
        print(f"   {origin:20s}  mean TT = {mean(sub):.1f} s")
    print("   Waltermart-origin runs also use 0.55 dwell scale when optimized.")
    print()

    print("4. SIGNAL PATTERN SENSITIVITY (4 one-way patterns: G-G, G-R, R-G, R-R)")
    by_pat: dict[str, list[float]] = defaultdict(list)
    for r in ROWS:
        tt = f("avg_travel_time_s", r)
        if tt:
            by_pat[r["encounter_pattern"]].append(tt)
    ranked = sorted(((p, mean(v)) for p, v in by_pat.items()), key=lambda x: x[1])
    print(f"   Spread across patterns: {ranked[0][1]:.1f}s (best) to {ranked[-1][1]:.1f}s (worst)")
    print("   Best patterns (lowest mean TT):")
    for p, m in ranked[:3]:
        print(f"      {p}  ->  {m:.1f} s")
    print("   Worst patterns:")
    for p, m in ranked[-3:]:
        print(f"      {p}  ->  {m:.1f} s")
    names = ["Pala-Pala EB", "Aguinaldo EB", "Waltermart EB", "Waltermart WB", "Aguinaldo WB", "Pala-Pala WB"]
    print("   Per-encounter GREEN vs RED (mean TT, all runs):")
    for i in range(1, 7):
        gk = f"encounter_{i}_green"
        g = [f("avg_travel_time_s", r) for r in ROWS if r.get(gk) == "True"]
        rd = [f("avg_travel_time_s", r) for r in ROWS if r.get(gk) == "False"]
        print(f"      Enc{i} {names[i-1]:14s}  G={mean(g):.1f}s  R={mean(rd):.1f}s  ({mean(g)-mean(rd):+.1f}s)")
    print("   First-encounter G vs R is small (~0.5 s); mid-trip patterns matter more.")
    print()

    pcts = [float(c["pct_improvement_travel_time"]) for c in COMP]
    print("5. PAIRED BASELINE vs OPTIMIZED (384 pairs)")
    print(f"   Mean improvement: {mean(pcts):.2f}%   Range: {min(pcts):.2f}% – {max(pcts):.2f}%")
    top = sorted(COMP, key=lambda c: -float(c["pct_improvement_travel_time"]))[:5]
    print("   Largest savings:")
    for c in top:
        print(
            f"      {float(c['pct_improvement_travel_time']):5.1f}%  "
            f"{c['session'][:12]:12s} {c['data_origin'][:12]:12s}  {c['encounter_pattern']}"
        )
    print()

    print("6. INTERPRETATION / LIMITATIONS")
    print("   - Optimized policy consistently lowers mean travel time vs full informal stops.")
    print("   - Delay can stay high even when TT drops (queues at formal stops/signals).")
    print("   - Signal G/R labels are timing sensitivity, not field-recorded phases.")
    print("   - Mixed-mode volumes use multipliers, not separate field counts per mode.")
    print("=" * 60)


if __name__ == "__main__":
    main()
