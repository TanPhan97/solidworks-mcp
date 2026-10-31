"""
Live smoke test for the v4.2 tools (drawing, loft/sweep, batch export,
import, edit_feature, rib/draft/hole wizard). Windows + SolidWorks running.

    python scripts\\smoke_test_v42.py [output_dir] [section ...]

sections: parts, loftsweep, drawing, batch   (default: all, in that order)
Can also be exec()'d inside the MCP server (execute_python) where `sw` exists.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(
    globals().get("__file__", r"D:\Solidworks-mcp\scripts\x.py"))), "..")))

for _m in [k for k in list(sys.modules) if k.startswith("solidworks_mcp.automation") or k == "solidworks_mcp.constants"]:
    del sys.modules[_m]
from solidworks_mcp.automation import SolidWorksAutomation  # noqa: E402

ARGS = globals().get("SMOKE_ARGS") or sys.argv[1:]
OUT = os.path.abspath(ARGS[0]) if ARGS else r"D:\Solidworks-mcp\_live"
SECTIONS = ARGS[1:] or ["parts", "loftsweep", "drawing", "batch"]
os.makedirs(OUT, exist_ok=True)

A = SolidWorksAutomation()
if "sw" in globals() and globals()["sw"] is not None:
    A._sw_app, A._connected = globals()["sw"], True
else:
    A.connect()
results = []


def step(label, r, show=None):
    ok = bool(r.get("success"))
    results.append({"step": label, "ok": ok, "message": r.get("message", "")})
    extra = ""
    if show and isinstance(r.get("data"), dict):
        extra = " " + json.dumps({k: r["data"].get(k) for k in show})
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {r.get('message')}{extra}")
    return r


TAG = os.path.basename(os.path.normpath(OUT))


def P(name):
    """Unique file names per run folder: SolidWorks cannot open two files with the same name."""
    stem, ext = os.path.splitext(name)
    return os.path.join(OUT, f"{stem}_{TAG}{ext}" if ext.lower() in (".sldprt", ".sldasm", ".slddrw") else name)


def save(path):
    return step(f"save {os.path.basename(path)}", A.save_document(path))


def last_feature():
    return A.list_features()["data"]["features"][-1]["name"]


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
    r = step("create_drawing plate", A.create_drawing(plate, model_dimensions=True, save_path=P("plate.SLDDRW")),
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


for sec in SECTIONS:
    print(f"--- {sec} ---")
    try:
        {"parts": parts, "loftsweep": loftsweep, "drawing": drawing, "batch": batch}[sec]()
    except Exception as e:  # keep going with other sections
        import traceback
        results.append({"step": f"{sec} crashed", "ok": False, "message": str(e)})
        print(traceback.format_exc()[-1500:])

passed = sum(r["ok"] for r in results)
print(f"\n{passed}/{len(results)} passed. Outputs in {OUT}")
with open(os.path.join(OUT, f"smoke_v42_{'_'.join(SECTIONS)}.json"), "w") as f:
    json.dump(results, f, indent=2)
