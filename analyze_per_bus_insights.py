"""
Exploratory insights from per-bus simulation results.
"""
from __future__ import annotations

import csv
import statistics as stats
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELOC_KEYS = ("robinsons", "rkp_trading", "villa_verde", "vista_mall", "waltermart")


def _f(row: dict, key: str) -> float | None:
    v = row.get(key, "")
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def median(vals: list[float]) -> float:
    return stats.median(vals) if vals else float("nan")


def mean(vals: list[float]) -> float:
    return stats.mean(vals) if vals else float("nan")


def mask_to_stops(mask: str) -> list[str]:
    bits = mask.replace("R_", "")
    return [RELOC_KEYS[i] for i, ch in enumerate(bits) if ch == "1"]


def group_median(rows: list[dict], key: str, metric: str = "sim_corridor_travel_min") -> list[tuple]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = _f(r, metric)
        if v is not None:
            buckets[r[key]].append(v)
    out = [(k, median(v), len(v), mean(v)) for k, v in buckets.items() if v]
    out.sort(key=lambda x: x[1])
    return out


def company_ranking_controlled(rows: list[dict]) -> list[tuple]:
    """Rank companies by median travel time within session×traffic×signal×direction."""
    cells: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = _f(r, "sim_corridor_travel_min")
        if v is None:
            continue
        cell = (
            r.get("session", ""),
            r.get("traffic_condition", ""),
            r.get("signal_pattern", ""),
            r.get("trip_direction", ""),
        )
        cells[cell][r.get("bus_company", "")].append(v)

    scores: dict[str, list[float]] = defaultdict(list)
    for cell_vals in cells.values():
        if len(cell_vals) < 2:
            continue
        cell_medians = {co: median(v) for co, v in cell_vals.items() if v}
        if len(cell_medians) < 2:
            continue
        pool = median(list(cell_medians.values()))
        for co, m in cell_medians.items():
            scores[co].append(m - pool)

    ranked = [(co, mean(v), len(v)) for co, v in scores.items() if len(v) >= 3]
    ranked.sort(key=lambda x: x[1])
    return ranked


def relocation_insights(rows: list[dict]) -> dict:
    by_mask = group_median(rows, "scenario_id")
    best = by_mask[:5]
    worst = by_mask[-5:][::-1]
    baseline = next((x for x in by_mask if x[0] == "R_00000"), None)

    per_stop: dict[str, list[float]] = defaultdict(list)
    masks = sorted({r["scenario_id"] for r in rows if r.get("scenario_id", "").startswith("R_")})
    mask_medians = {m: median([_f(r, "sim_corridor_travel_min") for r in rows if r["scenario_id"] == m and _f(r, "sim_corridor_travel_min")]) for m in masks}
    for m, med in mask_medians.items():
        if med != med:
            continue
        for stop in mask_to_stops(m):
            per_stop[stop].append(med)

    stop_effect = []
    all_med = median(list(mask_medians.values()))
    for stop in RELOC_KEYS:
        with_stop = [mask_medians[m] for m in masks if stop in mask_to_stops(m) and mask_medians[m] == mask_medians[m]]
        without = [mask_medians[m] for m in masks if stop not in mask_to_stops(m) and mask_medians[m] == mask_medians[m]]
        if with_stop and without:
            stop_effect.append((stop, mean(with_stop) - mean(without), len(with_stop), len(without)))
    stop_effect.sort(key=lambda x: x[1])

    return {
        "n_masks": len(by_mask),
        "overall_median_min": median([x[1] for x in by_mask]),
        "best_masks": best,
        "worst_masks": worst,
        "stop_shift_effect_min": stop_effect,
        "all_masks_median_min": all_med,
    }


