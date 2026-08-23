# OMR Last-Mile Connectivity Assessment

### Bus, Metro, and Facility Access Along the Old Mahabalipuram Road (Rajiv Gandhi Salai) Corridor

*Prepared for OpenCity Chennai — Public Transport Datajam Follow-UpData vintage: main analysis run current as of the latest completed pipeline execution (2011 Census population base, MTC GTFS bus data, CMRL Phase-II metro station data). South-of-Navalur section completed separately; see Section 7*

---

## 1. Executive Summary

Along a validated 20-ward stretch of the OMR corridor within Chennai Corporation (GCC) limits:

- **81.2% of schools** (78 of 96) and **46.2% of hospitals** (48 of 104) have no bus or metro stop within a 500-metre walk.
- **69.3% of slum settlements** (61 of 88, by area) fall outside walkable transit coverage.
- Weighted by population: **an estimated 73.7% of the corridor's ~556,500 residents (2011 Census baseline) live outside a 500m walk of either a bus stop or a metro station. [Within the GCC portion of the corridor]**
- **Metro adds comparatively little beyond what buses already reach** — only 2.0% of the corridor's population is within metro-walking-distance, versus 25.9% for buses. The two modes overlap in some places and are largely additive in others, but neither, and especially not metro alone, resolves the underlying gap.
- A stretch of OMR from **south of Navalur through Siruseri, Padur and Kelambakkam** falls outside GCC entirely (Chengalpattu district, panchayat-governed). A separate analysis of this stretch finds that **9 of 10 mapped schools/colleges (90.0%) and 6 of 10 hospitals/clinics (60.0%) have neither bus nor metro coverage within a 500m walking distance**. The analysis uses official MTC GTFS bus-stop data and a network-based walking model, but does not estimate population because there is no equivalent ward-level population framework for this panchayat-governed area.

---

## 2. Background & Objective

This analysis extends the team's original OpenCity Datajam (8 August) submission into a comprehensive last-mile connectivity assessment of the OMR corridor, per OpenCity's follow-up request. The brief asked for:

1. Street network data for areas outside GCC
2. Inclusion of upcoming CMRL metro expansions
3. A population layer
4. A comprehensive coverage assessment, in an interactive/shareable format

This report addresses points 1–4 for the GCC-governed portion of the corridor. Point 4's interactive format (web app) is a separate, planned deliverable (see Section 9).

---

## 3. Study Area & Scope

### 3.1 Corridor definition

The study area is defined by two independent dimensions:

- **Length (along the corridor):** Madhya Kailash to Navalur, covered by the main analysis (Sections 3–6); South of Navalur to Kelambakkam, covered by a separate script for the area outside GCC (Section 7)
- **Width (perpendicular to the road):** a 2km buffer on either side of the OMR/Rajiv Gandhi Salai road centerline, drawn from OpenStreetMap road geometry (name-matched on both "Old Mahabalipuram Road" and the current official name "Rajiv Gandhi Salai" — OSM tags the road under both).

All ward inclusion/exclusion decisions in Section 3.2 are based on this 2km-wide corridor definition.

### 3.2 Ward scope — `OMR_STUDY_WARDS`

Of the 200 wards in Chennai Corporation's current (2022, post-2011-expansion) delimitation, **20 wards** were confirmed to genuinely belong in this analysis. Every exclusion was individually verified, not assumed:

| Ward(s) | Status | Reason |
| --- | --- | --- |
| 170, 172, 173, 178, 182, 184, 190, 191, 193, 195, 196, 198–200 | **Included** | Confirmed within corridor buffer and genuinely OMR-adjacent |
| 179, 180, 181, 183, 192, 194 | **Included** | Sit east of East Coast Road (ECR), technically outside a strict OMR-only corridor — retained because MTC GTFS bus coverage data for these wards is real and directly relevant regardless of which side of ECR they fall on |
| 174 | **Excluded** | Besant Nagar — geographically close to the buffer but not part of the OMR corridor's residential catchment |
| 189 | **Excluded** | Does not directly touch the OMR road or its buffer; shielded from the corridor by wards 193/195/196 |
| 197 | **Excluded** | Sits east of ECR; unlike 192/194, judged too geographically removed from OMR to retain |
| 122, 123, 169, 171 | **Excluded** | Fall within the download extent but outside the study corridor definition |

Ward 170 was initially excluded (its polygon fell entirely outside the original OSM download extent, giving 0% data coverage) and was re-included once the download boundary was extended north to Madhya Kailash — OMR's actual point of origin. Excluding it originally would have understated the corridor's northern extent without valid reason.

