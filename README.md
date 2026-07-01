# UXsim Bus Transport Corridor Simulation

UXsim microsimulation of bus operations on a formal/informal stop corridor (Robinsons–Waltermart, San Agustin). Per-bus scenarios, signal patterns, mixed traffic, and June 2026 field-calibrated Python pipeline.

**Developed by:** Enchong *(replace with your full name if needed)*

## Requirements

- Python 3.10+
- [UXsim](https://github.com/UXsim/UXsim)
- `openpyxl`, `pandas` (for field workbook and exports)

```powershell
pip install uxsim openpyxl pandas
```

## Field data (not in this repo)

Place this file in the project root:

- `Bus_Data_Collection_June 2026.xlsx`

Then export field rows (optional):

```powershell
python simulation_per_vehicle.py --export-only
```

## Quick start

```powershell
cd simulation
python simulation_per_vehicle.py --transit-only
python simulation_per_vehicle.py --informal-only --no-resume
python simulation_per_vehicle.py --optimized --no-resume
```

Smoke test (1 bus, 1 signal):

```powershell
python simulation_per_vehicle.py --informal-only --limit 1 --single-signal --no-resume
```

List all scenario modes:

```powershell
python simulation_per_vehicle.py --list-scenarios
```

Batch run (separate output folder per mode):

```powershell
python run_all_scenario_modes.py --manifest
python run_all_scenario_modes.py --tier small
```

## Main entry points

| Script | Purpose |
|--------|---------|
| `simulation_per_vehicle.py` | Thesis per-bus runs (primary) |
| `simulation_session_hour.py` | 1-hour mixed session runs |
| `simulation_extended.py` | Extended aggregate study |
| `run_all_scenario_modes.py` | Batch all scenario modes → `results_by_mode/` |

## Outputs (generated locally)

- `results_per_bus.csv` — one row per bus × scenario × signal
- `results_per_bus_stop_detail.csv` — stop-by-stop timeline
- `results_by_mode/<slug>/` — batch runner output

## Scenario flags (pick one)

| Flag | Description |
|------|-------------|
| `--transit-only` | All formal + informal stops (default) |
| `--informal-only` | Informal curbs only |
| `--formal-only` | Formal mids only |
| `--optimized-only` | Formal only, 55% dwell |
| `--optimized` | A + E + D comparison |

See `SCENARIO_RUN_GUIDE.md` for the full list.

## License

Thesis / academic use. Field workbook remains separate and is not distributed in this repository.
