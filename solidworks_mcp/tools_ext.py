"""
MCP tool registry — the single source of truth for every tool
-------------------------------------------------------------
TOOL_TABLE: tool name -> (description, JSON-schema properties, required,
automation method name). Arguments are forwarded to the method by name,
filtered to the schema's properties, so schema keys must match the method's
parameter names (enforced by the test-suite). CATEGORIES groups the tools
for the README / user manual.
"""

from typing import Any, Dict, List, Tuple

from mcp.types import Tool

# ----------------------------------------------------------------------------
# Shared schema fragments
# ----------------------------------------------------------------------------

UNIT = {"type": "string", "enum": ["mm", "cm", "m", "inch", "ft"],
        "description": "Length unit (default: server default unit)"}

REF_SPEC = {
    "type": "object",
    "description": (
        "Reference entity. One of: {\"plane\": \"Front|Top|Right|<name>\"}, "
        "{\"edge_index\": n}, {\"face_index\": n} (indices from list_edges/list_faces), "
        "{\"name\": \"Axis1\", \"type\": \"AXIS\"}, "
        "{\"point\": [x,y,z], \"type\": \"FACE|EDGE|VERTEX\"} (model coords, user unit)"),
}

MATE_ENTITY = {
    "type": "object",
    "description": (
        "Assembly entity. One of: {\"component\": \"Part1-1\", \"plane\": \"Front\"}, "
        "{\"plane\": \"Top\"} (assembly plane), {\"point\": [x,y,z], \"type\": \"FACE\"}, "
        "{\"name\": \"Axis1@Shaft-1@Asm1\", \"type\": \"AXIS\"}"),
}

SKETCH_ENTITY = {
    "type": "object",
    "description": (
        "Sketch entity, located in active-sketch 2D coords: {\"point\": [x,y]} = segment through "
        "that point; add \"type\": \"SKETCHPOINT\" for an endpoint/center; or "
        "{\"name\": \"Point1@Origin\", \"type\": \"EXTSKETCHPOINT\"} for the origin"),
}

AXIS_ENUM = ["x", "y", "z"]
SIGNED_AXIS_ENUM = ["x", "y", "z", "+x", "+y", "+z", "-x", "-y", "-z"]
INT_LIST = {"type": "array", "items": {"type": "integer"}}
STR_LIST = {"type": "array", "items": {"type": "string"}}

EDGE_FILTERS = {
    "edge_type": {"type": "string", "enum": ["all", "line", "circle", "arc", "circular"],
                  "description": "circle = full circle, arc = partial, circular = both"},
    "parallel_to": {"type": "string", "enum": AXIS_ENUM, "description": "Linear edges parallel to axis"},
    "axis_parallel_to": {"type": "string", "enum": AXIS_ENUM,
                         "description": "Circular edges whose axis is parallel to axis (e.g. hole rims)"},
    "radius": {"type": "number", "description": "Circular edges with this radius"},
    "min_length": {"type": "number"},
    "max_length": {"type": "number"},
    "on_face_index": {"type": "integer", "description": "Only edges bounding this face"},
    "unit": UNIT,
}

FACE_FILTERS = {
    "face_type": {"type": "string", "enum": ["all", "plane", "cylinder", "cone", "sphere", "torus", "other"]},
    "normal": {"type": "string", "enum": SIGNED_AXIS_ENUM,
               "description": "Planar faces with this normal ('z' = ±Z, '+z' = outward +Z only)"},
    "radius": {"type": "number", "description": "Cylindrical faces with this radius"},
    "min_area": {"type": "number", "description": "In unit^2"},
    "unit": UNIT,
}

VIEW_ENUM = ["front", "back", "left", "right", "top", "bottom", "isometric", "trimetric", "dimetric"]


def _p(**props) -> Dict[str, Any]:
    return props


