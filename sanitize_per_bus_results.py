"""
Clean results_per_bus*.csv: drop corrupt rows, dedupe, UTF-8 BOM for Excel.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

VALID_STOP_KINDS = frozenset({"formal", "informal", "terminal_formal", "signal"})
VALID_SIGNALS = frozenset({"G-G", "G-R", "R-G", "R-R"})
VALID_TRAFFIC = frozenset({"Light", "Moderate", "Heavy"})
VALID_CROWDING = frozenset({"Low", "Medium", "High"})

# Legacy column renamed for thesis clarity
_TRIP_COLUMN_ALIASES = {
    "field_onboard_dest_travel_min": "session_onboard_reference_min_jan18",
    "field_onboard_speed_band_kmh": "session_speed_band_kmh_jan18",
}


def _is_obs_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", str(value).strip()))


def _dedupe_rows(rows: list[dict[str, str]], key_fields: tuple[str, ...]) -> list[dict[str, str]]:
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in key_fields)
        seen[key] = row
    return list(seen.values())


def _scenario_key(row: dict[str, str]) -> str:
    mode = (row.get("traffic_mode") or "").strip()
    scen = (row.get("scenario_id") or row.get("policy") or "").strip()
    return f"{mode}:{scen}" if mode else scen


def sanitize_stop_detail(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    good: list[dict[str, str]] = []
    for row in rows:
        if not _is_obs_id(row.get("obs_id", "")):
            continue
        kind = (row.get("stop_kind") or "").strip()
        if kind not in VALID_STOP_KINDS:
            continue
        if (row.get("signal_pattern") or "").strip() not in VALID_SIGNALS:
            continue
        if not (row.get("stop_key") or "").strip():
            continue
        good.append(row)
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in good:
        key = (
            str(row.get("obs_id", "")),
            _scenario_key(row),
            str(row.get("signal_pattern", "")),
            str(row.get("stop_sequence", "")),
            str(row.get("stop_key", "")),
        )
        seen[key] = row
    return list(seen.values())


def _normalize_trip_row(row: dict[str, str]) -> dict[str, str]:
    from corridor_config import normalize_crowding_label, normalize_traffic_label

    out = dict(row)
    for old, new in _TRIP_COLUMN_ALIASES.items():
        if old in out and new not in out:
            out[new] = out[old]
    if out.get("traffic_condition"):
        out["traffic_condition"] = normalize_traffic_label(str(out["traffic_condition"]))
    if out.get("crowding_level"):
        out["crowding_level"] = normalize_crowding_label(str(out["crowding_level"]))
    return out


def sanitize_trip_summary(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    good: list[dict[str, str]] = []
    for row in rows:
        row = _normalize_trip_row(row)
        if not _is_obs_id(row.get("obs_id", "")):
            continue
        if (row.get("signal_pattern") or "").strip() not in VALID_SIGNALS:
            continue
        if (row.get("traffic_condition") or "").strip() not in VALID_TRAFFIC:
            continue
        if (row.get("crowding_level") or "").strip() not in VALID_CROWDING:
            continue
        travel = row.get("sim_corridor_travel_min")
        if travel:
            try:
                if float(travel) < 2.0 and str(row.get("signal_pattern", "")).startswith("R"):
                    continue
            except ValueError:
                pass
        if not row.get("session_onboard_reference_note"):
            row["session_onboard_reference_note"] = (
                "Jan 18 on-board session average to destination; not this bus measured time"
            )
        good.append(row)
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in good:
        key = (str(row.get("obs_id", "")), _scenario_key(row), str(row.get("signal_pattern", "")))
        seen[key] = row
    return list(seen.values())


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def main() -> None:
    root = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Sanitize per-bus result CSVs for Excel")
    p.add_argument("--trip", type=Path, default=root / "results_per_bus.csv")
    p.add_argument("--stops", type=Path, default=root / "results_per_bus_stop_detail.csv")
    p.add_argument("--out-trip", type=Path, default=root / "results_per_bus_clean.csv")
    p.add_argument("--out-stops", type=Path, default=root / "results_per_bus_stop_detail_clean.csv")
    p.add_argument("--in-place", action="store_true", help="Overwrite source files")
    args = p.parse_args()

    trip_rows: list[dict[str, str]] = []
    if args.trip.is_file():
        with args.trip.open(newline="", encoding="utf-8-sig") as f:
            trip_rows = list(csv.DictReader(f))
        clean_trip = sanitize_trip_summary(trip_rows)
        trip_fields = list(trip_rows[0].keys()) if trip_rows else []
        out_trip = args.trip if args.in_place else args.out_trip
        _write_csv(out_trip, clean_trip, trip_fields)
        print(f"Trips: {len(trip_rows)} raw -> {len(clean_trip)} clean -> {out_trip}")

    stop_rows: list[dict[str, str]] = []
    if args.stops.is_file():
        with args.stops.open(newline="", encoding="utf-8-sig") as f:
            stop_rows = list(csv.DictReader(f))
        clean_stops = sanitize_stop_detail(stop_rows)
        stop_fields = list(stop_rows[0].keys()) if stop_rows else []
        out_stops = args.stops if args.in_place else args.out_stops
        _write_csv(out_stops, clean_stops, stop_fields)
        print(f"Stops: {len(stop_rows)} raw -> {len(clean_stops)} clean -> {out_stops}")


if __name__ == "__main__":
    main()
