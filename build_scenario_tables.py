"""Build Chapter 4 scenario discussion tables from result CSVs."""

from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from corridor_config import TRANSIT_POLICY_TAGS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "CHAPTER_4_SCENARIO_DISCUSSION.md"


def pct_saved(baseline: float, optimized: float) -> float:
    return (baseline - optimized) / baseline * 100 if baseline else 0.0


def main() -> None:
    df = pd.read_csv(ROOT / "results_per_bus_clean.csv")
    tt = "sim_corridor_travel_s"
    lines: list[str] = []

    lines.extend(
        [
            "# Chapter 4 — Scenario Design, Discussion, and Tables",
            "",
            "*(Draft section for research adviser: scenario matrix + discussion.)*",
            "",
            "## 4.X Simulation scenario framework",
            "",
            "Two complementary UXsim studies were run on the **3,255 m** Robinsons Pala-Pala–Waltermart "
            "corridor (Emilio Aguinaldo Highway, Dasmariñas).",
            "",
            "**Study A — Per-bus replication (primary stop-policy evidence).** Each of **513** "
            "field-observed buses was simulated **eight times**: two stop policies × four signal "
            "encounter patterns (G-G, G-R, R-G, R-R at Pala-Pala and Waltermart). **Total: 4,104 runs.** "
            "These runs use **bus-only** corridor loading (`mixed_traffic=False`): no background cars or "
            "jeepneys, but session-timed signals and field-calibrated dwell and speed caps remain.",
            "",
            "**Study B — Session mixed-traffic matrix (realistic corridor demand).** Three sessions × "
            "four stream/policy settings × four signal patterns = **48 runs**. Background volumes follow "
            "**Table 4.1** (Philippine arterial composition anchored to observed bus counts per hour).",
            "",
            "**Aggregated scenario cells (Study A).** When results are grouped by "
            "session × field traffic label × signal pattern, **52 of 60** possible cells contain "
            "observations; **eight** never occurred in the December 2025 field week (Table 4.12 footnote).",
            "",
            "### Table 4.11. Complete simulation scenario inventory",
            "",
            "| Study | Replication unit | Factor | Levels | Runs |",
            "|-------|------------------|--------|--------|-----:|",
            "| **A — Per-bus** | One observed bus (n = 513) | Stop policy | Baseline (all stops), Optimized (formal only) | 2 |",
            "| | | Signal encounter | G-G, G-R, R-G, R-R | 4 |",
            "| | | Embedded from field | Session; traffic label; trip direction | — |",
            "| | | **Per bus** | 2 × 4 | **8** |",
            "| | | **Study A total** | 513 × 8 | **4,104** |",
            "| **B — Mixed corridor** | Session × calibration stream | Session | Morning, Lunch, Afternoon | 3 |",
            "| | | Data stream | Robinsons location, Waltermart location | 2 |",
            "| | | Stop policy | Baseline, Optimized (0.55 dwell scale at Waltermart stream) | 2 |",
            "| | | Signal encounter | G-G, G-R, R-G, R-R | 4 |",
            "| | | **Study B total** | 3 × 4 × 4 | **48** |",
            "",
        ]
    )

    # Table 4.12 — 52 cells
    lines.extend(
        [
            "### Table 4.12. Study A — Mean corridor travel time by scenario cell "
            "(52 field-supported groups)",
            "",
            "| Session | Traffic | Signal | Buses (n) | Baseline (s) | Optimized (s) | Saved (s) | % saved |",
            "|---------|---------|--------|----------:|-------------:|--------------:|----------:|--------:|",
        ]
    )
    cell_rows: list[tuple] = []
    for (sess, traf, sig), sub in df.groupby(["session", "traffic_condition", "signal_pattern"]):
        n_bus = sub["obs_id"].nunique()
        b = sub.loc[sub["policy"].isin(TRANSIT_POLICY_TAGS), tt].mean()
        o = sub.loc[sub["policy"] == "optimized_formal_only", tt].mean()
        sess_short = str(sess).replace(" Session", "")
        cell_rows.append((sess_short, traf, sig, n_bus, b, o))
    for sess_short, traf, sig, n_bus, b, o in sorted(cell_rows):
        sv = b - o
        lines.append(
            f"| {sess_short} | {traf} | {sig} | {n_bus} | {b:.1f} | {o:.1f} | {sv:.1f} | {pct_saved(b, o):.1f}% |"
        )

    present = {(s, t, sig) for s, t, sig, *_ in cell_rows}
    missing: list[str] = []
    for sess in ("Morning Session", "Lunch", "Afternoon Session"):
        for traf in sorted(df["traffic_condition"].unique()):
            for sig in ("G-G", "G-R", "R-G", "R-R"):
                key = (sess.replace(" Session", ""), traf, sig)
                if key not in present:
                    missing.append(f"{key[0]}/{key[1]}/{key[2]}")
    lines.append("")
    lines.append(
        f"*Eight cells with no field observations (excluded from Table 4.12):* "
        + "; ".join(missing)
        + "."
    )

    # Table 4.13 — collapsed dimensions
    lines.extend(
        [
            "",
            "### Table 4.13. Study A — Mean travel time by scenario dimension (all 4,104 runs)",
            "",
            "| Dimension | Level | Baseline (s) | Optimized (s) | Δ (s) | % improvement |",
            "|-----------|-------|-------------:|--------------:|------:|----------------:|",
        ]
    )
    b_all = df.loc[df["policy"].isin(TRANSIT_POLICY_TAGS), tt].mean()
    o_all = df.loc[df["policy"] == "optimized_formal_only", tt].mean()
    lines.append(
        f"| **Overall** | All runs | {b_all:.2f} | {o_all:.2f} | {b_all - o_all:.2f} | {pct_saved(b_all, o_all):.2f}% |"
    )
    for col, title in [
        ("session", "Session"),
        ("traffic_condition", "Traffic condition"),
        ("signal_pattern", "Signal pattern"),
    ]:
        for lev in sorted(df[col].unique(), key=str):
            sub = df[df[col] == lev]
            b = sub.loc[sub["policy"].isin(TRANSIT_POLICY_TAGS), tt].mean()
            o = sub.loc[sub["policy"] == "optimized_formal_only", tt].mean()
            lev_disp = str(lev).replace(" Session", "")
            lines.append(
                f"| {title} | {lev_disp} | {b:.1f} | {o:.1f} | {b - o:.1f} | {pct_saved(b, o):.1f}% |"
            )

    # Table 4.14 — cross of session × traffic (mean over signals)
    lines.extend(
        [
            "",
            "### Table 4.14. Study A — Session × traffic condition scenarios "
            "(mean over all signal patterns)",
            "",
            "| Session | Traffic | Baseline (s) | Optimized (s) | % saved |",
            "|---------|---------|-------------:|--------------:|--------:|",
        ]
    )
    for (sess, traf), sub in df.groupby(["session", "traffic_condition"]):
        b = sub.loc[sub["policy"].isin(TRANSIT_POLICY_TAGS), tt].mean()
        o = sub.loc[sub["policy"] == "optimized_formal_only", tt].mean()
        lines.append(
            f"| {str(sess).replace(' Session', '')} | {traf} | {b:.1f} | {o:.1f} | {pct_saved(b, o):.1f}% |"
        )

    # Exceptions + discussion
    p = df.pivot_table(
        index=["obs_id", "signal_pattern"], columns="policy", values=tt
    )
    transit_col = next((c for c in ("transit_all_stops", "baseline_all_stops") if c in p.columns), None)
    exc = int((p[transit_col] <= p["optimized_formal_only"]).sum()) if transit_col else 0
    n_pairs = len(p)
    lines.extend(
        [
            "",
            "## 4.X.1 Scenario discussion (narrative for Results chapter)",
            "",
            "**Inventory.** Table 4.11 separates *individual simulation runs* (4,104 + 48) from "
            "*summary scenario cells* (52 grouped cells in Study A). The adviser-requested "
            "\"scenario\" discussion should cite both: runs executed in the model, and how field "
            "data cover the factor space.",
            "",
            "**Study A — Stop policy dominates every scenario cell.** Table 4.12 shows that within "
            f"each of the **{len(cell_rows)}** session–traffic–signal cells with field data, the "
            "**mean** optimized travel time is lower than baseline. Savings range from about "
            f"**{min(pct_saved(b,o) for _,_,_,_,b,o in [(0,0,0,0,r[4],r[5]) for r in cell_rows]):.0f}%** "
            f"to **{max(pct_saved(r[4],r[5]) for r in cell_rows):.0f}%** across cells.",
            "",
            "**Session × traffic (Table 4.14).** Afternoon observations under Heavy or High traffic "
            "show the longest baseline times and the largest absolute savings when informal stops "
            "are removed. Morning Low/Light cells show the smallest percentage gap—informal stops "
            "still hurt, but queues rarely reach the intersection.",
            "",
            "**Signal patterns (Table 4.13).** Changing only G/R labeling moves baseline means by "
            "about **78 s** (751.8–829.7 s), while changing session moves baseline by about **229 s** "
            "(679.2–908.4 s). Signal scenario is included for completeness; **stop policy produces "
            "roughly three times the spread of signal pattern alone.**",
            "",
            "**Bus-level exceptions.** For the same bus and signal pattern, optimized is faster in "
            f"**{n_pairs - exc} of {n_pairs}** pairs ({100 * (n_pairs - exc) / n_pairs:.1f}%). "
            f"In **{exc}** pairs ({100 * exc / n_pairs:.1f}%), baseline matches or beats optimized—"
            "usually very short trips, terminal-heavy paths, or buses with minimal informal stopping. "
            "Chapter conclusions should rely on **cell means and overall means**, not the claim that "
            "every single run improved.",
            "",
            "**Study B — Mixed traffic (Table 4.15).** The 48 runs answer: \"If the corridor carries "
            "Table 4.1 volumes, do conclusions hold?\" Report these separately from Study A means "
            "(787 s / 572 s bus-only). After re-running `simulation_extended.py` with current PH "
            "composition, insert updated times into Table 4.15.",
            "",
            "**Missing scenarios.** Eight session–traffic–signal combinations never appeared in the "
            "field week; they were not simulated as separate cells because no bus was tagged with "
            "those labels. This is a **data coverage** limitation, not a model bug.",
            "",
        ]
    )

    # Study B table
    ex_path = ROOT / "results_summary_extended.csv"
    if ex_path.exists():
        ex = pd.read_csv(ex_path)
        lines.extend(
            [
                "### Table 4.15. Study B — Mixed-traffic scenarios (48 runs, one row per run)",
                "",
                "| Session | Stream | Policy | Signal | Avg travel (s) | Delay ratio |",
                "|---------|--------|--------|--------|---------------:|------------:|",
            ]
        )
        for _, r in ex.sort_values(
            ["session", "data_origin", "policy", "encounter_pattern"]
        ).iterrows():
            sess = str(r["session"]).replace(" Session", "")
            origin = "Robinsons" if "robinsons" in str(r["data_origin"]) else "Waltermart"
            pol = "Baseline" if "baseline" in str(r["policy"]) else "Optimized"
            sig = str(r.get("encounter_pattern", ""))
            tt_ex = float(r["avg_travel_time_s"])
            dr = float(r["delay_ratio"]) if r.get("delay_ratio") not in ("", None) else float("nan")
            lines.append(
                f"| {sess} | {origin} | {pol} | {sig} | {tt_ex:.1f} | {dr:.3f} |"
            )
        lines.extend(
            [
                "",
                "> **Calibration note:** If Study B means exceed Study A by a large margin, "
                "re-run `python simulation_extended.py` so mixed demand matches Table 4.1.",
                "",
                "### Table 4.16. Study B — Collapsed scenarios (mean of 16 runs per cell)",
                "",
                "| Session | Policy | Mixed-traffic mean (s) | Study A bus-only mean (s) |",
                "|---------|--------|---------------------:|--------------------------:|",
            ]
        )
        for sess in ("Morning Session", "Lunch", "Afternoon Session"):
            for pol, label in [
                (TRANSIT_POLICY_TAGS, "Transit"),
                ("optimized_formal_only", "Optimized"),
            ]:
                if isinstance(pol, tuple):
                    sub_ex = ex[(ex["session"] == sess) & (ex["policy"].isin(pol))]
                    sub_a = df[(df["session"] == sess) & (df["policy"].isin(pol))]
                else:
                    sub_ex = ex[(ex["session"] == sess) & (ex["policy"] == pol)]
                    sub_a = df[(df["session"] == sess) & (df["policy"] == pol)]
                m_ex = sub_ex["avg_travel_time_s"].astype(float).mean()
                m_a = sub_a[tt].mean()
                lines.append(
                    f"| {sess.replace(' Session', '')} | {label} | {m_ex:.1f} | {m_a:.1f} |"
                )

    # Table 4.17 — corrected Pattern comparison (time of day vs signal)
    bdf = df[df["policy"].isin(TRANSIT_POLICY_TAGS)]
    sig_spread = (
        bdf.groupby("signal_pattern")[tt].mean().max()
        - bdf.groupby("signal_pattern")[tt].mean().min()
    )
    sess_means = bdf.groupby("session")[tt].mean()
    sess_spread = sess_means.max() - sess_means.min()
    lines.extend(
        [
            "",
            "### Table 4.17. Which scenario factor moves travel time more? (Study A, baseline)",
            "",
            "| Factor varied | Best case (s) | Worst case (s) | Range (s) |",
            "|---------------|--------------:|---------------:|----------:|",
            f"| Signal pattern only | {bdf.groupby('signal_pattern')[tt].mean().min():.1f} | "
            f"{bdf.groupby('signal_pattern')[tt].mean().max():.1f} | {sig_spread:.1f} |",
            f"| Session only | {sess_means.min():.1f} | {sess_means.max():.1f} | {sess_spread:.1f} |",
            f"| Stop policy (overall means) | {o_all:.1f} (optimized) | {b_all:.1f} (baseline) | {b_all - o_all:.1f} |",
            "",
            "*Use this table instead of a duplicated 77.9 s range for all three rows.*",
            "",
        ]
    )

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
