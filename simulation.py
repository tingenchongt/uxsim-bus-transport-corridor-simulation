"""
Legacy Aguinaldo Hwy UXsim prototype (12 aggregate runs).

This script runs session-level baseline vs optimized comparisons and writes
results_summary.csv / results_baseline_vs_optimized.csv. It does NOT produce
the per-bus thesis tables.

For current work, use instead:
  simulation_per_vehicle.py   — one row per Data_Collection bus (513 obs) x scenario x signal
  simulation_session_hour.py  — 1-hour mixed-traffic session runs + per-bus rows

Shared calibration: bus_calibration.py, corridor_config.py, corridor_network.py
Field data: Data_Collection.xlsx / Bus_Data_Collection_Dec-12-18.xlsx

Original 12-run layout (still what this file executes):
  Per session (Morning / Lunch / Afternoon): 4 runs x 3 sheets = 12 simulations.
  Sim 1–2: Robinsons-location subset (baseline informal vs optimized).
  Sim 3–4: Waltermart-location subset (same topology; WM demand window).
"""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

from uxsim import World

_PROJECT_DIR = Path(__file__).resolve().parent
FIGURES_OUTPUT_DIR = _PROJECT_DIR / "figures_output"
RESULTS_SUMMARY_CSV = _PROJECT_DIR / "results_summary.csv"
RESULTS_COMPARISON_CSV = _PROJECT_DIR / "results_baseline_vs_optimized.csv"

from bus_calibration import (
    SESSION_SHEETS,
    DataOrigin,
    SessionCalibration,
    load_session_stats,
    print_calibration,
)

# --- Highway physics ---
FREE_FLOW_MPS = 16.67  # ~60 km/h
LANES = 2
STOP_LINK_LENGTH_M = 25.0
STOP_LANES = 1
DEFAULT_DWELL_S = 40.0

# Cruise from Robinsons_Road to Waltermart_Road (excludes RB bay, WM bay; includes post-intersection bay links).
TOTAL_CRUISE_RB_ROAD_TO_WM_ROAD_M = 3300.0

# Signalized intersection (90 s cycle: EB green + WB green).
SIGNAL_GREEN_EB_S = 45.0
SIGNAL_GREEN_WB_S = 45.0

# Cruise from intersection to the formal stop after it (user-stated chainage; tune on Maps).
DIST_INTERSECTION_TO_POSTINT_CRUISE_M = 290.0

# Baseline RB->WM only: informal sits before the intersection (tune chainage on Maps).
CRUISE_RB_TO_INFORMAL_M = 500.0
CRUISE_INFORMAL_TO_SIGNAL_M = 450.0


def _cruise_post_int_to_wm_m() -> float:
    """Remaining RB-road to WM-road cruise after informal (50) + pre-signal + signal-post (290) + post bay (50)."""
    d = (
        TOTAL_CRUISE_RB_ROAD_TO_WM_ROAD_M
        - CRUISE_RB_TO_INFORMAL_M
        - 2.0 * STOP_LINK_LENGTH_M
        - CRUISE_INFORMAL_TO_SIGNAL_M
        - DIST_INTERSECTION_TO_POSTINT_CRUISE_M
        - 2.0 * STOP_LINK_LENGTH_M
    )
    if d < 150.0:
        raise ValueError(
            "Adjust CRUISE_RB_TO_INFORMAL_M / CRUISE_INFORMAL_TO_SIGNAL_M / "
            "DIST_INTERSECTION_TO_POSTINT_CRUISE_M: not enough distance left to Waltermart road node."
        )
    return d


# RB_road -> signal in optimized = informal leg lengths folded into one cruise (no curb dwell).
def _rb_road_to_signal_optimized_m() -> float:
    return CRUISE_RB_TO_INFORMAL_M + 2.0 * STOP_LINK_LENGTH_M + CRUISE_INFORMAL_TO_SIGNAL_M


POLICY_BASELINE = "baseline_stop_before_and_after"
POLICY_OPTIMIZED = "optimized_stop_after_only"

# Sim 4 (Waltermart subset, optimized): multiply modeled dwell seconds before converting to link speeds.
OPTIMIZED_SHORT_DWELL_SCALE = 0.55

SAVE_NETWORK_PNG = True
SHOW_NETWORK_WINDOW = False


