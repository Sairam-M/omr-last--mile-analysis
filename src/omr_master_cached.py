"""
OMR LAST-MILE CONNECTIVITY — FINAL CONSOLIDATED SCRIPT
=========================================================
One file, top to bottom. Every step prints a [SANITY CHECK] or [RESULT]
so a wrong number is visible immediately, not discovered three steps later.

WHAT THIS INCLUDES (all validated across the full analysis):
  - OMR road (OSM, name-filtered for both "Mahabalipuram" and its current
    name "Rajiv Gandhi Salai")
  - Bus stops, schools, hospitals (OSM), each filtered to the actual OMR
    corridor (2km buffer) before any coverage math — NOT the full download
    bounding box, which is much wider and pulls in unrelated interior
    neighbourhoods (Medavakkam, Kovilambakkam, etc.)
  - Slums (TNSCB KML), validated against official zone-ward ranges,
    filtered to the OMR corridor
  - Bus walking isochrone (network-based, not a circle buffer)
  - Metro Red Line stations (AI-estimated coordinates, sanity-checked via
    inter-station spacing + cross-check against Sholinganallur's confirmed
    coordinate), with a CORRECTED true-walking-distance method that
    accounts for the entry/exit snap distance an isochrone silently ate
  - GCC ward boundaries (2022, 200-ward scheme), used for both a ward-wise
    breakdown AND a true inside/outside-GCC test

WHAT THIS DELIBERATELY DOES NOT INCLUDE:
  - Population data — WorldPop API, windowed raster access, and Google
    Earth Engine were all attempted and each hit a confirmed, non-code-side
    blocker (see POPULATION NOTE at the bottom). Boundaries are ready for
    population once a working source exists (e.g. a colleague's
    QGIS-clipped WorldPop raster).
  - Metro Purple Line (Corridor 3, serves Medavakkam/Perumbakkam from the
    interior) — only the Red Line (Corridor 5, along OMR) is included.
    Flagged as a known limitation, not silently omitted.

A large block of alternate ward-aggregation code (functions like
compute_ward_summary/select_omr_wards, a "priority_score"/"slum_pressure"
metric) was tried via Copilot in an earlier notebook and is DELIBERATELY
EXCLUDED here — it used an unvalidated ward numbering scheme and produced
an impossible result (a summed "ward_id" of 20100). Nothing from that path
survives into this script.
"""

import os
os.chdir("C:/Users/Sairam/Downloads")

import geopandas as gpd
import pandas as pd
import osmnx as ox
import networkx as nx
import numpy as np
from shapely.geometry import Point as ShapelyPoint
from pathlib import Path
import pickle
import hashlib
from time import perf_counter

CRS_METRIC = 32644                    # UTM 44N — meters, correct for Chennai

# ============================================================================
# CACHE / TIMING LAYER
# ============================================================================
# Expensive downloads/computations are persisted under CACHE_DIR.
# Delete cache/ when you intentionally want a completely fresh run.
CACHE_DIR = Path("cache_omr")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_VERSION = "v1"

# BBOX must be defined before BBOX_KEY/CACHE_PREFIX below, which derive from it
# BBOX = (80.15, 12.80, 80.28, 12.95)   # (west, south, east, north) — wide download box
# BBOX = (80.15, 12.84, 80.28, 12.99)
BBOX = (80.1824, 12.8421, 80.2746, 13.0300)  # north edge extended to 13.03 to include Madhya Kailash /
                                               # true OMR origin (was 12.9913, missed ward 170's
                                               # southern sliver entirely — confirmed via satellite
                                               # check: 0% of ward 170 fell inside the old box)
OMR_BUFFER_M = 2000                   # corridor width around OMR itself
WALK_DIST_M = 500                     # walkability threshold

# BBOX_KEY derived directly from BBOX — cannot silently drift out of sync with the
# actual download extent (this was a real bug source earlier: BBOX_KEY was previously
# a separately hardcoded string, so changing BBOX alone would have left cache filenames
# lying about what extent they actually cover)
BBOX_KEY = f"{BBOX[0]}_{BBOX[1]}_{BBOX[2]}_{BBOX[3]}"
CACHE_PREFIX = f"{CACHE_VERSION}_{BBOX_KEY}_walk500"

_TIMERS = {}

# ============================================================================
# WARD SCOPE DECISION — the analysis-ready ward list, and why each excluded
# ward is excluded. Two distinct, real reasons (not three, as earlier
# confusion suggested):
#
# 1. GEOMETRICALLY NOT NEAR OMR — these wards never intersect omr_buffer_wide
#    (the 2km corridor buffer) at all, so they never appear in wards_near_omr
#    in the first place. Wards 185-188 fall in this category: they were
#    briefly considered (hence the old commented-out reference below) while
#    scanning the full Zone 13/14 numeric range, but geometrically never
#    touch the OMR corridor. Confirmed absent from the ward map entirely —
#    not a manual judgment call, just outside scope by definition.
#
# 2. INCLUDED IN wards_near_omr, BUT EXCLUDED FROM OMR_STUDY_WARDS below
#    for a specific documented reason:
#      - 170, 174: 0% of ward area falls inside the OSM download BBOX
#        (residential building footprint would be silently undercounted)
#      - 189: does not directly touch the OMR road or its buffer — sits
#        behind wards 193/195/196, which form a shield between it and OMR.
#        This also explains an earlier apparent contradiction (12 MTC stops
#        administratively assigned to ward 189, yet residential_bus_m2 = 0
#        in Step 3A) — those stops serve the ward's own area, not anything
#        adjacent to the OMR corridor.
#
# 170 and 174 remain listed below (population math will be unreliable for
# them due to BBOX clipping — treat their output with that caveat, or drop
# them from `OMR_STUDY_WARDS` entirely once confirmed not worth including).
# ============================================================================
OMR_STUDY_WARDS = [
    170, 172, 173, 178, 179, 180,
    181, 182, 183, 184,
    # 189 excluded — does not directly touch the OMR road/buffer, shielded
    # by wards 193/195/196 (confirmed via geometry check)
    # 197 excluded — sits east of ECR, separated from OMR (confirmed visually)
    190, 191, 192, 193, 194, 195, 196, 198, 199, 200
    # 170 — ADDED TEMPORARILY for this run, on a trial basis, now that BBOX
    # extends to 13.03°N and should capture real data for it (previously
    # 0% inside BBOX = no data at all). NOT yet a final decision — check
    # the resulting numbers: does 170's population/residential footprint
    # concentrate near OMR (Madhya Kailash, southern sliver) or does the
    # northern, non-OMR mass along the Adyar river still dominate the
    # ward total? Remove again if the north still dominates.
]

def timed_start(label):
    _TIMERS[label] = perf_counter()
    print(f"[START] {label}")

def timed_end(label):
    elapsed = perf_counter() - _TIMERS.pop(label, perf_counter())
    print(f"[TIME] {label}: {elapsed:.2f} sec")
    return elapsed

def cache_path(name):
    return CACHE_DIR / name

def cache_exists(name):
    return cache_path(name).exists()

def save_pickle(obj, name):
    path = cache_path(name)
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[CACHE SAVE] {path}")

def load_pickle(name):
    path = cache_path(name)
    with open(path, "rb") as f:
        obj = pickle.load(f)
    print(f"[CACHE HIT] {path}")
    return obj

def save_graph(graph, name):
    path = cache_path(name)
    ox.save_graphml(graph, filepath=path)
    print(f"[CACHE SAVE] {path}")

def load_graph(name):
    path = cache_path(name)
    graph = ox.load_graphml(filepath=path)
    print(f"[CACHE HIT] {path}")
    return graph

