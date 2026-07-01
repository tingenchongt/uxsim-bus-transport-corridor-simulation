# Simulation realism: UXsim vs SUMO

## What was wrong

1. **Short bus legs** — Mixed mode injected buses stop-to-stop as separate trips (~30 s each), then multiplied by number of stops. That skips stacking **175 s cross-red**, all dwells, and corridor queues in one movement story.
2. **G–G signal scenarios** — Departure time is shifted so buses **arrive on green** (sensitivity case), not “typical red at Pala-Pala.”
3. **Weak Heavy vs Light** — Only a small cruise cap change; jam/congestion was not strong enough.

## What we changed (UXsim)

### Full corridor bus path (`bus_full_corridor=True`, default)

- **Cars / jeepneys / motorcycles / trucks** — Main road + bypass links, hourly flows from field bus anchor × PH composition.
- **Buses** — **Chained through every modeled stop** (same path as field replication), not a single straight OD.
- Per-bus runs use each vehicle’s **traffic** and **crowding** for speed, jam density, and flow scaling.

```text
mixed_full_corridor = background vehicles on road + buses on stop chain
```

Disable (old leg-only behaviour):

```powershell
python simulation_session_hour.py --leg-bus-only
```

### Heavy vs Light traffic (stronger)

| Field traffic | Cruise multiplier | Flow multiplier | Jam density (veh/m) |
|---------------|-------------------|-----------------|---------------------|
| Light | 1.0 | 1.0 | 0.16 |
| Moderate | 0.88 | 0.92 | 0.22 |
| Heavy | 0.68 | 0.78 | 0.32 |
| High | 0.62 | 0.72 | 0.36 |

Heavy/High also use lower link **capacity_in** in UXsim so queues build.

### Lane geometry (field, now in config)

| Direction | Lanes | Chainage from Robinsons |
|-----------|-------|-------------------------|
| Robinsons → Waltermart | **3** | 0 m → **217 m** (Korean grocery + 140 m to Pala-Pala intersection line) |
| Robinsons → Waltermart | **2** | 217 m → Waltermart (7-Eleven through Waltermart) |
| Waltermart → Robinsons | **2** | **355 m** → Waltermart (**2.9 km** from Waltermart terminal) |
| Waltermart → Robinsons | **3** | 0 m → **355 m** (Pala-Pala area through Robinsons) |

GPS pins: `GPS_PALA_INTERSECTION_LINE`, `GPS_WM_RB_LANE_EXPAND` in `corridor_config.py`. UXsim sets `number_of_lanes` per link; SUMO `numLanes` per edge in `sumo/build_sumo_corridor.py`.

### What UXsim still cannot do

| Real world (Vissim / SUMO) | This UXsim corridor |
|----------------------------|---------------------|
| 2D map / OSM geometry | 1D chainage line (~3255 m) |
| Lane changing | Fixed lanes per link (`LANES_MAIN=2`) |
| Turning movements at Pala-Pala | Two-phase signal (main + side) |
| GPS trajectories | Demand + speed caps |

## Real-world map, lanes, lane-changing → use SUMO

The repo includes a **multi-lane SUMO** network built from the corridor (see `sumo/corridor.net.xml` — two lanes per direction, bus stops on lanes, signals).

```powershell
python sumo/build_sumo_corridor.py
cd sumo
sumo-gui -c corridor.sumocfg
```

Use SUMO for **visualisation and lane-level behaviour**; use UXsim for **thesis scenario matrix** (A/B/C/D, R_*, G/R patterns) once calibrated against on-board minutes.

## Recommended runs

```powershell
# Per observed bus, mixed traffic, full stop chain (thesis Study A)
python simulation_per_vehicle.py --optimized --no-resume

# One hour per session — A–D + all R_* relocation (default), full corridor buses
python simulation_session_hour.py --session "Afternoon Session"

# Same with GUI
python simulation_session_hour.py --visual --session "Afternoon Session"

# Policies A–D only (no relocation)
python simulation_session_hour.py --session "Afternoon Session" --policies-only

# Faster subset: baseline vs optimized only (A + D)
python simulation_session_hour.py --session "Afternoon Session" --optimized
```

## Hourly bus demand (1-hour session runs)

Per session and direction (field counts, not the 513 stationary rows):

| Session | Robinsons → Waltermart | Waltermart → Robinsons |
|---------|------------------------|-------------------------|
| Morning | 138 | 57 |
| Lunch | 44 | 83 |
| Afternoon | 106 | 101 |

**513** = individual bus observations in the Dec workbook (Study A per-bus runs).  
**529** = total buses/h if you add both directions (138+57+44+83+106+101).

## How to judge realism

Compare `avg_travel_time_s` or `bus_avg_travel_time_e2e_s` to:

- `onboard_target_travel_s` (Dec workbook / Jan 18: ~660 / 900 / 1140 s)
- `field_observed_travel_s`

If simulated minutes are still far below field, report **policy savings in %** (baseline vs optimized), not absolute “3 minutes to Waltermart.”

For **absolute** clock times, prefer **R–R** or average of four signal patterns, not G–G alone.
