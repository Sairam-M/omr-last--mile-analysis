import os
os.chdir("C:/Users/Sairam/Downloads")

import geopandas as gpd
import pandas as pd
import osmnx as ox
import networkx as nx
from shapely.geometry import Point as ShapelyPoint

CRS_METRIC = 32644
MAIN_SCRIPT_SOUTH_BOUND = 12.852093  
SOUTH_BBOX = (80.15, 12.75, 80.28, MAIN_SCRIPT_SOUTH_BOUND)  
WALK_DIST_M = 500

MTC_STOPS_PATH = "mtc-gtfs/stops.txt"
SLUM_KML_PATH = "slums.kml"

# Enforce fully offline settings
ox.settings.use_dns = False

# ============================================================================
# STEP S1 — OMR road network in the southern extent (OFFLINE via GeoJSON)
# ============================================================================
print("=" * 70); print("STEP S1: OMR road network (south of Navalur)"); print("=" * 70)

# Read the file you downloaded manually
edges = gpd.read_file("south_drive_network.geojson")
print(f"[SANITY CHECK] Total road segments loaded from file: {len(edges)}")

def matches_omr(row):
    name = row.get("name")
    ref = row.get("ref")
    names = name if isinstance(name, list) else [name] if isinstance(name, str) else []
    name_match = any(("Mahabalipuram" in n) or ("Rajiv Gandhi Salai" in n) or ("Rajiv Gandhi" in n)
                      for n in names)
    ref_match = isinstance(ref, str) and "OMR" in ref.upper()
    return name_match or ref_match

omr_edges = edges[edges.apply(matches_omr, axis=1)]
print(f"[SANITY CHECK] OMR-matching segments: {len(omr_edges)}")

omr_edges_m = omr_edges.to_crs(CRS_METRIC)
omr_buffer_south = omr_edges_m.buffer(2000).union_all()
print(f"[SANITY CHECK] OMR road bounds: {omr_edges_m.total_bounds}")


# ============================================================================
# STEP S2 — Bus stops (OSM + MTC GTFS), schools, hospitals (OFFLINE)
# ============================================================================
print("\n" + "=" * 70); print("STEP S2: Facilities (south of Navalur)"); print("=" * 70)

# Load manual feature layers bypassing ox.features_from_bbox
schools_raw = gpd.read_file("south_schools.geojson")
# print(f"Schools raw: {schools_raw.columns.tolist()}")
# schools_raw = schools_raw[schools_raw["amenity"].isin(["school", "college"])].copy()
# print(f"Schools after tag filter: {len(schools_raw)}")

hospitals_raw = gpd.read_file("south_hospitals.geojson")
print(f"[SANITY CHECK] File loaded counts — schools: {len(schools_raw)}, hospitals: {len(hospitals_raw)}")

schools_m = schools_raw.to_crs(CRS_METRIC)
hospitals_m = hospitals_raw.to_crs(CRS_METRIC)
schools_m["centroid"] = schools_m.geometry.centroid
hospitals_m["centroid"] = hospitals_m.geometry.centroid

schools_south = schools_m[schools_m["centroid"].within(omr_buffer_south)].copy()
hospitals_south = hospitals_m[hospitals_m["centroid"].within(omr_buffer_south)].copy()
print(f"[RESULT] Filtered to corridor — schools: {len(schools_south)}, hospitals: {len(hospitals_south)}")

mtc_stops_raw = pd.read_csv(MTC_STOPS_PATH)
mtc_south = mtc_stops_raw[
    (mtc_stops_raw["stop_lat"].between(SOUTH_BBOX[1], SOUTH_BBOX[3])) &
    (mtc_stops_raw["stop_lon"].between(SOUTH_BBOX[0], SOUTH_BBOX[2]))
].copy()
print(f"[RESULT] MTC GTFS stops in southern bbox: {len(mtc_south)}")

mtc_south_gdf = gpd.GeoDataFrame(
    mtc_south, geometry=gpd.points_from_xy(mtc_south["stop_lon"], mtc_south["stop_lat"]), crs=4326
).to_crs(CRS_METRIC)
mtc_south_omr = mtc_south_gdf[mtc_south_gdf.geometry.within(omr_buffer_south)].copy()
print(f"[RESULT] MTC stops within corridor buffer: {len(mtc_south_omr)}")


# ============================================================================
# STEP S3 — Walking isochrone from MTC stops (OFFLINE via NetworkX Graph)
# ============================================================================
print("\n" + "=" * 70); print(f"STEP S3: {WALK_DIST_M}m walking isochrone"); print("=" * 70)

# Build a NetworkX graph structure entirely offline out of your network GeoJSON file
walk_layer = gpd.read_file("south_walk_network.geojson").to_crs(CRS_METRIC)
G_walk = nx.Graph()