def save_gdf(gdf, name):
    path = cache_path(name)
    # Pickle preserves GeoDataFrame indexes/columns exactly, including OSM
    # multi-index structures that can be awkward in GeoJSON/GPKG.
    with open(path, "wb") as f:
        pickle.dump(gdf, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[CACHE SAVE] {path}")

def load_gdf(name):
    path = cache_path(name)
    with open(path, "rb") as f:
        gdf = pickle.load(f)
    print(f"[CACHE HIT] {path}")
    return gdf

def cache_signature(*parts):
    raw = repr(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]

print(f"[CACHE] Directory: {CACHE_DIR.resolve()}")
print(f"[CACHE] Version: {CACHE_VERSION}")

SLUM_KML_PATH = "slums.kml"                        # <-- SET THIS
WARD_KML_PATH = "chennai_gcc_wards_2022.kml"        # <-- SET THIS


# ============================================================================
# STEP 1 — OMR road network
# SOURCE: live download, OpenStreetMap via OSMnx
# ============================================================================
print("=" * 70); print("STEP 1: OMR road network"); print("=" * 70)

timed_start("STEP 1 — OSM drive network")
roads_cache = f"{CACHE_PREFIX}_drive.graphml"
if cache_exists(roads_cache):
    G_roads = load_graph(roads_cache)
    edges = ox.graph_to_gdfs(G_roads, nodes=False)
    print(f"[CACHE] Road network loaded: {len(edges)} segments")
else:
    print("[DOWNLOAD] OSM drive network")
    G_roads = ox.graph_from_bbox(bbox=BBOX, network_type="drive")
    edges = ox.graph_to_gdfs(G_roads, nodes=False)
    save_graph(G_roads, roads_cache)
    print(f"[SANITY CHECK] Total road segments downloaded: {len(edges)}")
timed_end("STEP 1 — OSM drive network")

def matches_omr(row):
    name = row.get("name")
    ref = row.get("ref")
    names = name if isinstance(name, list) else [name] if isinstance(name, str) else []
    name_match = any(("Mahabalipuram" in n) or ("Rajiv Gandhi Salai" in n) or ("Rajiv Gandhi" in n)
                      for n in names)
    ref_match = isinstance(ref, str) and "OMR" in ref.upper()
    return name_match or ref_match

omr_edges = edges[edges.apply(matches_omr, axis=1)]
print(f"[SANITY CHECK] OMR-matching segments: {len(omr_edges)} "
      f"({'OK' if len(omr_edges) > 50 else 'WARNING — low, check name filter'})")

omr_edges_m = omr_edges.to_crs(CRS_METRIC)
omr_buffer_wide = omr_edges_m.buffer(OMR_BUFFER_M).unary_union
print(f"[SANITY CHECK] OMR road bounds: {omr_edges_m.total_bounds}")


# ============================================================================
# STEP 2 — Bus stops, schools, hospitals — download, then filter to OMR
# SOURCE: live download, OpenStreetMap via OSMnx
# FIX: filtering to omr_buffer_wide happens BEFORE any coverage math — the
# raw download box is much wider than OMR and pulls in unrelated areas.
# ============================================================================
print("\n" + "=" * 70); print("STEP 2: Bus stops, schools, hospitals"); print("=" * 70)

timed_start("STEP 2 — OSM facilities")
bus_cache = f"{CACHE_PREFIX}_bus_stops_raw.pkl"
schools_cache = f"{CACHE_PREFIX}_schools_raw.pkl"
hospitals_cache = f"{CACHE_PREFIX}_hospitals_raw.pkl"

if cache_exists(bus_cache):
    bus_stops_raw = load_gdf(bus_cache)
else:
    print("[DOWNLOAD] OSM bus stops")
    bus_stops_raw = ox.features_from_bbox(
        bbox=BBOX, tags={"highway": "bus_stop", "amenity": "bus_station"}
    )
    save_gdf(bus_stops_raw, bus_cache)

if cache_exists(schools_cache):
    schools_raw = load_gdf(schools_cache)
else:
    print("[DOWNLOAD] OSM schools")
    schools_raw = ox.features_from_bbox(
        bbox=BBOX, tags={"amenity": ["school", "college"]}
    )
    save_gdf(schools_raw, schools_cache)

if cache_exists(hospitals_cache):
    hospitals_raw = load_gdf(hospitals_cache)
else:
    print("[DOWNLOAD] OSM hospitals")
    hospitals_raw = ox.features_from_bbox(
        bbox=BBOX, tags={"amenity": ["hospital", "clinic"]}
    )
    save_gdf(hospitals_raw, hospitals_cache)

print(f"[SANITY CHECK] Raw counts in full bbox — bus stops: {len(bus_stops_raw)}, "
      f"schools: {len(schools_raw)}, hospitals: {len(hospitals_raw)}")
timed_end("STEP 2 — OSM facilities")

bus_stops_m = bus_stops_raw.to_crs(CRS_METRIC)
schools_m = schools_raw.to_crs(CRS_METRIC)
hospitals_m = hospitals_raw.to_crs(CRS_METRIC)

bus_stops_m["centroid"] = bus_stops_m.geometry.centroid
schools_m["centroid"] = schools_m.geometry.centroid
hospitals_m["centroid"] = hospitals_m.geometry.centroid

bus_stops_omr = bus_stops_m[bus_stops_m["centroid"].within(omr_buffer_wide)].copy()
schools_omr = schools_m[schools_m["centroid"].within(omr_buffer_wide)].copy()
hospitals_omr = hospitals_m[hospitals_m["centroid"].within(omr_buffer_wide)].copy()

print(f"[RESULT] Filtered to OMR corridor — bus stops: {len(bus_stops_omr)}, "
      f"schools: {len(schools_omr)}, hospitals: {len(hospitals_omr)}")

# ============================================================================
# STEP X — MTC GTFS bus stops
# ============================================================================

print("\n" + "=" * 70)
print("STEP X: MTC GTFS bus stops — OMR study extent")
print("=" * 70)

MTC_STOPS_PATH = "mtc-gtfs/stops.txt"

OMR_MIN_LON, OMR_MIN_LAT, OMR_MAX_LON, OMR_MAX_LAT = BBOX  # derived from BBOX — was previously
                                                              # hardcoded separately, would have
                                                              # silently kept filtering MTC stops
                                                              # against the OLD extent otherwise

MTC_GTFS_CACHE = f"{CACHE_PREFIX}_mtc_omr_stops.csv"

if cache_exists(MTC_GTFS_CACHE):

    mtc_stops_omr = pd.read_csv(
        cache_path(MTC_GTFS_CACHE)
    )

    print(f"[CACHE HIT] {cache_path(MTC_GTFS_CACHE)}")

else:

    # ------------------------------------------------------------
    # 1. Load MTC GTFS stops.txt
    # ------------------------------------------------------------
    mtc_stops = pd.read_csv(MTC_STOPS_PATH)

    print(
        f"[SANITY CHECK] MTC GTFS total stops: "
        f"{len(mtc_stops):,}"
    )

    # ------------------------------------------------------------
    # 2. Validate expected schema
    # ------------------------------------------------------------
    required_cols = {
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon"
    }

    missing = required_cols - set(mtc_stops.columns)

    if missing:
        raise ValueError(
            f"MTC stops.txt missing required columns: {sorted(missing)}"
        )

    # ------------------------------------------------------------
    # 3. Geographic bounding-box filter
    # ------------------------------------------------------------
    mtc_stops_omr = mtc_stops[
        mtc_stops["stop_lon"].between(
            OMR_MIN_LON,
            OMR_MAX_LON
        )
        &
        mtc_stops["stop_lat"].between(
            OMR_MIN_LAT,
            OMR_MAX_LAT
        )
    ].copy()

    print(
        f"[RESULT] MTC stops in study extent: "
        f"{len(mtc_stops_omr):,}"
    )

    mtc_stops_omr.to_csv(
        cache_path(MTC_GTFS_CACHE),
        index=False
    )

    print(
        f"[CACHE SAVE] {cache_path(MTC_GTFS_CACHE)}"
    )

# ------------------------------------------------------------
# 4. Convert GTFS stops to GeoDataFrame
# ------------------------------------------------------------

mtc_stops_gdf = gpd.GeoDataFrame(
    mtc_stops_omr,
    geometry=gpd.points_from_xy(
        mtc_stops_omr["stop_lon"],
        mtc_stops_omr["stop_lat"]
    ),
    crs="EPSG:4326"
).to_crs(CRS_METRIC)







# ============================================================================
# STEP 3 — Bus walking isochrone (network-based, from OMR-filtered stops)
# ============================================================================
print("\n" + "=" * 70); print(f"STEP 3: {WALK_DIST_M}m walking isochrone from bus stops"); print("=" * 70)


timed_start("STEP 3 — Walking network + bus isochrone")
walk_cache = f"{CACHE_PREFIX}_walking_all_projected.graphml"
bus_iso_cache = f"{CACHE_PREFIX}_bus_isochrone.pkl"

if cache_exists(walk_cache):
    G_walk = load_graph(walk_cache)
else:
    print("[DOWNLOAD] OSM walking-support network")
    G_walk = ox.graph_from_bbox(bbox=BBOX, network_type="all")
    G_walk = ox.project_graph(G_walk, to_crs=CRS_METRIC)
    save_graph(G_walk, walk_cache)

print(f"[SANITY CHECK] Walking network: {len(G_walk.nodes)} nodes, {len(G_walk.edges)} edges")

if cache_exists(bus_iso_cache):
    isochrone_shape = load_pickle(bus_iso_cache)
else:
    reachable_nodes = set()
    skipped = 0
    for _, stop in bus_stops_omr.iterrows():
        pt = stop["centroid"]
        try:
            nearest_node = ox.distance.nearest_nodes(G_walk, X=pt.x, Y=pt.y)
            reachable = nx.ego_graph(
                G_walk, nearest_node, radius=WALK_DIST_M, distance="length"
            )
            reachable_nodes.update(reachable.nodes)
        except Exception:
            skipped += 1

    print(f"[SANITY CHECK] Bus stops processed: {len(bus_stops_omr) - skipped}, skipped: {skipped}")

    node_points = [
        ShapelyPoint((d["x"], d["y"]))
        for n, d in G_walk.nodes(data=True)
        if n in reachable_nodes
    ]
    isochrone_shape = gpd.GeoSeries(
        node_points, crs=CRS_METRIC
    ).buffer(30).union_all()
    save_pickle(isochrone_shape, bus_iso_cache)

print(f"[RESULT] Isochrone area: {isochrone_shape.area / 1_000_000:.2f} sq km")
timed_end("STEP 3 — Walking network + bus isochrone")

# ------------------------------------------------------------
# 6. Snap MTC stops to existing OSM walking network
# ------------------------------------------------------------

mtc_station_data = []

for _, stop in mtc_stops_gdf.iterrows():

    pt = stop.geometry

    nearest_node = ox.distance.nearest_nodes(
        G_walk,
        X=pt.x,
        Y=pt.y
    )

    node_pt = ShapelyPoint(
        G_walk.nodes[nearest_node]["x"],
        G_walk.nodes[nearest_node]["y"]
    )

    entry_snap = pt.distance(node_pt)

    lengths = nx.single_source_dijkstra_path_length(
        G_walk,
        nearest_node,
        cutoff=WALK_DIST_M,
        weight="length"
    )

    mtc_station_data.append({
        "stop_id": stop["stop_id"],
        "stop_name": stop["stop_name"],
        "stop_lat": stop["stop_lat"],
        "stop_lon": stop["stop_lon"],
        "entry_snap": entry_snap,
        "lengths": lengths
    })
def get_bus_isochrone(stop_data):

    bus_reachable_nodes = set()

    for s in stop_data:

        for node, network_dist in s["lengths"].items():

            if s["entry_snap"] + network_dist <= WALK_DIST_M:
                bus_reachable_nodes.add(node)

    bus_node_points = [
        ShapelyPoint(
            G_walk.nodes[n]["x"],
            G_walk.nodes[n]["y"]
        )
        for n in bus_reachable_nodes
    ]

    bus_walking_isochrone = (
        gpd.GeoSeries(
            bus_node_points,
            crs=CRS_METRIC
        )
        .buffer(30)
        .union_all()
    )

    return bus_walking_isochrone

mtc_bus_iso_cache = (
    f"{CACHE_PREFIX}_mtc_bus_isochrone.pkl"
)

if cache_exists(mtc_bus_iso_cache):

    mtc_bus_isochrone = load_pickle(
        mtc_bus_iso_cache
    )

else:

    mtc_bus_isochrone = get_bus_isochrone(
        mtc_station_data
    )

    save_pickle(
        mtc_bus_isochrone,
        mtc_bus_iso_cache
    )

print("\n" + "=" * 70)
print("BUS STOP SOURCE COMPARISON")
print("=" * 70)

# print(
#     f"MTC GTFS total stops:       {len(mtc_stops):,}"
# )

print(
    f"MTC stops in study extent:  {len(mtc_stops_omr):,}"
)

print(
    f"Old OSM bus stops:          {len(bus_stops_omr):,}"
)

# ----------------------------------------------------------------------
# FIX: point all downstream "bus" metrics at the official MTC GTFS
# isochrone instead of the raw-OSM one. Before this fix, Step 3A
# (population/residential accessibility) already used mtc_bus_isochrone
# directly, while Steps 4/5/8/10/10B/11 and the map still used the OSM
# isochrone_shape below — two different bus-stop sources feeding
# different halves of the same analysis. This line makes them consistent.
# The original OSM isochrone is kept under a new name purely for
# reference/comparison, never used for coverage math from here on.
# ----------------------------------------------------------------------
isochrone_shape_osm_legacy = isochrone_shape
osm_area_sqkm = isochrone_shape_osm_legacy.area / 1_000_000
mtc_area_sqkm = mtc_bus_isochrone.area / 1_000_000
print(f"\n[SANITY CHECK] OSM-based isochrone area:  {osm_area_sqkm:.2f} sq km "
      f"(from {len(bus_stops_omr)} OSM stops — no longer used for coverage)")
print(f"[SANITY CHECK] MTC-based isochrone area:  {mtc_area_sqkm:.2f} sq km "
      f"(from {len(mtc_stops_omr)} official MTC GTFS stops — used from here on)")
print(f"[NOTE] All coverage metrics from Step 4 onward now use the MTC GTFS isochrone. "
      f"This matches what Step 3A (population accessibility) already used.")

isochrone_shape = mtc_bus_isochrone


# ============================================================================
# STEP 4 — Bus coverage: schools & hospitals
# SOURCE: MTC GTFS official stops (mtc_bus_isochrone), NOT raw OSM stops
# ============================================================================
print("\n" + "=" * 70); print("STEP 4: Bus coverage — schools & hospitals (MTC GTFS source)"); print("=" * 70)

schools_omr["bus_covered"] = schools_omr["centroid"].within(isochrone_shape)
hospitals_omr["bus_covered"] = hospitals_omr["centroid"].within(isochrone_shape)

print(f"[RESULT] Schools bus-covered: {schools_omr['bus_covered'].sum()} / {len(schools_omr)}")
print(f"[RESULT] Hospitals bus-covered: {hospitals_omr['bus_covered'].sum()} / {len(hospitals_omr)}")


# ============================================================================
# STEP 5 — Slums: load, validate, filter to OMR, bus coverage by AREA
# SOURCE: TNSCB slum boundary KML (file you provide)
# ============================================================================
print("\n" + "=" * 70); print(f"STEP 5: Slums from {SLUM_KML_PATH}"); print("=" * 70)

timed_start("STEP 5 — Slum source load")
slums_cache = f"{CACHE_PREFIX}_slums_metric.pkl"
if cache_exists(slums_cache):
    slums_m = load_gdf(slums_cache)
    print(f"[CACHE] Slum features loaded: {len(slums_m)}")
else:
    slums = gpd.read_file(SLUM_KML_PATH, driver="KML")
    print(f"[SANITY CHECK] Slum features loaded: {len(slums)}")
    slums_m = slums.to_crs(CRS_METRIC)
    save_gdf(slums_m, slums_cache)
timed_end("STEP 5 — Slum source load")

slums_near_omr = slums_m[slums_m.geometry.intersects(omr_buffer_wide)].copy()
print(f"[RESULT] Slums near OMR: {len(slums_near_omr)} of {len(slums_m)} total citywide")

slums_near_omr["total_area_sqm"] = slums_near_omr.geometry.area
slums_near_omr["area_outside_isochrone"] = slums_near_omr.geometry.difference(isochrone_shape).area
slums_near_omr["pct_outside"] = slums_near_omr["area_outside_isochrone"] / slums_near_omr["total_area_sqm"]
slums_near_omr["outside_isochrone"] = slums_near_omr["pct_outside"] > 0.5

outside_count = slums_near_omr["outside_isochrone"].sum()
print(f"[RESULT] Slums majority-outside bus isochrone: {outside_count} / {len(slums_near_omr)}")

# Ward/zone validation (Zone 14 = wards 183-191, Zone 15 = wards 192-200 — GCC official ranges)
if "WARD_NO" in slums_near_omr.columns and "ZONE_NO" in slums_near_omr.columns:
    zone_ranges = {14: (183, 191), 15: (192, 200)}
    def in_range(row):
        r = zone_ranges.get(row["ZONE_NO"])
        return r[0] <= row["WARD_NO"] <= r[1] if r else True
    valid = slums_near_omr.apply(in_range, axis=1).sum()
    print(f"[SANITY CHECK] Ward/zone range validation: {valid} / {len(slums_near_omr)} pass "
          f"(note: ward numbers may reflect pre-2018 delimitation — see methodology notes)")


# ============================================================================
# STEP 6 — Metro Purple Line stations (Corridor 3 — runs directly along OMR)
# SOURCE: names from CMRL official station list; coordinates AI-estimated
# (Google Maps "Ask Maps"), sanity-checked via spacing + Sholinganallur match
# NAMING NOTE: Corridor 3 = Purple Line (this one, along OMR). Corridor 5 =
# Red Line (the separate interior line added in Step 7B, via Medavakkam/
# Perumbakkam). These were mislabeled swapped in an earlier draft — verified
# against CMRL/Wikipedia before finalizing.
# ============================================================================
print("\n" + "=" * 70); print("STEP 6: Metro Purple Line stations (Corridor 3, along OMR)"); print("=" * 70)

metro_stations = [
    # --- Underground Segment (Mylapore & Adyar Regions) ---
    # {"name": "Thirumayilai", "lat": 13.0331, "lon": 80.2694, "type": "Underground"},
    # {"name": "Mandaiveli", "lat": 13.0232, "lon": 80.2671, "type": "Underground"},
    # {"name": "Greenways Road", "lat": 13.0185, "lon": 80.2594, "type": "Underground"},
    {"name": "Adyar Junction", "lat": 13.0065, "lon": 80.2572, "type": "Underground"},
    
    # --- Micro-Adjusted Segment ---
    {"name": "Adyar Depot", "lat": 12.9972, "lon": 80.2555, "type": "Underground"},          # Shifted slightly West
    {"name": "Indira Nagar", "lat": 12.9955, "lon": 80.2515, "type": "Underground"},
    {"name": "Thiruvanmiyur", "lat": 12.9892, "lon": 80.2520, "type": "Underground"},
    {"name": "Taramani", "lat": 12.9805, "lon": 80.2528, "type": "Underground"},            # Shifted slightly East

    # --- Elevated Segment (The Upper OMR Stretch - Locked) ---
    {"name": "Nehru Nagar", "lat": 12.9675, "lon": 80.2490, "type": "Elevated"},
    {"name": "Kandanchavadi", "lat": 12.9610, "lon": 80.2460, "type": "Elevated"},
    {"name": "Perungudi", "lat": 12.9526, "lon": 80.2428, "type": "Elevated"},
    {"name": "Thoraipakkam", "lat": 12.9436, "lon": 80.2395, "type": "Elevated"},
    {"name": "Mettukuppam", "lat": 12.9355, "lon": 80.2341, "type": "Elevated"},
    {"name": "PTC Colony", "lat": 12.9288, "lon": 80.2325, "type": "Elevated"},
    {"name": "Okkiyampet", "lat": 12.9214, "lon": 80.2309, "type": "Elevated"},
    {"name": "Karapakkam", "lat": 12.9134, "lon": 80.2298, "type": "Elevated"},
    {"name": "Okkiyam Thoraipakkam", "lat": 12.9065, "lon": 80.2295, "type": "Elevated"},
    {"name": "Sholinganallur", "lat": 12.9011, "lon": 80.2269, "type": "Elevated"},
    {"name": "Sholinganallur Lake I", "lat": 12.8945, "lon": 80.2265, "type": "Elevated"},
    {"name": "Sholinganallur Lake II", "lat": 12.8875, "lon": 80.2262, "type": "Elevated"},
    {"name": "Semmancheri Depot", "lat": 12.8795, "lon": 80.2259, "type": "Elevated"},
    {"name": "Semmancheri I", "lat": 12.8715, "lon": 80.2254, "type": "Elevated"},
    {"name": "Semmancheri II", "lat": 12.8630, "lon": 80.2248, "type": "Elevated"},

    # --- Southern OMR Tail Segments (Locked) ---
    {"name": "Gandhi Nagar", "lat": 12.8545, "lon": 80.2255, "type": "Elevated"},
    {"name": "Navallur", "lat": 12.8465, "lon": 80.2258, "type": "Elevated"},
    {"name": "Siruseri", "lat": 12.8378, "lon": 80.2272, "type": "Elevated"},
    {"name": "SIPCOT 1", "lat": 12.8305, "lon": 80.2285, "type": "Elevated"},
    {"name": "SIPCOT 2", "lat": 12.8231, "lon": 80.2310, "type": "Elevated"}
]

metro_df = pd.DataFrame(metro_stations)
metro_gdf = gpd.GeoDataFrame(metro_df, geometry=gpd.points_from_xy(metro_df["lon"], metro_df["lat"]),
                              crs="EPSG:4326")
metro_gdf_m = metro_gdf.to_crs(CRS_METRIC)

spacing = metro_gdf_m.geometry.distance(metro_gdf_m.geometry.shift(-1))
print(f"[SANITY CHECK] Station count: {len(metro_gdf)}, median spacing: {spacing.median():.0f}m "
      f"(real metro spacing is typically 400-2500m)")


# ============================================================================
# STEP 7 — Purple Line coverage: CORRECTED true walking distance
# FIX: a naive isochrone silently absorbs the entry-snap distance into the
# walk budget (confirmed bug: gave 0 covered schools when 7 were within
# straight-line 500m). This computes entry_snap + network_path + exit_snap
# explicitly instead.
# ============================================================================
print("\n" + "=" * 70); print("STEP 7: Purple Line coverage — corrected walking distance"); print("=" * 70)

timed_start("STEP 7 — Purple Line Dijkstra")
purple_cache = f"{CACHE_PREFIX}_purple_station_data.pkl"

if cache_exists(purple_cache):
    station_data = load_pickle(purple_cache)
else:
    station_data = []
    for _, station in metro_gdf_m.iterrows():
        pt = station.geometry
        nearest_node = ox.distance.nearest_nodes(G_walk, X=pt.x, Y=pt.y)
        node_pt = ShapelyPoint(
            G_walk.nodes[nearest_node]["x"],
            G_walk.nodes[nearest_node]["y"]
        )
        entry_snap = pt.distance(node_pt)
        lengths = nx.single_source_dijkstra_path_length(
            G_walk, nearest_node, cutoff=1500, weight="length"
        )
        station_data.append({
            "name": station["name"],
            "entry_snap": entry_snap,
            "node": nearest_node,
            "lengths": lengths
        })
    save_pickle(station_data, purple_cache)

print(f"[SANITY CHECK] Stations processed: {len(station_data)}")
timed_end("STEP 7 — Purple Line Dijkstra")

def true_walking_distance(dest_point, station_data, G_walk):
    dest_node = ox.distance.nearest_nodes(G_walk, X=dest_point.x, Y=dest_point.y)
    dest_node_pt = ShapelyPoint(G_walk.nodes[dest_node]["x"], G_walk.nodes[dest_node]["y"])
    exit_snap = dest_point.distance(dest_node_pt)
    best = float("inf")
    for s in station_data:
        network_dist = s["lengths"].get(dest_node)
        if network_dist is not None:
            best = min(best, s["entry_snap"] + network_dist + exit_snap)
    return best

schools_omr["true_metro_dist"] = schools_omr["centroid"].apply(
    lambda pt: true_walking_distance(pt, station_data, G_walk))
schools_omr["metro_covered"] = schools_omr["true_metro_dist"] <= WALK_DIST_M

hospitals_omr["true_metro_dist"] = hospitals_omr["centroid"].apply(
    lambda pt: true_walking_distance(pt, station_data, G_walk))
hospitals_omr["metro_covered"] = hospitals_omr["true_metro_dist"] <= WALK_DIST_M

slums_near_omr["centroid"] = slums_near_omr.geometry.centroid
slums_near_omr["true_metro_dist"] = slums_near_omr["centroid"].apply(
    lambda pt: true_walking_distance(pt, station_data, G_walk))
slums_near_omr["metro_covered"] = slums_near_omr["true_metro_dist"] <= WALK_DIST_M

print(f"[RESULT] Schools metro-covered: {schools_omr['metro_covered'].sum()} / {len(schools_omr)}")
print(f"[RESULT] Hospitals metro-covered: {hospitals_omr['metro_covered'].sum()} / {len(hospitals_omr)}")
print(f"[RESULT] Slums metro-covered: {slums_near_omr['metro_covered'].sum()} / {len(slums_near_omr)}")


# ============================================================================
# STEP 7B — Red Line (Corridor 5): Kilkattalai to Sholinganallur stretch
# ADDED after discovering the OMR-corridor buffer legitimately includes
# Medavakkam/Perumbakkam (844m / 1884m from OMR — inside the 2km buffer),
# and that stretch is served by a SEPARATE metro line approaching from the
# interior, not the Purple Line along OMR itself. Coordinates cross-checked:
# Sholinganallur matches the independently-confirmed Wikipedia coordinate
# to within 4m — a strong validation anchor for the rest of this list.
# ============================================================================
print("\n" + "=" * 70); print("STEP 7B: Red Line (Medavakkam/Perumbakkam stretch)"); print("=" * 70)

red_line_stations = [
    # --- Upper Segment (Locked) ---
    {"name": "Kilkattalai", "lat": 12.9565, "lon": 80.1872, "type": "Elevated"},
    {"name": "Echangadu", "lat": 12.9475, "lon": 80.1852, "type": "Elevated"},
    {"name": "Kovilambakkam", "lat": 12.9395, "lon": 80.1825, "type": "Elevated"},
    {"name": "Vellakkal", "lat": 12.9320, "lon": 80.1818, "type": "Elevated"},
    {"name": "Medavakkam I", "lat": 12.9230, "lon": 80.1834, "type": "Elevated"},
    
    # --- Targeted Micro-Adjustment (North & East) ---
    {"name": "Medavakkam II", "lat": 12.9172, "lon": 80.1932, "type": "Elevated"}, # Shifted slightly North & East
    
    # --- Southern Segment (Locked) ---
    {"name": "Perumbakkam", "lat": 12.9085, "lon": 80.2015, "type": "Elevated"},
    {"name": "Classical Tamil Institute", "lat": 12.9048, "lon": 80.2090, "type": "Elevated"},
    {"name": "Elcot", "lat": 12.9022, "lon": 80.2185, "type": "Elevated"},
    {"name": "Sholinganallur", "lat": 12.9012, "lon": 80.2279, "type": "Elevated"}     
]
red_df = pd.DataFrame(red_line_stations)
red_gdf = gpd.GeoDataFrame(red_df, geometry=gpd.points_from_xy(red_df["lon"], red_df["lat"]), crs=4326)
red_gdf_m = red_gdf.to_crs(CRS_METRIC)

spacing_check = red_gdf_m.geometry.distance(red_gdf_m.geometry.shift(-1))
print(f"[SANITY CHECK] Red Line spacing: min={spacing_check.min():.0f}m, "
      f"median={spacing_check.median():.0f}m, max={spacing_check.max():.0f}m "
      f"(real metro spacing typically 400-2500m)")

timed_start("STEP 7B — Red Line Dijkstra")
red_cache = f"{CACHE_PREFIX}_red_station_data.pkl"

if cache_exists(red_cache):
    red_station_data = load_pickle(red_cache)
else:
    red_station_data = []
    for _, station in red_gdf_m.iterrows():
        pt = station.geometry
        nearest_node = ox.distance.nearest_nodes(G_walk, X=pt.x, Y=pt.y)
        node_pt = ShapelyPoint(
            G_walk.nodes[nearest_node]["x"],
            G_walk.nodes[nearest_node]["y"]
        )
        entry_snap = pt.distance(node_pt)
        lengths = nx.single_source_dijkstra_path_length(
            G_walk, nearest_node, cutoff=1500, weight="length"
        )
        red_station_data.append({
            "name": station["name"],
            "entry_snap": entry_snap,
            "lengths": lengths
        })
    save_pickle(red_station_data, red_cache)

print(f"[SANITY CHECK] Red Line stations processed: {len(red_station_data)}")
timed_end("STEP 7B — Red Line Dijkstra")

all_station_data = station_data + red_station_data  # Purple Line (OMR) + Red Line (interior) combined

for df in [schools_omr, hospitals_omr, slums_near_omr]:
    df["metro_covered_red_only"] = df["centroid"].apply(
        lambda pt: true_walking_distance(pt, red_station_data, G_walk)) <= WALK_DIST_M
    df["metro_covered_either_line"] = df["centroid"].apply(
        lambda pt: true_walking_distance(pt, all_station_data, G_walk)) <= WALK_DIST_M

print(f"\n[RESULT] Schools — Purple Line: {schools_omr['metro_covered'].sum()}, "
      f"Red Line: {schools_omr['metro_covered_red_only'].sum()}, "
      f"Either line: {schools_omr['metro_covered_either_line'].sum()} / {len(schools_omr)}")
print(f"[RESULT] Hospitals — Purple Line: {hospitals_omr['metro_covered'].sum()}, "
      f"Red Line: {hospitals_omr['metro_covered_red_only'].sum()}, "
      f"Either line: {hospitals_omr['metro_covered_either_line'].sum()} / {len(hospitals_omr)}")
print(f"[RESULT] Slums — Purple Line: {slums_near_omr['metro_covered'].sum()}, "
      f"Red Line: {slums_near_omr['metro_covered_red_only'].sum()}, "
      f"Either line: {slums_near_omr['metro_covered_either_line'].sum()} / {len(slums_near_omr)}")


# ============================================================================
# STEP 8 — Combined bus vs metro comparison
# ============================================================================
print("\n" + "=" * 70); print("STEP 8: Combined bus vs metro comparison"); print("=" * 70)

def summarize(df, bus_col, metro_col, label, invert_bus=False):
    bus_c = (~df[bus_col] if invert_bus else df[bus_col])
    metro_c = df[metro_col]
    total = len(df)
    result = {"label": label, "total": total,
              "bus_only": int((bus_c & ~metro_c).sum()),
              "metro_only": int((~bus_c & metro_c).sum()),
              "both": int((bus_c & metro_c).sum()),
              "neither": int((~bus_c & ~metro_c).sum())}
    print(f"\n{label} (n={total}): bus_only={result['bus_only']}, metro_only={result['metro_only']}, "
          f"both={result['both']}, neither={result['neither']} "
          f"({result['neither']/total:.1%} gap)")
    return result

summary_rows = [
    summarize(schools_omr, "bus_covered", "metro_covered_either_line", "Schools (Purple+Red Line)"),
    summarize(hospitals_omr, "bus_covered", "metro_covered_either_line", "Hospitals (Purple+Red Line)"),
    summarize(slums_near_omr, "outside_isochrone", "metro_covered_either_line", "Slums (Purple+Red Line)", invert_bus=True),
]
pd.DataFrame(summary_rows).to_csv("bus_metro_comparison_summary.csv", index=False)
print("\nSaved: bus_metro_comparison_summary.csv")


# ============================================================================
# STEP 9 — GCC ward boundaries: load, validate, filter to OMR
# SOURCE: Chennai GCC Ward Map 2022 KML (opencity.in, sourced from Chennai
# Corporation) — confirmed 200 wards, current delimitation scheme
# ============================================================================
print("\n" + "=" * 70); print(f"STEP 9: Ward boundaries from {WARD_KML_PATH}"); print("=" * 70)

timed_start("STEP 9 — GCC ward source")
wards_cache = f"{CACHE_PREFIX}_wards_metric.pkl"

if cache_exists(wards_cache):
    wards_m = load_gdf(wards_cache)
    print(f"[CACHE] Ward count: {len(wards_m)}")
else:
    wards = gpd.read_file(WARD_KML_PATH, driver="KML")
    print(f"[SANITY CHECK] Ward count: {len(wards)} "
          f"({'OK — 200 confirmed' if len(wards) == 200 else 'WARNING — expected 200'})")
    wards_m = wards.to_crs(CRS_METRIC)
    save_gdf(wards_m, wards_cache)

timed_end("STEP 9 — GCC ward source")
name_col = next((c for c in wards_m.columns if "name" in c.lower() or "ward" in c.lower()), wards_m.columns[0])
wards_m[name_col] = wards_m[name_col].astype(str).str.strip()

wards_near_omr_all_intersecting = wards_m[wards_m.geometry.intersects(omr_buffer_wide)].copy()
print(f"[RESULT] Wards geometrically near OMR (raw buffer intersect): "
      f"{len(wards_near_omr_all_intersecting)} of {len(wards_m)} total")

# FIX: restrict to OMR_STUDY_WARDS — the raw buffer intersect above includes
# wards later confirmed NOT to genuinely belong in this analysis (e.g. 174 is
# Besant Nagar, 189/197 are shielded from OMR by neighboring wards). Every
# downstream step (10, 10B) now uses this restricted set, not the raw one.
wards_near_omr = wards_near_omr_all_intersecting[
    wards_near_omr_all_intersecting[name_col].astype(str).astype(int).isin(OMR_STUDY_WARDS)
].copy()
print(f"[RESULT] Wards after OMR_STUDY_WARDS scope: {len(wards_near_omr)} "
      f"(excluded {len(wards_near_omr_all_intersecting) - len(wards_near_omr)}: "
      f"{sorted(set(wards_near_omr_all_intersecting[name_col].astype(int)) - set(OMR_STUDY_WARDS))})")

omr_study_ward_union = wards_near_omr.geometry.union_all()

# # Southernmost extent of the main script's actual study scope
study_wards_union_4326 = wards_near_omr.to_crs(4326).geometry.union_all()
south_bound_exact = study_wards_union_4326.bounds[1]  # (minx, miny, maxx, maxy) -> miny = southernmost lat
print(f"Southernmost latitude of OMR_STUDY_WARDS: {south_bound_exact:.6f}")
# exit(0)
# ============================================================================
# STEP 9B — Re-scope facility/slum totals to OMR_STUDY_WARDS
# Steps 2-8 filtered schools/hospitals/slums/bus stops using the raw 2km
# road buffer (omr_buffer_wide), which — same as the raw ward intersect
# above — includes areas later excluded from the study scope. This step
# re-derives the FINAL, ward-consistent totals. Treat Step 4/5/8's earlier
# numbers as a broader pre-scoping pass, not the reportable figures —
# everything from here on (and Steps 10/10B/11) uses the scoped versions.
# ============================================================================
print("\n" + "=" * 70); print("STEP 9B: Re-scoping facilities/slums to OMR_STUDY_WARDS"); print("=" * 70)

schools_omr_prescope = len(schools_omr)
hospitals_omr_prescope = len(hospitals_omr)
slums_near_omr_prescope = len(slums_near_omr)

schools_omr = schools_omr[schools_omr["centroid"].within(omr_study_ward_union)].copy()
hospitals_omr = hospitals_omr[hospitals_omr["centroid"].within(omr_study_ward_union)].copy()
slums_near_omr = slums_near_omr[
    slums_near_omr.geometry.centroid.within(omr_study_ward_union)
].copy()

print(f"[RESULT] Schools: {schools_omr_prescope} (broad buffer) -> {len(schools_omr)} (ward-scoped)")
print(f"[RESULT] Hospitals: {hospitals_omr_prescope} (broad buffer) -> {len(hospitals_omr)} (ward-scoped)")
print(f"[RESULT] Slums: {slums_near_omr_prescope} (broad buffer) -> {len(slums_near_omr)} (ward-scoped)")
print("[NOTE] These are now the FINAL, reportable counts. Step 4/5/8 numbers "
      "printed earlier reflect the broader pre-scoping pass and should not be "
      "quoted as the headline figures.")

# Re-print the headline comparison with the corrected, scoped counts
schools_bus_scoped = schools_omr["bus_covered"].sum()
hospitals_bus_scoped = hospitals_omr["bus_covered"].sum()
print(f"\n[RESULT] Schools bus-covered (ward-scoped): {schools_bus_scoped} / {len(schools_omr)}")
print(f"[RESULT] Hospitals bus-covered (ward-scoped): {hospitals_bus_scoped} / {len(hospitals_omr)}")

# Regenerate the bus/metro comparison CSV using the final, ward-scoped data —
# the version saved during Step 8 reflected the broader pre-scoping pass.
summary_rows_scoped = [
    summarize(schools_omr, "bus_covered", "metro_covered_either_line", "Schools (Purple+Red Line, ward-scoped)"),
    summarize(hospitals_omr, "bus_covered", "metro_covered_either_line", "Hospitals (Purple+Red Line, ward-scoped)"),
    summarize(slums_near_omr, "outside_isochrone", "metro_covered_either_line", "Slums (Purple+Red Line, ward-scoped)", invert_bus=True),
]
pd.DataFrame(summary_rows_scoped).to_csv("bus_metro_comparison_summary.csv", index=False)
print("\n[NOTE] bus_metro_comparison_summary.csv OVERWRITTEN with ward-scoped figures — "
      "this is now the reportable version.")


# ============================================================================
# STEP 10 — Ward-wise breakdown (schools, hospitals, slum area)
# ============================================================================
print("\n" + "=" * 70); print("STEP 10: Ward-wise breakdown"); print("=" * 70)

schools_ward_join = gpd.sjoin(
    schools_omr.set_geometry("centroid")[["centroid", "bus_covered", "metro_covered", "metro_covered_either_line"]],
    wards_near_omr[[name_col, "geometry"]], how="inner", predicate="within")
hospitals_ward_join = gpd.sjoin(
    hospitals_omr.set_geometry("centroid")[["centroid", "bus_covered", "metro_covered", "metro_covered_either_line"]],
    wards_near_omr[[name_col, "geometry"]], how="inner", predicate="within")

school_summary = schools_ward_join.groupby(name_col).agg(
    schools_total=("bus_covered", "count"), schools_bus_covered=("bus_covered", "sum"),
    schools_metro_covered=("metro_covered_either_line", "sum")).reset_index()
hospital_summary = hospitals_ward_join.groupby(name_col).agg(
    hospitals_total=("bus_covered", "count"), hospitals_bus_covered=("bus_covered", "sum"),
    hospitals_metro_covered=("metro_covered_either_line", "sum")).reset_index()

slums_pts = slums_near_omr.copy()
slums_pts = slums_pts.set_geometry("centroid")
slums_ward_join = gpd.sjoin(
    slums_pts[["centroid", "outside_isochrone", "metro_covered_either_line", "total_area_sqm", "area_outside_isochrone"]],
    wards_near_omr[[name_col, "geometry"]], how="left", predicate="within")
slums_ward_join["area_ha"] = slums_ward_join["total_area_sqm"] / 10000
slums_ward_join["area_outside_bus_ha"] = slums_ward_join["area_outside_isochrone"] / 10000
slums_ward_join["area_outside_metro_ha"] = slums_ward_join.apply(
    lambda r: 0 if r["metro_covered_either_line"] else r["area_ha"], axis=1)
slum_summary = slums_ward_join.groupby(name_col).agg(
    slum_count=("area_ha", "count"), slum_area_total_ha=("area_ha", "sum"),
    slum_area_outside_bus_ha=("area_outside_bus_ha", "sum"),
    slum_area_outside_metro_ha=("area_outside_metro_ha", "sum")).reset_index()

final_ward_table = wards_near_omr[[name_col]].merge(school_summary, on=name_col, how="left") \
    .merge(hospital_summary, on=name_col, how="left").merge(slum_summary, on=name_col, how="left").fillna(0)

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)

