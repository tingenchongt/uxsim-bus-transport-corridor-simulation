# SUMO — Robinsons to Waltermart (3255 m)

Aligned with `corridor_config.py`: two traffic signals (session-timed cycles).

| Signal | Chainage | GPS |
|--------|----------|-----|
| Pala-Pala | ~237 m | 14.30245, 120.95427 |
| Waltermart intersection | ~2955 m | 14.32556, 120.94083 |

## Install SUMO

https://eclipse.dev/sumo/ — set `SUMO_HOME` and add `%SUMO_HOME%\bin` to PATH.

## Build

```powershell
python sumo/build_sumo_corridor.py
```

## Run

```powershell
cd sumo
sumo-gui -c corridor.sumocfg
```

Outputs: `output/tripinfo.xml`, `output/summary.xml`.

**Note:** Schematic 1D chainage network (matches UXsim). Not the same engine as UXsim — compare results separately.
