"""
Build charts from results_summary.csv and results_baseline_vs_optimized.csv.

Run after: python simulation.py
Or standalone: python visualize_results.py
"""

from __future__ import annotations

import csv
from pathlib import Path

# Match simulation.py policy tags
POLICY_BASELINE = "baseline_stop_before_and_after"
POLICY_OPTIMIZED = "optimized_stop_after_only"

_SESSION_SHORT = {
    "Morning Session": "Morning",
    "Lunch": "Lunch",
    "Afternoon Session": "Afternoon",
}


def _short_session(name: str) -> str:
    return _SESSION_SHORT.get(name, name.replace(" Session", ""))


def _load_summary_rows(summary_path: Path) -> list[dict[str, str]]:
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing {summary_path}. Run python simulation.py first.")
    with summary_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_comparison_rows(comp_path: Path) -> list[dict[str, str]]:
    if not comp_path.is_file():
        return []
    with comp_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _pick_tt(rows: list[dict], session: str, origin: str, policy: str) -> float | None:
    for r in rows:
        if r.get("session") == session and r.get("data_origin") == origin and r.get("policy") == policy:
            try:
                return float(r["avg_travel_time_s"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _pick_metric(rows: list[dict], session: str, origin: str, policy: str, key: str) -> float | None:
    for r in rows:
        if r.get("session") == session and r.get("data_origin") == origin and r.get("policy") == policy:
            try:
                v = r.get(key, "")
                if v == "":
                    return None
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def generate_figures(project_dir: Path | None = None) -> Path:
    project_dir = project_dir or Path(__file__).resolve().parent
    summary_path = project_dir / "results_summary.csv"
    comp_path = project_dir / "results_baseline_vs_optimized.csv"
    out_dir = project_dir / "figures_output" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = _load_summary_rows(summary_path)
    comp_rows = _load_comparison_rows(comp_path)

    sessions_order = ("Morning Session", "Lunch", "Afternoon Session")
    x_labels = [_short_session(s) for s in sessions_order]
    x = range(len(sessions_order))
    width = 0.35

    def travel_bars(origin_key: str, title_suffix: str, fname: str) -> None:
        base_vals: list[float] = []
        opt_vals: list[float] = []
        for s in sessions_order:
            b = _pick_tt(rows, s, origin_key, POLICY_BASELINE)
            o = _pick_tt(rows, s, origin_key, POLICY_OPTIMIZED)
            base_vals.append(b if b is not None else 0.0)
            opt_vals.append(o if o is not None else 0.0)

        fig, ax = plt.subplots(figsize=(9, 5))
        bars1 = ax.bar([i - width / 2 for i in x], base_vals, width, label="Baseline", color="#2c5282")
        bars2 = ax.bar([i + width / 2 for i in x], opt_vals, width, label="Optimized", color="#38a169")
        ax.set_ylabel("Average travel time (s)")
        ax.set_title(f"Average travel time by period — {title_suffix}")
        ax.set_xticks(list(x))
        ax.set_xticklabels(x_labels)
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / fname, dpi=150)
        plt.close(fig)

    travel_bars("robinsons_location", "Robinsons-location calibration", "travel_time_robinsons.png")
    travel_bars("waltermart_location", "Waltermart-location calibration", "travel_time_waltermart.png")

    # Delay comparison (Robinsons subset)
    fig, ax = plt.subplots(figsize=(9, 5))
    d_base = []
    d_opt = []
    for s in sessions_order:
        d_base.append(_pick_metric(rows, s, "robinsons_location", POLICY_BASELINE, "avg_delay_s") or 0.0)
        d_opt.append(_pick_metric(rows, s, "robinsons_location", POLICY_OPTIMIZED, "avg_delay_s") or 0.0)
    ax.bar([i - width / 2 for i in x], d_base, width, label="Baseline", color="#2c5282")
    ax.bar([i + width / 2 for i in x], d_opt, width, label="Optimized", color="#38a169")
    ax.set_ylabel("Average delay (s)")
    ax.set_title("Average delay by period (Robinsons-location runs)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(x_labels)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "delay_robinsons.png", dpi=150)
    plt.close(fig)

    # Percent improvement from comparison CSV
    if comp_rows:

        def _pct(session: str, origin: str) -> float:
            for r in comp_rows:
                if r.get("session") == session and r.get("data_origin") == origin:
                    try:
                        v = r.get("pct_improvement_travel_time", "")
                        if v != "":
                            return float(v)
                    except (TypeError, ValueError):
                        pass
            return 0.0

        fig, ax = plt.subplots(figsize=(9, 5))
        rb_pct = [_pct(s, "robinsons_location") for s in sessions_order]
        wm_pct = [_pct(s, "waltermart_location") for s in sessions_order]
        ax.bar([i - width / 2 for i in x], rb_pct, width, label="Robinsons subset", color="#553c9a")
        ax.bar([i + width / 2 for i in x], wm_pct, width, label="Waltermart subset", color="#c05621")
        ax.set_ylabel("Improvement in avg travel time (%)")
        ax.set_title("Optimized vs baseline — percent reduction in average travel time")
        ax.set_xticks(list(x))
        ax.set_xticklabels(x_labels)
        ax.legend()
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "pct_travel_time_improvement.png", dpi=150)
        plt.close(fig)

    # Overview: all 12 runs travel time (horizontal bar chart)
    fig, ax = plt.subplots(figsize=(10, 7))
    labels: list[str] = []
    vals: list[float] = []
    colors: list[str] = []
    palette = {"baseline": "#2c5282", "optimized": "#38a169"}
    for s in sessions_order:
        for origin, oshort in (("robinsons_location", "RB"), ("waltermart_location", "WM")):
            for pol, pshort in ((POLICY_BASELINE, "base"), (POLICY_OPTIMIZED, "opt")):
                tt = _pick_tt(rows, s, origin, pol)
                if tt is None:
                    continue
                labels.append(f"{_short_session(s)} {oshort} {pshort}")
                vals.append(tt)
                colors.append(palette["baseline"] if pol == POLICY_BASELINE else palette["optimized"])
    y_pos = range(len(labels))
    ax.barh(list(y_pos), vals, color=colors)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Average travel time (s)")
    ax.set_title("All 12 runs — average travel time")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "travel_time_all_runs.png", dpi=150)
    plt.close(fig)

    return out_dir


def main() -> None:
    out = generate_figures()
    print(f"Saved analysis figures to: {out}")
    for p in sorted(out.glob("*.png")):
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