def stop_detail_insights(rows: list[dict]) -> dict:
    by_policy = group_median(rows, "policy")
    by_stop_dwell: dict[str, list[float]] = defaultdict(list)
    by_stop_leg: dict[str, list[float]] = defaultdict(list)
    informal_cost: dict[str, list[float]] = defaultdict(list)

    for r in rows:
        dwell = _f(r, "dwell_at_stop_s")
        leg = _f(r, "leg_travel_before_stop_s")
        key = r.get("stop_key", "")
        kind = r.get("stop_kind", "")
        if dwell is not None and key:
            by_stop_dwell[key].append(dwell)
        if leg is not None and key:
            by_stop_leg[key].append(leg)
        if kind == "informal" and dwell is not None:
            informal_cost[key].append(dwell)

    dwell_rank = sorted(
        ((k, median(v), mean(v), len(v)) for k, v in by_stop_dwell.items()),
        key=lambda x: -x[1],
    )
    leg_rank = sorted(
        ((k, median(v), mean(v), len(v)) for k, v in by_stop_leg.items()),
        key=lambda x: -x[1],
    )
    informal_rank = sorted(
        ((k, median(v), mean(v), len(v)) for k, v in informal_cost.items()),
        key=lambda x: -x[2],
    )

    baseline = [r for r in rows if r.get("policy") in ("transit_all_stops", "baseline_all_stops")]
    optimized = [r for r in rows if r.get("policy") == "optimized_formal_only"]
    policy_compare = {
        "baseline_median_dwell_by_stop": group_median(baseline, "stop_key", "dwell_at_stop_s")[:8],
        "optimized_median_dwell_by_stop": group_median(optimized, "stop_key", "dwell_at_stop_s")[:8],
        "policy_travel": by_policy,
    }
    return {
        "dwell_rank": dwell_rank,
        "leg_rank": leg_rank,
        "informal_rank": informal_rank,
        "policy_compare": policy_compare,
    }


def signal_traffic_insights(rows: list[dict]) -> dict:
    signals = group_median(rows, "signal_pattern")
    traffic = group_median(rows, "traffic_condition")
    crowding = group_median(rows, "crowding_level")
    sessions = group_median(rows, "session")
    directions = group_median(rows, "trip_direction")
    return {
        "signals": signals,
        "traffic": traffic,
        "crowding": crowding,
        "sessions": sessions,
        "directions": directions,
    }


