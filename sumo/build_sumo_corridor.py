"""
Generate SUMO network + demand for Robinsons–Waltermart corridor (aligned with corridor_config.py).

Run from project root:
  python sumo/build_sumo_corridor.py

If SUMO is installed (SUMO_HOME / PATH), runs netconvert to build corridor.net.xml.
Otherwise writes nodes + edges for manual: netconvert -n corridor.nod.xml -e corridor.edg.xml -o corridor.net.xml
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corridor_config import (  # noqa: E402
    CORRIDOR_LENGTH_M,
    CORRIDOR_SIGNALS,
    FREE_FLOW_MPS,
    GPS_ORIGIN_RB,
    SESSION_DEMAND,
    SESSIONS,
    STOPS_RB_TO_WM,
    main_road_lanes_for_segment,
    signal_cycle_seconds,
    signal_green_times,
)

SUMO_DIR = Path(__file__).resolve().parent
SPEED_KMH = FREE_FLOW_MPS * 3.6
SIM_END_S = 3600
# Offset between EB and WB centerlines (meters) — visible dual carriageway in sumo-gui
CARRIAGEWAY_OFFSET_M = 14.0
LANE_WIDTH_M = 3.25
NUM_LANES = 2  # fallback when chainage unknown

# Chainage → WGS84 for centerline (Dec 2025 field GPS)
GPS_CENTERLINE: list[tuple[float, float, float]] = [
    (0.0, 14.300037, 120.954412),
    (77.0, 14.300720, 120.954320),
    (237.0, 14.302125, 120.954055),
    (277.0, 14.301972, 120.954139),
    (355.0, 14.303230, 120.954053),
    (1250.0, 14.3149, 120.9450),
    (2255.0, 14.31687, 120.94415),
    (2955.0, 14.322364, 120.941649),
    (2995.0, 14.322737, 120.941631),
    (3255.0, 14.324939, 120.940955),
]


def _load_centerline() -> list[tuple[float, float, float]]:
    """Use OSM/Google corridor polyline when build_sumo_osm.py has been run."""
    cl = SUMO_DIR / "corridor_centerline.json"
    if not cl.is_file():
        return GPS_CENTERLINE
    data = json.loads(cl.read_text(encoding="utf-8"))
    wps = data.get("waypoints", [])
    if len(wps) < 2:
        return GPS_CENTERLINE
    out: list[tuple[float, float, float]] = []
    for wp in wps:
        c = float(wp["chainage_m"])
        lat, lon = float(wp["lat"]), float(wp["lon"])
        out.append((c, lat, lon))
    # Resample to ~25 points max for clean junctions
    if len(out) > 25:
        step = max(len(out) // 22, 1)
        out = [out[0]] + out[step:-1:step] + [out[-1]]
    return out


def _pretty_write(path: Path, root: ET.Element) -> None:
    rough = ET.tostring(root, encoding="unicode")
    doc = minidom.parseString(rough)
    path.write_text(doc.toprettyxml(indent="  "), encoding="utf-8")


def _latlon_to_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    from math import cos, radians

    r = 6371000.0
    x = r * cos(radians(lat0)) * radians(lon - lon0)
    y = r * radians(lat - lat0)
    return x, y


def _chainage_to_latlon(chainage_m: float) -> tuple[float, float]:
    pts = _load_centerline()
    max_c = pts[-1][0]
    if max_c > 1.0 and abs(max_c - CORRIDOR_LENGTH_M) > 50.0:
        chainage_m = chainage_m * (max_c / CORRIDOR_LENGTH_M)
    if chainage_m <= pts[0][0]:
        return pts[0][1], pts[0][2]
    if chainage_m >= pts[-1][0]:
        return pts[-1][1], pts[-1][2]
    for i in range(len(pts) - 1):
        c0, lat0, lon0 = pts[i]
        c1, lat1, lon1 = pts[i + 1]
        if c0 <= chainage_m <= c1:
            t = (chainage_m - c0) / (c1 - c0) if c1 > c0 else 0.0
            return lat0 + t * (lat1 - lat0), lon0 + t * (lon1 - lon0)
    return pts[-1][1], pts[-1][2]


def _offset_point(
    x: float, y: float, x_prev: float, y_prev: float, x_next: float, y_next: float, dist: float
) -> tuple[float, float]:
    from math import hypot

    dx = x_next - x_prev
    dy = y_next - y_prev
    length = hypot(dx, dy)
    if length < 1e-6:
        return x, y + dist
    nx, ny = -dy / length, dx / length
    return x + nx * dist, y + ny * dist


def _milestones() -> list[tuple[float, str, str]]:
    items: list[tuple[float, str, str]] = []
    for s in STOPS_RB_TO_WM:
        items.append((s.chainage_m, "stop", s.key))
    for sig in CORRIDOR_SIGNALS:
        items.append((sig.chainage_m, "signal", sig.key))
    by_c: dict[float, tuple[str, str]] = {}
    for c, k, key in sorted(items):
        if c in by_c and by_c[c][0] == "signal":
            continue
        by_c[c] = (k, key)
    return sorted((c, k, key) for c, (k, key) in by_c.items())


def _find_netconvert() -> str | None:
    home = os.environ.get("SUMO_HOME", "")
    if home:
        exe = Path(home) / "bin" / ("netconvert.exe" if sys.platform == "win32" else "netconvert")
        if exe.is_file():
            return str(exe)
    return shutil.which("netconvert")


def _node_positions(
    ms: list[tuple[float, str, str]],
) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Centerline from GPS; EB/WB offset perpendicular (dual carriageway)."""
    lat0, lon0 = GPS_ORIGIN_RB
    center: list[tuple[str, float, float]] = []
    for chain, _kind, key in ms:
        lat, lon = _chainage_to_latlon(chain)
        x, y = _latlon_to_xy(lat, lon, lat0, lon0)
        center.append((key, x, y))

    eb_pos: dict[str, tuple[float, float]] = {}
    wb_pos: dict[str, tuple[float, float]] = {}
    half = CARRIAGEWAY_OFFSET_M / 2.0
    for i, (key, x, y) in enumerate(center):
        if i == 0:
            xp, yp = center[0][1], center[0][2]
        else:
            xp, yp = center[i - 1][1], center[i - 1][2]
        if i + 1 < len(center):
            xn, yn = center[i + 1][1], center[i + 1][2]
        else:
            xn, yn = center[i][1], center[i][2]
        eb_pos[key] = _offset_point(x, y, xp, yp, xn, yn, half)
        wb_pos[key] = _offset_point(x, y, xp, yp, xn, yn, -half)
    return eb_pos, wb_pos