---

## 4. Data Sources & Methodology

| Layer | Source | Notes |
| --- | --- | --- |
| Road network | OpenStreetMap (OSMnx) | Name-matched for both historical and current OMR naming |
| Bus stops & coverage | **MTC GTFS (official feed)** | Switched from raw OSM bus-stop tags after confirming OSM significantly undercounted stops (98 vs. 733 in the full download extent) |
| Walking accessibility | Real walking-network isochrones (OSMnx + Dijkstra), not straight-line buffers | Accounts for actual path distance, not as-the-crow-flies distance |
| Schools & hospitals | OpenStreetMap | `amenity=school/college`, `amenity=hospital/clinic` |
| Slums | Tamil Nadu Slum Clearance Board (TNSCB) boundary data | Used for the GCC portion. The available TNSCB layer was not used for the South-of-Navalur analysis because the relevant features did not fall within the defined southern study boundary. |
| Metro — Purple Line (Corridor 3) | Station names from CMRL's official list; coordinates AI-generated, then manually fine-tuned using CMRL's published Phase-II route map as visual reference | **This is the line running directly along OMR** (Nehru Nagar, Kandanchavadi, Perungudi, Thoraipakkam, Sholinganallur, Navalur, Siruseri) |
| Metro — Red Line (Corridor 5) | Same method | The interior route via Kilkattalai, Kovilambakkam, Medavakkam, Perumbakkam, rejoining at Sholinganallur |
| Residential building footprint | OpenStreetMap (OSM) building polygons, classified as residential by tag (`building=yes/house/apartments`, excluding tagged commercial/office/shop uses) | Used to distribute ward-level Census population onto current built-up area (Section 4.2) |
| Population | 2011 Census figures, ward-level, from Chennai Corporation's own Delimitation of Wards draft proposal ([source PDF](https://chennaicorporation.gov.in/delimitation_draft/pdf/DELIMITATION_OF_WARDS_DRAFT_PROPOSAL_ENGLISH.pdf), mapped to the *current* 200-ward scheme, not the older pre-2011 155-ward scheme) | Combined with OSM residential building footprint area (above) to estimate population distribution and transit accessibility (Section 4.2) |
| GCC ward boundaries | 2022 GCC Ward Map (Chennai Corporation, via opencity.in) | Confirmed 200 wards, current delimitation |

### 4.1 A note on the metro line names

OpenCity's original request referenced "the upcoming metro expansions (red line CMRL)." Based on CMRL's own published Phase-II map (color-coded legend) and Wikipedia's Chennai Metro pages, **the line running along OMR itself is Corridor 3 (Purple Line)**; Corridor 5 (Red Line) is the interior route via Medavakkam/Perumbakkam, rejoining OMR only at the Sholinganallur interchange. This analysis includes **both lines**, which is more complete than the brief's literal wording — but the naming distinction is worth stating explicitly, since it will likely be immediately apparent to anyone at CUMTA familiar with the network.

### 4.2 Population methodology and its limitation

Ward-level 2011 population was distributed across current (present-day) OSM residential building footprint area within each ward, producing a population-per-square-metre density figure, then applied to the portion of that footprint falling within walking distance of bus/metro. **This estimates current population distribution using a 2011 population base and a present-day building footprint** — it likely *underestimates* population in wards with substantial post-2011 construction (very plausible along a rapidly-developed IT corridor). No more current, ward-level population figure was found to be publicly available (see Section 8).

**South-of-Navalur methodology:** Because the area is outside GCC and lacks the ward-level population framework used for the main analysis, Section 7 reports facility-level connectivity only. Schools, hospitals and bus stops are filtered to the southern study boundary and 2km OMR corridor; accessibility is based on 500m network walking distance rather than straight-line distance. MTC coverage uses the official GTFS feed, while metro coverage uses the Purple Line station set defined for the southern analysis.

---

## 5. Key Findings

### 5.1 GCC Facility coverage (ward-scoped final figures)

|  | Total | Bus only | Metro only | Both | **Neither (gap)** |
| --- | --- | --- | --- | --- | --- |
| Schools | 96 | 14 | 4 | 0 | **78 (81.2%)** |
| Hospitals | 104 | 43 | 5 | 8 | **48 (46.2%)** |
| Slums (by area) | 88 | 21 | 1 | 5 | **61 (69.3%)** |

### 5.2 Population-weighted finding

Using the 2011 Census baseline distributed over current residential building footprint:

- **Total corridor population (20 wards): ~556,500**
- **Population within 500m walk of a bus stop: ~144,300 (25.9%)**
- **Population within 500m walk of a metro station: ~10,900 (2.0%)**
- **Population within 500m of either: ~146,500 (26.3%)**
- **Population within 500m of neither: ~410,000 (73.7%)**

The gap between "bus" (25.9%) and "either" (26.3%) is small — metro overlaps almost entirely with areas buses already reach, adding minimal new population coverage on its own.

### 5.3 South-of-Navalur facility coverage

The area south of Navalur falls outside Chennai Corporation and is governed through panchayat-level administration in Chengalpattu district. Because the ward-level population framework used for the GCC analysis does not extend to this area, the southern analysis reports facility-level connectivity rather than population-weighted accessibility.

| Facility | Total | Bus only | Metro only | Both | **Neither (gap)** |
| --- | --- | --- | --- | --- | --- |
| Schools/colleges | 10 | 0 | 0 | 1 | **9 (90.0%)** |
| Hospitals/clinics | 10 | 3 | 0 | 1 | **6 (60.0%)** |

The southern corridor contains **91 MTC GTFS bus stops within the defined OMR corridor**. Despite this network, only 1 of the 10 mapped schools/colleges and 4 of the 10 mapped hospitals/clinics fall within 500m network walking distance of at least one transit mode. The single transit-accessible school/college is within walking distance of **both** bus and metro; among hospitals, three are bus-only and one is accessible by both modes.

---

## 6. Priority Wards

### 6.0 Ranking methodology

This report uses **population** — the validated, reconciled figures from Section 5.2 — as the basis for prioritizing wards, rather than raw facility counts. Facility presence is a proxy for the underlying question ("do people have access?"); using population directly answers that question without an intermediate proxy.

Two separate rankings are presented, deliberately not combined into one score:

- **Magnitude** — the raw number of people without bus/metro access in a ward. This answers *"where would fixing the problem help the most people?"*
- **Severity** — the percentage of a ward's population without access. This answers *"where is the problem worst, regardless of the ward's size?"*

These reflect two legitimate, different policy framings (roughly: utilitarian vs. prioritarian resource allocation), and they do not agree with each other, as the tables below show. Blending them into a single number would require choosing how much each should count — an arbitrary judgment call this report deliberately leaves to the decision-maker rather than making silently on their behalf.

### 6.1 By magnitude — where do the most people lack access?

| Rank | Ward | Population without bus/metro access |
| --- | --- | --- |
| 1 | 180 | ~34,400 |
| 2 | 172 | ~32,500 |
| 3 | 170 | ~31,600 |
| 4 | 173 | ~29,500 |
| 5 | 178 | ~28,900 |

### 6.2 By severity — where is the *proportion* of underserved population highest?

| Rank | Ward | % of ward population without bus/metro access |
| --- | --- | --- |
| 1 | 184 | 93.8% |
| 2 | 199 | 88.6% |
| 3 | 192 | 87.0% |
| 4 | 194 | 86.6% |
| 5 | 198 | 85.8% |

**These lists barely overlap** — a direct, empirical demonstration of why a single blended score would have hidden this. Ward 184 — the corridor's single worst case by severity — doesn't appear in the magnitude top 5 at all, because it's a smaller ward. Ward 172 ranks #2 by raw population affected but only mid-table by severity, because it's a larger, only-moderately-underserved ward. Neither ranking is "more correct" than the other; they answer different questions, and a resource-allocation decision should be made with both in view, not by collapsing them into one number.

### 6.3 Case study: Ward 184

Ward 184 is worth naming specifically. It ranks #1 by severity (93.8% of its population lacks bus/metro access) and was independently confirmed through three separate checks during this project:

- **OSM data**: only 6 bus stops nearby, all clustered at the ward's edge (414–491m away)
- **Oorvani's field audit**: found essentially nothing in this stretch during ground survey
- **Official MTC GTFS data**: zero stops assigned inside the ward boundary; residential building footprint shows 6.2% bus coverage even against the corrected, larger MTC-based isochrone

Three independent methods, one consistent finding: ward 184 is a genuine, verified transit desert, not a data artifact.

---

## 7. Outside GCC — South of Navalur

The OMR corridor continues south of GCC's boundary into Chengalpattu district — covering the Siruseri, Padur and Kelambakkam stretch — which is outside Chennai Corporation and governed through panchayat-level administration.

A separate analysis was conducted for this stretch using the same 2km OMR corridor concept and a southern boundary of **12.852093°N**, chosen to partition the study area from the main GCC analysis without overlap.