for _, row in walk_layer.iterrows():
    if row.geometry and row.geometry.geom_type == 'LineString':
        coords = list(row.geometry.coords)
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i+1]
            dist = ShapelyPoint(p1).distance(ShapelyPoint(p2))
            G_walk.add_node(p1, x=p1[0], y=p1[1])
            G_walk.add_node(p2, x=p2[0], y=p2[1])
            G_walk.add_edge(p1, p2, length=dist)

print(f"[SANITY CHECK] Local Walking network: {len(G_walk.nodes)} nodes, {len(G_walk.edges)} edges")

import numpy as np
from scipy.spatial import cKDTree

# Build ONCE, right after G_walk is constructed (before Step S3's loop starts)
node_ids = list(G_walk.nodes)
node_coords = np.array(node_ids)  # node IDs ARE (x, y) tuples in this graph, so this works directly
node_tree = cKDTree(node_coords)

def get_local_nearest_node(graph, pt):
    _, idx = node_tree.query([pt.x, pt.y])
    return node_ids[idx]

print(f"G_walk node count: {len(G_walk.nodes)}")
print(f"South BBOX: {SOUTH_BBOX}")

reachable_nodes = set()
skipped = 0
for _, stop in mtc_south_omr.iterrows():
    pt = stop.geometry
    try:
        nearest_node = get_local_nearest_node(G_walk, pt)
        lengths = nx.single_source_dijkstra_path_length(G_walk, nearest_node, cutoff=WALK_DIST_M, weight="length")
        reachable_nodes.update(lengths.keys())
    except Exception:
        skipped += 1

print(f"[SANITY CHECK] Stops processed: {len(mtc_south_omr) - skipped}, skipped: {skipped}")

node_points = [ShapelyPoint(n[0], n[1]) for n in G_walk.nodes if n in reachable_nodes]
if node_points:
    isochrone_south = gpd.GeoSeries(node_points, crs=CRS_METRIC).buffer(30).union_all()
else:
    isochrone_south = gpd.GeoSeries([], crs=CRS_METRIC)
print(f"[RESULT] Isochrone area: {isochrone_south.area / 1_000_000:.2f} sq km")

schools_south["bus_covered"] = schools_south["centroid"].apply(lambda p: p.within(isochrone_south) if not isochrone_south.is_empty else False)
hospitals_south["bus_covered"] = hospitals_south["centroid"].apply(lambda p: p.within(isochrone_south) if not isochrone_south.is_empty else False)


# ============================================================================
# STEP S4 — Metro coverage (Purple Line only)
# ============================================================================
print("\n" + "=" * 70); print("STEP S4: Metro Purple Line coverage"); print("=" * 70)

purple_line_stations = [
   {"name": "Sholinganallur", "lat": 12.9011, "lon": 80.2269, "type": "Elevated"},
   {"name": "Sholinganallur Lake I", "lat": 12.8945, "lon": 80.2265, "type": "Elevated"},
   {"name": "Sholinganallur Lake II", "lat": 12.8875, "lon": 80.2262, "type": "Elevated"},
   {"name": "Semmancheri Depot", "lat": 12.8795, "lon": 80.2259, "type": "Elevated"},
   {"name": "Semmancheri I", "lat": 12.8715, "lon": 80.2254, "type": "Elevated"},
   {"name": "Semmancheri II", "lat": 12.8630, "lon": 80.2248, "type": "Elevated"},
   {"name": "Gandhi Nagar", "lat": 12.8545, "lon": 80.2255, "type": "Elevated"},
   {"name": "Navallur", "lat": 12.8465, "lon": 80.2258, "type": "Elevated"},
   {"name": "Siruseri", "lat": 12.8378, "lon": 80.2272, "type": "Elevated"},
   {"name": "SIPCOT 1", "lat": 12.8305, "lon": 80.2285, "type": "Elevated"},
   {"name": "SIPCOT 2", "lat": 12.8231, "lon": 80.2310, "type": "Elevated"}
]
metro_df = pd.DataFrame(purple_line_stations)
metro_gdf_m = gpd.GeoDataFrame(
    metro_df, geometry=gpd.points_from_xy(metro_df["lon"], metro_df["lat"]), crs=4326
).to_crs(CRS_METRIC)

station_data = []
metro_reachable_nodes = set()

for _, station in metro_gdf_m.iterrows():
    pt = station.geometry
    nearest_node = get_local_nearest_node(G_walk, pt)
    node_pt = ShapelyPoint(nearest_node[0], nearest_node[1])
    entry_snap = pt.distance(node_pt)
    lengths = nx.single_source_dijkstra_path_length(G_walk, nearest_node, cutoff=1500, weight="length")
    station_data.append({"name": station["name"], "entry_snap": entry_snap, "lengths": lengths})
    
    # Track metro walking buffer nodes
    metro_lengths = nx.single_source_dijkstra_path_length(G_walk, nearest_node, cutoff=WALK_DIST_M, weight="length")
    metro_reachable_nodes.update(metro_lengths.keys())