# Shortened column names — DISPLAY ONLY, the saved CSV keeps full descriptive names
short_names = {
    "schools_total": "sch_tot", "schools_bus_covered": "sch_bus", "schools_metro_covered": "sch_metro",
    "hospitals_total": "hos_tot", "hospitals_bus_covered": "hos_bus", "hospitals_metro_covered": "hos_metro",
    "slum_count": "slm_cnt", "slum_area_total_ha": "slm_ha", "slum_area_outside_bus_ha": "slm_out_bus",
    "slum_area_outside_metro_ha": "slm_out_metro",
}
print(final_ward_table.rename(columns=short_names).round(1).to_string(index=False))
final_ward_table.to_csv("ward_wise_summary.csv", index=False)
print("\nSaved: ward_wise_summary.csv")


# ============================================================================
# STEP 10B — Priority wards: rank by "neither bus nor metro" gap
# Combines schools + hospitals + slum area into one composite score so
# wards can be ranked, not just tabulated. Score is unitless (normalized
# 0-1 per metric, summed) — meant for RANKING, not as an absolute measure.
# ============================================================================
print("\n" + "=" * 70); print("STEP 10B: Priority wards"); print("=" * 70)

# "Neither" per facility, computed directly from the join tables built in Step 10
schools_ward_join["neither"] = ~schools_ward_join["bus_covered"] & ~schools_ward_join["metro_covered_either_line"]
hospitals_ward_join["neither"] = ~hospitals_ward_join["bus_covered"] & ~hospitals_ward_join["metro_covered_either_line"]