# name: (description, properties, required, method)
TOOL_TABLE: Dict[str, Tuple[str, Dict, List[str], str]] = {

    # ------------------------------------------------------------ connection / documents
    "connect_solidworks": ("Connect to SolidWorks (launches it if not running).", {}, [], "connect"),
    "get_solidworks_info": ("Installed SolidWorks version/path and the running version.", {}, [],
                            "get_solidworks_info"),
    "create_new_part": ("New part from the default (or config.json) part template.", {}, [], "create_new_part"),
    "create_new_assembly": ("New assembly from the default assembly template.", {}, [], "create_new_assembly"),
    "open_document": ("Open a .sldprt / .sldasm / .slddrw file.", _p(filepath={"type": "string"}),
                      ["filepath"], "open_document"),
    "save_document": ("Save the active document; filepath = Save As (.sldprt/.sldasm/.slddrw).",
                      _p(filepath={"type": "string"}), [], "save_document"),
    "close_document": ("Close the active document.", _p(save={"type": "boolean", "default": False}), [],
                       "close_document"),
    "get_document_info": ("Title, path, type and configuration of the active document.", {}, [],
                          "get_document_info"),
    "list_open_documents": ("List open documents.", {}, [], "list_open_documents"),
    "set_units": ("Default length unit for all tools.",
                  _p(unit={"type": "string", "enum": ["mm", "cm", "m", "inch", "ft"]}), ["unit"], "set_units"),
    "execute_python": (
        "Run Python against the SolidWorks API (sw, doc, automation in scope; print() and `result` are "
        "returned). For anything the tools do not cover. Full machine access: trusted use only.",
        _p(code={"type": "string"}), ["code"], "execute_python"),

    # ------------------------------------------------------------ sketch basics
    "create_sketch": ("Start a sketch on Front / Top / Right or any reference plane by name (e.g. 'P25').",
                      _p(plane={"type": "string", "default": "Front"}), [], "create_sketch"),
    "create_sketch_on_face": ("Start a sketch on the body face at model point x, y, z.",
                              _p(x={"type": "number", "default": 0}, y={"type": "number", "default": 0},
                                 z={"type": "number", "default": 0}, unit=UNIT), [], "create_sketch_on_face"),
    "close_sketch": ("Exit the active sketch (coincident endpoints are merged first).", {}, [], "close_sketch"),
    "get_sketch_status": ("Is a sketch open; sketch names in the tree.", {}, [], "get_sketch_status"),
    "draw_line": ("Line in the active sketch (sketch coordinates).",
                  _p(x1={"type": "number"}, y1={"type": "number"}, x2={"type": "number"}, y2={"type": "number"},
                     unit=UNIT), ["x1", "y1", "x2", "y2"], "draw_line"),
    "draw_circle": ("Circle by centre and radius.", _p(x={"type": "number", "default": 0},
                                                       y={"type": "number", "default": 0},
                                                       radius={"type": "number"}, unit=UNIT),
                    ["radius"], "draw_circle"),
    "draw_rectangle": ("Corner rectangle from (x1, y1) to (x2, y2).",
                       _p(x1={"type": "number"}, y1={"type": "number"}, x2={"type": "number"},
                          y2={"type": "number"}, unit=UNIT), ["x1", "y1", "x2", "y2"], "draw_rectangle"),
    "draw_arc": ("Arc by centre, radius, start and end angle (deg, counter-clockwise).",
                 _p(cx={"type": "number"}, cy={"type": "number"}, radius={"type": "number"},
                    start_angle={"type": "number"}, end_angle={"type": "number"}, unit=UNIT),
                 ["cx", "cy", "radius", "start_angle", "end_angle"], "draw_arc_center"),
    "draw_polygon": ("Regular polygon (circumscribed radius).",
                     _p(cx={"type": "number", "default": 0}, cy={"type": "number", "default": 0},
                        radius={"type": "number"}, sides={"type": "integer", "default": 6}, unit=UNIT),
                     ["radius"], "draw_polygon"),

    # ------------------------------------------------------------ basic features
    "extrude_sketch": ("Boss-extrude the last sketch (blind or mid-plane). See `extrude` for all options.",
                       _p(depth={"type": "number", "default": 10},
                          both_directions={"type": "boolean", "default": False}, unit=UNIT), [], "extrude_sketch"),
    "cut_extrude": ("Cut-extrude the last sketch (blind / through all, one or both directions).",
                    _p(depth={"type": "number", "default": 10}, through_all={"type": "boolean", "default": False},
                       both_directions={"type": "boolean", "default": False}, unit=UNIT), [], "cut_extrude"),
    "fillet_edges": ("Constant-radius fillet on the selected edges (select_edges first).",
                     _p(radius={"type": "number"}, unit=UNIT), ["radius"], "fillet_edges"),
    "chamfer_edges": ("Distance-angle chamfer on the selected edges (select_edges first).",
                      _p(distance={"type": "number"}, angle={"type": "number", "default": 45}, unit=UNIT),
                      ["distance"], "chamfer_edges"),
    "list_features": ("Feature tree: name, type, suppressed.", {}, [], "list_features"),

    # ------------------------------------------------------------ selection
    "list_edges": (
        "List edges of the active part with stable indices and geometry (type, length, midpoint, "
        "direction / radius). Use before select_edges, fillet, chamfer, patterns. Indices change "
        "after any feature edit — re-list.",
        _p(**EDGE_FILTERS, limit={"type": "integer", "default": 200}), [], "list_edges"),
    "list_faces": (
        "List faces of the active part with indices, type, area, normal / radius and a point on "
        "the face. Use before select_faces, shell, sketch-on-face, mates.",
        _p(**FACE_FILTERS, limit={"type": "integer", "default": 200}), [], "list_faces"),
    "select_edges": (
        "Select edges by index list and/or geometric filter, e.g. all vertical edges "
        "(parallel_to='z') or all R2.5 hole rims (radius=2.5, axis_parallel_to='z'). "
        "Then call fillet_edges / chamfer_edges.",
        _p(indices=INT_LIST, **EDGE_FILTERS,
           append={"type": "boolean", "default": False},
           mark={"type": "integer", "default": 0}), [], "select_edges"),
    "select_faces": (
        "Select faces by index list and/or filter (type, normal, radius, min area).",
        _p(indices=INT_LIST, **FACE_FILTERS,
           append={"type": "boolean", "default": False},
           mark={"type": "integer", "default": 0}), [], "select_faces"),
    "select_entity": (
        "Generic SelectByID2: select by name (e.g. 'Front Plane', 'Sketch1', 'Boss-Extrude1') "
        "and/or a point. sketch_coords=true interprets point in the active sketch's 2D space.",
        _p(entity_type={"type": "string",
                        "description": "PLANE, FACE, EDGE, VERTEX, AXIS, SKETCH, SKETCHSEGMENT, "
                                       "SKETCHPOINT, BODYFEATURE, COMPONENT, EXTSKETCHPOINT"},
           name={"type": "string", "default": ""},
           point={"type": "array", "items": {"type": "number"}},
           append={"type": "boolean", "default": False},
           mark={"type": "integer", "default": 0},
           sketch_coords={"type": "boolean", "default": False},
           unit=UNIT), ["entity_type"], "select_entity"),
    "clear_selection": ("Clear the current selection.", {}, [], "clear_selection"),
    "get_selection": ("Show what is currently selected (type, mark, pick point).",
                      _p(unit=UNIT), [], "get_selection"),

    # ------------------------------------------------------------ sketch
    "draw_centerline": (
        "Draw a construction centerline in the active sketch (revolve axis / symmetry line).",
        _p(x1={"type": "number"}, y1={"type": "number"}, x2={"type": "number"},
           y2={"type": "number"}, unit=UNIT), ["x1", "y1", "x2", "y2"], "draw_centerline"),
    "draw_slot": (
        "Draw a straight slot, center-to-center from (x1,y1) to (x2,y2), given width.",
        _p(x1={"type": "number"}, y1={"type": "number"}, x2={"type": "number"},
           y2={"type": "number"}, width={"type": "number"},
           add_dimensions={"type": "boolean", "default": False}, unit=UNIT),
        ["x1", "y1", "x2", "y2", "width"], "draw_slot"),
    "sketch_fillet": (
        "Round a sketch corner (shared endpoint of two segments) at corner=[x,y].",
        _p(corner={"type": "array", "items": {"type": "number"}},
           radius={"type": "number"}, unit=UNIT), ["corner", "radius"], "sketch_fillet"),
    "add_sketch_dimension": (
        "Smart dimension in the active sketch. 1 entity: line length / circle diameter / arc radius. "
        "2 entities: distance or angle between them. `value` drives geometry. Use unit='deg' for angles.",
        _p(entities={"type": "array", "items": SKETCH_ENTITY, "minItems": 1, "maxItems": 2},
           value={"type": "number"},
           text_position={"type": "array", "items": {"type": "number"}},
           unit={"type": "string", "enum": ["mm", "cm", "m", "inch", "ft", "deg", "rad"]}),
        ["entities"], "add_sketch_dimension"),
    "add_sketch_relation": (
        "Add a geometric relation between sketch entities.",
        _p(relation={"type": "string",
                     "enum": ["horizontal", "vertical", "coincident", "concentric", "coradial",
                              "tangent", "parallel", "perpendicular", "collinear", "equal",
                              "midpoint", "symmetric", "fixed"]},
           entities={"type": "array", "items": SKETCH_ENTITY, "minItems": 1},
           unit=UNIT), ["relation", "entities"], "add_sketch_relation"),

    # ------------------------------------------------------------ features
    "revolve": (
        "Revolve (boss) or cut-revolve the last sketch about its centerline (or `axis`). "
        "Profile must be closed and must not cross the axis.",
        _p(angle={"type": "number", "default": 360},
           cut={"type": "boolean", "default": False},
           mid_plane={"type": "boolean", "default": False},
           reverse={"type": "boolean", "default": False},
           thin_thickness={"type": "number", "description": "Thin-feature wall; omit for solid"},
           axis=REF_SPEC, unit=UNIT), [], "revolve_sketch"),
    "shell": (
        "Shell the part with given wall thickness, removing faces by index or by normal "
        "(e.g. face_normal='+z' opens the top). No faces = hollow closed body.",
        _p(thickness={"type": "number"}, face_indices=INT_LIST,
           face_normal={"type": "string", "enum": SIGNED_AXIS_ENUM},
           outward={"type": "boolean", "default": False}, unit=UNIT),
        ["thickness"], "shell"),
    "linear_pattern": (
        "Linear pattern of features. direction = linear edge, axis or planar face (normal).",
        _p(features=STR_LIST, direction1=REF_SPEC,
           count1={"type": "integer"}, spacing1={"type": "number"},
           direction2=REF_SPEC, count2={"type": "integer", "default": 1},
           spacing2={"type": "number", "default": 0},
           flip1={"type": "boolean", "default": False}, flip2={"type": "boolean", "default": False},
           geometry_pattern={"type": "boolean", "default": False}, unit=UNIT),
        ["features", "direction1", "count1", "spacing1"], "linear_pattern"),
    "circular_pattern": (
        "Circular pattern of features. axis = cylindrical face (uses its axis), axis feature, "
        "or linear edge. equal_spacing=true: angle = total span; false: angle = pitch.",
        _p(features=STR_LIST, axis=REF_SPEC, count={"type": "integer"},
           angle={"type": "number", "default": 360},
           equal_spacing={"type": "boolean", "default": True},
           flip={"type": "boolean", "default": False},
           geometry_pattern={"type": "boolean", "default": False}),
        ["features", "axis", "count"], "circular_pattern"),
    "mirror": (
        "Mirror features (or all solid bodies with mirror_bodies=true) about a plane or planar face.",
        _p(plane=REF_SPEC, features=STR_LIST,
           mirror_bodies={"type": "boolean", "default": False},
           merge={"type": "boolean", "default": True},
           geometry_pattern={"type": "boolean", "default": False}),
        ["plane"], "mirror"),
    "create_ref_plane": (
        "Create a reference plane. mode=offset: parallel to base at distance. mode=angle: through "
        "`axis` at angle to base. mode=mid: midway between base and `second`.",
        _p(base=REF_SPEC, mode={"type": "string", "enum": ["offset", "angle", "mid"], "default": "offset"},
           distance={"type": "number", "default": 10}, angle={"type": "number", "default": 45},
           axis=REF_SPEC, second=REF_SPEC, flip={"type": "boolean", "default": False},
           name={"type": "string"}, unit=UNIT), ["base"], "create_ref_plane"),

    # ------------------------------------------------------------ model / parametric
    "list_dimensions": (
        "List driving dimensions (name usable with set_dimension, value, unit). Optional feature filter.",
        _p(feature={"type": "string"}, unit=UNIT), [], "list_dimensions"),
    "set_dimension": (
        "Change a dimension by name (e.g. 'D1@Sketch1', 'D1@Boss-Extrude1') and rebuild. "
        "Reports rebuild errors. Kind is auto-detected: angles in degrees (unit='rad' for radians), "
        "pattern counts as integers, lengths in `unit`.",
        _p(name={"type": "string"}, value={"type": "number"},
           unit={"type": "string", "enum": ["mm", "cm", "m", "inch", "ft", "deg", "rad"]}),
        ["name", "value"], "set_dimension"),
    "suppress_feature": (
        "Suppress or unsuppress a feature by name.",
        _p(name={"type": "string"}, suppress={"type": "boolean", "default": True}),
        ["name"], "suppress_feature"),
    "rebuild": ("Rebuild the model (force=true for Ctrl+Q) and report features with errors.",
                _p(force={"type": "boolean", "default": False}), [], "rebuild_model"),
    "undo": ("Undo the last N operations.", _p(steps={"type": "integer", "default": 1}), [], "undo"),
    "get_mass_properties": (
        "Mass (g, kg), volume, surface area, density, center of mass, principal moments of inertia, material.",
        _p(unit=UNIT), [], "get_mass_properties"),
    "set_material": (
        "Assign a material by exact library name (e.g. 'AISI 304', '6061-T6 (SS)', 'ABS', 'PA Type 6').",
        _p(material={"type": "string"},
           database={"type": "string", "default": "SOLIDWORKS Materials"},
           config={"type": "string"}), ["material"], "set_material"),
    "set_custom_property": (
        "Add/overwrite a text custom property (PartNo, Description, Material, Revision...). "
        "config='' = file-level.",
        _p(name={"type": "string"}, value={"type": "string"},
           config={"type": "string", "default": ""}), ["name", "value"], "set_custom_property"),
    "get_custom_properties": (
        "Read all custom properties (value and resolved value).",
        _p(config={"type": "string", "default": ""}), [], "get_custom_properties"),
    "export_document": (
        "Export a copy of the active document; format from extension: .step/.stp, .igs, .x_t, .stl, "
        ".3mf, .eprt, .pdf/.dxf (drawings)...",
        _p(filepath={"type": "string"}), ["filepath"], "export_document"),
    "set_view": (
        "Set a standard view orientation and zoom to fit.",
        _p(view={"type": "string", "enum": VIEW_ENUM, "default": "isometric"},
           zoom_to_fit={"type": "boolean", "default": True}), [], "set_view"),
    "capture_view": (
        "Render the current viewport (optionally re-oriented) and return it as an image, so the "
        "result of a modeling step can be checked visually.",
        _p(view={"type": "string", "enum": VIEW_ENUM},
           width={"type": "integer", "default": 1280}, height={"type": "integer", "default": 800},
           save_path={"type": "string"}), [], "capture_view"),

    # ------------------------------------------------------------ assembly
    "insert_component": (
        "Insert a part/sub-assembly file into the active assembly at (x, y, z).",
        _p(filepath={"type": "string"}, x={"type": "number", "default": 0},
           y={"type": "number", "default": 0}, z={"type": "number", "default": 0},
           config={"type": "string", "default": ""}, unit=UNIT), ["filepath"], "insert_component"),
    "add_mate": (
        "Add a standard mate between two entities of the active assembly.",
        _p(mate_type={"type": "string",
                      "enum": ["coincident", "concentric", "perpendicular", "parallel",
                               "tangent", "distance", "angle", "lock"]},
           entity1=MATE_ENTITY, entity2=MATE_ENTITY,
           alignment={"type": "string", "enum": ["aligned", "anti_aligned", "closest"],
                      "default": "closest"},
           flip={"type": "boolean", "default": False},
           distance={"type": "number", "default": 0}, angle={"type": "number", "default": 0},
           unit=UNIT), ["mate_type", "entity1", "entity2"], "add_mate"),
    "list_components": (
        "List components of the active assembly (name, path, config, suppressed, fixed).",
        _p(top_level_only={"type": "boolean", "default": True}), [], "list_components"),

    # ------------------------------------------------------------ drawing
    "create_drawing": (
        "New drawing of a saved part/assembly (default: the active model). Default layout: projected "
        "Front/Top/Right per the sheet's 1st/3rd-angle setting + isometric, auto-scaled to the sheet. "
        "`views` gives independent named views instead. Optional model dimensions and save path.",
        _p(model_path={"type": "string"}, views={"type": "array", "items": {"type": "string", "enum": VIEW_ENUM}},
           scale={"type": "string", "default": "auto", "description": "'auto' or e.g. '1:2', '2:1'"},
           template={"type": "string", "description": ".drwdot path (default: SolidWorks default template)"},
           include_iso={"type": "boolean", "default": True},
           model_dimensions={"type": "boolean", "default": False},
           center_marks={"type": "boolean", "default": True},
           save_path={"type": "string", "description": "Save as .slddrw"}),
        [], "create_drawing"),
    "list_drawing_views": (
        "List sheets and views of the active drawing: name, model, scale, outline and center in sheet mm. "
        "Use the outline to place section/detail views.", {}, [], "list_drawing_views"),
    "add_drawing_view": (
        "Add a named model view (front/top/.../isometric) at sheet position x, y (mm).",
        _p(view={"type": "string", "enum": VIEW_ENUM}, x={"type": "number"}, y={"type": "number"},
           model_path={"type": "string"}, scale={"type": "string"}),
        ["view", "x", "y"], "add_drawing_view"),
    "add_section_view": (
        "Full section through a view: cutting line vertical/horizontal at `position` (0..1 across the view). "
        "Placed beside/below the parent unless x, y (sheet mm) are given.",
        _p(parent_view={"type": "string"}, direction={"type": "string", "enum": ["vertical", "horizontal"]},
           position={"type": "number", "default": 0.5}, x={"type": "number"}, y={"type": "number"},
           label={"type": "string", "default": "A"}, flip={"type": "boolean", "default": False}),
        ["parent_view"], "add_section_view"),
    "add_detail_view": (
        "Detail view: circle centred at sheet point `center` [x, y] mm inside the parent view, radius mm.",
        _p(parent_view={"type": "string"}, center={"type": "array", "items": {"type": "number"}},
           radius={"type": "number"}, scale={"type": "string", "default": "2:1"},
           x={"type": "number"}, y={"type": "number"}, label={"type": "string", "default": "B"}),
        ["parent_view", "center", "radius"], "add_detail_view"),
    "insert_model_annotations": (
        "Import model items into the drawing (all views or listed views). Default: dimensions marked "
        "for drawing + hole callouts.",
        _p(types={"type": "array", "items": {"type": "string", "enum": [
               "dimensions_marked", "dimensions_all", "hole_callouts", "cosmetic_threads", "datums", "gtols",
               "notes", "surface_finish", "axes", "center_of_mass", "hole_wizard_locations",
               "hole_wizard_profiles"]}},
           views={"type": "array", "items": {"type": "string"}}),
        [], "insert_model_annotations"),
    "insert_bom": (
        "Insert a BOM table for a view's model at a sheet corner. Template auto-found if omitted.",
        _p(view={"type": "string"}, bom_type={"type": "string", "enum": ["parts_only", "top_level", "indented"],
                                              "default": "parts_only"},
           template={"type": "string", "description": ".sldbomtbt path"},
           anchor={"type": "string", "enum": ["top_left", "top_right", "bottom_left", "bottom_right"],
                   "default": "top_right"},
           configuration={"type": "string", "default": ""}),
        [], "insert_bom"),
    "auto_balloon": (
        "Auto-balloon components in views (all views if none given); needs a BOM for item numbers.",
        _p(views={"type": "array", "items": {"type": "string"}},
           layout={"type": "string", "enum": ["square", "circle", "top", "bottom", "right", "left"],
                   "default": "square"},
           style={"type": "string", "enum": ["circular", "triangle", "hexagon", "box", "diamond",
                                             "split_circle"], "default": "circular"}),
        [], "auto_balloon"),

    # ------------------------------------------------------------ loft / sweep
    "loft": (
        "Loft (boss or cut) through >= 2 closed profile sketches in order, optional guide curves. "
        "Sketch profiles on offset planes first (create_ref_plane, then create_sketch(plane=<name>)).",
        _p(profiles=STR_LIST, guides={"type": "array", "items": {}},
           cut={"type": "boolean", "default": False}, closed={"type": "boolean", "default": False},
           start_tangency={"type": "string", "enum": ["none", "normal", "direction", "all_faces"], "default": "none"},
           end_tangency={"type": "string", "enum": ["none", "normal", "direction", "all_faces"], "default": "none"},
           thin_thickness={"type": "number"}, merge={"type": "boolean", "default": True}, unit=UNIT),
        ["profiles"], "loft"),
    "sweep": (
        "Sweep (boss or cut) a profile sketch — or a circle of circular_diameter — along a path "
        "(sketch name or {\"edge_index\": n}). Optional guides and twist (degrees).",
        _p(path={"description": "Path sketch name or reference object"},
           profile={"type": "string"}, circular_diameter={"type": "number"},
           guides={"type": "array", "items": {}}, cut={"type": "boolean", "default": False},
           twist_angle={"type": "number", "default": 0},
           keep_normal_constant={"type": "boolean", "default": False},
           thin_thickness={"type": "number"}, merge={"type": "boolean", "default": True}, unit=UNIT),
        ["path"], "sweep"),

    # ------------------------------------------------------------ batch / import
    "batch_export": (
        "Export every .sldprt/.sldasm (optionally .slddrw) in a folder to STEP/STL/3MF/IGES/Parasolid/PDF/"
        "DXF/eDrawings. Mirrors folder structure under output_dir (default <folder>/export).",
        _p(folder={"type": "string"}, formats={"type": "array", "items": {"type": "string", "enum": [
               "step", "stp", "iges", "parasolid", "x_b", "stl", "3mf", "acis", "pdf", "dxf", "dwg",
               "edrawings", "png", "jpg"]}},
           recursive={"type": "boolean", "default": False}, output_dir={"type": "string"},
           file_types={"type": "array", "items": {"type": "string", "enum": ["sldprt", "sldasm", "slddrw"]}},
           overwrite={"type": "boolean", "default": False}, max_files={"type": "integer", "default": 100}),
        ["folder"], "batch_export"),
    "import_file": (
        "Open a STEP/IGES/Parasolid/STL/3MF or Inventor/CATIA/NX/Creo file (import or 3D Interconnect), "
        "optionally save as .sldprt/.sldasm. Reports bodies/components.",
        _p(filepath={"type": "string"}, save_as={"type": "string"}), ["filepath"], "import_file"),
    "activate_document": (
        "Bring an open document to the front by its title.",
        _p(name={"type": "string"}), ["name"], "activate_document"),

    # ------------------------------------------------------------ edit
    "get_feature_info": (
        "Feature type and editable parameters (extrude depth/end condition, revolve angle, fillet radius, "
        "chamfer, shell/rib thickness, pattern counts/spacing, hole size).",
        _p(name={"type": "string"}, unit=UNIT), ["name"], "get_feature_info"),
    "edit_feature": (
        "Edit an existing feature's definition and rebuild. params by kind — extrude: depth, depth2, "
        "end_condition(2) [blind, through_all, through_all_both, mid_plane, up_to_next, through_next], "
        "reverse, draft_angle; revolve: angle, angle2; fillet: radius; chamfer: distance, angle; "
        "shell/rib: thickness; linear_pattern: count1, spacing1, reverse1, count2, spacing2, reverse2; "
        "circular_pattern: count, angle, equal_spacing, reverse. Angles in degrees.",
        _p(name={"type": "string"}, params={"type": "object"}, unit=UNIT), ["name", "params"], "edit_feature"),

    # ------------------------------------------------------------ rib / draft / hole
    "rib": (
        "Rib from the last sketch (open contour touching the walls).",
        _p(thickness={"type": "number"}, two_sided={"type": "boolean", "default": True},
           flip_material={"type": "boolean", "default": False},
           reverse_thickness={"type": "boolean", "default": False},
           draft_angle={"type": "number", "default": 0}, draft_outward={"type": "boolean", "default": False},
           normal_to_sketch={"type": "boolean", "default": False}, unit=UNIT),
        ["thickness"], "rib"),
    "draft": (
        "Neutral-plane draft (degrees) on faces chosen by index or filter, e.g. outer side faces "
        "face_type='plane' + face_normal='x' + min_area=100. Retries with tangent propagation and flip.",
        _p(angle={"type": "number"},
           neutral={"type": "object", "description": "Neutral plane: {\"face_normal\": \"-y\"} = largest planar "
                    "model face with that normal (most reliable), or a reference spec ({\"plane\": \"Top\"}, "
                    "{\"face_index\": n})"},
           face_indices=INT_LIST,
           face_normal={"type": "string", "enum": SIGNED_AXIS_ENUM},
           face_type={"type": "string", "enum": ["plane", "cylinder", "cone", "other"]},
           min_area={"type": "number", "description": "Skip faces smaller than this (unit^2), e.g. hole walls"},
           flip={"type": "boolean", "default": False},
           propagation={"type": "string", "enum": ["none", "tangent"], "default": "none"}, unit=UNIT),
        ["angle", "neutral"], "draft"),
    "hole_wizard": (
        "ISO Hole Wizard holes at model points [[x,y,z],...] on one planar face. kind: tapped "
        "(size 'M3x0.5'), tapped_bottoming, clearance/counterbore/countersink/countersink_socket "
        "(size 'M3'), drill. Give depth (+ thread_depth for tapped) or through_all.",
        _p(size={"type": "string"}, points={"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
           kind={"type": "string", "enum": ["tapped", "tapped_bottoming", "clearance", "drill", "counterbore",
                                            "countersink", "countersink_socket"], "default": "tapped"},
           depth={"type": "number"}, through_all={"type": "boolean", "default": False},
           thread_depth={"type": "number"}, standard={"type": "string", "default": "ISO"}, unit=UNIT),
        ["size", "points"], "hole_wizard"),

    # ------------------------------------------------------------ part design (v4.3)
    "extrude": (
        "Extrude the last sketch with full options: boss or cut, end condition (blind, through_all, "
        "through_all_both, mid_plane, up_to_next, through_next), second direction (depth2), draft, "
        "thin wall, reverse, flip side to cut.",
        _p(depth={"type": "number", "default": 10},
           end_condition={"type": "string", "enum": ["blind", "through_all", "through_all_both", "mid_plane",
                                                     "up_to_next", "through_next"], "default": "blind"},
           depth2={"type": "number"}, end_condition2={"type": "string", "default": "blind"},
           reverse={"type": "boolean", "default": False}, draft_angle={"type": "number", "default": 0},
           draft_outward={"type": "boolean", "default": False}, thin_thickness={"type": "number"},
           cut={"type": "boolean", "default": False}, flip_side={"type": "boolean", "default": False},
           merge={"type": "boolean", "default": True}, unit=UNIT), [], "extrude"),
    "draw_spline": ("Spline through [[x, y], ...] in the active sketch.",
                    _p(points={"type": "array", "items": {"type": "array", "items": {"type": "number"}}}, unit=UNIT),
                    ["points"], "draw_spline"),
    "draw_ellipse": ("Ellipse by centre, major/minor radius and rotation (deg).",
                     _p(cx={"type": "number"}, cy={"type": "number"}, major_radius={"type": "number"},
                        minor_radius={"type": "number"}, angle={"type": "number", "default": 0}, unit=UNIT),
                     ["cx", "cy", "major_radius", "minor_radius"], "draw_ellipse"),
    "convert_entities": ("Project a face's loops (face_index) or edges (edge_indices) into the active sketch.",
                         _p(face_index={"type": "integer"}, edge_indices=INT_LIST,
                            inner_loops={"type": "boolean", "default": True}), [], "convert_entities"),
    "offset_entities": ("Offset model edges (face_index / edge_indices) or sketch entities into the active sketch.",
                        _p(distance={"type": "number"}, face_index={"type": "integer"}, edge_indices=INT_LIST,
                           entities={"type": "array", "items": SKETCH_ENTITY}, both_directions={"type": "boolean", "default": False},
                           reverse={"type": "boolean", "default": False}, unit=UNIT), ["distance"], "offset_entities"),
    "sketch_mirror": ("Mirror sketch entities about a sketch line / centerline.",
                      _p(entities={"type": "array", "items": SKETCH_ENTITY}, mirror_line=SKETCH_ENTITY, unit=UNIT),
                      ["entities", "mirror_line"], "sketch_mirror"),
    "sketch_pattern": ("Sketch step-and-repeat: linear (count_x × count_y, spacing, angle) or circular "
                       "(count over total_angle about center [x, y]).",
                       _p(entities={"type": "array", "items": SKETCH_ENTITY}, kind={"type": "string", "enum": ["linear", "circular"],
                                                          "default": "linear"},
                          count_x={"type": "integer", "default": 2}, spacing_x={"type": "number", "default": 10},
                          count_y={"type": "integer", "default": 1}, spacing_y={"type": "number", "default": 10},
                          angle_x={"type": "number", "default": 0}, count={"type": "integer", "default": 4},
                          center={"type": "array", "items": {"type": "number"}},
                          total_angle={"type": "number", "default": 360}, unit=UNIT),
                       ["entities"], "sketch_pattern"),
    "set_construction": ("Toggle sketch entities to construction geometry (or back).",
                         _p(entities={"type": "array", "items": SKETCH_ENTITY}, construction={"type": "boolean", "default": True}, unit=UNIT),
                         ["entities"], "set_construction"),
    "create_ref_axis": ("Reference axis from a cylindrical face, a linear edge, or two planes (reference specs).",
                        _p(refs={"type": "array", "items": REF_SPEC}, name={"type": "string"}, unit=UNIT),
                        ["refs"], "create_ref_axis"),
    "list_configurations": ("Configurations of the active model and the active one.", {}, [], "list_configurations"),
    "add_configuration": ("Add a configuration (activated by default).",
                          _p(name={"type": "string"}, description={"type": "string", "default": ""},
                             activate={"type": "boolean", "default": True}), ["name"], "add_configuration"),
    "activate_configuration": ("Switch the active configuration.", _p(name={"type": "string"}), ["name"],
                               "activate_configuration"),
    "list_equations": ("Equations and global variables with current values.", {}, [], "list_equations"),
    "set_equation": ("Add or replace an equation / global variable, e.g. '\"Wall\" = 2' or "
                     "'\"D1@Boss-Extrude1\" = \"Wall\" * 3'. Rebuilds and reports errors.",
                     _p(equation={"type": "string"}), ["equation"], "set_equation"),
    "delete_feature": ("Delete a feature (absorbed sketches too; children only if asked).",
                       _p(name={"type": "string"}, delete_children={"type": "boolean", "default": False}),
                       ["name"], "delete_feature"),
    "rename_feature": ("Rename a feature.", _p(name={"type": "string"}, new_name={"type": "string"}),
                       ["name", "new_name"], "rename_feature"),
    "measure": ("Measure 1–2 entities (reference specs): distance, normal/centre distance, angle, length, "
                "radius, area.", _p(entities={"type": "array", "items": REF_SPEC}, unit=UNIT), ["entities"], "measure"),

    # ------------------------------------------------------------ assembly (v4.3)
    "move_component": ("Translate a non-fixed component by dx, dy, dz and optionally rotate it about assembly "
                       "x/y/z (deg). Mates still win on rebuild.",
                       _p(name={"type": "string"}, dx={"type": "number", "default": 0}, dy={"type": "number", "default": 0},
                          dz={"type": "number", "default": 0}, rotate_axis={"type": "string", "enum": AXIS_ENUM},
                          rotate_angle={"type": "number", "default": 0}, unit=UNIT), ["name"], "move_component"),
    "fix_component": ("Fix (or float) components.", _p(names=STR_LIST, fixed={"type": "boolean", "default": True}),
                      ["names"], "fix_component"),
    "set_component_state": ("Suppress / resolve and/or hide / show components.",
                            _p(names=STR_LIST, suppressed={"type": "boolean"}, visible={"type": "boolean"}),
                            ["names"], "set_component_state"),
    "replace_component": ("Replace a component with another file (mates re-attached when possible).",
                          _p(name={"type": "string"}, filepath={"type": "string"},
                             all_instances={"type": "boolean", "default": False},
                             reattach_mates={"type": "boolean", "default": True}),
                          ["name", "filepath"], "replace_component"),
    "component_pattern": ("Linear (direction ref + spacing) or circular (axis ref + total angle) pattern of "
                          "components.",
                          _p(components=STR_LIST, kind={"type": "string", "enum": ["linear", "circular"],
                                                        "default": "linear"},
                             direction=REF_SPEC, count={"type": "integer", "default": 3},
                             spacing={"type": "number", "default": 20}, axis=REF_SPEC,
                             total_angle={"type": "number", "default": 360}, unit=UNIT),
                          ["components"], "component_pattern"),
    "list_mates": ("Mates: type, components, suppressed and error code (over-defined / unsolved).", {}, [],
                   "list_mates"),
    "check_interference": ("Interference detection: component pairs and interference volume.",
                           _p(treat_coincidence={"type": "boolean", "default": False}, unit=UNIT), [],
                           "check_interference"),
    "create_exploded_view": ("Exploded view: steps [{components, direction x|y|z, distance, reverse}].",
                             _p(steps={"type": "array", "items": {"type": "object"}}, unit=UNIT), ["steps"],
                             "create_exploded_view"),

    # ------------------------------------------------------------ drawing (v4.3)
    "add_sheet": ("New drawing sheet with the current sheet's size and format (title block).",
                  _p(name={"type": "string"}, scale={"type": "string"},
                     copy_format={"type": "boolean", "default": True}), [], "add_sheet"),
    "activate_sheet": ("Switch the active drawing sheet.", _p(name={"type": "string"}), ["name"], "activate_sheet"),
    "add_note": ("Text note at sheet position x, y (mm).", _p(text={"type": "string"}, x={"type": "number"},
                                                              y={"type": "number"}), ["text", "x", "y"], "add_note"),
    "insert_center_marks": ("Auto center marks for holes / slots / fillets in views (default all).",
                            _p(views={"type": "array", "items": {"type": "string"}},
                               holes={"type": "boolean", "default": True},
                               fillets={"type": "boolean", "default": False},
                               slots={"type": "boolean", "default": True}), [], "insert_center_marks"),
}


# Groups for documentation (README / user manual are generated from this).
CATEGORIES: List[Tuple[str, List[str]]] = [
    ("Connection & documents", ["connect_solidworks", "get_solidworks_info", "create_new_part",
                                "create_new_assembly", "open_document", "import_file", "save_document",
                                "close_document", "activate_document", "get_document_info",
                                "list_open_documents", "set_units"]),
    ("Sketch", ["create_sketch", "create_sketch_on_face", "close_sketch", "get_sketch_status", "draw_line",
                "draw_circle", "draw_rectangle", "draw_arc", "draw_polygon", "draw_centerline", "draw_slot",
                "draw_spline", "draw_ellipse", "sketch_fillet", "convert_entities", "offset_entities",
                "sketch_mirror", "sketch_pattern", "set_construction", "add_sketch_dimension",
                "add_sketch_relation"]),
    ("Part features", ["extrude", "extrude_sketch", "cut_extrude", "revolve", "loft", "sweep", "fillet_edges",
                       "chamfer_edges", "shell", "rib", "draft", "hole_wizard", "linear_pattern",
                       "circular_pattern", "mirror", "create_ref_plane", "create_ref_axis"]),
    ("Selection & topology", ["list_edges", "list_faces", "select_edges", "select_faces", "select_entity",
                              "clear_selection", "get_selection", "measure"]),
    ("Parametric edit", ["list_features", "get_feature_info", "edit_feature", "list_dimensions", "set_dimension",
                         "list_equations", "set_equation", "list_configurations", "add_configuration",
                         "activate_configuration", "suppress_feature", "delete_feature", "rename_feature",
                         "rebuild", "undo"]),
    ("Properties & output", ["get_mass_properties", "set_material", "set_custom_property",
                             "get_custom_properties", "export_document", "batch_export", "set_view",
                             "capture_view"]),
    ("Assembly", ["insert_component", "add_mate", "list_components", "list_mates", "move_component",
                  "fix_component", "set_component_state", "replace_component", "component_pattern",
                  "check_interference", "create_exploded_view"]),
    ("Drawing", ["create_drawing", "list_drawing_views", "add_drawing_view", "add_section_view",
                 "add_detail_view", "insert_model_annotations", "insert_center_marks", "insert_bom",
                 "auto_balloon", "add_note", "add_sheet", "activate_sheet"]),
    ("Advanced", ["execute_python"]),
]


def ext_tools() -> List[Tool]:
    return [
        Tool(name=name,
             description=desc,
             inputSchema={"type": "object", "properties": props, "required": required})
        for name, (desc, props, required, _m) in TOOL_TABLE.items()
    ]


def has_tool(name: str) -> bool:
    return name in TOOL_TABLE


def dispatch(automation, name: str, arguments: Dict) -> Dict:
    """Forward schema-declared arguments to the automation method."""
    _desc, props, required, method = TOOL_TABLE[name]
    missing = [r for r in required if r not in arguments]
    if missing:
        return automation._result(False, f"Missing required argument(s): {missing}",
                                  _invalid_input())
    kwargs = {k: v for k, v in (arguments or {}).items() if k in props}
    return getattr(automation, method)(**kwargs)


def _invalid_input():
    from .constants import SwErrors
    return SwErrors.swInvalidInput
