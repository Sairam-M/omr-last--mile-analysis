# OMR Last-Mile Connectivity Analysis

An exploratory analysis of last-mile connectivity along the Old Mahabalipuram Road (OMR) corridor in Chennai.

This repository contains the code, source data and outputs from an extension of the existing Data Jam analysis. It brings together additional datasets and spatial accessibility analysis for further review and use in the project.

- Bus accessibility using official MTC GTFS stops
- Metro accessibility using walking catchments around planned/current metro stations
- Accessibility of schools and hospitals
- Slum locations and accessibility gaps
- Ward-level analysis and prioritisation
- Population accessibility estimates using 2011 Census ward populations and residential building footprints
- A separate analysis of the OMR stretch south of Navalur

The work is intended as a **research/analysis contribution for the team to review and potentially incorporate**, rather than as a final production methodology.

---

## Repository Structure

```text
OMR_LAST_MILE_ANALYSIS/
│
├── README.md
├── requirements.txt
│
├── data/
│   ├── buildings.geojson
│   ├── chennai_gcc_wards_2022.kml
│   ├── gcc_2011_pop_data_170_200_Scraped.xlsx
│   ├── slums.kml
│   │
│   ├── mtc-gtfs/
│   │   └── stops.txt
│   │
│   └── south_of_navalur/
│       ├── south_drive_network.geojson
│       ├── south_walk_network.geojson
│       ├── south_schools.geojson
│       └── south_hospitals.geojson
│
├── docs/
│   └── OMR Last-Mile Connectivity Assessment.md
│
├── outputs/
│   ├── [main analysis outputs]
│   │
│   └── south_of_navalur/
│       └── [south-of-Navalur outputs]
│
└── src/
    ├── omr_master_cached.py
    │
    └── south_of_navalur/
        └── omr_south_of_navalur.py
```
## Setup

Python 3.10+ is recommended.

From the repository root:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### First-time data setup

The current script expects its input files in the repository root. To preserve the cleaner repository structure, copy the required inputs from `data/` to the root before running:

```bat
copy data\buildings.geojson .
copy data\chennai_gcc_wards_2022.kml .
copy data\gcc_2011_pop_data_170_200_Scraped.xlsx .
copy data\slums.kml .
copy data\mtc-gtfs\stops.txt mtc-gtfs-stops.txt
```

### Prepare data for the South-of-Navalur analysis

The South-of-Navalur script also expects its manually prepared OSM inputs in the repository root. Copy them before running:

```bat
copy data\south_of_navalur\south_drive_network.geojson .
copy data\south_of_navalur\south_walk_network.geojson .
copy data\south_of_navalur\south_schools.geojson .
copy data\south_of_navalur\south_hospitals.geojson .
copy .\data\mtc-gtfs\stops.txt mtc-gtfs-stops.txt
```

## Running the analysis

Run these commands from the repository root.

### Main OMR analysis
```bat
python src\omr_master_cached.py
```

### Run the South-of-Navalur analysis

```bat
python src\south_of_navalur\omr_south_of_navalur.py
```

This analysis is kept separate because the area south of Navalur falls outside the GCC ward framework used for the main analysis.

The OSM network and facility inputs for this section are included under:

```text
data/south_of_navalur/
```

They were retained because the required OSM downloads were not reliable during the analysis.

## Important outputs

### Interactive maps

The two most useful outputs to open first are:

```text
outputs/omr_full_map.html
outputs/south_of_navalur/omr_south_of_navalur_map.html
```

Open these directly in a browser to explore the spatial analysis.

### Main analysis

Key CSV outputs:

```text
outputs/ward_wise_summary.csv
outputs/priority_wards.csv
outputs/bus_metro_comparison_summary.csv
outputs/ward_population_accessibility_3B.csv
outputs/ward_population_density_omr.csv
```

The spatial outputs are:

```text
outputs/output_schools_final.geojson
outputs/output_hospitals_final.geojson
outputs/output_slums_final.geojson
outputs/output_wards_near_omr.geojson
```

### South of Navalur

The main summary is:

```text
outputs/south_of_navalur/south_of_navalur_summary.csv
```

Spatial outputs:

```text
outputs/south_of_navalur/output_schools_south.geojson
outputs/south_of_navalur/output_hospitals_south.geojson
outputs/south_of_navalur/output_slums_south.geojson
outputs/south_of_navalur/output_isochrone_south.geojson
```

### Report

The detailed analysis and methodology are documented here:

```text
docs/OMR Last-Mile Connectivity Assessment.md
```

For a quick review, I would start with the **main HTML map**, **`ward_wise_summary.csv`**, **`priority_wards.csv`**, and the **report**.

## What was added

The main additions to the existing analysis are:

- **Official MTC GTFS bus stops** used for the final bus accessibility calculations, instead of relying on OSM bus stops.
- **School and hospital accessibility** against bus and metro walking catchments.
- **Slum accessibility** as an additional equity dimension.
- **Ward-level accessibility gaps** and a priority-ward ranking.
- **Population accessibility estimates** using 2011 Census ward populations and residential building footprints.
- **South-of-Navalur analysis**, handled separately because it falls outside the GCC ward framework.

### Main analysis — final ward-scoped results

The final analysis covers 20 OMR-relevant GCC wards:

| | Count |
|---|---:|
| Schools | 96 |
| Hospitals | 104 |
| Slum locations | 88 |

For the combined bus + metro accessibility analysis:

| | Bus only | Metro only | Both | Neither |
|---|---:|---:|---:|---:|
| Schools | 14 | 4 | 0 | 78 |
| Hospitals | 43 | 5 | 8 | 48 |
| Slums | 21 | 1 | 5 | 61 |

These are the **final ward-scoped figures**. Earlier broader-buffer figures printed by the script should not be used as the headline results.

### Population

The population analysis estimates how much of each ward's 2011 Census population falls within the analysed bus/metro accessibility areas.

The results are in:

```text
outputs/ward_population_accessibility_3B.csv
```
## Important caveats

- **Population:** The population accessibility layer is an estimate based on 2011 Census ward totals and residential building footprints. It is not a current official population estimate.
- **OSM data:** Schools, hospitals, buildings and walking networks depend on OpenStreetMap completeness and tagging.
- **Bus accessibility:** Final bus coverage uses MTC GTFS stops. The earlier OSM-based bus isochrone should not be used for the final coverage figures.
- **500 m walking catchment:** Accessibility is based on walking distance through the available network. It does not model actual travel time, waiting time, crossings or transfers.
- **Metro accessibility:** Metro coverage represents walking access to stations, not end-to-end metro travel time.
- **Ward scope:** The reportable main-analysis figures are the final ward-scoped figures. Intermediate broader-buffer figures printed by the script are not the headline results.
- **Priority score:** The priority score is a ranking aid for ordering wards, not an absolute measure of need.
- **South of Navalur:** This is analysed separately because it falls outside the GCC ward framework used for the main analysis. The same ward-level population/slum methodology therefore cannot currently be applied there in the same way.

## Data sources

The main source datasets included in the repository are:

| Dataset | Local copy | Original source |
|---|---|---|
| OSM building footprints | [`buildings.geojson`](data/buildings.geojson) | OpenStreetMap |
| GCC 2022 ward boundaries | [`chennai_gcc_wards_2022.kml`](data/chennai_gcc_wards_2022.kml) | [`OpenCity`](https://data.opencity.in/dataset/gcc-ward-information) |
| 2011 ward population | [`gcc_2011_pop_data_170_200_Scraped.xlsx`](data/gcc_2011_pop_data_170_200_Scraped.xlsx) | [`Chennai Corporation`](https://chennaicorporation.gov.in/delimitation_draft/pdf/DELIMITATION_OF_WARDS_DRAFT_PROPOSAL_ENGLISH.pdf) |
| Slum locations | [`slums.kml`](data/slums.kml) | [`OpenCity`](https://data.opencity.in/dataset/chennai-slums) |
| MTC GTFS stops | [`stops.txt`](data/mtc-gtfs/stops.txt) | [`ChennaiGTFS`](https://github.com/ungalsoththu/ChennaiGTFS/tree/main) |
| South-of-Navalur OSM inputs | [`south_of_navalur/`](data/south_of_navalur/) | OpenStreetMap / manually prepared inputs |

Additional source/methodology details are available in the report under:

```text
docs/OMR Last-Mile Connectivity Assessment.md
```

## Status

This repository is intended as a handoff of the additional data discovery, analysis and outputs explored during the project.

The results and methodology should be reviewed before being incorporated into the final project, particularly the population estimation approach and the assumptions around accessibility.

The main value-add explored here is the combination of **official MTC GTFS data, spatial accessibility analysis, ward-level gaps, equity layers and population estimates** into outputs that can be further evaluated by the team.

