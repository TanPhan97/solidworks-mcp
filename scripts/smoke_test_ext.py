"""
Live smoke test for the extended tools — run on Windows with SolidWorks open.

    python scripts\\smoke_test_ext.py [output_dir]

Builds a 60x40x10 mm plate with a Ø8 hole and exercises every new tool group.
Each step prints PASS/FAIL with the server message; the run continues after a
failure so one bad API call does not hide the rest.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from solidworks_mcp.automation import SolidWorksAutomation  # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="swmcp_smoke_")
os.makedirs(OUT, exist_ok=True)
results = []


def step(label, r):
    ok = bool(r.get("success"))
    results.append((label, ok, r.get("message", "")))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {r.get('message')}")
    return r


sw = SolidWorksAutomation()
if not step("connect", sw.connect())["success"]:
    sys.exit("Cannot connect to SolidWorks - aborting")
r = step("new part", sw.create_new_part())
if not r["success"]:
    print(json.dumps(r.get("data", {}), indent=2))
    sys.exit("Cannot create a part - fix the template first (see 'tried' above)")
print("  template:", r["data"].get("template"))

# Base plate
step("sketch Top", sw.create_sketch("Top"))
step("rectangle", sw.draw_rectangle(-30, -20, 30, 20))
if not step("extrude 10", sw.extrude_sketch(10))["success"]:
    sys.exit("Base extrude failed - later steps depend on it, aborting")

# Hole through top face (sketch on face at plate top, y=10 mm in model)
step("sketch on top face", sw.create_sketch_on_face(15, 10, 5))
step("circle R4", sw.draw_circle(0, 0, 4))
step("cut through", sw.cut_extrude(through_all=True))

# Topology
r = step("list_edges", sw.list_edges())
step("list_faces +y", sw.list_faces(normal="+y"))

# Fillet vertical plate edges (model Y is up for a Top-plane extrude)
step("select vertical edges", sw.select_edges(parallel_to="y", edge_type="line"))
step("fillet R3", sw.fillet_edges(3))

# Chamfer hole rims
step("select hole rims", sw.select_edges(radius=4, axis_parallel_to="y"))
step("chamfer 0.5x45", sw.chamfer_edges(0.5, 45))

# Pattern the hole: find the cut feature name
feats = sw.list_features().get("data", {}).get("features", [])
cut_name = next((f["name"] for f in feats if f["type"] in ("ICE", "Cut", "CutExtrude")), None)
print("  cut feature:", cut_name)
edges = sw.list_edges(parallel_to="x", edge_type="line", min_length=20).get("data", {}).get("edges", [])
if cut_name and edges:
    lp = step("linear pattern x3", sw.linear_pattern([cut_name], {"edge_index": edges[0]["index"]}, 3, 12))
    lp_name = lp.get("data", {}).get("feature")
    if lp_name:   # pattern goes to +X; mirror it to -X
        step("mirror pattern about Right", sw.mirror({"plane": "Right"}, features=[lp_name]))

# Reference plane + revolve on it is skipped; plane creation alone:
step("ref plane offset 25 from Top", sw.create_ref_plane({"plane": "Top"}, distance=25, name="P25"))

# Parametric edit
dims = step("list_dimensions", sw.list_dimensions()).get("data", {}).get("dimensions", [])
print("  dims:", json.dumps(dims[:6]))
d_ext = next((d["name"] for d in dims if "Boss-Extrude1" in d["full_name"]), None)
if d_ext:
    step(f"set {d_ext}=12", sw.set_dimension(d_ext, 12))
    step("undo", sw.undo(1))

# Properties, mass, export, capture
step("material 6061", sw.set_material("6061-T6 (SS)"))
step("mass properties", sw.get_mass_properties())
step("custom prop", sw.set_custom_property("PartNo", "SMOKE-001"))
step("read props", sw.get_custom_properties())
step("export STEP", sw.export_document(os.path.join(OUT, "smoke.step")))
step("export STL", sw.export_document(os.path.join(OUT, "smoke.stl")))
step("capture iso", sw.capture_view("isometric", 800, 600, os.path.join(OUT, "smoke.png")))

# Revolve test in a second part
step("new part (revolve)", sw.create_new_part())
step("sketch Front", sw.create_sketch("Front"))
step("centerline", sw.draw_centerline(0, -30, 0, 30))
step("profile rect", sw.draw_rectangle(5, -10, 15, 10))
step("revolve 360", sw.revolve_sketch(360))
step("shell open +y", sw.shell(1.0, face_normal="+y"))

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{passed}/{len(results)} passed. Outputs in {OUT}")
with open(os.path.join(OUT, "smoke_results.json"), "w") as f:
    json.dump([{"step": s, "ok": ok, "message": m} for s, ok, m in results], f, indent=2)