schools_neither = schools_ward_join.groupby(name_col)["neither"].sum().rename("schools_neither")
hospitals_neither = hospitals_ward_join.groupby(name_col)["neither"].sum().rename("hospitals_neither")

slums_ward_join["neither_area_ha"] = slums_ward_join.apply(
    lambda r: r["area_ha"] if (r["outside_isochrone"] and not r["metro_covered_either_line"]) else 0, axis=1)
slum_neither_area = slums_ward_join.groupby(name_col)["neither_area_ha"].sum().rename("slum_neither_area_ha")

priority = final_ward_table[[name_col]].merge(schools_neither, on=name_col, how="left") \
    .merge(hospitals_neither, on=name_col, how="left") \
    .merge(slum_neither_area, on=name_col, how="left").fillna(0)

# Min-max normalize each metric to 0-1, sum for a composite score
for col in ["schools_neither", "hospitals_neither", "slum_neither_area_ha"]:
    rng = priority[col].max() - priority[col].min()
    priority[f"{col}_norm"] = (priority[col] - priority[col].min()) / rng if rng > 0 else 0

priority["priority_score"] = (
    priority["schools_neither_norm"] + priority["hospitals_neither_norm"] + priority["slum_neither_area_ha_norm"]
)
priority = priority.sort_values("priority_score", ascending=False)

