# Scenario catalog — how to run

## Scenario definitions (35 total)

| Group | IDs | Count |
|-------|-----|------:|
| **Policy** | `A_baseline`, `B_informal_only`, `C_formal_only`, `D_optimized` | 4 |
| **Relocation** | `R_00001` … `R_11111` (5-bit mask, formal only, +5 m per `1`) | 31 |

Relocatable stops (S1–S5): `robinsons`, `rkp_trading`, `villa_verde`, `vista_mall`, `waltermart`

List all: `python scenario_catalog.py` or `python simulation_per_vehicle.py --list-scenarios`

## Study A — per-bus (`simulation_per_vehicle.py`)

```powershell
# Default (same as before): A + D, 4 signals, 513 buses → 4,104 runs
python simulation_per_vehicle.py --optimized

# All policies A–D only → 8,208 runs
python simulation_per_vehicle.py --scenario-groups policies

# One relocation example (Villa Verde +5 m)
python simulation_per_vehicle.py --scenarios R_00100 --limit 5

# Everything (35 × 4 × 513 = 71,820 runs)
python simulation_per_vehicle.py --all-scenarios --no-resume

# Policies + relocations
python simulation_per_vehicle.py --scenario-groups policies,relocation --no-resume
```

## Study B — mixed traffic (`simulation_extended.py`)

```powershell
# Default: A + D, 48 runs (3 sessions × 2 streams × 2 policies × 4 signals)
python simulation_extended.py

# All 35 scenarios × 48 structure → 1,680 runs
python simulation_extended.py --all-scenarios

# Relocation only (31 × 48 = 1,488 runs)
python simulation_extended.py --scenario-groups relocation
```

## Output columns (new)

- `scenario_id` — e.g. `A_baseline`, `R_00100`
- `scenario_group` — `policy` or `relocation`
- `relocate_mask` — 5-bit string for S1–S5 (e.g. `00100` = Villa Verde shifted)
- `corridor_length_m` — extended when Waltermart terminal is shifted

## Module

Logic lives in `scenario_catalog.py`; network shifts use `chainage_overrides` in `build_corridor_network()`.
