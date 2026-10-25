"""
Extended MCP tool registry
--------------------------
Declarative table: tool name -> (description, JSON schema properties,
required, automation method). Arguments are forwarded to the method by name,
filtered to the schema's properties, so schema keys must match method
parameter names.
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
        "Reports rebuild errors. unit='deg' for angles.",
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
}


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