def build_nod_edg(
    nod_path: Path,
    edg_path: Path,
) -> tuple[list[str], list[str], list[tuple[float, str, str]], dict[str, tuple[float, float]]]:
    ms = _milestones()
    signal_keys = {s.key for s in CORRIDOR_SIGNALS}
    eb_pos, wb_pos = _node_positions(ms)

    nod = ET.Element("nodes")
    for _chain, _kind, key in ms:
        ntype = "traffic_light" if key in signal_keys else "priority"
        ex, ey = eb_pos[key]
        ET.SubElement(
            nod,
            "node",
            attrib={
                "id": f"n_eb_{key}",
                "x": f"{ex:.2f}",
                "y": f"{ey:.2f}",
                "type": ntype if key in signal_keys else "priority",
            },
        )
        wx, wy = wb_pos[key]
        ET.SubElement(
            nod,
            "node",
            attrib={
                "id": f"n_wb_{key}",
                "x": f"{wx:.2f}",
                "y": f"{wy:.2f}",
                "type": ntype if key in signal_keys else "priority",
            },
        )
    _pretty_write(nod_path, nod)

    def _shape(a: str, b: str, pos: dict[str, tuple[float, float]]) -> str:
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        return f"{x0:.2f},{y0:.2f} {x1:.2f},{y1:.2f}"

    edg = ET.Element("edges")
    eb_edges: list[str] = []
    for i in range(len(ms) - 1):
        a, b = ms[i][2], ms[i + 1][2]
        c0, c1 = ms[i][0], ms[i + 1][0]
        eb_lanes = main_road_lanes_for_segment(c0, c1, "rb_to_wm")
        eid = f"eb_{a}__{b}"
        eb_edges.append(eid)
        ET.SubElement(
            edg,
            "edge",
            attrib={
                "id": eid,
                "from": f"n_eb_{a}",
                "to": f"n_eb_{b}",
                "numLanes": str(eb_lanes),
                "speed": f"{SPEED_KMH:.2f}",
                "priority": "3",
                "shape": _shape(a, b, eb_pos),
            },
        )

    wb_edges: list[str] = []
    for i in range(len(ms) - 1, 0, -1):
        a, b = ms[i][2], ms[i - 1][2]
        c0, c1 = ms[i][0], ms[i - 1][0]
        wb_lanes = main_road_lanes_for_segment(c1, c0, "wm_to_rb")
        eid = f"wb_{a}__{b}"
        wb_edges.append(eid)
        ET.SubElement(
            edg,
            "edge",
            attrib={
                "id": eid,
                "from": f"n_wb_{a}",
                "to": f"n_wb_{b}",
                "numLanes": str(wb_lanes),
                "speed": f"{SPEED_KMH:.2f}",
                "priority": "3",
                "shape": _shape(a, b, wb_pos),
            },
        )
    _pretty_write(edg_path, edg)
    return eb_edges, wb_edges, ms, eb_pos