def main() -> None:
    main_path = ROOT / "results_per_bus_clean.csv"
    stop_path = ROOT / "results_per_bus_stop_detail_clean.csv"
    rows = load_rows(main_path)
    stop_rows = load_rows(stop_path) if stop_path.exists() else []

    print("=" * 72)
    print("PER-BUS SIMULATION INSIGHTS")
    print("=" * 72)
    print(f"Dataset: {main_path.name}  ({len(rows):,} trips)")
    print(f"Bus companies: {len({r['bus_company'] for r in rows})}")
    print(f"Scenarios: {sorted({r['scenario_id'] for r in rows})[:3]} ... ({len({r['scenario_id'] for r in rows})} relocation masks)")
    print()

    travel_vals = [_f(r, "sim_corridor_travel_min") for r in rows]
    travel_vals = [v for v in travel_vals if v is not None]
    implied_vals = [_f(r, "sim_implied_speed_kmh") for r in rows]
    implied_vals = [v for v in implied_vals if v is not None]
    print("OVERALL TRIP PERFORMANCE (relocation scenarios, formal-only +5 m tests)")
    print(f"  Corridor travel: median {median(travel_vals):.1f} min  (range {min(travel_vals):.1f}–{max(travel_vals):.1f})")
    print(f"  Implied speed:   median {median(implied_vals):.1f} km/h")
    print()

    st = signal_traffic_insights(rows)
    print("SIGNAL PATTERNS (median corridor travel, min) — lower is better")
    for pat, med, n, _ in st["signals"]:
        print(f"  {pat:6s}  {med:5.1f} min  (n={n:,})")
    print()
    print("TRAFFIC CONDITION")
    for t, med, n, _ in st["traffic"]:
        print(f"  {t:10s}  {med:5.1f} min  (n={n:,})")
    print()
    print("CROWDING")
    for c, med, n, _ in st["crowding"]:
        print(f"  {c:8s}  {med:5.1f} min  (n={n:,})")
    print()
    print("SESSION")
    for s, med, n, _ in st["sessions"]:
        print(f"  {s:20s}  {med:5.1f} min  (n={n:,})")
    print()

    companies = company_ranking_controlled(rows)
    print("BUS COMPANY RANKING (vs peers in same session/traffic/signal/direction)")
    print("  Negative score = faster than cell median; positive = slower")
    print("  Top 8 fastest:")
    for co, score, n in companies[:8]:
        print(f"    {co[:42]:42s}  {score:+.2f} min  ({n} matched cells)")
    print("  Bottom 8 slowest:")
    for co, score, n in companies[-8:]:
        print(f"    {co[:42]:42s}  {score:+.2f} min  ({n} matched cells)")
    print()

    raw_co = group_median(rows, "bus_company")
    print("RAW COMPANY MEDIAN (confounded by route mix — use controlled rank above)")
    for co, med, n, _ in raw_co[:5]:
        print(f"  fastest: {co[:40]:40s} {med:.1f} min (n={n})")
    for co, med, n, _ in raw_co[-3:]:
        print(f"  slowest: {co[:40]:40s} {med:.1f} min (n={n})")
    print()

    reloc = relocation_insights(rows)
    print("STOP RELOCATION (+5 m shift, formal-only layout)")
    print(f"  {reloc['n_masks']} non-zero masks tested; overall median {reloc['overall_median_min']:.1f} min")
    print("  Best masks (shortest trips):")
    for m, med, n, _ in reloc["best_masks"]:
        stops = ", ".join(mask_to_stops(m)) or "(none)"
        print(f"    {m}  {med:.1f} min  shifts: {stops}")
    print("  Worst masks (longest trips):")
    for m, med, n, _ in reloc["worst_masks"]:
        stops = ", ".join(mask_to_stops(m)) or "(none)"
        print(f"    {m}  {med:.1f} min  shifts: {stops}")
    print("  Effect of shifting each stop +5 m (avg mask median vs masks without that stop):")
    for stop, delta, n1, n2 in reloc["stop_shift_effect_min"]:
        tag = "helps" if delta < -0.05 else "hurts" if delta > 0.05 else "~neutral"
        print(f"    {stop:14s}  {delta:+.2f} min  ({tag})")
    print()

    if stop_rows:
        sd = stop_detail_insights(stop_rows)
        print(f"STOP-LEVEL DETAIL ({stop_path.name}, {len(stop_rows):,} stop events)")
        print("  Highest median dwell (seconds):")
        for k, med, avg, n in sd["dwell_rank"][:7]:
            print(f"    {k:16s}  median {med:.0f}s  mean {avg:.0f}s  (n={n})")
        print("  Longest leg before stop (queue + drive, seconds):")
        for k, med, avg, n in sd["leg_rank"][:7]:
            print(f"    {k:16s}  median {med:.0f}s  mean {avg:.0f}s  (n={n})")
        if sd["informal_rank"]:
            print("  Informal stops — dwell cost:")
            for k, med, avg, n in sd["informal_rank"]:
                print(f"    {k:16s}  median dwell {med:.0f}s  (n={n})")
        print("  Policy comparison (median dwell by stop, baseline vs optimized):")
        base = {k: v for k, v, *_ in sd["policy_compare"]["baseline_median_dwell_by_stop"]}
        opt = {k: v for k, v, *_ in sd["policy_compare"]["optimized_median_dwell_by_stop"]}
        for k in sorted(set(base) | set(opt)):
            b, o = base.get(k), opt.get(k)
            if b is not None and o is not None:
                print(f"    {k:16s}  baseline {b:.0f}s  →  optimized {o:.0f}s  (Δ {o-b:+.0f}s)")
        print()

    print("KEY TAKEAWAYS")
    print("  1. Compare companies using controlled scores — raw medians mix Light/Heavy traffic.")
    print("  2. G-G patterns beat R-first patterns; crowding/traffic tier dominates trip time.")
    print("  3. +5 m relocation effects are small (~0.1–0.5 min); policy (informal removal + 55% dwell) matters more.")
    print("  4. Run --optimized --no-resume for full A vs D policy comparison (not in relocation-only CSV).")


if __name__ == "__main__":
    main()
