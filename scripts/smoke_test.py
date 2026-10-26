"""
Live smoke test for every tool group — Windows + SolidWorks 2023-2026 running.

    python scripts\\smoke_test.py [output_dir] [section ...]

sections (default: all, in order):
  core       sketch, extrude, cut, selection, fillet/chamfer, patterns, mirror, plane,
             dimensions, material, mass, properties, export, capture, revolve, shell
  parts      hole wizard, edit_feature, draft, rib
  loftsweep  loft, sweep, cut-sweep
  drawing    drawing views, section, detail, annotations, BOM, balloons
  batch      batch export, STEP import
  partplus   full extrude, spline/ellipse, convert/offset, sketch mirror/pattern/trim,
             axis, configurations, equations, rename/delete, measure
  asmplus    mates list, interference, move/fix/state, component pattern, explode, replace
  drawplus   center marks, notes, sheets
  mold       sketch text, scale, multi-body, cosmetic thread
  smetal     base / edge flange, flatten, flat DXF
  asmtools   advanced mates, BOM CSV, Pack and Go
  drawtools  revision, hole table, auxiliary view, broken-out section
  surface    surface extrude/revolve/planar/offset/loft, knit to solid, thicken, cut, delete face

Each step prints PASS/FAIL; results also go to smoke_<sections>.json in output_dir.
Can be exec()'d inside the MCP server (execute_python): set SMOKE_ARGS first.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(
    globals().get("__file__", r"D:\\Solidworks-mcp\\scripts\\x.py"))), "..")))

for _m in [k for k in list(sys.modules) if k.startswith("solidworks_mcp.automation") or k == "solidworks_mcp.constants"]:
    del sys.modules[_m]
from solidworks_mcp.automation import SolidWorksAutomation  # noqa: E402

ARGS = globals().get("SMOKE_ARGS") or sys.argv[1:]
OUT = os.path.abspath(ARGS[0]) if ARGS else os.path.join(os.path.expanduser("~"), "swmcp_smoke")
ALL = ["core", "parts", "loftsweep", "drawing", "batch", "partplus", "asmplus", "drawplus",
       "mold", "smetal", "asmtools", "drawtools", "surface"]
SECTIONS = ARGS[1:] or ALL
os.makedirs(OUT, exist_ok=True)

A = SolidWorksAutomation()
if "sw" in globals() and globals()["sw"] is not None:
    A._sw_app, A._connected = globals()["sw"], True
elif not A.connect()["success"]:
    sys.exit("Cannot connect to SolidWorks")
results = []


def step(label, r, show=None):
    ok = bool(r.get("success"))
    results.append({"step": label, "ok": ok, "message": r.get("message", "")})
    extra = ""
    if show and isinstance(r.get("data"), dict):
        extra = " " + json.dumps({k: r["data"].get(k) for k in show}, default=str)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {r.get('message')}{extra}")
    return r


def check(label, cond, msg=""):
    return step(label, {"success": bool(cond), "message": msg})


TAG = os.path.basename(os.path.normpath(OUT))


def P(name):
    """Unique file names per run folder: SolidWorks cannot open two files with the same name."""
    stem, ext = os.path.splitext(name)
    return os.path.join(OUT, f"{stem}_{TAG}{ext}" if ext.lower() in (".sldprt", ".sldasm", ".slddrw") else name)


def save(path):
    return step(f"save {os.path.basename(path)}", A.save_document(path))


def last_feature():
    return A.list_features()["data"]["features"][-1]["name"]


def feature_names():
    return [f["name"] for f in A.list_features()["data"]["features"]]


# ---------------------------------------------------------------------------
def core():
    r = step("new part", A.create_new_part(), ["template"])
    if not r["success"]:
        raise RuntimeError("Cannot create a part - set part_template in config.json")
    A.create_sketch("Top")
    A.draw_rectangle(-30, -20, 30, 20)
    step("extrude 10", A.extrude_sketch(10))
    step("sketch on top face", A.create_sketch_on_face(15, 10, 5))
    A.draw_circle(0, 0, 4)
    step("cut through", A.cut_extrude(through_all=True))
    step("list_edges", A.list_edges(), ["total_edges"])
    step("select vertical edges", A.select_edges(parallel_to="y", edge_type="line"))
    step("fillet R3", A.fillet_edges(3))
    step("select hole rims", A.select_edges(radius=4, axis_parallel_to="y"))
    step("chamfer 0.5x45", A.chamfer_edges(0.5, 45))
    feats = A.list_features()["data"]["features"]
    cut = next((f["name"] for f in feats if f["type"] in ("ICE", "Cut")), None)
    edges = A.list_edges(parallel_to="x", edge_type="line", min_length=20)["data"]["edges"]
    lp = step("linear pattern x3", A.linear_pattern([cut], {"edge_index": edges[0]["index"]}, 3, 12))
    if lp["success"]:
        step("mirror pattern", A.mirror({"plane": "Right"}, features=[lp["data"]["feature"]]))
    step("ref plane P25", A.create_ref_plane({"plane": "Top"}, distance=25, name="P25"))
    dims = step("list_dimensions", A.list_dimensions())["data"]["dimensions"]
    by = {d["name"]: d for d in dims}
    check("dimension kinds", by.get("D2@Chamfer1", {}).get("unit") == "deg"
          and next((d for n, d in by.items() if n.startswith("D1@LPattern")), {}).get("kind") == "count",
          "chamfer angle in deg, pattern count as count")
    step("set D1@Boss-Extrude1=12", A.set_dimension("D1@Boss-Extrude1", 12))
    step("undo", A.undo(1))
    step("material 6061", A.set_material("6061-T6 (SS)"))
    step("mass properties", A.get_mass_properties(), ["mass_g"])
    step("custom prop", A.set_custom_property("PartNo", "SMOKE-001"))
    step("read props", A.get_custom_properties())
    step("export STEP", A.export_document(os.path.join(OUT, "core.step")))
    step("export STL", A.export_document(os.path.join(OUT, "core.stl")))
    step("capture iso", A.capture_view("isometric", 800, 600, os.path.join(OUT, "core.png")))
    save(P("core.SLDPRT"))
    step("new part (revolve)", A.create_new_part())
    A.create_sketch("Front")
    A.draw_centerline(0, -30, 0, 30)
    A.draw_rectangle(5, -10, 15, 10)
    step("revolve 360", A.revolve_sketch(360))
    step("shell open +y", A.shell(1.0, face_normal="+y"))
    A.create_sketch("Top")
    A.draw_line(0, 0, 20, 0)
    A.draw_line(20, 0, 20, 10)
    step("sketch dimension", A.add_sketch_dimension([{"point": [10, 0]}], value=25))
    step("sketch relation", A.add_sketch_relation("vertical", [{"point": [25, 5]}]))
    A.exit_sketch()
    step("suppress Shell1", A.suppress_feature("Shell1", True))
    step("unsuppress Shell1", A.suppress_feature("Shell1", False))
    step("rebuild", A.rebuild_model())


# ---------------------------------------------------------------------------
def parts():
    step("new part (plate)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_rectangle(-30, -20, 30, 20)
    step("extrude 10", A.extrude_sketch(10))
    step("hole tapped M3x0.5 x3", A.hole_wizard("M3x0.5", [[-20, 10, 10], [0, 10, 10], [20, 10, 10]],
                                                kind="tapped", depth=8, thread_depth=6), ["holes", "dimensions"])
    step("hole cbore M4 thru x2", A.hole_wizard("M4", [[-20, 10, -10], [20, 10, -10]],
                                                kind="counterbore", through_all=True), ["holes", "dimensions"])
    A.create_sketch("Right")
    A.draw_circle(0, 5, 2)
    step("cut through_all both (fixed enum 9)", A.cut_extrude(through_all=True, both_directions=True))
    A.select_edges(parallel_to="y", edge_type="line", min_length=9)
    step("fillet R3 vertical edges", A.fillet_edges(3))
    step("info Boss-Extrude1", A.get_feature_info("Boss-Extrude1"), ["params"])
    step("edit extrude depth 12", A.edit_feature("Boss-Extrude1", {"depth": 12}), ["after"])
    step("edit fillet R4", A.edit_feature("Fillet1", {"radius": 4}), ["after"])
    step("draft 2deg on x side faces", A.draft(2, {"face_normal": "-y"}, face_type="plane", face_normal="x", min_area=100), ["faces"])
    save(P("plate.SLDPRT"))
    A.capture_view("isometric", 800, 600, P("plate.png"))

    step("new part (rib box)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_rectangle(-30, -20, 30, 20)
    A.extrude_sketch(20)
    step("shell 1.5 open +y", A.shell(1.5, face_normal="+y"))
    A.create_sketch("Front")
    A.draw_line(-29, 12, 29, 12)
    step("rib t=2", A.rib(2.0))
    step("edit shell 2.0", A.edit_feature("Shell1", {"thickness": 2.0}), ["after"])
    save(P("ribbox.SLDPRT"))
    A.capture_view("isometric", 800, 600, P("ribbox.png"))


# ---------------------------------------------------------------------------
def loftsweep():
    step("new part (loft)", A.create_new_part())
    step("plane P30", A.create_ref_plane({"plane": "Top"}, distance=30, name="P30"))
    A.create_sketch("Top")
    A.draw_rectangle(-10, -10, 10, 10)
    A.exit_sketch()
    s1 = last_feature()
    step("sketch on P30", A.create_sketch("P30"))
    A.draw_circle(0, 0, 6)
    A.exit_sketch()
    s2 = last_feature()
    step(f"loft {s1}->{s2}", A.loft([s1, s2]))
    save(P("loft.SLDPRT"))
    A.capture_view("isometric", 800, 600, P("loft.png"))

    step("new part (sweep)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_circle(0, 0, 3)
    A.exit_sketch()
    prof = last_feature()
    A.create_sketch("Front")
    A.draw_line(0, 0, 0, 20)
    A.draw_arc_center(15, 20, 15, 90, 180)
    A.exit_sketch()
    path = last_feature()
    step(f"sweep {prof} along {path}", A.sweep(path, profile=prof))
    step("sweep circular Ø2 cut along path", A.sweep(path, circular_diameter=2, cut=True))
    save(P("sweep.SLDPRT"))
    A.capture_view("isometric", 800, 600, P("sweep.png"))


# ---------------------------------------------------------------------------
def drawing():
    plate = P("plate.SLDPRT")
    step("open plate", A.open_document(plate))
    step("create_drawing plate", A.create_drawing(plate, model_dimensions=True, save_path=P("plate.SLDDRW")),
             ["views", "scale", "projection", "sheet_mm"])
    v = step("list views", A.list_drawing_views(), ["views"])
    views = v.get("data", {}).get("views", [])
    if views:
        front = views[0]["name"]
        step("section A-A", A.add_section_view(front, "vertical", 0.5))
        ol = views[0]["outline_mm"]
        step("detail B", A.add_detail_view(front, [ol[0] + 6, ol[3] - 6], 6, "3:1"))
    step("model annotations", A.insert_model_annotations(["dimensions_marked", "hole_callouts"]))
    step("save drawing", A.save_document(P("plate.SLDDRW")))
    A.capture_view(None, 1200, 850, P("plate_drawing.png"))

    step("new assembly", A.create_new_assembly())
    step("insert plate", A.insert_component(plate, 0, 0, 0))
    step("insert ribbox", A.insert_component(P("ribbox.SLDPRT"), 80, 0, 0))
    save(P("asm.SLDASM"))
    step("create_drawing asm", A.create_drawing(P("asm.SLDASM"), views=["isometric"], save_path=P("asm.SLDDRW")))
    step("insert BOM", A.insert_bom(), ["rows", "template"])
    step("auto balloon", A.auto_balloon(), ["count"])
    step("save asm drawing", A.save_document(P("asm.SLDDRW")))
    A.capture_view(None, 1200, 850, P("asm_drawing.png"))


# ---------------------------------------------------------------------------
def batch():
    out = P("export")
    step("batch_export step+stl", A.batch_export(OUT, ["step", "stl"], output_dir=out, overwrite=True),
         ["output_dir", "failed"])
    step("batch_export drawings pdf", A.batch_export(OUT, ["pdf"], output_dir=out, file_types=["slddrw"],
                                                     overwrite=True))
    step("import STEP", A.import_file(os.path.join(out, f"plate_{TAG}.step"), save_as=P("plateimp.SLDPRT")),
         ["type", "solid_bodies", "saved_as"])
    step("mass of import", A.get_mass_properties(), ["volume", "mass_g"])
    step("activate plate", A.activate_document(os.path.basename(P("plate.SLDPRT"))))



# ---------------------------------------------------------------------------
def partplus():
    step("new part (partplus)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_rectangle(-40, -25, 40, 25)
    step("extrude depth 12 + depth2 3 + draft 2", A.extrude(12, depth2=3, draft_angle=2))
    step("sketch on top", A.create_sketch_on_face(0, 12, 0))
    top = A.list_faces(normal="+y")["data"]["faces"]
    step("offset top face edges 5 inward", A.offset_entities(5, face_index=top[0]["index"], reverse=True))
    step("cut pocket 3 (extrude cut)", A.extrude(3, cut=True))
    step("sketch on Front", A.create_sketch("Front"))
    A.draw_centerline(0, -5, 0, 30)
    A.draw_circle(10, 6, 2)
    step("sketch mirror", A.sketch_mirror([{"point": [12, 6]}], {"point": [0, 10]}))
    step("sketch linear pattern", A.sketch_pattern([{"point": [12, 6]}], "linear", count_x=2, spacing_x=6))
    step("set construction", A.set_construction([{"point": [0, 10]}]))
    A.draw_spline([[-30, 25], [-20, 28], [-10, 25]])
    A.draw_ellipse(-20, 10, 4, 2, 30)
    step("close sketch", A.close_sketch())
    step("ref axis from 2 planes", A.create_ref_axis([{"plane": "Front"}, {"plane": "Right"}], name="AX1"))
    step("list configurations", A.list_configurations(), ["configurations"])
    step("add configuration Long", A.add_configuration("Long"))
    step("global variable L=20", A.set_equation('"L" = 20'))
    step("drive depth by L", A.set_equation('"D1@Boss-Extrude1" = "L"'))
    step("list equations", A.list_equations(), ["equations"])
    dep = A.get_feature_info("Boss-Extrude1")["data"]["params"]["depth"]
    check("depth follows equation", abs(dep - 20) < 1e-6, f"depth={dep}")
    feats = feature_names()
    pocket = next((n for n in reversed(feats) if n.startswith("Cut-Extrude")), None)
    step(f"rename {pocket}", A.rename_feature(pocket, "Pocket"))
    faces = A.list_faces(normal="y")["data"]["faces"]
    big = sorted(faces, key=lambda f: -f["area"])[:2]
    step("measure top-bottom", A.measure([{"face_index": big[0]["index"]}, {"face_index": big[1]["index"]}]),
         ["values"])
    step("delete Pocket", A.delete_feature("Pocket"))
    check("Pocket gone", "Pocket" not in feature_names())
    cfgs = A.list_configurations()["data"]["configurations"]
    step("activate original config", A.activate_configuration(next(c for c in cfgs if c != "Long")))
    save(P("partplus.SLDPRT"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "partplus.png"))


# ---------------------------------------------------------------------------
def asmplus():
    plate, rib = P("plate.SLDPRT"), P("ribbox.SLDPRT")
    if not os.path.isfile(plate):
        raise RuntimeError("run the 'parts' section first (needs plate/ribbox)")
    step("new assembly", A.create_new_assembly())
    step("insert plate A", A.insert_component(plate, 0, 0, 0))
    step("insert plate B (overlapping)", A.insert_component(plate, 20, 0, 0))
    comps = [c["name"] for c in A.list_components()["data"]["components"]]
    print("  components:", comps)
    a, b = comps[0], comps[1]
    step("fix A", A.fix_component([a]))
    step("interference (expect >= 1)", A.check_interference(), ["interferences"])
    step("move B +100 x", A.move_component(b, dx=100), ["origin"])
    r = step("interference after move", A.check_interference())
    check("no interference after move", not r["data"]["interferences"], str(r["data"]["interferences"]))
    step("mate B top coincident A top", A.add_mate("coincident", {"component": a, "plane": "Top"},
                                                   {"component": b, "plane": "Top"}))
    step("list mates", A.list_mates(), ["mates"])
    step("hide B", A.set_component_state([b], visible=False))
    step("show B", A.set_component_state([b], visible=True))
    step("float A", A.fix_component([a], fixed=False))
    step("fix A again", A.fix_component([a]))
    step("component pattern B along Right normal", A.component_pattern([b], "linear", {"plane": "Right"},
                                                                          count=2, spacing=80), ["new_components"])
    step("exploded view", A.create_exploded_view([{"components": [b], "direction": "y", "distance": 40}]),
         ["steps"])
    step("replace B with ribbox", A.replace_component(b, rib))
    save(P("asmplus.SLDASM"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "asmplus.png"))


# ---------------------------------------------------------------------------
def drawplus():
    plate = P("plate.SLDPRT")
    step("open plate", A.open_document(plate))
    step("drawing with center marks", A.create_drawing(plate, center_marks=True))
    step("center marks again (explicit)", A.insert_center_marks())
    step("note", A.add_note("NOTES:\n1. BREAK ALL SHARP EDGES 0.2\n2. ANODIZE BLACK", 20, 60))
    step("add sheet", A.add_sheet("Sheet2"))
    step("note on sheet 2", A.add_note("SHEET 2", 30, 150))
    names = A.list_drawing_views()["data"]["sheets"]
    step("activate sheet 1", A.activate_sheet(names[0]))
    step("save drawing", A.save_document(P("drawplus.SLDDRW")))
    A.capture_view(None, 1200, 850, os.path.join(OUT, "drawplus.png"))


# ---------------------------------------------------------------------------
def block(x1, z1, x2, z2, h, plane="Top"):
    A.create_sketch(plane)
    A.draw_rectangle(x1, z1, x2, z2)
    return A.extrude(h)


def mold():
    step("new part (mold)", A.create_new_part())
    step("block 60x40x10", block(-30, -20, 30, 20, 10))
    step("sketch on top", A.create_sketch_on_face(0, 10, 0))
    step("sketch text H11-001", A.sketch_text("H11-001", -20, -3, height=6))
    step("engrave 0.5", A.extrude(0.5, cut=True))
    r = step("scale 1.02 (shrinkage)", A.scale_part(1.02), ["volume_ratio"])
    check("volume ratio = 1.02^3", abs((r["data"] or {}).get("volume_ratio", 0) - 1.02 ** 3) < 1e-4,
          str((r["data"] or {}).get("volume_ratio")))
    A.create_sketch("Top")
    A.draw_circle(0, 0, 8)
    step("second body (merge=false)", A.extrude(25, merge=False))
    r = step("list bodies", A.list_bodies(), ["bodies"])
    check("2 bodies", len(r["data"]["bodies"]) == 2)
    bl = sorted(r["data"]["bodies"], key=lambda b: -b["volume"])
    r = step("combine: block minus cylinder", A.combine_bodies(bl[0]["name"], [bl[1]["name"]], "subtract"),
             ["bodies"])
    check("1 body after subtract", len(r["data"]["bodies"]) == 1)
    r = step("split by Right plane", A.split_body({"plane": "Right"}), ["bodies"])
    check("2 bodies after split", len(r["data"]["bodies"]) == 2)
    r = step("delete body 1", A.delete_body([1]), ["bodies"])
    check("1 body after delete", len(r["data"]["bodies"]) == 1)
    save(P("mold.SLDPRT"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "mold.png"))
    step("new part (pin)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_circle(0, 0, 3)
    A.extrude(20)
    e = [x for x in A.list_edges(edge_type="circle")["data"]["edges"] if x["mid"][1] > 19][0]
    r = step("cosmetic thread M6x1.0", A.cosmetic_thread({"edge_index": e["index"]}, size="M6x1.0", depth=12),
             ["diameter_mm", "callout"])
    check("minor diameter 4.773", abs(r["data"]["diameter_mm"] - 4.773) < 1e-3)
    save(P("pin.SLDPRT"))


def smetal():
    step("new part (sheet metal)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_rectangle(-40, -25, 40, 25)
    step("base flange t1.5 R2", A.base_flange(1.5, bend_radius=2), ["flat_pattern"])
    edges = A.list_edges(edge_type="line", parallel_to="x")["data"]["edges"]
    top = max(edges, key=lambda e: e["mid"][1])
    top = [e for e in edges if abs(e["mid"][1] - top["mid"][1]) < 1e-6][0]
    r = step("edge flange L20", A.edge_flange({"edge_index": top["index"]}, 20), ["length"])
    check("flange length 20", abs((r["data"] or {}).get("length", 0) - 20) < 1e-3)
    save(P("sheet.SLDPRT"))
    r = step("export flat DXF", A.export_flat_pattern(P("sheet_flat.dxf")))
    check("dxf written", os.path.isfile(P("sheet_flat.dxf")))
    step("flatten", A.flatten(True))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "sheet_flat.png"))
    step("unflatten", A.flatten(False))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "sheet.png"))


def asmtools():
    # parts. insert_component centres each component's bounding box on the given point,
    # so the face points below are relative to those centres.
    A.create_new_part()
    block(-50, -30, 50, 30, 10)
    A.create_sketch_on_face(0, 10, 0)
    A.draw_slot(-15, 0, 15, 0, 6)
    A.draw_circle(30, 0, 3)
    A.extrude(cut=True, end_condition="through_all")
    save(P("base.SLDPRT"))
    A.create_new_part()
    A.create_sketch("Top")
    A.draw_circle(0, 0, 3)
    A.extrude(30)
    save(P("pin6.SLDPRT"))
    A.create_new_part()
    block(-5, -2, 5, 2, 20)
    save(P("tab.SLDPRT"))
    A.create_new_part()
    block(-10, -10, 10, 10, 10)
    save(P("blk.SLDPRT"))
    # assembly
    step("new assembly", A.create_new_assembly())
    step("insert base", A.insert_component(P("base.SLDPRT"), 0, 0, 0))
    for nm, x, y, z in (("pin6", 0, 40, 0), ("pin6", 30, 40, 0), ("pin6", -80, 0, 60), ("pin6", -60, 0, 60),
                        ("tab", 60, 40, 50), ("blk", 150, 0, 0), ("blk", -150, 0, 0), ("blk", 0, 0, 150)):
        A.insert_component(P(nm + ".SLDPRT"), x, y, z)
    comps = [c["name"] for c in A.list_components()["data"]["components"]]
    print("  components:", comps)
    base = comps[0]
    pins = [c for c in comps if c.startswith(f"pin6_{TAG}")]
    blks = [c for c in comps if c.startswith(f"blk_{TAG}")]
    A.fix_component([c for c in comps if c != base], fixed=False)   # SW fixes the first inserted part
    A.fix_component([base])
    F = lambda x, y, z: {"point": [x, y, z], "type": "FACE"}
    step("width (tab in slot)", A.add_advanced_mate("width", width_entities=[F(0, 0, 3), F(0, 0, -3)],
                                                    tab_entities=[F(60, 40, 52), F(60, 40, 48)]))
    step("slot mate (pin in slot)", A.add_advanced_mate("slot", [F(-18, 0, 0), F(3, 40, 0)]))
    step("hinge (pin in hole)", A.add_advanced_mate("hinge", [F(33, 0, 0), F(33, 40, 0), F(-40, 5, 20), F(31, 25, 1)]))
    step("gear 1:2", A.add_advanced_mate("gear", [F(-77, 0, 60), F(-57, 0, 60)], ratio=[1, 2]))
    step("symmetric blocks", A.add_advanced_mate("symmetric", [F(140, 0, 0), F(-140, 0, 0)],
                                                 symmetry_plane={"plane": "Right"}))
    step("limit distance 5..20", A.add_advanced_mate("limit_distance", [{"component": blks[0], "plane": "Top"},
                                                                        {"plane": "Top"}],
                                                     value=10, min_value=5, max_value=20))
    step("limit angle 0..30", A.add_advanced_mate("limit_angle", [{"component": blks[2], "plane": "Front"},
                                                                  {"plane": "Front"}],
                                                  value=10, min_value=0, max_value=30))
    r = step("list mates", A.list_mates(), ["mates"])
    bad = [m for m in r["data"].get("mates", []) if m.get("error_code")]
    check("no mate errors", not bad, str(bad)[:300])
    save(P("asmtools.SLDASM"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "asmtools.png"))
    r = step("export BOM parts_only", A.export_bom(P("bom.csv")), ["lines", "rows"])
    qty = {row[2]: row[4] for row in r["data"]["rows"]}
    check("pin qty 4, blk qty 3", qty.get(f"pin6_{TAG}.SLDPRT") == 4 and qty.get(f"blk_{TAG}.SLDPRT") == 3, str(qty))
    step("export BOM indented", A.export_bom(P("bom_indented.csv"), mode="indented"), ["lines"])
    r = step("pack and go", A.pack_and_go(os.path.join(OUT, "packed"), prefix="PG_"), ["files"])
    check("packed asm + 4 parts", len([f for f in (r.get("data") or {}).get("files", []) if f.startswith("PG_")]) >= 5,
          str(r.get("data")))
    deps = [str(x) for x in A.app.GetDocumentDependencies2(os.path.join(OUT, "packed", f"PG_asmtools_{TAG}.SLDASM"),
                                                           True, True, False) or []]
    check("packed asm references packed parts", deps and all("packed" in d for d in deps[1::2]), str(deps)[:300])


def drawtools():
    step("new part (drawtools)", A.create_new_part())
    block(-30, -20, 30, 20, 12)
    A.create_sketch_on_face(0, 12, 0)
    for x, z in ((-20, -10), (0, -10), (20, -10), (-20, 10), (20, 10)):
        A.draw_circle(x, z, 2.5)
    A.extrude(cut=True, end_condition="through_all")
    e = [x for x in A.list_edges(edge_type="line", parallel_to="z")["data"]["edges"]
         if x["mid"][1] > 11 and x["mid"][0] > 29][0]
    A.select_edges(indices=[e["index"]])
    step("chamfer 4 (inclined face)", A.chamfer_edges(4))
    save(P("dt.SLDPRT"))
    step("drawing", A.create_drawing(P("dt.SLDPRT"), save_path=P("dt.SLDDRW")))
    views = A.list_drawing_views()["data"]["views"]
    names = [v["name"] for v in views]
    r = step("revision A", A.add_revision("A", "INITIAL RELEASE", "PCT"), ["row"])
    step("revision B", A.add_revision("B", "CHAMFER 4", "PCT"), ["row"])
    r = step("hole table (auto view)", A.insert_hole_table(), ["rows"])
    check("5 holes in table", len(r["data"]["rows"]) - 1 == 5, str(r["data"].get("rows"))[:200])
    locs = [float(x) for row in r["data"]["rows"][1:] for x in row[1:3]]
    check("origin bottom-left (all X/Y LOC >= 0)", min(locs) >= 0, str(locs))
    step("auxiliary view of front", A.add_auxiliary_view(names[0], label="C"), ["outline_mm"])
    top = max(views[:3], key=lambda v: (v["outline_mm"][3] - v["outline_mm"][1]))
    ol = top["outline_mm"]
    step("broken-out section", A.add_broken_out_section(top["name"], [ol[0] + 10, ol[1] + 10], 7, 5))
    step("save drawing", A.save_document(P("dt.SLDDRW")))
    A.capture_view(None, 1400, 990, os.path.join(OUT, "drawtools.png"))



def surface():
    vol = lambda: A.get_mass_properties()["data"].get("volume")
    # open surface -> offset -> thicken
    step("new part (surface)", A.create_new_part())
    A.create_sketch("Front")
    A.draw_arc_center(0, -40, 50, 60, 120)
    step("surface extrude 40 (open arc)", A.surface_extrude(40))
    step("offset surface 3", A.offset_surface([{"face_index": 0}], 3))
    r = step("list surface bodies", A.list_bodies("surface"), ["bodies"])
    check("2 surface bodies", len(r["data"]["bodies"]) == 2)
    step("thicken 2 mm", A.thicken_surface(r["data"]["bodies"][0]["name"], 2))
    check("1 solid after thicken", len(A.list_bodies("solid")["data"]["bodies"]) == 1)
    save(P("surf_thicken.SLDPRT"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "surf_thicken.png"))
    # closed surfaces -> knit to solid -> cut with surface -> delete face (patch)
    step("new part (knit)", A.create_new_part())
    A.create_sketch("Top")
    A.draw_rectangle(-20, -20, 20, 20)
    step("tube surface 30", A.surface_extrude(30))
    step("bottom cap", A.planar_surface("Sketch1"))
    pl = A.create_ref_plane({"plane": "Top"}, distance=30)["data"]["feature"]
    A.create_sketch(pl)
    A.draw_rectangle(-20, -20, 20, 20)
    step("top cap", A.planar_surface())
    r = step("knit -> solid", A.knit_surfaces(form_solid=True), ["solid"])
    check("solid volume 48000", abs((vol() or 0) - 48000) < 1, str(vol()))
    pl2 = A.create_ref_plane({"plane": "Top"}, distance=15)["data"]["feature"]
    A.create_sketch(pl2)
    A.draw_rectangle(-30, -30, 30, 30)
    cut_s = A.planar_surface()["data"]["feature"]
    r = step("cut with surface", A.cut_with_surface(cut_s), ["volume_ratio"])
    check("half kept", abs((r["data"] or {}).get("volume_ratio", 0) - 0.5) < 1e-3)
    v_half = vol()
    step("sketch on top", A.create_sketch_on_face(0, 15, 0))
    A.draw_circle(0, 0, 5)
    step("pocket 4", A.extrude(4, cut=True))
    floor = min(A.list_faces(face_type="plane")["data"]["faces"], key=lambda f: f["area"])
    cyl = A.list_faces(face_type="cylinder")["data"]["faces"][0]
    step("delete pocket faces (patch)", A.delete_face([{"face_index": cyl["index"]}, {"face_index": floor["index"]}]))
    check("pocket healed", abs((vol() or 0) - v_half) < 1, f"{vol()} vs {v_half}")
    save(P("surf_knit.SLDPRT"))
    # revolve + loft surfaces
    step("new part (revolve/loft)", A.create_new_part())
    A.create_sketch("Front")
    A.draw_centerline(0, 0, 0, 40)
    A.draw_line(10, 0, 20, 30)
    step("revolve surface 360", A.surface_revolve(360))
    A.create_sketch("Front")
    A.draw_circle(60, 20, 10)
    s1 = last_feature()
    pl3 = A.create_ref_plane({"plane": "Front"}, distance=40)["data"]["feature"]
    A.create_sketch(pl3)
    A.draw_circle(60, 20, 5)
    s2 = last_feature()
    A.close_sketch()
    step("loft surface", A.loft_surface([s1, s2]))
    check("2 surface bodies", len(A.list_bodies("surface")["data"]["bodies"]) == 2)
    save(P("surf_revloft.SLDPRT"))
    A.capture_view("isometric", 800, 600, os.path.join(OUT, "surf_revloft.png"))


SECTION_FUNCS = {"core": core, "parts": parts, "loftsweep": loftsweep, "drawing": drawing, "batch": batch,
                 "partplus": partplus, "asmplus": asmplus, "drawplus": drawplus,
                 "mold": mold, "smetal": smetal, "asmtools": asmtools, "drawtools": drawtools,
                 "surface": surface}
for sec in SECTIONS:
    print(f"--- {sec} ---")
    try:
        SECTION_FUNCS[sec]()
    except Exception as e:  # keep going with other sections
        import traceback
        results.append({"step": f"{sec} crashed", "ok": False, "message": str(e)})
        print(traceback.format_exc()[-1500:])

passed = sum(r["ok"] for r in results)
print(f"\n{passed}/{len(results)} passed. Outputs in {OUT}")
with open(os.path.join(OUT, f"smoke_{'_'.join(SECTIONS)}.json"), "w") as f:
    json.dump(results, f, indent=2)