metro_node_points = [ShapelyPoint(n[0], n[1]) for n in G_walk.nodes if n in metro_reachable_nodes]
if metro_node_points:
    metro_isochrone_south = gpd.GeoSeries(metro_node_points, crs=CRS_METRIC).buffer(30).union_all()
else:
    metro_isochrone_south = gpd.GeoSeries([], crs=CRS_METRIC)
print(f"[RESULT] Metro isochrone area: {metro_isochrone_south.area / 1_000_000:.2f} sq km")

def true_walking_distance(dest_point, station_data, graph):
    dest_node = get_local_nearest_node(graph, dest_point)
    dest_node_pt = ShapelyPoint(dest_node[0], dest_node[1])
    exit_snap = dest_point.distance(dest_node_pt)
    best = float("inf")
    for s in station_data:
        network_dist = s["lengths"].get(dest_node)
        if network_dist is not None:
            best = min(best, s["entry_snap"] + network_dist + exit_snap)
    return best

schools_south["metro_covered"] = schools_south["centroid"].apply(lambda pt: true_walking_distance(pt, station_data, G_walk) <= WALK_DIST_M)
hospitals_south["metro_covered"] = hospitals_south["centroid"].apply(lambda pt: true_walking_distance(pt, station_data, G_walk) <= WALK_DIST_M)

print(f"[RESULT] Schools metro-covered: {schools_south['metro_covered'].sum()} / {len(schools_south)}")
print(f"[RESULT] Hospitals metro-covered: {hospitals_south['metro_covered'].sum()} / {len(hospitals_south)}")


# ============================================================================
# STEP S5 — Slums: check if the GCC-sourced KML has ANY coverage here
# ============================================================================
print("\n" + "=" * 70); print("STEP S5: Slum layer check (south of Navalur)"); print("=" * 70)
print("skipped, see methodology note at the end of this script for explanation")

# slums = gpd.read_file(SLUM_KML_PATH).to_crs(CRS_METRIC)
# slums_south = slums[slums.geometry.centroid.within(omr_buffer_south)]
# print(f"[RESULT] Slums found in this extent: {len(slums_south)}")

# ### new

# # Plot slums in the southern OMR extent
# slums_south_4326 = slums_south.to_crs(4326)

# print("\nSlum geometries:")
# print(slums_south_4326.geometry.geom_type.value_counts())

# print("\nSlum attributes:")
# print(slums_south_4326.drop(columns="geometry").to_string(index=False))

# # Save the actual southern slum features
# slums_south_4326.to_file(
#     "output_slums_south.geojson",
#     driver="GeoJSON"
# )

# ### new


# ============================================================================
# STEP S6 — Combined summary (aggregate only — no ward breakdown available)
# ============================================================================
print("\n" + "=" * 70); print("STEP S6: Combined summary"); print("=" * 70)

def summarize(df, label):
    total = len(df)
    if total == 0:
        print(f"{label}: 0 features")
        return {"label": label, "total": 0}
    bus_only = (df["bus_covered"] & ~df["metro_covered"]).sum()
    metro_only = (~df["bus_covered"] & df["metro_covered"]).sum()
    both = (df["bus_covered"] & df["metro_covered"]).sum()
    neither = (~df["bus_covered"] & ~df["metro_covered"]).sum()
    print(f"{label} (n={total}): bus_only={bus_only}, metro_only={metro_only}, "
          f"both={both}, neither={neither} ({neither/total:.1%} gap)")
    return {"label": label, "total": total, "bus_only": int(bus_only), "metro_only": int(metro_only),
            "both": int(both), "neither": int(neither), "neither_pct": round(neither/total*100, 1)}

results = [summarize(schools_south, "Schools (south of Navalur)"),
           summarize(hospitals_south, "Hospitals (south of Navalur)")]
pd.DataFrame(results).to_csv("south_of_navalur_summary.csv", index=False)
print("\nSaved: south_of_navalur_summary.csv")


# ============================================================================
# STEP S7 — Save outputs
# ============================================================================
schools_south.drop(columns=["centroid"], errors="ignore").to_crs(4326).to_file(
    "output_schools_south.geojson", driver="GeoJSON")
hospitals_south.drop(columns=["centroid"], errors="ignore").to_crs(4326).to_file(
    "output_hospitals_south.geojson", driver="GeoJSON")
gpd.GeoDataFrame(geometry=[isochrone_south], crs=CRS_METRIC).to_crs(4326).to_file(
    "output_isochrone_south.geojson", driver="GeoJSON")

print("\nSaved: output_schools_south.geojson, output_hospitals_south.geojson, output_isochrone_south.geojson")