### 7.1 Connectivity findings

The southern analysis identified **10 schools/colleges and 10 hospitals/clinics** within the OMR corridor. Bus accessibility was evaluated using the official MTC GTFS feed and a 500m network-walking threshold; metro accessibility was evaluated against the planned Purple Line stations using the same network-walking methodology.

| Facility | Total | Bus only | Metro only | Both | **Neither (gap)** |
| --- | --- | --- | --- | --- | --- |
| Schools/colleges | 10 | 0 | 0 | 1 | **9 (90.0%)** |
| Hospitals/clinics | 10 | 3 | 0 | 1 | **6 (60.0%)** |

The southern study area contains **146 MTC GTFS stops within the download bounding box**, of which **91 fall within the 2km OMR corridor**. Nevertheless, facility-level accessibility remains limited: only **1 of 10 schools/colleges (10.0%)** and **4 of 10 hospitals/clinics (40.0%)** have access to either bus or metro within a 500m network walking distance.

The metro contribution is particularly limited at facility level. Only **1 school/college and 1 hospital/clinic** are within 500m network walking distance of a Purple Line station, and both are also within bus coverage. Thus, in this southern stretch, the metro analysis does not identify any additional school or hospital coverage beyond that already provided by the bus network.

### 7.2 Interpretation and limitation

These figures should not be interpreted as population-level accessibility rates. Unlike the GCC portion, this area does not have the ward-level Census-to-current-building-footprint framework used for the population-weighted estimates in Section 5.2. The southern results therefore describe **facility accessibility**, not the proportion of residents lacking access.

The available TNSCB slum layer was not used to report southern slum coverage. Six features were initially returned when the layer was filtered using the OMR corridor buffer, but these were located north of Navalur and therefore fall outside the intended southern study boundary. They have been excluded rather than treated as southern slum settlements.

---

## 8. Known Limitations

Stated plainly, not hidden:

1. **Population figures use a 2011 Census base applied to current building footprint** — likely underestimates the newest, highest-density development along the corridor.
2. **Metro station coordinates are cross-verified but not official CMRL survey data** — initially AI-generated, then manually adjusted against visual reference (CMRL's published route map and satellite imagery), and sanity-checked for realistic inter-station spacing. One coordinate (Sholinganallur) was independently confirmed against its Wikipedia-listed location, matching to within 4m.
3. **The slum/equity layer (TNSCB) only covers GCC** — there is currently no equivalent low-income/informal-settlement proxy for the Chengalpattu stretch (Section 7).
4. **The South-of-Navalur analysis is facility-level only.** No population-weighted accessibility estimate is reported because the ward-level population methodology used for GCC does not have an equivalent framework in the panchayat-governed Chengalpattu stretch.
5. **This is a corridor-level, not household-level, analysis.** All figures are estimates derived from public geospatial and Census data, not primary survey data (though cross-validated against Oorvani's field bus-stop audit where available).

---

## 9. Recommended Next Steps

1. Build a lightweight interactive viewer (map + headline statistics) for sharing with CUMTA/authorities, per the original brief's request for an actionable, shareable format.
2. Consider a targeted micro-survey (not a full household survey — impractical in the project timeline) at a handful of the highest-priority wards (184, 180, 172) to qualitatively corroborate the geospatial findings.
3. If a more current population source becomes available (e.g. updated electoral roll data, or a colleague's independently-sourced dataset), re-run the population-weighted analysis to test sensitivity to the 2011 baseline assumption.
4. **Validate the southern facility inventory against additional local/official sources where available**, particularly for schools, hospitals and MTC stop coverage, since OSM facility completeness is not independently established.

---

## Appendix A: Exact Study Area Coordinates

For reproducibility, the precise bounding coordinates used in each analysis:

| Parameter | Value |
| --- | --- |
| Main analysis download extent (west, south, east, north) | 80.1824, 12.8421, 80.2746, 13.0300 |
| Main analysis northern boundary rationale | Extended to 13.03°N to fully capture Madhya Kailash junction and ward 170's OMR-adjacent southern portion |
| South-of-Navalur script northern boundary | 12.852093°N — set to exactly match the main analysis's southernmost ward extent, ensuring the two study areas partition the corridor with no overlap and no gap |
| South-of-Navalur script download extent (west, south, east, north) | 80.15, 12.75, 80.28, 12.852093 |
| Walking accessibility threshold | 500 metres (network path distance, not straight-line) |
| Corridor width (both scripts) | 2km buffer either side of the OMR road centerline |