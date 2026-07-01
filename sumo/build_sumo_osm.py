"""
Build SUMO network from OpenStreetMap — matches Google Maps Waltermart ↔ Robinsons corridor.

Google route: Waltermart Dasmariñas → Aguinaldo Hwy → Governor's Dr / Palapala → Robinsons (~3.2 km).

Run from project root:
  python sumo/build_sumo_osm.py

Requires: osmnx, SUMO (netconvert + sumolib on SUMO_HOME/tools).
Opens corridor_osm.sumocfg (real street geometry). Use build_sumo_corridor.py for the
schematic thesis network aligned to chainage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from corridor_config import (  # noqa: E402
    CORRIDOR_LENGTH_M,
    FREE_FLOW_MPS,
    GPS_ORIGIN_RB,
    SESSION_DEMAND,
)

# Google Maps corridor endpoints (Waltermart north → Robinsons south)
WALTERMART_LONLAT = (120.9414853, 14.324744)
ROBINSONS_LONLAT = (120.9529, 14.3002)  # corridor_config GPS_ORIGIN_RB (lon, lat)

# Tight bbox around the blue route on your map (west, south, east, north)
CORRIDOR_BBOX = (120.9365, 14.2975, 120.9585, 14.3285)

SPEED_KMH = FREE_FLOW_MPS * 3.6
SIM_END_S = 3600


def _sumo_tools() -> Path:
    home = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo"))
    tools = home / "tools"
    if not tools.is_dir():
        raise RuntimeError("SUMO_HOME/tools not found — set SUMO_HOME to your SUMO install")
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    return tools


def _find_exe(name: str) -> str:
    home = os.environ.get("SUMO_HOME", "")
    if home:
        exe = Path(home) / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
        if exe.is_file():
            return str(exe)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"{name} not found — install SUMO and set SUMO_HOME")


def download_osm(bbox: tuple[float, float, float, float], osm_path: Path):
    import osmnx as ox

    west, south, east, north = bbox
    G = ox.graph_from_bbox(bbox=(west, south, east, north), network_type="drive", simplify=False)
    ox.save_graph_xml(G, filepath=osm_path)
    Gs = ox.simplify_graph(G.copy())
    return Gs


def run_netconvert(osm_path: Path, net_path: Path) -> None:
    nc = _find_exe("netconvert")
    cmd = [
        nc,
        "--osm-files",
        str(osm_path),
        "--output-file",
        str(net_path),
        "--geometry.remove",
        "false",
        "--ramps.guess",
        "true",
        "--junctions.join",
        "true",
        "--tls.guess-signals",
        "true",
        "--tls.discard-simple",
        "true",
        "--default.speed",
        str(SPEED_KMH),
    ]
    subprocess.run(cmd, check=True, cwd=SUMO_DIR)


def shortest_path_edges(G, lonlat_from: tuple[float, float], lonlat_to: tuple[float, float]) -> list[tuple[int, int, int]]:
    import osmnx as ox

    u = ox.distance.nearest_nodes(G, lonlat_from[0], lonlat_from[1])
    v = ox.distance.nearest_nodes(G, lonlat_to[0], lonlat_to[1])
    path = ox.shortest_path(G, u, v, weight="length")
    edges: list[tuple[int, int, int]] = []
    for a, b in zip(path[:-1], path[1:]):
        data = G.get_edge_data(a, b)
        if data is None:
            continue
        k = min(data.keys())
        edges.append((a, b, k))
    return edges


def path_nodes_to_sumo(G, net, path_nodes: list[int]) -> list[str]:
    """Map OSMnx node path to SUMO edge ids via OSM way id."""
    import sumolib

    if isinstance(net, (str, Path)):
        net = sumolib.net.readNet(str(net))

    sumo_ids: list[str] = []
    for a, b in zip(path_nodes[:-1], path_nodes[1:]):
        data = G.get_edge_data(a, b)
        if not data:
            continue
        k = min(data.keys())
        d = data[k]
        osmid = d.get("osmid", "")
        if isinstance(osmid, list):
            osmid = osmid[0]
        osmid = str(osmid)
        found = None
        for cand in (osmid, f"-{osmid}", f"{osmid}#0", f"-{osmid}#0"):
            try:
                net.getEdge(cand)
                found = cand
                break
            except Exception:
                pass
        if not found:
            for e in net.getEdges():
                eid = e.getID()
                if eid == osmid or eid.startswith(f"{osmid}#") or eid.startswith(f"-{osmid}#"):
                    found = eid
                    break
        if found:
            sumo_ids.append(found)

    out: list[str] = []
    for eid in sumo_ids:
        if not out or out[-1] != eid:
            out.append(eid)
    return out


def route_with_sumolib(net_path: Path, from_lonlat: tuple[float, float], to_lonlat: tuple[float, float]) -> list[str]:
    import sumolib

    net = sumolib.net.readNet(str(net_path))
    lon0, lat0 = from_lonlat
    lon1, lat1 = to_lonlat
    x0, y0 = net.convertLonLat2XY(lon0, lat0)
    x1, y1 = net.convertLonLat2XY(lon1, lat1)
    near0 = net.getNeighboringEdges(x0, y0, 120)
    near1 = net.getNeighboringEdges(x1, y1, 120)
    if not near0 or not near1:
        return []
    fe = near0[0][0]
    te = near1[0][0]
    path, _cost = net.getShortestPath(fe, te)
    if not path:
        return []
    return [e.getID() for e in path]


def sample_centerline_simple(G, path_edges: list[tuple[int, int, int]]) -> list[tuple[float, float, float]]:
    """Cumulative chainage from Robinsons (0) along shortest path toward Waltermart."""
    from math import asin, cos, radians, sin, sqrt

    lat0, lon0 = GPS_ORIGIN_RB

    def hav(lat1, lon1, lat2, lon2):
        r = 6371000.0
        p1, p2 = radians(lat1), radians(lat2)
        dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2) ** 2
        return 2 * r * asin(sqrt(a))

    chain = 0.0
    out: list[tuple[float, float, float]] = [(0.0, lat0, lon0)]
    prev_lat, prev_lon = lat0, lon0
    for u, v, k in path_edges:
        lat, lon = G.nodes[v]["y"], G.nodes[v]["x"]
        chain += hav(prev_lat, prev_lon, lat, lon)
        out.append((chain, lat, lon))
        prev_lat, prev_lon = lat, lon
    return out


def write_routes(
    rou_path: Path,
    edges_wm_rb: list[str],
    edges_rb_wm: list[str],
) -> None:
    from xml.dom import minidom
    import xml.etree.ElementTree as ET

    root = ET.Element("routes")
    ET.SubElement(
        root,
        "vType",
        attrib={"id": "bus", "vClass": "bus", "length": "12", "maxSpeed": f"{SPEED_KMH:.2f}", "color": "yellow"},
    )
    ET.SubElement(
        root,
        "vType",
        attrib={"id": "car", "vClass": "passenger", "length": "4.5", "maxSpeed": f"{SPEED_KMH:.2f}", "color": "1,0,0"},
    )
    if edges_wm_rb:
        ET.SubElement(root, "route", attrib={"id": "route_wm_rb", "edges": " ".join(edges_wm_rb)})
    if edges_rb_wm:
        ET.SubElement(root, "route", attrib={"id": "route_rb_wm", "edges": " ".join(edges_rb_wm)})

    d = SESSION_DEMAND["Morning Session"]
    t_end = str(SIM_END_S)
    bus_period = max(3600 / max(d["bus"] * 3600, 10), 45)
    if edges_wm_rb:
        ET.SubElement(
            root,
            "flow",
            attrib={
                "id": "bus_wm_rb",
                "type": "bus",
                "route": "route_wm_rb",
                "begin": "0",
                "end": t_end,
                "period": str(int(bus_period)),
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
                "vehsPerHour": str(int(d["car"] * 3600)),
            },
        )
    if edges_rb_wm:
        ET.SubElement(
            root,
            "flow",
            attrib={
                "id": "bus_rb_wm",
                "type": "bus",
                "route": "route_rb_wm",
                "begin": "0",
                "end": t_end,
                "period": str(int(bus_period * 1.5)),
            },
        )

    rough = ET.tostring(root, encoding="unicode")
    rou_path.write_text(minidom.parseString(rough).toprettyxml(indent="  "), encoding="utf-8")


def write_sumocfg(path: Path, net_name: str, rou_name: str) -> None:
    from xml.dom import minidom
    import xml.etree.ElementTree as ET

    root = ET.Element("configuration")
    inp = ET.SubElement(root, "input")
    ET.SubElement(inp, "net-file", attrib={"value": net_name})
    ET.SubElement(inp, "route-files", attrib={"value": rou_name})
    tme = ET.SubElement(root, "time")
    ET.SubElement(tme, "begin", attrib={"value": "0"})
    ET.SubElement(tme, "end", attrib={"value": str(SIM_END_S)})
    gui = ET.SubElement(root, "gui_only")
    ET.SubElement(gui, "start", attrib={"value": "true"})
    path.write_text(
        minidom.parseString(ET.tostring(root, encoding="unicode")).toprettyxml(indent="  "),
        encoding="utf-8",
    )


def main() -> None:
    _sumo_tools()
    SUMO_DIR.mkdir(parents=True, exist_ok=True)
    (SUMO_DIR / "output").mkdir(exist_ok=True)

    osm_path = SUMO_DIR / "corridor_raw.osm"
    net_path = SUMO_DIR / "corridor_osm.net.xml"

    print("Downloading OpenStreetMap (Waltermart–Robinsons bbox)...")
    G = download_osm(CORRIDOR_BBOX, osm_path)

    print("Running netconvert (real road geometry)...")
    run_netconvert(osm_path, net_path)

    import sumolib

    print("Finding routes on Aguinaldo corridor (Waltermart -> Robinsons)...")
    import osmnx as ox

    net = sumolib.net.readNet(str(net_path))
    u_wm = ox.distance.nearest_nodes(G, WALTERMART_LONLAT[0], WALTERMART_LONLAT[1])
    u_rb = ox.distance.nearest_nodes(G, ROBINSONS_LONLAT[0], ROBINSONS_LONLAT[1])
    path_wm_rb_nodes = ox.shortest_path(G, u_wm, u_rb, weight="length")
    path_rb_wm_nodes = list(reversed(path_wm_rb_nodes))

    edges_wm_rb = path_nodes_to_sumo(G, net, path_wm_rb_nodes)
    edges_rb_wm = list(reversed(edges_wm_rb))
    if len(edges_rb_wm) < 2:
        edges_rb_wm = path_nodes_to_sumo(G, net, path_rb_wm_nodes)

    if len(edges_wm_rb) < 2:
        edges_wm_rb = route_with_sumolib(net_path, WALTERMART_LONLAT, ROBINSONS_LONLAT)
    if len(edges_rb_wm) < 2:
        edges_rb_wm = route_with_sumolib(net_path, ROBINSONS_LONLAT, WALTERMART_LONLAT)

    path_rb_wm_edges = [
        (path_rb_wm_nodes[i], path_rb_wm_nodes[i + 1], 0) for i in range(len(path_rb_wm_nodes) - 1)
    ]
    centerline = sample_centerline_simple(G, path_rb_wm_edges)
    cl_path = SUMO_DIR / "corridor_centerline.json"
    cl_path.write_text(
        json.dumps(
            {
                "source": "OpenStreetMap shortest path (Waltermart–Robinsons, Google Maps corridor)",
                "length_m": centerline[-1][0] if centerline else CORRIDOR_LENGTH_M,
                "waypoints": [{"chainage_m": c, "lat": lat, "lon": lon} for c, lat, lon in centerline],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    write_routes(SUMO_DIR / "corridor_osm.rou.xml", edges_wm_rb, edges_rb_wm)
    write_sumocfg(SUMO_DIR / "corridor_osm.sumocfg", "corridor_osm.net.xml", "corridor_osm.rou.xml")

    n_edges = len(list(net.getEdges()))
    print(f"OSM network: {net_path.name}  ({n_edges} edges)")
    print(f"Waltermart -> Robinsons: {len(edges_wm_rb)} edges")
    print(f"Robinsons -> Waltermart: {len(edges_rb_wm)} edges")
    print(f"Centerline length: {centerline[-1][0]:.0f} m (field model {CORRIDOR_LENGTH_M:.0f} m)")
    print(f"Saved centerline: {cl_path.name}")
    print()
    print("Run Google-map style network:")
    print("  sumo-gui -c sumo/corridor_osm.sumocfg")
    print()
    print("Optional: refresh schematic network from OSM centerline:")
    print("  python sumo/build_sumo_corridor.py")


if __name__ == "__main__":
    main()