def run_netconvert(nod_path: Path, edg_path: Path, net_path: Path) -> bool:
    nc = _find_netconvert()
    if not nc:
        return False
    cmd = [
        nc,
        "--node-files",
        str(nod_path),
        "--edge-files",
        str(edg_path),
        "--output-file",
        str(net_path),
        "--junctions.join",
        "false",
        "--no-turnarounds",
        "true",
        "--default.lanewidth",
        str(LANE_WIDTH_M),
        "--geometry.min-radius",
        "12",
        "--junctions.corner-detail",
        "5",
    ]
    subprocess.run(cmd, check=True, cwd=SUMO_DIR)
    return True


def build_add_xml(
    path: Path,
    eb_edges: list[str],
    ms: list[tuple[float, str, str]],
    eb_pos: dict[str, tuple[float, float]],
    session: str = "Afternoon Session",
) -> None:
    root = ET.Element("additional")
    signal_keys = {s.key for s in CORRIDOR_SIGNALS}
    stop_keys = {s.key for s in STOPS_RB_TO_WM}

    for vid, vclass, length, color in [
        ("bus", "bus", "12", "yellow"),
        ("car", "passenger", "4.5", "1,0,0"),
        ("jeepney", "bus", "7", "1,0.5,0"),
        ("truck", "truck", "10", "0.5,0.5,0.5"),
        ("motorcycle", "motorcycle", "2.2", "0,1,0"),
        ("van", "delivery", "5.5", "0,1,1"),
    ]:
        ET.SubElement(
            root,
            "vType",
            attrib={
                "id": vid,
                "vClass": vclass,
                "length": length,
                "maxSpeed": f"{SPEED_KMH:.2f}",
                "color": color,
            },
        )

    for eid in eb_edges:
        parts = eid.replace("eb_", "").split("__")
        if len(parts) != 2:
            continue
        key = parts[0]
        if key == "robinsons" or key in signal_keys or key not in stop_keys:
            continue
        ET.SubElement(
            root,
            "busStop",
            attrib={
                "id": f"bs_{key}",
                "lane": f"{eid}_0",
                "startPos": "8",
                "endPos": "22",
                "name": key.replace("_", " "),
            },
        )

    if eb_edges:
        ET.SubElement(
            root,
            "busStop",
            attrib={
                "id": "bs_robinsons",
                "lane": f"{eb_edges[0]}_0",
                "startPos": "2",
                "endPos": "18",
                "name": "Robinsons",
            },
        )
        last = eb_edges[-1]
        last_len = max(ms[-1][0] - ms[-2][0], 30.0) if len(ms) >= 2 else 50.0
        ET.SubElement(
            root,
            "busStop",
            attrib={
                "id": "bs_waltermart",
                "lane": f"{last}_0",
                "startPos": str(max(last_len - 28, 5)),
                "endPos": str(max(last_len - 8, 15)),
                "name": "Waltermart",
            },
        )

    for sig in CORRIDOR_SIGNALS:
        g_eb, g_wb = signal_green_times(session, sig.key)
        cycle = signal_cycle_seconds(session, sig.key)
        for prefix, green_s, offset_s in (
            ("n_eb", g_eb, "0"),
            ("n_wb", g_wb, str(int(g_eb))),
        ):
            tl = ET.SubElement(
                root,
                "tlLogic",
                attrib={
                    "id": f"{prefix}_{sig.key}",
                    "type": "static",
                    "programID": "0",
                    "offset": offset_s,
                },
            )
            ET.SubElement(tl, "phase", attrib={"duration": str(int(round(green_s))), "state": "GG"})
            ET.SubElement(
                tl,
                "phase",
                attrib={"duration": str(int(round(cycle - green_s))), "state": "rr"},
            )

    xs = [p[0] for p in eb_pos.values()]
    ys = [p[1] for p in eb_pos.values()]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    for _chain, kind, key in ms:
        if key in signal_keys:
            continue
        x, y = eb_pos[key]
        ET.SubElement(
            root,
            "poi",
            attrib={
                "id": f"lbl_{key}",
                "x": f"{x:.2f}",
                "y": f"{y + 18:.2f}",
                "color": "0,0,1",
                "type": "stop",
                "layer": "1",
            },
        )
    _gui_path = path.parent / "corridor.view.xml"
    _gui_path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<viewsettings>
  <viewport zoom="250" x="{cx:.0f}" y="{cy:.0f}"/>
  <scheme name="real world"/>