print("Priority wards (highest gap first):")
priority_short_names = {
    "schools_neither": "sch_gap", "hospitals_neither": "hos_gap",
    "slum_neither_area_ha": "slm_gap_ha", "priority_score": "score"
}
print(priority[[name_col, "schools_neither", "hospitals_neither", "slum_neither_area_ha",
                 "priority_score"]].rename(columns=priority_short_names).round(2).to_string(index=False))

priority.to_csv("priority_wards.csv", index=False)
print("\nSaved: priority_wards.csv")
print("[NOTE] priority_score is a normalized ranking aid, not an absolute measure — "
      "use for ordering wards, not for claiming a precise magnitude of need.")


# ============================================================================
# STEP 11 — True outside-GCC test (against the FULL 200-ward layer, not
# just the 15-ward near-OMR subset — that distinction was a real bug found
# and fixed: a facility can be inside GCC without being near OMR)
# ============================================================================
print("\n" + "=" * 70); print("STEP 11: True outside-GCC facilities"); print("=" * 70)

full_name_col = name_col
schools_gcc_join = gpd.sjoin(
    schools_omr.set_geometry("centroid")[["centroid", "bus_covered", "metro_covered"]],
    wards_m[[full_name_col, "geometry"]], how="left", predicate="within")
hospitals_gcc_join = gpd.sjoin(
    hospitals_omr.set_geometry("centroid")[["centroid", "bus_covered", "metro_covered"]],
    wards_m[[full_name_col, "geometry"]], how="left", predicate="within")

