# UXsim Bus Transport Corridor Simulation

UXsim microsimulation of bus operations on a formal/informal stop corridor (Robinsons–Waltermart, San Agustin). Per-bus scenarios, signal patterns, mixed traffic, and June 2026 field-calibrated Python pipeline.

**Developed by:** Ting Enchong

## Requirements

- Python 3.10+
- [UXsim](https://github.com/UXsim/UXsim)
- `openpyxl`, `pandas`

```powershell
pip install uxsim openpyxl pandas
```

Optional (SUMO comparison): [SUMO](https://eclipse.dev/sumo/) — see `sumo/README.md`.

## Field data

Included in this repo:

- `Bus_Data_Collection_June 2026.xlsx` — San Agustin per-bus field rows (June 2026)

Export field rows to CSV (optional):

```powershell
python simulation_per_vehicle.py --export-only
python simulation_extended.py --export-field-vehicles
```

---

## Quick start

```powershell
cd C:\Users\Enchong\Downloads\simulation

# Default: A_transit only, all 4 signal patterns (G-G, G-R, R-G, R-R)
python simulation_per_vehicle.py

# Smoke test — 1 bus, 1 signal
python simulation_per_vehicle.py --transit-only --limit 1 --single-signal --no-resume

# List every scenario mode and row count
python simulation_per_vehicle.py --list-scenarios
python scenario_catalog.py
```

---

## `simulation_per_vehicle.py` — primary entry (thesis per-bus runs)

Each run = one bus from the workbook × stop policy × signal pattern. Default output: `results_per_bus.csv`, `results_per_bus_stop_detail.csv`.

### Scenario modes (pick at most one)

| Command | Rows (9 buses × 4 signals) | Description |
|---------|---------------------------:|-------------|
| *(default)* | 36 | `A_transit` — all formal + informal stops |
| `--transit-only` | 36 | Same as default |
| `--informal-only` | 36 | Informal curbs only |
| `--formal-only` | 36 | Formal mids only |
| `--optimized-only` | 36 | Formal only, 55% dwell |
| `--optimized-transit-only` | 36 | All stops, 55% dwell (`E_optimized_transit`) |
| `--optimized` | 108 | A + E + D (3 policies) |
| `--policies-only` | 180 | Named policies A–E |
| `--unlisted-stop-only` | 36 | All mapped stops + 1 unlisted curb |
| `--unlisted-stop-all` | 108 | All stops + U0/U1/U2 unlisted |
| `--optimized-unlisted-stop-all` | 108 | U0–U2 at 55% dwell |
| `--partial-informal-only` | 216 | 6 partial informal masks |
| `--driver-service-only` | 180 | Drop-off / brief stop / unlisted |
| `--relocation-only` / `--relocation-all` | 1,116 | 31 relocation (+5 m) masks |
| `--optimized-relocation-all` | 1,116 | Relocation at 55% dwell |
| `--informal-all` | 576 | 16 informal subsets |
| `--formal-all` | 576 | 16 formal subsets |
| `--optimized-informal-all` | 288 | 8 informal @ 55% |
| `--optimized-formal-all` | 288 | 8 formal @ 55% |
| `--optimized-transit-all` / `--optimized-all` | 2,304 | 64 encounter combos @ 55% |
| `--transit-all` | 4,608 | All 128 stop combos |
| `--full-encounter-only` | 4,608 | 128 `X_*` masks |
| `--all-scenarios` | 5,724 | 128 encounter + 31 relocation |
| `--all-possible` | 41,472 | Full grid (1,152 policies) |

### Examples

```powershell
# Core policy comparison
python simulation_per_vehicle.py --transit-only --no-resume
python simulation_per_vehicle.py --informal-only --no-resume
python simulation_per_vehicle.py --formal-only --no-resume
python simulation_per_vehicle.py --optimized --no-resume

# Filter by session or origin
python simulation_per_vehicle.py --transit-only --session "Morning Session"
python simulation_per_vehicle.py --transit-only --origin robinsons
python simulation_per_vehicle.py --transit-only --origin waltermart

# Specific scenarios by ID
python simulation_per_vehicle.py --scenarios A_transit,D_optimized,R_00100
python simulation_per_vehicle.py --scenario-groups policies,relocation

# Custom policy + stop removal
python simulation_per_vehicle.py --policy transit --remove grocery,vista

# Run controls
python simulation_per_vehicle.py --transit-only --limit 3 --single-signal --no-resume
python simulation_per_vehicle.py --transit-only --bus-only
python simulation_per_vehicle.py --transit-only --all-companies
python simulation_per_vehicle.py --transit-only --visual --limit 1 --single-signal
python simulation_per_vehicle.py --transit-only --verbose --limit 1
python simulation_per_vehicle.py --transit-only --output-dir results_by_mode\my_run
python simulation_per_vehicle.py --transit-only --jan18-targets
```

### All flags

| Flag | Purpose |
|------|---------|
| `--export-only` | Export field rows; no simulation |
| `--limit N` | Max buses (0 = all San Agustin rows) |
| `--session` | `Morning Session`, `Lunch`, or `Afternoon Session` |
| `--origin` | `robinsons` or `waltermart` |
| `--single-signal` | G-G only (4× faster) |
| `--no-resume` | Ignore checkpoint; start fresh |
| `--bus-only` | Buses only (no cars/jeeps/motorcycles) |
| `--leg-bus-only` | Short-leg buses only (legacy; underestimates time) |
| `--visual` | Open UXsim animation window |
| `--verbose` | Full terminal output each run |
| `--all-companies` | All companies in workbook (default: San Agustin) |
| `--output-dir DIR` | Write CSVs/checkpoints under `DIR` |
| `--jan18-targets` | Jan 18 on-board calibration instead of June 2026 |
| `--list-scenarios` | Print catalog and exit |

---

## `run_all_scenario_modes.py` — batch all modes

Writes each mode to `results_by_mode/<slug>/`.

```powershell
# List modes, row counts, and output paths (no simulation)
python run_all_scenario_modes.py --manifest

# Run by size tier
python run_all_scenario_modes.py --tier small
python run_all_scenario_modes.py --tier medium
python run_all_scenario_modes.py --tier large
python run_all_scenario_modes.py --tier mega

# One mode by slug
python run_all_scenario_modes.py --mode transit_only
python run_all_scenario_modes.py --mode optimized --single-signal --limit 1

# All modes (~66k UXsim runs — days of compute)
python run_all_scenario_modes.py
```

| Tier | Modes | Approx. rows |
|------|-------|-------------:|
| `small` | 12 modes | 36–216 each |
| `medium` | 6 modes | 288–1,116 |
| `large` | 5 modes | 2,304–5,724 |
| `mega` | `--all-possible` | 41,472 |

---

## `simulation_session_hour.py` — 1-hour mixed session

```powershell
python simulation_session_hour.py --transit-only
python simulation_session_hour.py --all-scenarios
python simulation_session_hour.py --session "Lunch" --optimized
python simulation_session_hour.py --single-signal --figures
python simulation_session_hour.py --list-scenarios
```

Outputs: `results_session_hour.csv`, `results_session_hour_per_bus.csv` (unless `--no-per-vehicle-results`).

---

## `simulation_extended.py` — aggregate corridor study

```powershell
python simulation_extended.py
python simulation_extended.py --all-scenarios --no-resume
python simulation_extended.py --scenario-groups policies,relocation
python simulation_extended.py --scenarios A_transit,D_optimized
python simulation_extended.py --quick --single-signal
python simulation_extended.py --bus-only --figures
python simulation_extended.py --list-scenarios
python simulation_extended.py --list-signals
python simulation_extended.py --export-only
```

Outputs: `results_summary_extended.csv`, `results_baseline_vs_optimized_extended.csv`.

---

## SUMO (optional)

```powershell
cd sumo
python build_sumo_corridor.py
python build_sumo_osm.py
.\run_sumo.ps1
```

See `sumo/README.md` for details.

---

## Generated outputs (not in repo)

These are created when you run simulations (see `.gitignore`):

| Path | Description |
|------|-------------|
| `results_per_bus.csv` | One row per bus × scenario × signal |
| `results_per_bus_stop_detail.csv` | Stop-by-stop timeline |
| `results_per_bus_clean.csv` | Sanitized export |
| `results_by_mode/<slug>/` | Batch runner output |
| `results_summary_extended.csv` | Extended aggregate results |
| `figures_output/` | PNG charts (`--figures`) |
| `*.checkpoint.csv` | Resume checkpoints |

---

## Docs

- `SCENARIO_RUN_GUIDE.md` — scenario IDs and study design
- `SIMULATION_REALISM.md` — calibration and realism notes

## License

Thesis / academic use.