</viewsettings>
""",
        encoding="utf-8",
    )

    _pretty_write(path, root)


def build_rou_xml(path: Path, eb_edges: list[str], wb_edges: list[str]) -> None:
    root = ET.Element("routes")
    ET.SubElement(root, "route", attrib={"id": "route_rb_wm", "edges": " ".join(eb_edges)})
    ET.SubElement(root, "route", attrib={"id": "route_wm_rb", "edges": " ".join(wb_edges)})

    d = SESSION_DEMAND["Morning Session"]
    t_end = str(SIM_END_S)
    bus_period = max(3600 / max(d["bus"] * 3600, 10), 45)

    ET.SubElement(
        root,
        "flow",
        attrib={
            "id": "bus_rb_wm",
            "type": "bus",
            "route": "route_rb_wm",
            "begin": "0",
            "end": t_end,
            "period": str(int(bus_period)),
            "line": "RB_WM",
        },
    )
    ET.SubElement(
        root,
        "flow",
        attrib={
            "id": "bus_wm_rb",
            "type": "bus",
            "route": "route_wm_rb",
            "begin": "0",
            "end": t_end,
            "period": str(int(bus_period * 1.5)),
            "line": "WM_RB",
        },
    )
    ET.SubElement(
        root,
        "flow",
        attrib={
            "id": "car_rb_wm",
            "type": "car",
            "route": "route_rb_wm",
            "begin": "0",
            "end": t_end,
            "vehsPerHour": str(int(d["car"] * 3600)),
        },
    )
    ET.SubElement(
        root,
        "flow",
        attrib={
            "id": "car_wm_rb",
            "type": "car",
            "route": "route_wm_rb",
            "begin": "0",
            "end": t_end,
            "vehsPerHour": str(int(d["car"] * 3600 * 0.7)),
        },
    )
    ET.SubElement(
        root,
        "flow",
        attrib={
            "id": "jeep_rb_wm",
            "type": "jeepney",
            "route": "route_rb_wm",
            "begin": "0",
            "end": t_end,
            "vehsPerHour": str(int(d["jeepney"] * 3600)),
        },
    )
    _pretty_write(path, root)


def build_sumocfg(path: Path) -> None:
    root = ET.Element("configuration")
    inp = ET.SubElement(root, "input")
    ET.SubElement(inp, "net-file", attrib={"value": "corridor.net.xml"})
    ET.SubElement(inp, "route-files", attrib={"value": "corridor.rou.xml"})
    ET.SubElement(inp, "additional-files", attrib={"value": "corridor.add.xml"})
    gui = ET.SubElement(root, "gui_only")
    ET.SubElement(gui, "gui-settings-file", attrib={"value": "corridor.view.xml"})
    ET.SubElement(gui, "start", attrib={"value": "true"})
    tme = ET.SubElement(root, "time")
    ET.SubElement(tme, "begin", attrib={"value": "0"})
    ET.SubElement(tme, "end", attrib={"value": str(SIM_END_S)})
    ET.SubElement(tme, "step-length", attrib={"value": "1"})
    rep = ET.SubElement(root, "report")
    ET.SubElement(rep, "tripinfo-output", attrib={"value": "output/tripinfo.xml"})
    ET.SubElement(rep, "summary-output", attrib={"value": "output/summary.xml"})
    _pretty_write(path, root)


def write_readme(path: Path) -> None:
    path.write_text(
        f"""# SUMO — Robinsons to Waltermart ({CORRIDOR_LENGTH_M:.0f} m)