schools_outside_gcc = schools_gcc_join[schools_gcc_join[full_name_col].isna()]
hospitals_outside_gcc = hospitals_gcc_join[hospitals_gcc_join[full_name_col].isna()]

print(f"[RESULT] Schools outside GCC: {len(schools_outside_gcc)} / {len(schools_omr)}")
print(f"[RESULT] Hospitals outside GCC: {len(hospitals_outside_gcc)} / {len(hospitals_omr)}")
print("[NOTE] Verified via nearest-ward distance: outside-GCC facilities range from near-boundary "
      "cases (<500m, e.g. Perumbakkam) to genuinely distant Chengalpattu-district locations "
      "(e.g. Guduvancheri, ~4.2km) — a real mix, not a data artifact.")

def outside_gcc_stats(df, label):
    if len(df) == 0:
        return {"label": label, "total": 0, "bus_covered": 0, "metro_covered": 0, "neither": 0}
    total = len(df)
    bus_c, metro_c = df["bus_covered"].sum(), df["metro_covered"].sum()
    neither = (~df["bus_covered"] & ~df["metro_covered"]).sum()
    print(f"{label} (n={total}): bus={bus_c} ({bus_c/total:.1%}), metro={metro_c} ({metro_c/total:.1%}), "
          f"neither={neither} ({neither/total:.1%})")
    return {"label": label, "total": total, "bus_covered": int(bus_c),
            "metro_covered": int(metro_c), "neither": int(neither)}

outside_results = [outside_gcc_stats(schools_outside_gcc, "Schools outside GCC"),
                    outside_gcc_stats(hospitals_outside_gcc, "Hospitals outside GCC")]
print("Slums outside GCC: 0 (slum layer source only covers GCC's own zone/ward system)")
pd.DataFrame(outside_results).to_csv("outside_gcc_summary.csv", index=False)
print("Saved: outside_gcc_summary.csv")


# ============================================================================
# STEP 12 — Save all layers + full interactive map
# ============================================================================

def get_mtro_isochrone(station_data):
    metro_reachable_nodes = set()

    for s in station_data:
        for node, network_dist in s["lengths"].items():
            if s["entry_snap"] + network_dist <= WALK_DIST_M:
                metro_reachable_nodes.add(node)

    metro_node_points = [
        ShapelyPoint(
            G_walk.nodes[n]["x"],
            G_walk.nodes[n]["y"]
        )
        for n in metro_reachable_nodes
    ]

    metro_walking_isochrone = (
        gpd.GeoSeries(
            metro_node_points,
            crs=CRS_METRIC
        )
        .buffer(30)
        .union_all()
    )

    return metro_walking_isochrone

purple_iso_cache = f"{CACHE_PREFIX}_purple_isochrone.pkl"
red_iso_cache = f"{CACHE_PREFIX}_red_isochrone.pkl"

if cache_exists(purple_iso_cache):
    purple_line_isochrone = load_pickle(purple_iso_cache)
else:
    purple_line_isochrone = get_mtro_isochrone(station_data)
    save_pickle(purple_line_isochrone, purple_iso_cache)

print(
    f"[MAP] Purple Metro walking catchment: "
    f"{purple_line_isochrone.area / 1_000_000:.2f} sq km"
)

if cache_exists(red_iso_cache):
    red_line_isochrone = load_pickle(red_iso_cache)
else:
    red_line_isochrone = get_mtro_isochrone(red_station_data)
    save_pickle(red_line_isochrone, red_iso_cache)

print(
    f"[MAP] Red Metro walking catchment: "
    f"{red_line_isochrone.area / 1_000_000:.2f} sq km"
)

print("Red geometry:", red_line_isochrone.geom_type)
print("Red empty:", red_line_isochrone.is_empty)
print("Red bounds:", red_line_isochrone.bounds)
print("Red area:", red_line_isochrone.area)

red_wgs = gpd.GeoSeries(
    [red_line_isochrone], crs=CRS_METRIC
).to_crs(4326)

print("Red WGS84 bounds:", red_wgs.total_bounds)

print("\n" + "=" * 70); print("STEP 12: Saving outputs + map"); print("=" * 70)

for df, name in [(schools_omr, "schools"), (hospitals_omr, "hospitals")]:
    df["true_metro_dist"] = df["true_metro_dist"].replace(float("inf"), 999999)
    df.drop(columns=["centroid"], errors="ignore").to_crs(4326).to_file(
        f"output_{name}_final.geojson", driver="GeoJSON")
slums_near_omr["true_metro_dist"] = slums_near_omr["true_metro_dist"].replace(float("inf"), 999999)
slums_near_omr.drop(columns=["centroid"], errors="ignore").to_crs(4326).to_file(
    "output_slums_final.geojson", driver="GeoJSON")
wards_near_omr.to_crs(4326).to_file("output_wards_near_omr.geojson", driver="GeoJSON")

import folium
from folium.plugins import Fullscreen

m = folium.Map(location=[12.90, 80.21], zoom_start=12, tiles="cartodbpositron")
Fullscreen().add_to(m)

fg = folium.FeatureGroup(name="OMR road", show=True)
folium.GeoJson(omr_edges.to_crs(4326), style_function=lambda x: {"color": "black", "weight": 2}).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Bus isochrone — OSM (legacy, not used in metrics)", show=False)
gpd.GeoDataFrame(geometry=[isochrone_shape_osm_legacy], crs=CRS_METRIC).to_crs(4326).apply(
    lambda r: folium.GeoJson(r.geometry.__geo_interface__,
        style_function=lambda x: {"fillColor": "black", "color": "black", "weight": 1, "fillOpacity": 0.15}
    ).add_to(fg), axis=1)
fg.add_to(m)

fg = folium.FeatureGroup(name="Bus isochrone — MTC GTFS (used in all metrics)", show=True)
gpd.GeoDataFrame(geometry=[mtc_bus_isochrone], crs=CRS_METRIC).to_crs(4326).apply(
    lambda r: folium.GeoJson(r.geometry.__geo_interface__,
        style_function=lambda x: {"fillColor": "blue", "color": "blue", "weight": 1, "fillOpacity": 0.15}
    ).add_to(fg), axis=1)
fg.add_to(m)

fg = folium.FeatureGroup(name="Purple Line coverage (500m walking, OMR)", show=True)
gpd.GeoDataFrame(
    geometry=[purple_line_isochrone],
    crs=CRS_METRIC
).to_crs(4326).apply(
    lambda r: folium.GeoJson(
        r.geometry.__geo_interface__,
        style_function=lambda x: {
            "fillColor": "purple",
            "color": "purple",
            "weight": 1,
            "fillOpacity": 0.15
        }
    ).add_to(fg),
    axis=1
)
fg.add_to(m)

fg = folium.FeatureGroup(name="Red Line coverage (500m walking, OMR)", show=True)
gpd.GeoDataFrame(
    geometry=[red_line_isochrone],
    crs=CRS_METRIC
).to_crs(4326).apply(
    lambda r: folium.GeoJson(
        r.geometry.__geo_interface__,
        style_function=lambda x: {
            "fillColor": "red",
            "color": "red",
            "weight": 1,
            "fillOpacity": 0.15
        }
    ).add_to(fg),
    axis=1
)
fg.add_to(m)

fg = folium.FeatureGroup(name="Bus stops — OSM (legacy, not used in metrics)", show=False)
for _, row in bus_stops_omr.to_crs(4326).iterrows():
    pt = row.geometry.centroid
    folium.CircleMarker([pt.y, pt.x], radius=3, color="black", fill=True, fill_opacity=0.8).add_to(fg)
fg.add_to(m)