def _collect_metrics_row(
    W: World,
    cal: SessionCalibration,
    sheet_name: str,
    policy_tag: str,
    baseline_sim1_informal_rb_to_wm: bool,
    short_dwell_scale: float,
) -> dict[str, object]:
    a = W.analyzer
    att = float(getattr(a, "average_travel_time", -1.0))
    adel = float(getattr(a, "average_delay", -1.0))
    dr = (adel / att) if att > 0 and adel >= 0 else None
    tc = int(getattr(a, "trip_completed", 0))
    ta = int(getattr(a, "trip_all", 0))
    dist = float(getattr(a, "total_distance_traveled", -1.0))
    ttot = float(getattr(a, "total_travel_time", -1.0))
    vavg = (dist / ttot) if ttot > 0 and dist >= 0 else None
    return {
        "session": sheet_name,
        "data_origin": cal.data_origin,
        "policy": policy_tag,
        "informal_curb_rb_to_wm": baseline_sim1_informal_rb_to_wm,
        "short_dwell_scale": short_dwell_scale if short_dwell_scale < 1.0 else "",
        "vol_rb_to_wm": cal.vol_rb_to_wm,
        "vol_wm_to_rb": cal.vol_wm_to_rb,
        "n_rows_calibration_subset": cal.n_rows_calibration_subset,
        "mean_boarding_subset": round(cal.mean_boarding_at_origin_s, 3)
        if cal.mean_boarding_at_origin_s is not None
        else "",
        "mean_alighting_subset": round(cal.mean_alighting_at_origin_s, 3)
        if cal.mean_alighting_at_origin_s is not None
        else "",
        "mean_arrival_rate_subset": round(cal.mean_arrival_rate_at_origin_s, 3)
        if cal.mean_arrival_rate_at_origin_s is not None
        else "",
        "crowding_top_subset": cal.crowding_summary,
        "traffic_top_subset": cal.traffic_condition_summary,
        "bus_companies_top_subset": cal.bus_companies_summary,
        "routes_top_subset": cal.routes_summary,
        "demand_window_s": round(cal.demand_t1_s - cal.demand_t0_s, 1),
        "demand_window_capped": cal.demand_window_capped,
        "avg_travel_time_s": round(att, 2) if att >= 0 else "",
        "avg_delay_s": round(adel, 2) if adel >= 0 else "",
        "delay_ratio": round(dr, 4) if dr is not None else "",
        "completed_trips": tc,
        "total_trips": ta,
        "total_distance_m": round(dist, 1) if dist >= 0 else "",
        "avg_speed_mps": round(vavg, 3) if vavg is not None else "",
    }


def _write_results_csv(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with RESULTS_SUMMARY_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  Results table (all runs): {RESULTS_SUMMARY_CSV}")


def _write_comparison_csv(rows: list[dict[str, object]]) -> None:
    by: dict[tuple[str, str], dict[str, dict]] = {}
    for r in rows:
        sess = str(r["session"])
        origin = str(r.get("data_origin", ""))
        pol = str(r["policy"])
        by.setdefault((sess, origin), {})[pol] = r
    out = []
    for (sess, origin), pols in by.items():
        b = pols.get(POLICY_BASELINE)
        o = pols.get(POLICY_OPTIMIZED)
        if not b or not o:
            continue
        tt_b = b.get("avg_travel_time_s")
        tt_o = o.get("avg_travel_time_s")
        if tt_b == "" or tt_o == "" or tt_b is None or tt_o is None:
            continue
        try:
            tt_bf = float(tt_b)
            tt_of = float(tt_o)
        except (TypeError, ValueError):
            continue
        save = tt_bf - tt_of
        pct = (save / tt_bf * 100.0) if tt_bf else None
        out.append(
            {
                "session": sess,
                "data_origin": origin,
                "baseline_avg_travel_time_s": tt_bf,
                "optimized_avg_travel_time_s": tt_of,
                "time_saved_per_trip_s": round(save, 2),
                "pct_improvement_travel_time": round(pct, 2) if pct is not None else "",
            }
        )
    if not out:
        return
    keys = list(out[0].keys())
    with RESULTS_COMPARISON_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)
    print(f"  Baseline vs optimized summary: {RESULTS_COMPARISON_CSV}")


def _apply_dwell_scale(seconds: float, scale: float) -> float:
    if scale >= 1.0:
        return seconds
    return max(8.0, seconds * scale)


