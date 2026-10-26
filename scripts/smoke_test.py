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
ALL = ["core", "parts", "loftsweep", "drawing", "batch", "partplus", "asmplus", "drawplus"]
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



SECTION_FUNCS = {"core": core, "parts": parts, "loftsweep": loftsweep, "drawing": drawing, "batch": batch,
                 "partplus": partplus, "asmplus": asmplus, "drawplus": drawplus}
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