mtc_stops_map = mtc_stops_gdf.to_crs("EPSG:4326")
fg = folium.FeatureGroup(name="Bus stops — MTC GTFS (used in all metrics)", show=True)
for _, row in mtc_stops_map.iterrows():
    pt = row.geometry
    folium.CircleMarker([pt.y, pt.x], radius=3, color="blue", fill=True, fill_opacity=0.8,
                         popup=row.get("stop_name", "")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Metro stations — Purple Line (OMR)", show=True)
for _, row in metro_gdf.iterrows():
    folium.CircleMarker([row["lat"], row["lon"]], radius=7, color="purple", fill=True,
                         fill_opacity=0.9, popup=row["name"]).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Metro stations — Red Line (interior)", show=True)
for _, row in red_gdf.iterrows():
    folium.CircleMarker([row["lat"], row["lon"]], radius=7, color="red", fill=True,
                         fill_opacity=0.9, popup=row["name"]).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Schools", show=True)
for _, row in schools_omr.to_crs(4326).iterrows():
    pt = row.geometry.centroid if row.geometry.geom_type != "Point" else row.geometry
    color = "green" if (row["bus_covered"] or row["metro_covered"]) else "red"
    folium.CircleMarker([pt.y, pt.x], radius=5, color=color, fill=True, fill_opacity=0.8,
                         popup=row.get("name", "school")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Hospitals", show=True)
for _, row in hospitals_omr.to_crs(4326).iterrows():
    pt = row.geometry.centroid if row.geometry.geom_type != "Point" else row.geometry
    color = "green" if (row["bus_covered"] or row["metro_covered"]) else "orange"
    folium.CircleMarker([pt.y, pt.x], radius=5, color=color, fill=True, fill_opacity=0.8,
                         popup=row.get("name", "hospital")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Slums", show=True)
for _, row in slums_near_omr.to_crs(4326).iterrows():
    covered = (not row["outside_isochrone"]) or row["metro_covered"]
    color = "green" if covered else "darkred"
    folium.GeoJson(row.geometry.__geo_interface__,
        style_function=lambda x, c=color: {"fillColor": c, "color": c, "weight": 1, "fillOpacity": 0.5},
        tooltip=row.get("SLUM_NAME", "slum")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="GCC wards (near OMR)", show=False)
folium.GeoJson(wards_near_omr.to_crs(4326),
               style_function=lambda x: {"fillColor": "none", "color": "gray", "weight": 1}).add_to(fg)
for _, row in wards_near_omr.to_crs(4326).iterrows():
    label_pt = row.geometry.centroid
    folium.Marker(
        [label_pt.y, label_pt.x],
        icon=folium.DivIcon(html=f'<div style="font-size:11pt;font-weight:bold;color:black;'
                                  f'text-shadow:1px 1px 2px white,-1px -1px 2px white">'
                                  f'{row[name_col]}</div>')
    ).add_to(fg)
fg.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.save("omr_full_map.html")

print("Saved: output_schools_final.geojson, output_hospitals_final.geojson,")
print("       output_slums_final.geojson, output_wards_near_omr.geojson, omr_full_map.html")


# ============================================================================
# POPULATION NOTE (not computed — see script docstring)
# ============================================================================
print("\n" + "=" * 70)
print("POPULATION: not included in this script.")
print("Methodology note for presentation:")
print('"Population data (WorldPop) could not be retrieved within the project')
print('timeline. Synchronous and asynchronous WorldPop APIs, direct windowed')
print('raster access, and Google Earth Engine were each attempted and hit')
print('confirmed technical blockers (server errors, unsupported range')
print('requests, and platform-specific client library issues respectively).')
print('Boundary layers (wards, slums) are validated and ready for population')
print('once a working source exists — most likely a colleague\'s already-')
print('clipped WorldPop raster from QGIS."')
print("=" * 70)

#

# --------------------------------------------------
# 1. Load data
# --------------------------------------------------

timed_start("BUILDINGS — load/project")
buildings_cache = f"{CACHE_PREFIX}_buildings_metric.pkl"
if cache_exists(buildings_cache):
    buildings_m = load_gdf(buildings_cache)
else:
    buildings = gpd.read_file("buildings.geojson")
    buildings_m = buildings.to_crs(CRS_METRIC).copy()
    save_gdf(buildings_m, buildings_cache)

wards_near_omr_m = wards_near_omr.to_crs(CRS_METRIC).copy()
print(f"[SANITY CHECK] Buildings loaded: {len(buildings_m)}")
timed_end("BUILDINGS — load/project")


# ------------------------------------------------------------
# 1. Residential classification
# ------------------------------------------------------------

explicit_residential = {
    "residential",
    "apartments",
    "house",
    "detached",
    "semidetached_house",
    "terrace",
    "bungalow",
    "dormitory",
}

non_residential_building_types = {
    "university",
    "school",
    "college",
    "commercial",
    "retail",
    "industrial",
    "office",
    "hospital",
    "hotel",
    "church",
    "temple",
    "pavilion",
    "shed",
    "parking",
    "carport",
    "construction",
    "storage_tank",
    "roof",
    "kiosk",
    "train_station",
    "stable",
}

building_type = buildings_m["building"].astype(str).str.lower()

is_explicit_residential = building_type.isin(explicit_residential)
is_yes = building_type.eq("yes")
is_non_residential_type = building_type.isin(non_residential_building_types)

has_amenity = buildings_m["amenity"].notna()
has_shop = buildings_m["shop"].notna()
has_office = buildings_m["office"].notna()

has_commercial_landuse = (
    buildings_m["landuse"]
    .astype(str)
    .str.lower()
    .isin({"commercial", "retail", "industrial"})
)

is_residential = (
    is_explicit_residential
    |
    (
        is_yes
        & ~is_non_residential_type
        & ~has_amenity
        & ~has_shop
        & ~has_office
        & ~has_commercial_landuse
    )
)

res_buildings = buildings_m[is_residential].copy()


# ------------------------------------------------------------
# 2. Building footprint area
# ------------------------------------------------------------

res_buildings["residential_area_m2"] = res_buildings.geometry.area


# ------------------------------------------------------------
# 3. Intersect with ONLY wards_near_omr
# ------------------------------------------------------------

joined = gpd.sjoin(
    res_buildings[["residential_area_m2", "geometry"]],
    wards_near_omr_m[[name_col, "geometry"]],
    how="inner",
    predicate="intersects"
)


# ------------------------------------------------------------
# 4. Sum residential building area per ward
# ------------------------------------------------------------

residential_area_by_ward = (
    joined
    .groupby(name_col)["residential_area_m2"]
    .sum()
    .reset_index()
)


# ------------------------------------------------------------
# 5. Keep every ward in wards_near_omr
# ------------------------------------------------------------

residential_area_by_ward = (
    wards_near_omr_m[[name_col]]
    .drop_duplicates()
    .merge(
        residential_area_by_ward,
        on=name_col,
        how="left"
    )
    .fillna({"residential_area_m2": 0})
    .sort_values(name_col)
    .reset_index(drop=True)
)


print("\nResidential building footprint area by OMR-relevant ward:")
print(
    residential_area_by_ward
    .round(2)
    .to_string(index=False)
)

residential_area_by_ward.to_csv(
    "ward_residential_building_area_omr.csv",
    index=False
)

print("\nSaved: ward_residential_building_area_omr.csv")

# Check whether wards 170 and 174 fall inside the OSM building-download BBOX

# BBOX = (80.15, 12.84, 80.28, 12.99)  # west, south, east, north

from shapely.geometry import box

bbox_geom = box(BBOX[0], BBOX[1], BBOX[2], BBOX[3])

# Reproject BBOX to the ward CRS
bbox_geom_m = gpd.GeoSeries(
    [bbox_geom], crs="EPSG:4326"
).to_crs(wards_near_omr_m.crs).iloc[0]

for ward_no in ["170", "174"]:
    ward = wards_near_omr_m[
        wards_near_omr_m[name_col].astype(str) == ward_no
    ]

    if len(ward) == 0:
        print(f"Ward {ward_no}: NOT FOUND")
        continue

    intersection = ward.geometry.intersection(bbox_geom_m)
    ward_area = ward.geometry.area.iloc[0]
    covered_area = intersection.area.iloc[0]

    print(f"Ward {ward_no}:")
    print(f"  Ward area:       {ward_area:,.0f} m²")
    print(f"  Inside BBOX:     {covered_area:,.0f} m²")
    print(f"  % inside BBOX:   {covered_area / ward_area * 100:.2f}%")

    # ============================================================================
# STEP 2 — Population density per residential built-up area
# ============================================================================

POP_PATH = "gcc_2011_pop_data_170_200_Scraped.xlsx"
RES_AREA_PATH = "ward_residential_building_area_omr.csv"

# Load population data
pop = pd.read_excel(POP_PATH)

# Load residential footprint area
res_area = pd.read_csv(RES_AREA_PATH)

# Keep only the columns needed
pop = pop[["Ward", "Zone", "Buildings", "Households", "2011 Population"]].copy()
res_area = res_area[["Name", "residential_area_m2"]].copy()

# Normalize ward numbers
pop["Ward"] = pd.to_numeric(pop["Ward"], errors="coerce").astype("Int64")
res_area["Ward"] = pd.to_numeric(res_area["Name"], errors="coerce").astype("Int64")

# OMR-relevant population wards
# Excluding 170 and 174 , 185-188 as decided
# OMR_STUDY_WARDS = [
#     172, 173, 178, 179, 180,
#     181, 182, 183, 184, #185, 186, 187, 188, 
#     189,
#     190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200
# ]

pop = pop[pop["Ward"].isin(OMR_STUDY_WARDS)].copy()
res_area = res_area[res_area["Ward"].isin(OMR_STUDY_WARDS)].copy()

# Merge
ward_population = pop.merge(
    res_area,
    on="Ward",
    how="left"
)

# Population per m² of residential building footprint
ward_population["population_per_res_m2"] = (
    ward_population["2011 Population"]
    / ward_population["residential_area_m2"]
)

# Also useful: population per 1,000 m² residential footprint
ward_population["population_per_1000_res_m2"] = (
    ward_population["population_per_res_m2"] * 1000
)

# Diagnostics
print("\n" + "=" * 70)
print("STEP 2: Population density per residential built-up area")
print("=" * 70)

print(
    ward_population[
        ["Ward", "Zone", "2011 Population",
         "residential_area_m2",
         "population_per_res_m2",
         "population_per_1000_res_m2"]
    ]
    .round(4)
    .to_string(index=False)
)

# Check for missing/zero residential area
print("\n--- Diagnostics ---")

print(
    "Missing residential area:",
    ward_population["residential_area_m2"].isna().sum()
)

print(
    "Zero residential area:",
    (ward_population["residential_area_m2"] == 0).sum()
)

# Save
ward_population.to_csv(
    "ward_population_density_omr.csv",
    index=False
)

print("\nSaved: ward_population_density_omr.csv")

#####

# ============================================================================
# STEP 3A — Residential building footprint within accessibility catchments
# ============================================================================

print("\n" + "=" * 70)
print("STEP 3A: Residential footprint — bus / metro accessibility")
print("=" * 70)

step3a_cache = f"{CACHE_PREFIX}_wards{cache_signature(sorted(OMR_STUDY_WARDS))}_step3a_residential_accessibility.csv"

if cache_exists(step3a_cache):

    step3a = pd.read_csv(cache_path(step3a_cache))
    step3a_loaded_from_cache = True
    print(f"[CACHE HIT] {cache_path(step3a_cache)}")

else:

    step3a_loaded_from_cache = False

    # ----------------------------------------------------------------------
    # 1. Use SAME residential classification as Step 1B
    # ----------------------------------------------------------------------
    res_buildings = buildings_m[is_residential].copy()

    print(f"Residential buildings before ward assignment: {len(res_buildings)}")

    # ----------------------------------------------------------------------
    # 2. Spatially assign buildings to wards
    #
    # Rename the ward column BEFORE sjoin so we don't depend on
    # GeoPandas suffix behaviour / name_col.
    # ----------------------------------------------------------------------
    ward_for_join = wards_m[[name_col, "geometry"]].copy()
    ward_for_join = ward_for_join.rename(columns={name_col: "Ward"})

    ward_for_join["Ward"] = (
        ward_for_join["Ward"]
        .astype(str)
        .str.strip()
        .astype(int)
    )

    res_buildings = gpd.sjoin(
        res_buildings,
        ward_for_join,
        how="inner",
        predicate="intersects"
    )

    # Keep only the wards selected for the population analysis
    res_buildings = res_buildings[
        res_buildings["Ward"].isin(OMR_STUDY_WARDS)
    ].copy()

    print(
        f"Residential buildings in analysis wards: "
        f"{len(res_buildings)}"
    )

    # ----------------------------------------------------------------------
    # 3. Intersect residential footprints with BUS walking isochrone
    # ----------------------------------------------------------------------
    # bus_geom = isochrone_shape
    bus_geom = mtc_bus_isochrone

    res_buildings["area_bus_m2"] = (
        res_buildings.geometry
        .intersection(bus_geom)
        .area
    )

    # ----------------------------------------------------------------------
    # 4. Intersect residential footprints with METRO walking isochrone
    # ----------------------------------------------------------------------
    metro_geom = (
        purple_line_isochrone
        .union(red_line_isochrone)
    )

    res_buildings["area_metro_m2"] = (
        res_buildings.geometry
        .intersection(metro_geom)
        .area
    )

    # ----------------------------------------------------------------------
    # 5. Either = bus OR metro
    # ----------------------------------------------------------------------
    either_geom = bus_geom.union(metro_geom)

    res_buildings["area_either_m2"] = (
        res_buildings.geometry
        .intersection(either_geom)
        .area
    )

    # ----------------------------------------------------------------------
    # 6. Both = bus AND metro
    # ----------------------------------------------------------------------
    both_geom = bus_geom.intersection(metro_geom)

    res_buildings["area_both_m2"] = (
        res_buildings.geometry
        .intersection(both_geom)
        .area
    )

    # ----------------------------------------------------------------------
    # 7. Ward-level aggregation
    # ----------------------------------------------------------------------
    step3a = (
        res_buildings
        .groupby("Ward")
        .agg(
            residential_area_m2=("geometry", lambda x: x.area.sum()),
            residential_bus_m2=("area_bus_m2", "sum"),
            residential_metro_m2=("area_metro_m2", "sum"),
            residential_either_m2=("area_either_m2", "sum"),
            residential_both_m2=("area_both_m2", "sum"),
        )
        .reset_index()
    )

    # ----------------------------------------------------------------------
    # 8. Make sure every analysis ward appears
    # ----------------------------------------------------------------------
    step3a = (
        pd.DataFrame({"Ward": OMR_STUDY_WARDS})
        .merge(step3a, on="Ward", how="left")
        .fillna(0)
    )

    # ----------------------------------------------------------------------
    # 9. Percentages
    # ----------------------------------------------------------------------
    step3a["bus_pct"] = (
        step3a["residential_bus_m2"]
        / step3a["residential_area_m2"]
        * 100
    ).where(step3a["residential_area_m2"] > 0, 0)

    step3a["metro_pct"] = (
        step3a["residential_metro_m2"]
        / step3a["residential_area_m2"]
        * 100
    ).where(step3a["residential_area_m2"] > 0, 0)

    step3a["either_pct"] = (
        step3a["residential_either_m2"]
        / step3a["residential_area_m2"]
        * 100
    ).where(step3a["residential_area_m2"] > 0, 0)

    step3a["both_pct"] = (
        step3a["residential_both_m2"]
        / step3a["residential_area_m2"]
        * 100
    ).where(step3a["residential_area_m2"] > 0, 0)

    # ----------------------------------------------------------------------
    # 10. Save cache
    # ----------------------------------------------------------------------
    step3a.to_csv(cache_path(step3a_cache), index=False)

    print(f"[CACHE SAVE] {cache_path(step3a_cache)}")


print("\n" + "-" * 70)
print("STEP 3A RESULT")
print("-" * 70)

print(
    step3a.round({
        "residential_area_m2": 2,
        "residential_bus_m2": 2,
        "residential_metro_m2": 2,
        "residential_either_m2": 2,
        "residential_both_m2": 2,
        "bus_pct": 2,
        "metro_pct": 2,
        "either_pct": 2,
        "both_pct": 2,
    }).to_string(index=False)
)


# ============================================================================
# STEP 3B — Estimated population reached / not reached
# ============================================================================

print("\n" + "=" * 70)
print("STEP 3B: Estimated population — bus / metro accessibility")
print("=" * 70)

step3b_cache = (
    f"v1_{BBOX[0]:.4f}_{BBOX[1]:.4f}_"
    f"{BBOX[2]:.4f}_{BBOX[3]:.4f}_walk500_"
    f"wards{cache_signature(sorted(OMR_STUDY_WARDS))}_"
    f"step3b_population_accessibility.csv"
)

if cache_exists(step3b_cache):

    step3b = pd.read_csv(cache_path(step3b_cache))
    print(f"[CACHE HIT] {cache_path(step3b_cache)}")

else:

    # ----------------------------------------------------------------------
    # 1. Start with Step 3A footprint areas
    # ----------------------------------------------------------------------
    step3b = step3a.copy()

    # ----------------------------------------------------------------------
    # 2. Attach ward-specific population density from Step 2
    #
    # population_per_res_m2 =
    #     2011 ward population / total residential building footprint
    # ----------------------------------------------------------------------
    density_cols = [
        "Ward",
        "2011 Population",
        "residential_area_m2",
        "population_per_res_m2"
    ]

    step2_density = ward_population[density_cols].copy()

    step2_density["Ward"] = (
        step2_density["Ward"]
        .astype(str)
        .str.strip()
        .astype(int)
    )

    step3b = step3b.merge(
        step2_density[
            ["Ward", "2011 Population", "population_per_res_m2"]
        ],
        on="Ward",
        how="left",
        suffixes=("", "_step2")
    )

    # ----------------------------------------------------------------------
    # 3. Estimate population reached
    # ----------------------------------------------------------------------
    step3b["population_bus"] = (
        step3b["residential_bus_m2"]
        * step3b["population_per_res_m2"]
    )

    step3b["population_metro"] = (
        step3b["residential_metro_m2"]
        * step3b["population_per_res_m2"]
    )

    step3b["population_either"] = (
        step3b["residential_either_m2"]
        * step3b["population_per_res_m2"]
    )

    step3b["population_both"] = (
        step3b["residential_both_m2"]
        * step3b["population_per_res_m2"]
    )

    # ----------------------------------------------------------------------
    # 4. Estimated population NOT reached
    # ----------------------------------------------------------------------
    step3b["population_not_bus"] = (
        step3b["2011 Population"]
        - step3b["population_bus"]
    )

    step3b["population_not_metro"] = (
        step3b["2011 Population"]
        - step3b["population_metro"]
    )

    step3b["population_not_either"] = (
        step3b["2011 Population"]
        - step3b["population_either"]
    )

    step3b["population_not_both"] = (
        step3b["2011 Population"]
        - step3b["population_both"]
    )

    # Avoid tiny floating-point negatives
    population_cols = [
        "population_bus",
        "population_metro",
        "population_either",
        "population_both",
        "population_not_bus",
        "population_not_metro",
        "population_not_either",
        "population_not_both",
    ]

    for col in population_cols:
        step3b[col] = step3b[col].clip(lower=0)

    # ----------------------------------------------------------------------
    # 5. Sanity-check that reached + not reached = total population
    # ----------------------------------------------------------------------
    step3b["bus_check"] = (
        step3b["population_bus"]
        + step3b["population_not_bus"]
        - step3b["2011 Population"]
    ).abs()

    step3b["metro_check"] = (
        step3b["population_metro"]
        + step3b["population_not_metro"]
        - step3b["2011 Population"]
    ).abs()

    step3b["either_check"] = (
        step3b["population_either"]
        + step3b["population_not_either"]
        - step3b["2011 Population"]
    ).abs()

    step3b["both_check"] = (
        step3b["population_both"]
        + step3b["population_not_both"]
        - step3b["2011 Population"]
    ).abs()

    print(
        "\n[CHECK] Maximum population reconciliation error:"
    )
    print(
        f"  Bus:    {step3b['bus_check'].max():.10f}"
    )
    print(
        f"  Metro:  {step3b['metro_check'].max():.10f}"
    )
    print(
        f"  Either: {step3b['either_check'].max():.10f}"
    )
    print(
        f"  Both:   {step3b['both_check'].max():.10f}"
    )

    # ----------------------------------------------------------------------
    # 6. Save cache
    # ----------------------------------------------------------------------
    step3b.to_csv(
        cache_path(step3b_cache),
        index=False
    )

    print(f"\n[CACHE SAVE] {cache_path(step3b_cache)}")


# ============================================================================
# DISPLAY
# ============================================================================

display_cols = [
    "Ward",
    "2011 Population",
    "population_bus",
    "population_metro",
    "population_either",
    "population_both",
    "population_not_bus",
    "population_not_metro",
    "population_not_either",
    "population_not_both",
]

print("\nEstimated population:")
print(
    step3b[display_cols]
    .round(0)
    .to_string(index=False)
)

# Save human-readable output as well
step3b.to_csv(
    "ward_population_accessibility_3B.csv",
    index=False
)

print("\nSaved: ward_population_accessibility_3B.csv")


print("\n" + "=" * 70)
print("CACHE SUMMARY")
print("=" * 70)
print(f"Cache directory: {CACHE_DIR.resolve()}")
print("To force a completely fresh run, delete the cache_omr directory.")

# ------------------------------------------------------------
# 5. Assign stops to the 21 analysis wards
# ------------------------------------------------------------

ward_for_join = wards_m[[name_col, "geometry"]].copy()

ward_for_join = ward_for_join.rename(
    columns={name_col: "Ward"}
)

ward_for_join["Ward"] = (
    ward_for_join["Ward"]
    .astype(str)
    .str.strip()
    .astype(int)
)

ward_for_join = ward_for_join[
    ward_for_join["Ward"].isin(OMR_STUDY_WARDS)
].copy()

mtc_stops_wards = gpd.sjoin(
    mtc_stops_gdf,
    ward_for_join,
    how="left",
    predicate="within"
)

print(
    f"[RESULT] MTC stops assigned to analysis wards: "
    f"{mtc_stops_wards['Ward'].notna().sum()} / "
    f"{len(mtc_stops_wards)}"
)

print("\nMTC stops by ward:")

print(
    mtc_stops_wards
    .groupby("Ward")
    .size()
    .reindex(OMR_STUDY_WARDS, fill_value=0)
    .to_string()
)

ward_170_geom = wards_near_omr[wards_near_omr[name_col].astype(str) == "170"].geometry.iloc[0]
buildings_170 = buildings_m[buildings_m.geometry.centroid.within(ward_170_geom)]

print(f"Total buildings (any type) in ward 170: {len(buildings_170)}")
if len(buildings_170) > 0:
    print(buildings_170["building"].value_counts(dropna=False))  # or whatever the OSM tag column is named