def build_network(
    W: World,
    cal: SessionCalibration,
    *,
    include_stop_before_mid: bool,
    short_dwell_scale: float = 1.0,
):
    """
    include_stop_before_mid=True  : informal curb on RB->WM before signal (when topology includes it).
    include_stop_before_mid=False : no informal curb (optimized path RB->WM).
    short_dwell_scale < 1.0       : shrink all modeled dwells (Sim 4 Waltermart optimized).
    """
    baseline = include_stop_before_mid
    u = FREE_FLOW_MPS
    c_post_wm = _cruise_post_int_to_wm_m()
    rb_to_sig_opt = _rb_road_to_signal_optimized_m()

    dwell_rb = _apply_dwell_scale(float(cal.mean_dwell_rb_s or DEFAULT_DWELL_S), short_dwell_scale)
    dwell_wm = _apply_dwell_scale(float(cal.mean_dwell_wm_s or DEFAULT_DWELL_S), short_dwell_scale)
    dwell_informal_s = _apply_dwell_scale(max(float(cal.mean_dwell_rb_s or DEFAULT_DWELL_S) * 1.12, 45.0), short_dwell_scale)
    u_informal = max(STOP_LINK_LENGTH_M / dwell_informal_s, 0.12)
    dwell_post_s = _apply_dwell_scale(max(float(cal.mean_dwell_rb_s or DEFAULT_DWELL_S) * 0.48, 18.0), short_dwell_scale)
    u_post = max(STOP_LINK_LENGTH_M / dwell_post_s, 0.15)
    u_rb = max(STOP_LINK_LENGTH_M / max(dwell_rb, 5.0), 0.15)
    u_wm = max(STOP_LINK_LENGTH_M / max(dwell_wm, 5.0), 0.15)

    x = 0.0
    rb_stop = W.addNode("Robinsons_BusStop", x, 0.0)
    x += STOP_LINK_LENGTH_M
    rb_road = W.addNode("Robinsons_Road", x, 0.0)

    if baseline:
        x += CRUISE_RB_TO_INFORMAL_M
        inf_entry = W.addNode("Informal_Curb_Entry", x, 0.0)
        x += STOP_LINK_LENGTH_M
        inf_stop = W.addNode("Informal_Curb_RB_to_WM", x, 0.0)
        x += STOP_LINK_LENGTH_M
        inf_exit = W.addNode("Informal_Curb_Exit", x, 0.0)
        x += CRUISE_INFORMAL_TO_SIGNAL_M
    else:
        inf_entry = inf_stop = inf_exit = None
        x += rb_to_sig_opt

    intersection = W.addNode(
        "Aguinaldo_Signal",
        x,
        0.0,
        signal=[SIGNAL_GREEN_EB_S, SIGNAL_GREEN_WB_S],
    )
    x += DIST_INTERSECTION_TO_POSTINT_CRUISE_M
    post_entry = W.addNode("PostIntersection_Road", x, 0.0)
    x += STOP_LINK_LENGTH_M
    post_stop = W.addNode("PostIntersection_BusStop", x, 0.0)
    x += STOP_LINK_LENGTH_M
    post_exit = W.addNode("PostIntersection_Road_Out", x, 0.0)
    x += c_post_wm
    wm_road = W.addNode("Waltermart_Road", x, 0.0)
    x += STOP_LINK_LENGTH_M
    wm_stop = W.addNode("Waltermart_BusStop", x, 0.0)

    W.addLink(
        "RB_Stop_in",
        rb_road,
        rb_stop,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_rb,
        number_of_lanes=STOP_LANES,
    )
    W.addLink(
        "RB_Stop_out",
        rb_stop,
        rb_road,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_rb,
        number_of_lanes=STOP_LANES,
    )

    W.addLink(
        "WM_Stop_in",
        wm_road,
        wm_stop,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_wm,
        number_of_lanes=STOP_LANES,
    )
    W.addLink(
        "WM_Stop_out",
        wm_stop,
        wm_road,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_wm,
        number_of_lanes=STOP_LANES,
    )

    if baseline:
        assert inf_entry is not None and inf_stop is not None and inf_exit is not None
        W.addLink(
            "RB_to_Informal_cruise",
            rb_road,
            inf_entry,
            length=CRUISE_RB_TO_INFORMAL_M,
            free_flow_speed=u,
            number_of_lanes=LANES,
        )
        W.addLink(
            "Informal_Bay_in",
            inf_entry,
            inf_stop,
            length=STOP_LINK_LENGTH_M,
            free_flow_speed=u_informal,
            number_of_lanes=STOP_LANES,
        )
        W.addLink(
            "Informal_Bay_out",
            inf_stop,
            inf_exit,
            length=STOP_LINK_LENGTH_M,
            free_flow_speed=u_informal,
            number_of_lanes=STOP_LANES,
        )
        W.addLink(
            "Informal_to_Signal",
            inf_exit,
            intersection,
            length=CRUISE_INFORMAL_TO_SIGNAL_M,
            free_flow_speed=u,
            number_of_lanes=LANES,
            signal_group=[0],
        )
    else:
        W.addLink(
            "RB_to_Signal",
            rb_road,
            intersection,
            length=rb_to_sig_opt,
            free_flow_speed=u,
            number_of_lanes=LANES,
            signal_group=[0],
        )

    W.addLink(
        "Signal_to_PostInt",
        intersection,
        post_entry,
        length=DIST_INTERSECTION_TO_POSTINT_CRUISE_M,
        free_flow_speed=u,
        number_of_lanes=LANES,
        signal_group=[0],
    )
    W.addLink(
        "PostInt_Bay_in",
        post_entry,
        post_stop,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_post,
        number_of_lanes=STOP_LANES,
        signal_group=[0],
    )
    W.addLink(
        "PostInt_Bay_out",
        post_stop,
        post_exit,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_post,
        number_of_lanes=STOP_LANES,
        signal_group=[0],
    )
    W.addLink(
        "PostInt_to_WM",
        post_exit,
        wm_road,
        length=c_post_wm,
        free_flow_speed=u,
        number_of_lanes=LANES,
        signal_group=[0],
    )

    # Westbound: Waltermart toward Robinsons (no informal).
    W.addLink(
        "WM_to_PostExit",
        wm_road,
        post_exit,
        length=c_post_wm,
        free_flow_speed=u,
        number_of_lanes=LANES,
        signal_group=[1],
    )
    W.addLink(
        "PostInt_Bay_in_WB",
        post_exit,
        post_stop,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_post,
        number_of_lanes=STOP_LANES,
        signal_group=[1],
    )
    W.addLink(
        "PostInt_Bay_out_WB",
        post_stop,
        post_entry,
        length=STOP_LINK_LENGTH_M,
        free_flow_speed=u_post,
        number_of_lanes=STOP_LANES,
        signal_group=[1],
    )
    W.addLink(
        "PostInt_to_Signal",
        post_entry,
        intersection,
        length=DIST_INTERSECTION_TO_POSTINT_CRUISE_M,
        free_flow_speed=u,
        number_of_lanes=LANES,
        signal_group=[1],
    )
    W.addLink(
        "Signal_to_RB",
        intersection,
        rb_road,
        length=rb_to_sig_opt,
        free_flow_speed=u,
        number_of_lanes=LANES,
        signal_group=[1],
    )

    if baseline:
        policy_note = (
            "Baseline: RB->WM informal curb before signal + post-intersection stop + WM; "
            "WM->RB post-intersection + signal only"
        )
    else:
        policy_note = (
            "Optimized: no informal curb; RB->WM signal + post-intersection + WM only; "
            "WM->RB unchanged pattern without informal"
        )

    print(f"  Layout: {policy_note}")
    print(
        f"  Interior RB road to WM road: {TOTAL_CRUISE_RB_ROAD_TO_WM_ROAD_M:.0f} m (3.3 km) "
        f"including post-intersection bay links in chain."
    )
    print(
        f"  Signal cycle: {SIGNAL_GREEN_EB_S + SIGNAL_GREEN_WB_S:.0f} s "
        f"(EB green {SIGNAL_GREEN_EB_S:.0f} s, WB green {SIGNAL_GREEN_WB_S:.0f} s)"
    )
    print(f"  Signal to post-intersection stop cruise: {DIST_INTERSECTION_TO_POSTINT_CRUISE_M:.0f} m")
    print(f"  Post-intersection to WM cruise: {c_post_wm:.0f} m")
    if baseline:
        print(
            f"  Baseline RB->WM before signal: cruise to curb {CRUISE_RB_TO_INFORMAL_M:.0f} m, "
            f"curb bays 50 m, curb to signal {CRUISE_INFORMAL_TO_SIGNAL_M:.0f} m"
        )
        print(
            f"  Informal curb dwell proxy: ~{dwell_informal_s:.0f} s (survey RB mean x1.12, after any scale)"
        )
    else:
        print(f"  Optimized RB->signal cruise (no curb dwell): {rb_to_sig_opt:.0f} m")
    print(
        f"  Post-intersection formal dwell proxy: ~{dwell_post_s:.0f} s | "
        f"Robinsons bay ~{dwell_rb:.0f} s | Waltermart ~{dwell_wm:.0f} s"
    )
    if short_dwell_scale < 1.0:
        print(f"  Short-dwell scale applied: {short_dwell_scale:.2f}")

    return rb_stop, wm_stop