Aligned with `corridor_config.py`: two traffic signals (session-timed cycles).

| Signal | Chainage | GPS |
|--------|----------|-----|
| Pala-Pala | ~{CORRIDOR_SIGNALS[0].chainage_m:.0f} m | 14.30245, 120.95427 |
| Waltermart intersection | ~{CORRIDOR_SIGNALS[1].chainage_m:.0f} m | 14.32556, 120.94083 |

## Install SUMO

https://eclipse.dev/sumo/ — set `SUMO_HOME` and add `%SUMO_HOME%\\bin` to PATH.

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
""",
        encoding="utf-8",
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Build schematic SUMO corridor")
    ap.add_argument(
        "--session",
        choices=SESSIONS,
        default="Afternoon Session",
        help="Signal cycle timing for this session",
    )
    args = ap.parse_args()
    session = args.session

    global GPS_CENTERLINE
    if (SUMO_DIR / "corridor_centerline.json").is_file():
        GPS_CENTERLINE = _load_centerline()
        print("Using OSM/Google corridor centerline from corridor_centerline.json")

    SUMO_DIR.mkdir(parents=True, exist_ok=True)
    (SUMO_DIR / "output").mkdir(exist_ok=True)

    nod = SUMO_DIR / "corridor.nod.xml"
    edg = SUMO_DIR / "corridor.edg.xml"
    net = SUMO_DIR / "corridor.net.xml"

    eb, wb, ms, eb_pos = build_nod_edg(nod, edg)
    built = run_netconvert(nod, edg, net)
    if not built:
        print("netconvert not found — install SUMO, then run:")
        print(f"  netconvert -n {nod.name} -e {edg.name} -o {net.name}")

    build_add_xml(SUMO_DIR / "corridor.add.xml", eb, ms, eb_pos, session=session)
    for sh in SESSIONS:
        if sh != session:
            build_add_xml(SUMO_DIR / f"corridor.add.{sh.replace(' ', '_').lower()}.xml", eb, ms, eb_pos, session=sh)
    build_rou_xml(SUMO_DIR / "corridor.rou.xml", eb, wb)
    build_sumocfg(SUMO_DIR / "corridor.sumocfg")
    write_readme(SUMO_DIR / "README.md")

    print(f"SUMO files in {SUMO_DIR}  (signal timing: {session!r})")
    print(f"  Milestones: {len(ms)}  EB edges: {len(eb)}  Signals: {len(CORRIDOR_SIGNALS)}")
    for s in CORRIDOR_SIGNALS:
        c = signal_cycle_seconds(session, s.key)
        main, side = signal_green_times(session, s.key)
        print(f"    {s.key}: field cycle {c:.0f} s  (main {main:.0f} s / side {side:.0f} s)")
    if built:
        print("  corridor.net.xml built (GPS-aligned dual carriageway)")
    print("  In sumo-gui: restart if the network was already open")
    print("  Run: sumo-gui -c sumo/corridor.sumocfg")


if __name__ == "__main__":
    main()
