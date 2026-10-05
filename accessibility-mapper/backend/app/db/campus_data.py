"""Seed dataset: a realistic university campus accessibility network.

Modelled on the University of Washington (Seattle) campus footprint so the demo
renders on a recognisable real map: coordinates are approximate building
centroids/pathway junctions in the 47.649..-47.661 / -122.302..-122.313 box.

Three narratives are deliberately baked into the topology so the prototype is
demonstrable without hand-crafting a scenario live:

1. **More Hall** is served by a 1.9 m wide accessible ramp AND a stair flight.
   A citizen-reported ``blocked_ramp`` sits on the ramp, so the step-free graph
   has to route around it - and if you resolve that barrier from the admin
   dashboard the wheelchair route snaps back to the short ramp.
2. **Health Sciences Clinic (Level 3)** is lift-only. A ``broken_lift`` report
   severs the step-free chain entirely, which exercises the router's
   graceful-degradation path (least-bad route + loud warnings).
3. Historic resolved reports give the dashboard real resolution-time analytics.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Nodes: buildings, entrances, lifts, path intersections
# ---------------------------------------------------------------------------
NODES: list[dict[str, Any]] = [
    # --- campus buildings ------------------------------------------------
    {"id": "bld_suzzallo", "name": "Suzzallo Library (Central Library)", "kind": "building", "latitude": 47.65564, "longitude": -122.30807, "building_code": "SUZ", "campus_zone": "Central", "has_elevator": True, "accessible_notes": "Historic Reading Room. Lift to all floors; step-free entrance from Red Square."},
    {"id": "bld_odegaard", "name": "Odegaard Undergraduate Library", "kind": "building", "latitude": 47.65657, "longitude": -122.30953, "building_code": "ODG", "campus_zone": "North", "has_elevator": True, "accessible_notes": "24-hour study space, automatic doors on the south side."},
    {"id": "bld_allen_lib", "name": "Allen Library", "kind": "building", "latitude": 47.65589, "longitude": -122.30672, "building_code": "ALB", "campus_zone": "Central", "has_elevator": True, "accessible_notes": "Linked to Suzzallo. Research Commons on level 4 via lift."},
    {"id": "bld_kane", "name": "Kane Hall", "kind": "building", "latitude": 47.65726, "longitude": -122.30906, "building_code": "KNE", "campus_zone": "North", "has_elevator": True, "accessible_notes": "Lecture Hall 130 has step-free seating and lift access."},
    {"id": "bld_gerberding", "name": "Gerberding Hall", "kind": "building", "latitude": 47.65638, "longitude": -122.30872, "building_code": "GER", "campus_zone": "Central"},
    {"id": "bld_denny", "name": "Denny Hall", "kind": "building", "latitude": 47.65842, "longitude": -122.30846, "building_code": "DEN", "campus_zone": "North", "accessible_notes": "Oldest building on campus; north side has a continued step-free route."},
    {"id": "bld_savery", "name": "Savery Hall", "kind": "building", "latitude": 47.65805, "longitude": -122.30696, "building_code": "SAV", "campus_zone": "North"},
    {"id": "bld_smith", "name": "Smith Hall", "kind": "building", "latitude": 47.65703, "longitude": -122.30779, "building_code": "SMI", "campus_zone": "North"},
    {"id": "bld_johnson", "name": "Johnson Hall", "kind": "building", "latitude": 47.65720, "longitude": -122.30653, "building_code": "JHN", "campus_zone": "North"},
    {"id": "bld_padelford", "name": "Padelford Hall", "kind": "building", "latitude": 47.65689, "longitude": -122.30551, "building_code": "PDL", "campus_zone": "North", "has_elevator": True},
    {"id": "bld_guggenheim", "name": "Guggenheim Hall", "kind": "building", "latitude": 47.65577, "longitude": -122.30640, "building_code": "GUG", "campus_zone": "Central"},
    {"id": "bld_more", "name": "More Hall", "kind": "building", "latitude": 47.65622, "longitude": -122.30424, "building_code": "MOR", "campus_zone": "Engineering", "has_elevator": True, "accessible_notes": "Dean's office and labs. Accessible entry via the east ramp; the grand stair is the direct route from the quad."},
    {"id": "bld_mech_eng", "name": "Mechanical Engineering Building", "kind": "building", "latitude": 47.65547, "longitude": -122.30430, "building_code": "MEB", "campus_zone": "Engineering"},
    {"id": "bld_hub", "name": "Husky Union Building (HUB)", "kind": "building", "latitude": 47.65518, "longitude": -122.30498, "building_code": "HUB", "campus_zone": "Central", "has_elevator": True, "accessible_notes": "Main services floor. Bookstore, food court and accessible washrooms on level 1."},
    {"id": "bld_cse", "name": "Paul G. Allen Center for CSE", "kind": "building", "latitude": 47.65380, "longitude": -122.30570, "building_code": "CSE", "campus_zone": "Engineering", "has_elevator": True, "accessible_notes": "Atrium entrance is step-free with power-assisted doors."},
    {"id": "bld_mary_gates", "name": "Mary Gates Hall", "kind": "building", "latitude": 47.65541, "longitude": -122.30929, "building_code": "MGH", "campus_zone": "Central", "has_elevator": True},
    {"id": "bld_bagley", "name": "Bagley Hall", "kind": "building", "latitude": 47.65420, "longitude": -122.30908, "building_code": "BAG", "campus_zone": "South"},
    {"id": "bld_chem", "name": "Chemistry Building", "kind": "building", "latitude": 47.65379, "longitude": -122.30962, "building_code": "CHB", "campus_zone": "South"},
    {"id": "bld_physics", "name": "Physics / Astronomy Building", "kind": "building", "latitude": 47.65356, "longitude": -122.31112, "building_code": "PAT", "campus_zone": "South", "accessible_notes": "West ramp approach from Rainier Vista at 6.5% incline."},
    {"id": "bld_health_sci", "name": "Health Sciences Building", "kind": "building", "latitude": 47.65024, "longitude": -122.30928, "building_code": "HSB", "campus_zone": "Medical", "has_elevator": True, "accessible_notes": "Clinical floors are lift-only. South ramp entrance avoids the grand staircase."},
    {"id": "bld_uwmc", "name": "UW Medical Center - Montlake", "kind": "building", "latitude": 47.64988, "longitude": -122.30723, "building_code": "UWMC", "campus_zone": "Medical", "has_elevator": True},
    {"id": "bld_burke", "name": "Burke Museum of Natural History", "kind": "building", "latitude": 47.66134, "longitude": -122.31032, "building_code": "BUR", "campus_zone": "North", "has_elevator": True},
    {"id": "bld_stadium", "name": "Husky Stadium", "kind": "building", "latitude": 47.65026, "longitude": -122.30168, "building_code": "HUS", "campus_zone": "East", "accessible_notes": "Accessible seating via Gate 8."},
    {"id": "bld_south_cc", "name": "South Campus Center", "kind": "building", "latitude": 47.64804, "longitude": -122.30900, "building_code": "SCC", "campus_zone": "South"},
    {"id": "bld_uw_tower", "name": "UW Tower", "kind": "building", "latitude": 47.66010, "longitude": -122.31300, "building_code": "UWT", "campus_zone": "West", "has_elevator": True},

    # --- entrances -------------------------------------------------------
    {"id": "ent_more_steps", "name": "More Hall - Grand Stair Entrance", "kind": "entrance", "latitude": 47.65632, "longitude": -122.30438, "is_entrance": True, "is_step_free": False, "building_code": "MOR", "campus_zone": "Engineering", "accessible_notes": "12 steps, no handrail on the outer flight."},
    {"id": "ent_more_ramp", "name": "More Hall - Accessible East Ramp", "kind": "entrance", "latitude": 47.65612, "longitude": -122.30437, "is_entrance": True, "is_step_free": True, "building_code": "MOR", "campus_zone": "Engineering", "has_elevator": False},
    {"id": "ent_suzzallo_south", "name": "Suzzallo - South Ramp Entrance", "kind": "entrance", "latitude": 47.65548, "longitude": -122.30809, "is_entrance": True, "is_step_free": True, "building_code": "SUZ", "campus_zone": "Central"},
    {"id": "ent_hub_main", "name": "HUB - Main Step-Free Entrance", "kind": "entrance", "latitude": 47.65524, "longitude": -122.30506, "is_entrance": True, "is_step_free": True, "building_code": "HUB", "campus_zone": "Central"},
    {"id": "ent_cse_atrium", "name": "CSE - Atrium Entrance", "kind": "entrance", "latitude": 47.65387, "longitude": -122.30561, "is_entrance": True, "is_step_free": True, "building_code": "CSE", "campus_zone": "Engineering"},
    {"id": "ent_health_ramp", "name": "Health Sciences - South Ramp Entrance", "kind": "entrance", "latitude": 47.65010, "longitude": -122.30934, "is_entrance": True, "is_step_free": True, "building_code": "HSB", "campus_zone": "Medical"},
    {"id": "ent_hsb_steps", "name": "Health Sciences - Grand Staircase Entrance", "kind": "entrance", "latitude": 47.65014, "longitude": -122.30962, "is_entrance": True, "is_step_free": False, "building_code": "HSB", "campus_zone": "Medical"},

    # --- lifts & lift-served facilities ----------------------------------
    {"id": "lift_more", "name": "More Hall Lift Lobby (Level 1)", "kind": "lift", "latitude": 47.65617, "longitude": -122.30419, "has_elevator": True, "building_code": "MOR", "campus_zone": "Engineering"},
    {"id": "more_3f", "name": "More Hall - Computer Labs (Level 3, lift only)", "kind": "facility", "latitude": 47.65622, "longitude": -122.30412, "has_elevator": True, "building_code": "MOR", "campus_zone": "Engineering"},
    {"id": "lift_health", "name": "Health Sciences Lift Bank A (Level 1)", "kind": "lift", "latitude": 47.65028, "longitude": -122.30931, "has_elevator": True, "building_code": "HSB", "campus_zone": "Medical"},
    {"id": "hsb_clinic_3", "name": "Health Sciences Clinic (Level 3, lift only)", "kind": "facility", "latitude": 47.65031, "longitude": -122.30936, "has_elevator": True, "building_code": "HSB", "campus_zone": "Medical", "accessible_notes": "Accessible exam rooms. Lift access only - no stair alternative."},

    # --- pathway intersections -------------------------------------------
    {"id": "jct_burke_lot", "name": "Burke Museum Lot Junction", "kind": "intersection", "latitude": 47.66070, "longitude": -122.31070, "campus_zone": "North"},
    {"id": "jct_uw_tower_plz", "name": "UW Tower Plaza", "kind": "intersection", "latitude": 47.65960, "longitude": -122.31230, "campus_zone": "West"},
    {"id": "jct_denny_yard", "name": "Denny Yard Junction", "kind": "intersection", "latitude": 47.65885, "longitude": -122.30720, "campus_zone": "North"},
    {"id": "jct_quad_ne", "name": "Science Quad North East Junction", "kind": "intersection", "latitude": 47.65770, "longitude": -122.30580, "campus_zone": "Engineering"},
    {"id": "jct_red_square", "name": "Red Square Crossing", "kind": "intersection", "latitude": 47.65599, "longitude": -122.30836, "campus_zone": "Central"},
    {"id": "jct_central_walk_e", "name": "Central Walk East", "kind": "intersection", "latitude": 47.65577, "longitude": -122.30490, "campus_zone": "Central"},
    {"id": "jct_lib_walk", "name": "Library Walk Junction", "kind": "intersection", "latitude": 47.65508, "longitude": -122.30734, "campus_zone": "Central"},
    {"id": "jct_rainier_vista", "name": "Rainier Vista Crossing", "kind": "intersection", "latitude": 47.65461, "longitude": -122.30630, "campus_zone": "Central"},
    {"id": "jct_cse_plaza", "name": "CSE Plaza", "kind": "intersection", "latitude": 47.65390, "longitude": -122.30460, "campus_zone": "Engineering"},
    {"id": "jct_stadium_gate", "name": "Stadium Gate Junction", "kind": "intersection", "latitude": 47.65110, "longitude": -122.30290, "campus_zone": "East"},
    {"id": "jct_health_walk", "name": "Health Sciences Walk", "kind": "intersection", "latitude": 47.65120, "longitude": -122.30900, "campus_zone": "Medical"},
    {"id": "jct_montlake_cross", "name": "Montlake Crossing", "kind": "intersection", "latitude": 47.64940, "longitude": -122.30620, "campus_zone": "Medical"},
]


# ---------------------------------------------------------------------------
# Edges: footpaths, corridors, ramps, stairs, lifts, crossings
# distance_m is computed from node coordinates at seed time (haversine) so the
# dataset can never drift out of sync with the geometry.
# ---------------------------------------------------------------------------
EDGES: list[dict[str, Any]] = [
    # --- north / west ----------------------------------------------------
    {"id": "e_burke_denny", "name": "Memorial Way (Burke to Denny)", "kind": "footpath", "source": "bld_burke", "target": "jct_burke_lot", "width_m": 3.4, "incline_pct": 1.5, "traffic_weight": 0.55, "is_step_free": True},
    {"id": "e_burke_path", "name": "Burke Museum Path", "kind": "footpath", "source": "jct_burke_lot", "target": "bld_denny", "width_m": 3.0, "incline_pct": 0.8, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_tower_path", "name": "UW Tower Approach", "kind": "footpath", "source": "jct_uw_tower_plz", "target": "jct_burke_lot", "width_m": 2.6, "incline_pct": 3.2, "traffic_weight": 0.35, "is_step_free": True},
    {"id": "e_tower_crossing", "name": "UW Tower Crossing", "kind": "crossing", "source": "jct_uw_tower_plz", "target": "bld_uw_tower", "width_m": 3.0, "incline_pct": 2.2, "traffic_weight": 0.4, "is_step_free": True, "has_kerb_ramp": True},
    {"id": "e_denny_walk", "name": "Denny Walk", "kind": "footpath", "source": "bld_denny", "target": "jct_denny_yard", "width_m": 3.2, "incline_pct": 2.0, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_denny_yard_savery", "name": "Denny Yard Path", "kind": "footpath", "source": "jct_denny_yard", "target": "bld_savery", "width_m": 2.8, "incline_pct": 4.5, "traffic_weight": 0.45, "is_step_free": True},
    {"id": "e_savery_steps", "name": "Savery Hall Steps", "kind": "stairs", "source": "bld_savery", "target": "jct_red_square", "width_m": 3.6, "incline_pct": 14.0, "traffic_weight": 0.5, "is_step_free": False, "steps_count": 22},
    {"id": "e_denny_odegaard", "name": "Odegaard Approach", "kind": "footpath", "source": "jct_denny_yard", "target": "bld_odegaard", "width_m": 3.0, "incline_pct": 3.0, "traffic_weight": 0.55, "is_step_free": True},
    {"id": "e_odegaard_kane", "name": "Kane Hall Walk", "kind": "footpath", "source": "bld_odegaard", "target": "bld_kane", "width_m": 2.4, "incline_pct": 2.6, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_kane_red_square", "name": "Kane Hall Ramp", "kind": "ramp", "source": "bld_kane", "target": "jct_red_square", "width_m": 2.2, "incline_pct": 7.0, "traffic_weight": 0.6, "is_step_free": True},

    # --- central: Red Square & Library Walk ------------------------------
    {"id": "e_rs_gerberding", "name": "Red Square North Walk", "kind": "footpath", "source": "bld_gerberding", "target": "jct_red_square", "width_m": 3.6, "incline_pct": 0.5, "traffic_weight": 0.85, "is_step_free": True},
    {"id": "e_rs_suzzallo", "name": "Suzzallo Walk", "kind": "footpath", "source": "jct_red_square", "target": "bld_suzzallo", "width_m": 4.0, "incline_pct": 0.4, "traffic_weight": 0.95, "is_step_free": True},
    {"id": "e_rs_suzzallo_ramp", "name": "Suzzallo South Ramp Entrance", "kind": "ramp", "source": "jct_red_square", "target": "ent_suzzallo_south", "width_m": 2.4, "incline_pct": 6.0, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_suzzallo_atrium", "name": "Suzzallo Atrium Corridor", "kind": "corridor", "source": "ent_suzzallo_south", "target": "bld_suzzallo", "width_m": 2.2, "incline_pct": 0.0, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_rs_mary_gates", "name": "Mary Gates Walk", "kind": "footpath", "source": "jct_red_square", "target": "bld_mary_gates", "width_m": 3.2, "incline_pct": 1.2, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_mary_gates_chem", "name": "Chemistry Approach", "kind": "footpath", "source": "bld_mary_gates", "target": "bld_chem", "width_m": 2.8, "incline_pct": 3.4, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_chem_service_alley", "name": "Chemistry Service Alley", "kind": "footpath", "source": "bld_chem", "target": "bld_physics", "width_m": 1.2, "incline_pct": 1.0, "traffic_weight": 0.2, "is_step_free": True, "accessible_notes": "Minimum clear width 1.2 m - too narrow for two wheelchairs to pass."},
    {"id": "e_chem_bagley", "name": "Bagley Link", "kind": "footpath", "source": "bld_bagley", "target": "bld_chem", "width_m": 2.6, "incline_pct": 2.0, "traffic_weight": 0.45, "is_step_free": True},
    {"id": "e_rs_smith", "name": "Red Square North East", "kind": "footpath", "source": "jct_red_square", "target": "bld_smith", "width_m": 3.0, "incline_pct": 1.8, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_smith_johnson", "name": "Smith-Johnson Walk", "kind": "footpath", "source": "bld_smith", "target": "bld_johnson", "width_m": 2.8, "incline_pct": 2.4, "traffic_weight": 0.55, "is_step_free": True},
    {"id": "e_johnson_padelford", "name": "Padelford Link", "kind": "footpath", "source": "bld_johnson", "target": "bld_padelford", "width_m": 2.6, "incline_pct": 2.0, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_padelford_quad", "name": "Padelford Quad Walk", "kind": "footpath", "source": "bld_padelford", "target": "jct_quad_ne", "width_m": 3.0, "incline_pct": 3.6, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_libwalk_red_square", "name": "Library Walk", "kind": "footpath", "source": "jct_red_square", "target": "jct_lib_walk", "width_m": 3.8, "incline_pct": 1.0, "traffic_weight": 1.0, "is_step_free": True},
    {"id": "e_libwalk_allen", "name": "Library Walk West", "kind": "footpath", "source": "jct_lib_walk", "target": "bld_allen_lib", "width_m": 3.0, "incline_pct": 1.4, "traffic_weight": 0.65, "is_step_free": True},
    {"id": "e_allen_guggenheim", "name": "Allen-Guggenheim Path", "kind": "footpath", "source": "bld_allen_lib", "target": "bld_guggenheim", "width_m": 2.4, "incline_pct": 2.6, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_guggenheim_central", "name": "Guggenheim Walk", "kind": "footpath", "source": "bld_guggenheim", "target": "jct_central_walk_e", "width_m": 3.0, "incline_pct": 3.2, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_central_quad", "name": "Science Quad Walk", "kind": "footpath", "source": "jct_quad_ne", "target": "jct_central_walk_e", "width_m": 3.4, "incline_pct": 4.0, "traffic_weight": 0.75, "is_step_free": True},
    {"id": "e_quad_steps", "name": "Quad Central Steps", "kind": "stairs", "source": "jct_central_walk_e", "target": "jct_red_square", "width_m": 3.8, "incline_pct": 15.0, "traffic_weight": 0.85, "is_step_free": False, "steps_count": 28, "accessible_notes": "28 steps on the direct Central Walk <-> Red Square alignment. There is no step-free link on this alignment; wheelchair users must use the Smith Hall / Padelford loop or the Science Quad Walk."},

    # --- more hall (blocked ramp scenario) -------------------------------
    {"id": "e_quad_more_steps", "name": "More Hall Grand Stair", "kind": "stairs", "source": "jct_quad_ne", "target": "ent_more_steps", "width_m": 3.0, "incline_pct": 16.0, "traffic_weight": 0.5, "is_step_free": False, "steps_count": 12},
    {"id": "e_more_steps_foyer", "name": "More Hall Foyer (via stair landing)", "kind": "corridor", "source": "ent_more_steps", "target": "bld_more", "width_m": 1.6, "incline_pct": 0.0, "traffic_weight": 0.4, "is_step_free": True},
    {"id": "e_more_ramp", "name": "More Hall Accessible East Ramp", "kind": "ramp", "source": "ent_more_ramp", "target": "jct_central_walk_e", "width_m": 1.9, "incline_pct": 8.5, "traffic_weight": 0.65, "is_step_free": True, "accessible_notes": "Only step-free approach to More Hall from Central Walk. 1.9 m clear width."},
    {"id": "e_more_ramp_foyer", "name": "More Hall Ramp Landing", "kind": "corridor", "source": "ent_more_ramp", "target": "bld_more", "width_m": 1.8, "incline_pct": 0.0, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_more_lift_lobby", "name": "More Hall Lift Lobby Corridor", "kind": "corridor", "source": "bld_more", "target": "lift_more", "width_m": 1.9, "incline_pct": 0.0, "traffic_weight": 0.45, "is_step_free": True},
    {"id": "e_more_lift", "name": "More Hall Lift (Levels 1-4)", "kind": "elevator", "source": "lift_more", "target": "more_3f", "width_m": 1.4, "incline_pct": 0.0, "traffic_weight": 0.4, "is_step_free": True, "has_elevator": True},

    # --- central walk east / HUB / CSE -----------------------------------
    {"id": "e_central_mech_eng", "name": "Mechanical Engineering Path", "kind": "footpath", "source": "jct_central_walk_e", "target": "bld_mech_eng", "width_m": 2.6, "incline_pct": 1.2, "traffic_weight": 0.55, "is_step_free": True},
    {"id": "e_central_hub", "name": "Central Walk to HUB", "kind": "footpath", "source": "jct_central_walk_e", "target": "bld_hub", "width_m": 4.2, "incline_pct": 1.0, "traffic_weight": 0.95, "is_step_free": True},
    {"id": "e_hub_entrance", "name": "HUB Main Entrance", "kind": "corridor", "source": "jct_central_walk_e", "target": "ent_hub_main", "width_m": 3.0, "incline_pct": 0.5, "traffic_weight": 0.8, "is_step_free": True},
    {"id": "e_hub_entrance_inner", "name": "HUB Level 1 Concourse", "kind": "corridor", "source": "ent_hub_main", "target": "bld_hub", "width_m": 3.2, "incline_pct": 0.0, "traffic_weight": 0.85, "is_step_free": True},
    {"id": "e_hub_cse", "name": "Rainier Vista Path (HUB to CSE)", "kind": "footpath", "source": "bld_hub", "target": "jct_cse_plaza", "width_m": 3.6, "incline_pct": 3.0, "traffic_weight": 0.8, "is_step_free": True},
    {"id": "e_cse_plaza_path", "name": "CSE Plaza Path", "kind": "footpath", "source": "jct_cse_plaza", "target": "bld_cse", "width_m": 3.0, "incline_pct": 1.5, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_cse_atrium_link", "name": "CSE Atrium Link", "kind": "corridor", "source": "jct_cse_plaza", "target": "ent_cse_atrium", "width_m": 2.8, "incline_pct": 0.8, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_cse_atrium_inner", "name": "CSE Atrium Concourse", "kind": "corridor", "source": "ent_cse_atrium", "target": "bld_cse", "width_m": 3.0, "incline_pct": 0.0, "traffic_weight": 0.75, "is_step_free": True},
    {"id": "e_cse_stadium", "name": "Stadium Way", "kind": "footpath", "source": "jct_cse_plaza", "target": "jct_stadium_gate", "width_m": 3.2, "incline_pct": 4.5, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_stadium_crossing", "name": "Husky Stadium Crossing", "kind": "crossing", "source": "jct_stadium_gate", "target": "bld_stadium", "width_m": 3.0, "incline_pct": 1.0, "traffic_weight": 0.45, "is_step_free": True, "has_kerb_ramp": True},

    # --- Rainier Vista / south -------------------------------------------
    {"id": "e_libwalk_rainier", "name": "Rainier Vista Walk", "kind": "footpath", "source": "jct_lib_walk", "target": "jct_rainier_vista", "width_m": 3.2, "incline_pct": 5.5, "traffic_weight": 1.0, "is_step_free": True},
    {"id": "e_rainier_physics_ramp", "name": "Physics West Ramp", "kind": "ramp", "source": "jct_rainier_vista", "target": "bld_physics", "width_m": 2.6, "incline_pct": 6.5, "traffic_weight": 0.55, "is_step_free": True},
    {"id": "e_rainier_bagley", "name": "Bagley Walk", "kind": "footpath", "source": "jct_rainier_vista", "target": "bld_bagley", "width_m": 2.8, "incline_pct": 2.2, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_rainier_health_walk", "name": "Health Sciences Walk", "kind": "footpath", "source": "jct_rainier_vista", "target": "jct_health_walk", "width_m": 3.0, "incline_pct": 6.0, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_health_walk_ramp", "name": "Health Sciences South Ramp", "kind": "ramp", "source": "jct_health_walk", "target": "ent_health_ramp", "width_m": 2.5, "incline_pct": 5.0, "traffic_weight": 0.65, "is_step_free": True},
    {"id": "e_health_walk_stairs", "name": "Health Sciences Grand Staircase", "kind": "stairs", "source": "jct_health_walk", "target": "ent_hsb_steps", "width_m": 4.0, "incline_pct": 12.0, "traffic_weight": 0.7, "is_step_free": False, "steps_count": 34},
    {"id": "e_health_ramp_lobby", "name": "Health Sciences South Lobby", "kind": "corridor", "source": "ent_health_ramp", "target": "bld_health_sci", "width_m": 3.0, "incline_pct": 0.0, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_health_stairs_lobby", "name": "Health Sciences Stair Landing", "kind": "corridor", "source": "ent_hsb_steps", "target": "bld_health_sci", "width_m": 3.0, "incline_pct": 0.0, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_health_lift_lobby", "name": "Health Sciences Lift Lobby Corridor", "kind": "corridor", "source": "bld_health_sci", "target": "lift_health", "width_m": 2.6, "incline_pct": 0.0, "traffic_weight": 0.6, "is_step_free": True},
    {"id": "e_health_lift", "name": "Health Sciences Lift Bank A (Levels 1-8)", "kind": "elevator", "source": "lift_health", "target": "hsb_clinic_3", "width_m": 1.5, "incline_pct": 0.0, "traffic_weight": 0.55, "is_step_free": True, "has_elevator": True, "accessible_notes": "Only step-free access to the Level 3 clinics."},
    {"id": "e_health_walk_uwmc", "name": "UWMC Approach", "kind": "footpath", "source": "jct_health_walk", "target": "bld_uwmc", "width_m": 3.4, "incline_pct": 2.0, "traffic_weight": 0.7, "is_step_free": True},
    {"id": "e_uwmc_montlake", "name": "Montlake Connector", "kind": "footpath", "source": "bld_uwmc", "target": "jct_montlake_cross", "width_m": 2.8, "incline_pct": 3.0, "traffic_weight": 0.5, "is_step_free": True},
    {"id": "e_montlake_south_cc", "name": "South Campus Path", "kind": "footpath", "source": "jct_montlake_cross", "target": "bld_south_cc", "width_m": 2.6, "incline_pct": 4.0, "traffic_weight": 0.4, "is_step_free": True},
]


# ---------------------------------------------------------------------------
# Initial barrier set: 3 active + historic resolved reports for analytics
# ``offset_hours`` is subtracted from "now" at seed time.
# ---------------------------------------------------------------------------
BARRIER_SCENARIOS: list[dict[str, Any]] = [
    {
        "slug": "blocked_ramp_more",
        "category": "blocked_ramp",
        "edge_id": "e_more_ramp",
        "latitude_offset": 0.00003,
        "longitude_offset": -0.00006,
        "confidence": 0.91,
        "status": "verified",
        "confirmations": 2,
        "detection_source": "yolov8",
        "description": "Two e-scooters abandoned across the More Hall ramp - the only step-free way in from Central Walk.",
        "offset_hours": 7.5,
        "reporter_label": "j.okafor@campus.edu",
        "auto_verify_reason": "Confidence 0.91 >= 0.85 threshold",
    },
    {
        "slug": "broken_lift_hsb",
        "category": "broken_lift",
        "edge_id": "e_health_lift",
        "latitude_offset": 0.00002,
        "longitude_offset": 0.00002,
        "confidence": 0.84,
        "status": "verified",
        "confirmations": 3,
        "detection_source": "citizen_manual",
        "description": "Lift Bank A out of service (error E04). Level 3 clinics currently have no step-free access.",
        "offset_hours": 26.0,
        "reporter_label": "clinic.reception@campus.edu",
        "auto_verify_reason": "3 independent confirmations (>= 2) confirmed the lift outage",
    },
    {
        "slug": "construction_rainier",
        "category": "construction",
        "edge_id": "e_libwalk_rainier",
        "latitude_offset": 0.00001,
        "longitude_offset": 0.00007,
        "confidence": 0.63,
        "status": "unverified",
        "confirmations": 1,
        "detection_source": "heuristic",
        "description": "Scaffolding and barrier fencing narrowing Rainier Vista Walk near the fountain.",
        "offset_hours": 3.2,
        "reporter_label": "student.union@campus.edu",
        "auto_verify_reason": None,
    },
    {
        "slug": "obstacle_hub_walk",
        "category": "obstacle",
        "edge_id": "e_central_hub",
        "latitude_offset": -0.00002,
        "longitude_offset": 0.00004,
        "confidence": 0.88,
        "status": "resolved",
        "confirmations": 1,
        "detection_source": "heuristic",
        "description": "Delivery pallets blocking half of Central Walk outside the HUB.",
        "offset_hours": 52.0,
        "resolved_after_hours": 5.5,
        "reporter_label": "facilities.rounds@campus.edu",
        "resolution_note": "Pallets relocated to the loading bay; path cleared and swept.",
    },
    {
        "slug": "narrow_path_alley",
        "category": "narrow_path",
        "edge_id": "e_chem_service_alley",
        "latitude_offset": 0.00001,
        "longitude_offset": -0.00003,
        "confidence": 0.72,
        "status": "resolved",
        "confirmations": 2,
        "detection_source": "heuristic",
        "description": "Overgrown hedges reduced the Chemistry service alley to a 1.0 m gap.",
        "offset_hours": 120.0,
        "resolved_after_hours": 41.0,
        "reporter_label": "grounds.watch@campus.edu",
        "resolution_note": "Grounds team cut the hedge line back to 2.1 m clear width.",
    },
    {
        "slug": "missing_signage_bagley",
        "category": "missing_signage",
        "edge_id": "e_rainier_bagley",
        "latitude_offset": 0.00002,
        "longitude_offset": 0.00002,
        "confidence": 0.58,
        "status": "resolved",
        "confirmations": 0,
        "detection_source": "heuristic",
        "description": "No signage directing wheelchair users to the Bagley Hall accessible entrance.",
        "offset_hours": 190.0,
        "resolved_after_hours": 96.0,
        "reporter_label": "accessibility.office@campus.edu",
        "resolution_note": "Wayfinding plates installed at both approach points.",
    },
    {
        "slug": "broken_lift_more_historic",
        "category": "broken_lift",
        "edge_id": "e_more_lift",
        "latitude_offset": 0.0,
        "longitude_offset": 0.00001,
        "confidence": 0.9,
        "status": "resolved",
        "confirmations": 1,
        "detection_source": "yolov8",
        "description": "More Hall lift stuck between levels 2 and 3 during a lecture changeover.",
        "offset_hours": 340.0,
        "resolved_after_hours": 3.0,
        "reporter_label": "m.tanaka@campus.edu",
        "resolution_note": "Lift engineer reset the door interlock; back in service the same evening.",
    },
    {
        "slug": "construction_quad_historic",
        "category": "construction",
        "edge_id": "e_central_quad",
        "latitude_offset": -0.00002,
        "longitude_offset": -0.00001,
        "confidence": 0.81,
        "status": "resolved",
        "confirmations": 4,
        "detection_source": "heuristic",
        "description": "Science Quad resurfacing closed the eastern half of the walk for a week.",
        "offset_hours": 260.0,
        "resolved_after_hours": 118.0,
        "reporter_label": "estates.projectsoffice@campus.edu",
        "resolution_note": "Resurfacing complete; tactile paving reinstated at both junctions.",
    },
]


# ---------------------------------------------------------------------------
# Demo accounts
# ---------------------------------------------------------------------------
USERS: list[dict[str, Any]] = [
    {"email": "admin@campus.edu", "full_name": "Priya Raman", "role": "admin", "password": "admin123"},
    {"email": "facilities@campus.edu", "full_name": "Dan Whitlock", "role": "staff", "password": "facilities123"},
    {"email": "demo@campus.edu", "full_name": "Demo Student", "role": "student", "password": "demo123"},
]


#: Quick-pick destinations exposed to the route planner sidebar.
PRESET_DESTINATIONS: list[dict[str, Any]] = [
    {"node_id": "bld_suzzallo", "label": "Central Library", "category": "study", "icon": "library"},
    {"node_id": "bld_hub", "label": "HUB (Student Union)", "category": "services", "icon": "hub"},
    {"node_id": "bld_cse", "label": "Allen Center for CSE", "category": "academic", "icon": "code"},
    {"node_id": "bld_more", "label": "More Hall", "category": "academic", "icon": "academic", "note": "Step-free entry only via the east ramp"},
    {"node_id": "more_3f", "label": "More Hall Computer Labs (L3)", "category": "academic", "icon": "academic", "note": "Lift access only"},
    {"node_id": "hsb_clinic_3", "label": "Health Sciences Clinic (L3)", "category": "medical", "icon": "medical", "note": "Lift access only"},
    {"node_id": "bld_health_sci", "label": "Health Sciences Building", "category": "medical", "icon": "medical"},
    {"node_id": "bld_odegaard", "label": "Odegaard Library", "category": "study", "icon": "library"},
    {"node_id": "bld_burke", "label": "Burke Museum", "category": "culture", "icon": "museum"},
    {"node_id": "bld_stadium", "label": "Husky Stadium", "category": "sports", "icon": "stadium"},
]