def run_session(
    sheet_name: str,
    *,
    data_origin: DataOrigin,
    include_stop_before_mid: bool,
    policy_tag: str,
    short_dwell_scale: float = 1.0,
    results_rows: list | None = None,
) -> World:
    cal = load_session_stats(sheet_name, data_origin=data_origin)
    print(f"\n{'='*60}")
    print(f"  SESSION: {sheet_name}  |  ORIGIN: {cal.data_origin}  |  POLICY: {policy_tag}")
    print(f"{'='*60}")
    print_calibration(cal)

    safe_sheet = sheet_name.replace(" ", "_")
    safe_name = f"{safe_sheet}_{cal.data_origin}_{policy_tag}"

    W = World(
        name=safe_name,
        print_mode=1,
        tmax=cal.sim_tmax_s,
        save_mode=1,
        show_mode=1 if SHOW_NETWORK_WINDOW else 0,
    )
    origin_rb, dest_wm = build_network(
        W,
        cal,
        include_stop_before_mid=include_stop_before_mid,
        short_dwell_scale=short_dwell_scale,
    )
    W.adddemand(origin_rb, dest_wm, cal.demand_t0_s, cal.demand_t1_s, volume=float(cal.vol_rb_to_wm))
    W.adddemand(dest_wm, origin_rb, cal.demand_t0_s, cal.demand_t1_s, volume=float(cal.vol_wm_to_rb))
    W.exec_simulation()
    W.analyzer.print_simple_stats(force_print=True)
    W.analyzer.link_analysis_coarse()
    print("  Link average travel times (s):")
    for ln in W.LINKS:
        tt = W.analyzer.linkc_tt_ave[ln]
        if tt and tt > 0:
            print(f"    {ln.name}: {tt:.1f} (free {ln.length / ln.u:.1f})")

    if SAVE_NETWORK_PNG:
        W.analyzer.network_average(left_handed=0, figsize=(10, 6), network_font_size=8)
        png = _PROJECT_DIR / f"out{safe_name}" / "network_average.png"
        print(f"  Network figure saved: {png}")
        FIGURES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        fig_dest = FIGURES_OUTPUT_DIR / f"{safe_name}_network_average.png"
        if png.is_file():
            shutil.copy2(png, fig_dest)
            print(f"  Same figure copied to: {fig_dest}")
        else:
            print(f"  WARNING: PNG not found at {png} (check matplotlib install).")

    if results_rows is not None:
        results_rows.append(
            _collect_metrics_row(
                W,
                cal,
                sheet_name,
                policy_tag,
                include_stop_before_mid,
                short_dwell_scale,
            )
        )

    return W