# ============================================================================
# STEP S8 — Map (same layer/color scheme as the main script's map, for
# visual consistency when both are shown together)
# ============================================================================
print("\n" + "=" * 70); print("STEP S8: Building map"); print("=" * 70)

import folium
from folium.plugins import Fullscreen

map_center_lat = (SOUTH_BBOX[1] + SOUTH_BBOX[3]) / 2
map_center_lon = (SOUTH_BBOX[0] + SOUTH_BBOX[2]) / 2
m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=13, tiles="cartodbpositron")
Fullscreen().add_to(m)

fg = folium.FeatureGroup(name="OMR road", show=True)
folium.GeoJson(omr_edges.to_crs(4326),
               style_function=lambda x: {"color": "black", "weight": 2}).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Bus isochrone — MTC GTFS", show=True)
gpd.GeoDataFrame(geometry=[isochrone_south], crs=CRS_METRIC).to_crs(4326).apply(
    lambda r: folium.GeoJson(r.geometry.__geo_interface__,
        style_function=lambda x: {"fillColor": "blue", "color": "blue", "weight": 1, "fillOpacity": 0.15}
    ).add_to(fg), axis=1)
fg.add_to(m)

fg = folium.FeatureGroup(name="Purple Line coverage (500m walking isochrone)", show=True)
gpd.GeoDataFrame(geometry=[metro_isochrone_south], crs=CRS_METRIC).to_crs(4326).apply(
    lambda r: folium.GeoJson(r.geometry.__geo_interface__,
        style_function=lambda x: {"fillColor": "purple", "color": "purple", "weight": 1, "fillOpacity": 0.15}
    ).add_to(fg), axis=1)
fg.add_to(m)

fg = folium.FeatureGroup(name="Bus stops — MTC GTFS", show=True)
for _, row in mtc_south_omr.to_crs(4326).iterrows():
    pt = row.geometry
    folium.CircleMarker([pt.y, pt.x], radius=3, color="blue", fill=True, fill_opacity=0.8,
                         popup=row.get("stop_name", "")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Metro stations — Purple Line", show=True)
for _, row in metro_df.iterrows():
    folium.CircleMarker([row["lat"], row["lon"]], radius=7, color="purple", fill=True,
                         fill_opacity=0.9, popup=row["name"]).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Schools", show=True)
for _, row in schools_south.to_crs(4326).iterrows():
    pt = row.geometry.centroid if row.geometry.geom_type != "Point" else row.geometry
    color = "green" if (row["bus_covered"] or row["metro_covered"]) else "red"
    folium.CircleMarker([pt.y, pt.x], radius=5, color=color, fill=True, fill_opacity=0.8,
                         popup=row.get("name", "school")).add_to(fg)
fg.add_to(m)

fg = folium.FeatureGroup(name="Hospitals", show=True)
for _, row in hospitals_south.to_crs(4326).iterrows():
    pt = row.geometry.centroid if row.geometry.geom_type != "Point" else row.geometry
    color = "green" if (row["bus_covered"] or row["metro_covered"]) else "orange"
    folium.CircleMarker([pt.y, pt.x], radius=5, color=color, fill=True, fill_opacity=0.8,
                         popup=row.get("name", "hospital")).add_to(fg)
fg.add_to(m)

# Add to the existing map
fg = folium.FeatureGroup(name="Slums — GCC/TNSCB layer", show=True)

for _, row in slums_south_4326.iterrows():
    geom = row.geometry

    folium.GeoJson(
        geom.__geo_interface__,
        style_function=lambda x: {
            "color": "red",
            "weight": 2,
            "fillColor": "red",
            "fillOpacity": 0.35
        },
        tooltip=str(row.get("name", "Slum"))
    ).add_to(fg)

fg.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.save("omr_south_of_navalur_map.html")
print("Saved: omr_south_of_navalur_map.html")
print("[NOTE] No slum layer, no ward outlines, no population — this extent has "
      "none of those data sources, consistent with the methodology note below.")


print("\n" + "=" * 70)
print("METHODOLOGY NOTE FOR REPORT:")
print("=" * 70)
print('"This stretch (south of Navalur — Siruseri, Padur, Kelambakkam) falls')
print('outside Chennai Corporation (GCC) in Chengalpattu district. Connectivity')
print('metrics (bus, metro, school/hospital coverage) are reported at an')
print('aggregate level, since no GCC-equivalent ward boundary system exists')
print('here. Population and slum/equity data are NOT available for this')
print("stretch -- the Census-based population methodology used for the GCC")
print('portion of this analysis has no equivalent source here, and the')
print("No slum/equity data are included in the south-of-Navalur analysis")
print("because the available slum layer does not provide a reliable feature")
print("set within the defined southern study boundary.")