def main():
    os.chdir(_PROJECT_DIR)
    _cruise_post_int_to_wm_m()
    results_rows: list[dict[str, object]] = []
    # (data_origin, informal_baseline, short_dwell_scale, policy_tag) -> 4 runs x 3 sheets = 12 sims
    run_plan: list[tuple[DataOrigin, bool, float, str]] = [
        ("robinsons", True, 1.0, POLICY_BASELINE),
        ("robinsons", False, 1.0, POLICY_OPTIMIZED),
        ("waltermart", True, 1.0, POLICY_BASELINE),
        ("waltermart", False, OPTIMIZED_SHORT_DWELL_SCALE, POLICY_OPTIMIZED),
    ]
    for sh in SESSION_SHEETS:
        for origin, informal, dwell_scale, pol in run_plan:
            run_session(
                sh,
                data_origin=origin,
                include_stop_before_mid=informal,
                policy_tag=pol,
                short_dwell_scale=dwell_scale,
                results_rows=results_rows,
            )
    _write_results_csv(results_rows)
    _write_comparison_csv(results_rows)
    try:
        from visualize_results import generate_figures

        analysis_dir = generate_figures(_PROJECT_DIR)
        print(f"  Analysis charts: {analysis_dir}")
    except Exception as exc:
        print(f"  Analysis charts skipped ({exc}). Run: python visualize_results.py")
    print("\n" + "=" * 60)
    print("  12 runs: 3 session sheets x (Robinsons baseline, Robinsons optimized,")
    print("           Waltermart baseline, Waltermart short-dwell optimized).")
    print("  VISUALS:")
    print(f"    {FIGURES_OUTPUT_DIR}")
    print("  Tune CRUISE_RB_TO_INFORMAL_M, CRUISE_INFORMAL_TO_SIGNAL_M, DIST_INTERSECTION_TO_POSTINT_CRUISE_M on Maps.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
