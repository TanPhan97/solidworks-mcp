"""
Offline tests for the extended tools with a fake SolidWorks COM object model.

Runs on any OS (win32com / pythoncom are stubbed). Verifies:
- tool registry integrity (unique names, schema keys == method params)
- topology listing / filtering / selection marks
- COM call shapes (parameter counts, flags, selection marks) for each feature
- server dispatch incl. image return

Run:  python -m pytest solidworks_mcp/tests/test_ext_mock.py -q
"""

import os
import sys
import math
import types
import asyncio
import inspect
import importlib

import pytest

# win32com / pythoncom are stubbed in the repo-root conftest.py when absent.

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from solidworks_mcp.automation import SolidWorksAutomation  # noqa: E402
from solidworks_mcp.automation import com_utils as cu       # noqa: E402
from solidworks_mcp import tools_ext                         # noqa: E402

MM = 0.001


# ----------------------------------------------------------------------------
# Fake geometry: 20 x 10 x 5 mm box (origin corner) with Ø5 through hole at (10,5)
# ----------------------------------------------------------------------------

class FakeCurve:
    def __init__(self, kind, **kw):
        self.kind, self.kw = kind, kw
        # LineParams / CircleParams exposed as properties (like SW late binding)
        if kind == "line":
            p, d = kw["p"], kw["d"]
            self.LineParams = (*p, *d)
        else:
            self.CircleParams = (*kw["c"], *kw["axis"], kw["r"])

    def IsLine(self):
        return self.kind == "line"

    def IsCircle(self):
        return self.kind == "circle"

    def Evaluate2(self, t, n):
        if self.kind == "line":
            p, d = self.kw["p"], self.kw["d"]
            return tuple(p[i] + d[i] * t for i in range(3)) + (0,) * 3
        c, r = self.kw["c"], self.kw["r"]
        return (c[0] + r * math.cos(t), c[1] + r * math.sin(t), c[2], 0, 0, 0)

    def GetLength3(self, t0, t1):
        if self.kind == "line":
            return abs(t1 - t0)
        return self.kw["r"] * abs(t1 - t0)


class Selectable:
    def __init__(self, sel_log):
        self._sel_log = sel_log

    def Select4(self, append, sd):
        self._sel_log.append(("Select4", self, append, sd.Mark))
        return True


class FakeEdge(Selectable):
    def __init__(self, sel_log, curve, t0, t1):
        super().__init__(sel_log)
        self._curve, self._t0, self._t1 = curve, t0, t1

    def GetCurve(self):
        return self._curve

    def GetCurveParams2(self):
        s = self._curve.Evaluate2(self._t0, 0)[:3]
        e = self._curve.Evaluate2(self._t1, 0)[:3]
        return (*s, *e, self._t0, self._t1, 0, 0, 0)


class FakeSurface:
    def __init__(self, kind, **kw):
        self.kind, self.kw = kind, kw
        if kind == "cylinder":
            self.CylinderParams = (*kw["o"], *kw["axis"], kw["r"])

    def IsPlane(self):
        return self.kind == "plane"

    def IsCylinder(self):
        return self.kind == "cylinder"

    def IsCone(self):
        return False

    def IsSphere(self):
        return False

    def IsTorus(self):
        return False


class FakeFace(Selectable):
    def __init__(self, sel_log, surf, area, normal, tri, edges):
        super().__init__(sel_log)
        self._surf, self._area, self._edges, self._tri = surf, area, edges, tri
        self.Normal = normal

    def GetSurface(self):
        return self._surf

    def GetArea(self):
        return self._area

    def GetTessTriangles(self, noConversion):
        return self._tri

    def GetEdges(self):
        return self._edges


def build_box(sel_log):
    L, W, H, R = 20 * MM, 10 * MM, 5 * MM, 2.5 * MM
    P = [(0, 0, 0), (L, 0, 0), (L, W, 0), (0, W, 0)]

    def line(a, b):
        d = tuple(b[i] - a[i] for i in range(3))
        n = math.sqrt(sum(v * v for v in d))
        return FakeEdge(sel_log, FakeCurve("line", p=a, d=tuple(v / n for v in d)), 0.0, n)

    bottom = [line(P[i], P[(i + 1) % 4]) for i in range(4)]
    top = [line((*P[i][:2], H), (*P[(i + 1) % 4][:2], H)) for i in range(4)]
    vert = [line(P[i], (*P[i][:2], H)) for i in range(4)]
    hole_b = FakeEdge(sel_log, FakeCurve("circle", c=(L / 2, W / 2, 0), axis=(0, 0, 1), r=R), 0, 2 * math.pi)
    hole_t = FakeEdge(sel_log, FakeCurve("circle", c=(L / 2, W / 2, H), axis=(0, 0, 1), r=R), 0, 2 * math.pi)
    edges = bottom + top + vert + [hole_b, hole_t]

    def tri(pt):
        x, y, z = pt
        return (x, y, z, x + 1e-4, y, z, x, y + 1e-4, z)

    plane = lambda: FakeSurface("plane")
    faces = [
        FakeFace(sel_log, plane(), L * W - math.pi * R * R, (0, 0, -1), tri((1 * MM, 1 * MM, 0)), bottom + [hole_b]),
        FakeFace(sel_log, plane(), L * W - math.pi * R * R, (0, 0, 1), tri((1 * MM, 1 * MM, H)), top + [hole_t]),
        FakeFace(sel_log, plane(), L * H, (0, -1, 0), tri((1 * MM, 0, 1 * MM)), [bottom[0], top[0], vert[0], vert[1]]),
        FakeFace(sel_log, plane(), W * H, (1, 0, 0), tri((L, 1 * MM, 1 * MM)), [bottom[1], top[1], vert[1], vert[2]]),
        FakeFace(sel_log, plane(), L * H, (0, 1, 0), tri((1 * MM, W, 1 * MM)), [bottom[2], top[2], vert[2], vert[3]]),
        FakeFace(sel_log, plane(), W * H, (-1, 0, 0), tri((0, 1 * MM, 1 * MM)), [bottom[3], top[3], vert[3], vert[0]]),
        FakeFace(sel_log, FakeSurface("cylinder", o=(L / 2, W / 2, 0), axis=(0, 0, 1), r=R),
                 2 * math.pi * R * H, None, tri((L / 2 + R, W / 2, 1 * MM)), [hole_b, hole_t]),
    ]
    return edges, faces


class FakeBody:
    def __init__(self, edges, faces):
        self._edges, self._faces = edges, faces

    def GetEdges(self):
        return tuple(self._edges)

    def GetFaces(self):
        return tuple(self._faces)

    def Select2(self, append, sd):
        return True


# ----------------------------------------------------------------------------
# Fake document / app
# ----------------------------------------------------------------------------

class Recorder:
    """Records every method call: name, args. Returns `ret` (callable or value)."""

    def __init__(self, log, ret=None):
        self._log, self._ret = log, ret or {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args):
            self._log.append((name, args))
            r = self._ret.get(name, FakeFeature(name + "1"))
            return r(*args) if callable(r) and not isinstance(r, FakeFeature) else r
        return method


class FakeFeature:
    def __init__(self, name, type_name="Feature", nxt=None):
        self.Name, self._type, self._next = name, type_name, nxt
        self.selected = []

    @property
    def GetTypeName2(self):          # property style, like SW2025 late binding
        return self._type

    @property
    def GetNextFeature(self):
        return self._next

    def Select2(self, append, mark):
        self.selected.append((append, mark))
        return True

    def GetFirstDisplayDimension(self):
        return None


class SelectData:
    Mark = 0


class FakeSelMgr:
    def __init__(self, doc):
        self._doc = doc

    def CreateSelectData(self):
        return SelectData()

    def GetSelectedObjectCount2(self, mark):
        return len(self._doc.sel_log)


class FakeExtension:
    def __init__(self, doc):
        self._doc = doc

    def SelectByID2(self, name, typ, x, y, z, append, mark, callout, opt):
        rec = ("SelectByID2", name, typ, (x, y, z), append, mark)
        self._doc.sel_log.append(rec)
        self._doc.sel_history.append(rec)        # never cleared
        return True

    def SaveAs(self, path, ver, opts, data, errs, warns):
        with open(path, "wb") as f:
            f.write(b"ISO-10303-21;")
        self._doc.calls.append(("SaveAs", (path, ver, opts)))
        return True


class FakeDim:
    def __init__(self):
        self.SystemValue = 0.010
        self.FullName = "D1@Sketch1@Part1.SLDPRT"

    def SetSystemValue3(self, v, opt, cfgs):
        self.SystemValue = v
        return 0


class FakeDoc:
    def __init__(self, doc_type=1):
        self.sel_log, self.calls, self.sel_history = [], [], []
        self._type = doc_type
        edges, faces = build_box(self.sel_log)
        self._body = FakeBody(edges, faces)
        self.Extension = FakeExtension(self)
        self.SelectionManager = FakeSelMgr(self)
        self.FeatureManager = Recorder(self.calls)
        sk3 = FakeFeature("Sketch3", "ProfileFeature")
        boss = FakeFeature("Boss-Extrude1", "Extrusion", sk3)
        sk1 = FakeFeature("Sketch1", "ProfileFeature", boss)
        self._feats = {f.Name: f for f in (sk1, boss, sk3)}
        self.FirstFeature = sk1
        self.SketchManager = types.SimpleNamespace(ActiveSketch=None)
        self.dim = FakeDim()

    def GetType(self):
        return self._type

    def GetTitle(self):
        return "Part1"

    def GetBodies2(self, t, visible):
        return (self._body,)

    def ClearSelection2(self, b):
        self.sel_log.clear()

    def FeatureByName(self, n):
        return self._feats.get(n)

    def Parameter(self, n):
        return self.dim if n == "D1@Sketch1" else None

    def EditRebuild3(self):
        return True

    def ShowNamedView2(self, n, i):
        self.calls.append(("ShowNamedView2", (n, i)))

    def ViewZoomtofit2(self):
        pass

    def GraphicsRedraw2(self):
        pass

    def SaveBMP(self, path, w, h):
        from PIL import Image
        Image.new("RGB", (w, h), (200, 200, 200)).save(path, "BMP")
        return True


class FakeApp:
    def __init__(self, doc):
        self.ActiveDoc = doc
        self.RevisionNumber = "33.1.0"


@pytest.fixture
def sw():
    a = SolidWorksAutomation()
    doc = FakeDoc()
    a._sw_app, a._connected = FakeApp(doc), True
    a._units.default_unit = "mm"
    return a, doc


def fm_call(doc, name):
    hits = [c for c in doc.calls if c[0] == name]
    assert hits, f"{name} not called; calls={[c[0] for c in doc.calls]}"
    return hits[-1][1]


# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------

def test_registry_matches_method_signatures():
    for name, (_d, props, required, method) in tools_ext.TOOL_TABLE.items():
        fn = getattr(SolidWorksAutomation, method)
        params = set(inspect.signature(fn).parameters) - {"self"}
        assert set(props) <= params, f"{name}: schema keys {set(props) - params} not in {method}()"
        assert set(required) <= set(props), f"{name}: required not in properties"


def test_server_tool_names_unique():
    import solidworks_mcp.server as server
    tools = asyncio.run(server.list_tools())
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), "duplicate tool names"
    assert len(names) == 25 + len(tools_ext.TOOL_TABLE)


# ----------------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------------

def test_list_edges_counts_and_types(sw):
    a, doc = sw
    r = a.list_edges()
    assert r["success"] and r["data"]["total_edges"] == 14
    types_ = [e["type"] for e in r["data"]["edges"]]
    assert types_.count("line") == 12 and types_.count("circle") == 2
    assert r["data"]["edges"][0]["length"] == 20.0      # mm


def test_select_vertical_edges_with_mark(sw):
    a, doc = sw
    r = a.select_edges(parallel_to="z", mark=1)
    assert r["success"] and len(r["data"]["selected"]) == 4
    assert all(m == 1 for (_n, _o, _ap, m) in doc.sel_log)


def test_select_hole_rims_by_radius(sw):
    a, doc = sw
    r = a.select_edges(radius=2.5, axis_parallel_to="z")
    assert r["data"]["selected"] == [12, 13]


def test_select_edges_requires_criteria(sw):
    a, _ = sw
    assert not a.select_edges()["success"]


def test_edges_on_face(sw):
    a, _ = sw
    r = a.list_edges(on_face_index=1)          # top face: 4 lines + hole rim
    assert r["data"]["matched"] == 5


def test_face_normal_filters(sw):
    a, _ = sw
    assert a.list_faces(normal="+z")["data"]["matched"] == 1
    assert a.list_faces(normal="z")["data"]["matched"] == 2
    assert a.list_faces(face_type="cylinder", radius=2.5)["data"]["matched"] == 1


# ----------------------------------------------------------------------------
# Feature call shapes
# ----------------------------------------------------------------------------

def test_revolve_20_params(sw):
    a, doc = sw
    r = a.revolve_sketch(angle=180, cut=True)
    assert r["success"], r
    args = fm_call(doc, "FeatureRevolve2")
    assert len(args) == 20
    assert args[3] is True and abs(args[8] - math.pi) < 1e-12


def test_shell_removes_top_face(sw):
    a, doc = sw
    r = a.shell(1.0, face_normal="+z")
    assert r["success"] and r["data"]["removed_faces"] == [1]
    assert fm_call(doc, "InsertFeatureShell") == (0.001, False)


def test_linear_pattern_marks_and_22_params(sw):
    a, doc = sw
    r = a.linear_pattern(["Boss-Extrude1"], {"edge_index": 0}, 4, 25)
    assert r["success"], r
    args = fm_call(doc, "FeatureLinearPattern5")
    assert len(args) == 22 and args[0] == 4 and abs(args[1] - 0.025) < 1e-12 and args[2] == 1
    assert ("Select4", doc._body._edges[0], True, 1) in [s for s in doc.sel_log if s[0] == "Select4"] \
        or any(s[0] == "SelectByID2" and s[5] == 1 for s in doc.sel_log)
    assert doc._feats["Boss-Extrude1"].selected[-1] == (True, 4)


def test_circular_pattern_14_params(sw):
    a, doc = sw
    r = a.circular_pattern(["Boss-Extrude1"], {"face_index": 6}, 6)
    assert r["success"], r
    args = fm_call(doc, "FeatureCircularPattern5")
    assert len(args) == 14 and args[0] == 6 and abs(args[1] - 2 * math.pi) < 1e-12


def test_mirror_marks(sw):
    a, doc = sw
    r = a.mirror({"plane": "Right"}, features=["Boss-Extrude1"])
    assert r["success"]
    assert ("SelectByID2", "Right Plane", "PLANE", (0, 0, 0), True, 2) in doc.sel_log
    assert doc._feats["Boss-Extrude1"].selected[-1] == (True, 1)
    assert len(fm_call(doc, "InsertMirrorFeature2")) == 5


def test_ref_plane_offset_flip(sw):
    a, doc = sw
    r = a.create_ref_plane({"plane": "Top"}, distance=15, flip=True, name="P_top15")
    assert r["success"]
    args = fm_call(doc, "InsertRefPlane")
    assert args[0] == 8 | 256 and abs(args[1] - 0.015) < 1e-12 and len(args) == 6


def test_fillet_and_chamfer_param_counts(sw):
    a, doc = sw
    assert a.fillet_edges(1.5)["success"]
    assert len(fm_call(doc, "FeatureFillet3")) == 14
    assert a.chamfer_edges(0.5, 45)["success"]
    args = fm_call(doc, "InsertFeatureChamfer")
    assert len(args) == 8 and args[:2] == (4, 1)


# ----------------------------------------------------------------------------
# Model ops
# ----------------------------------------------------------------------------

def test_set_dimension(sw):
    a, doc = sw
    r = a.set_dimension("D1@Sketch1", 25)
    assert r["success"] and r["data"]["old"] == 10.0 and r["data"]["new"] == 25.0
    assert not a.set_dimension("D9@Nope", 1)["success"]


def test_export_step(sw, tmp_path):
    a, doc = sw
    out = tmp_path / "part.step"
    r = a.export_document(str(out))
    assert r["success"] and out.exists()
    assert fm_call(doc, "SaveAs")[2] == 3           # Silent | Copy
    assert not a.export_document(str(tmp_path / "x.foo"))["success"]


def test_capture_view_returns_image_via_server(sw, monkeypatch):
    a, doc = sw
    import solidworks_mcp.server as server
    monkeypatch.setattr(server, "sw_automation", a)
    content = asyncio.run(server.call_tool("capture_view", {"view": "isometric", "width": 64, "height": 48}))
    kinds = [c.type for c in content]
    assert kinds == ["text", "image"]
    assert "_image_png_b64" not in content[0].text


def test_dispatch_missing_required(sw):
    a, _ = sw
    r = tools_ext.dispatch(a, "set_dimension", {"name": "D1@Sketch1"})
    assert not r["success"] and "value" in r["message"]


# ----------------------------------------------------------------------------
# Sketch transform
# ----------------------------------------------------------------------------

def test_sketch_to_model_top_plane():
    """Top plane: sketch (x, y) -> model (x, 0, -y)."""
    class Pt:
        def __init__(self, v):
            self.ArrayData = tuple(v)

        def MultiplyTransform(self, m):
            x, y, z = self.ArrayData
            return Pt((x, z, -y))

    class MU:
        def CreatePoint(self, arr):
            return Pt(arr.value)

    class X:
        Inverse = "inv"     # property-style

    sk = types.SimpleNamespace(ModelToSketchTransform=X())
    doc = types.SimpleNamespace(SketchManager=types.SimpleNamespace(ActiveSketch=sk))
    app = types.SimpleNamespace(GetMathUtility=MU())
    assert cu.sketch_to_model(app, doc, 0.01, 0.02) == [0.01, 0.0, -0.02]


# ----------------------------------------------------------------------------
# Assembly / sketch
# ----------------------------------------------------------------------------

class FakeAsm(FakeDoc):
    def __init__(self):
        super().__init__(doc_type=2)
        self.mates = []

    def GetTitle(self):
        return "Asm1.SLDASM"

    def AddMate5(self, *args):
        self.mates.append(args)
        return FakeFeature("Coincident1")


def test_add_mate_component_planes():
    a = SolidWorksAutomation()
    asm = FakeAsm()
    a._sw_app, a._connected = FakeApp(asm), True
    r = a.add_mate("distance", {"component": "Bracket-1", "plane": "Front"},
                   {"plane": "Front"}, distance=12, unit="mm")
    assert r["success"], r
    assert len(asm.mates[-1]) == 15 and asm.mates[-1][0] == 5 and abs(asm.mates[-1][3] - 0.012) < 1e-12
    names = [s[1] for s in asm.sel_history]
    marks = [s[5] for s in asm.sel_history]
    assert names == ["Front Plane@Bracket-1@Asm1", "Front Plane"] and marks == [1, 1]


def test_part_rejects_assembly_tools(sw):
    a, _ = sw
    assert not a.add_mate("coincident", {"plane": "Front"}, {"plane": "Top"})["success"]


class SketchDoc(FakeDoc):
    def __init__(self):
        super().__init__()
        self.SketchManager = types.SimpleNamespace(ActiveSketch=types.SimpleNamespace(
            ModelToSketchTransform=None))   # transform fails -> identity fallback
        self.constraints = []
        self.dd = types.SimpleNamespace(GetDimension2=lambda i: self.dim)

    def SketchAddConstraints(self, sg):
        self.constraints.append(sg)

    def AddDimension2(self, x, y, z):
        self.calls.append(("AddDimension2", (x, y, z)))
        return self.dd


class PrefApp(FakeApp):
    def __init__(self, doc):
        super().__init__(doc)
        self.prefs = {10: True}

    def GetUserPreferenceToggle(self, k):
        return self.prefs.get(k)

    def SetUserPreferenceToggle(self, k, v):
        self.prefs[k] = v


def test_sketch_dimension_and_relation():
    a = SolidWorksAutomation()
    doc = SketchDoc()
    app = PrefApp(doc)
    a._sw_app, a._connected = app, True
    r = a.add_sketch_dimension([{"point": [10, 0]}], value=42, unit="mm")
    assert r["success"], r
    assert abs(doc.dim.SystemValue - 0.042) < 1e-12
    assert app.prefs[10] is True                      # input-box preference restored
    r = a.add_sketch_relation("horizontal", [{"point": [10, 0]}])
    assert r["success"] and doc.constraints == ["sgHORIZONTAL2D"]
    assert not a.add_sketch_relation("weird", [{"point": [0, 0]}])["success"]


def test_sketch_tools_require_active_sketch(sw):
    a, _ = sw
    r = a.draw_slot(0, 0, 10, 0, 4)
    assert not r["success"] and "No active sketch" in r["message"]


# ----------------------------------------------------------------------------
# Template resolution
# ----------------------------------------------------------------------------

from solidworks_mcp.automation.templates import resolve_template   # noqa: E402


class TplApp:
    def __init__(self, prefs=None, gdt=""):
        self.prefs, self.gdt, self.new_docs = prefs or {}, gdt, []

    def GetUserPreferenceStringValue(self, k):
        return self.prefs.get(k, "")

    def GetDocumentTemplate(self, mode, tpl, paper, w, h):
        return self.gdt

    def NewDocument(self, t, a, b, c):
        self.new_docs.append(t)
        return FakeDoc()


def test_template_from_default_pref(tmp_path):
    t = tmp_path / "Vulcan_Part_mm.prtdot"
    t.write_bytes(b"x")
    path, src, _ = resolve_template(TplApp({8: str(t)}), "part")
    assert path == str(t) and "default" in src


def test_template_scan_custom_folder(tmp_path):
    d = tmp_path / "SW TEMPLATES VERSION 05"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "PART_MM.prtdot").write_bytes(b"x")
    (d / "ASSY.asmdot").write_bytes(b"x")
    app = TplApp({0: f"{tmp_path / 'missing'};{d}"})
    assert resolve_template(app, "part")[0].endswith("PART_MM.prtdot")
    assert resolve_template(app, "assembly")[0].endswith("ASSY.asmdot")


def test_template_config_override_and_missing(tmp_path):
    t = tmp_path / "x.prtdot"
    t.write_bytes(b"x")
    assert resolve_template(TplApp(), "part", str(t))[1] == "config.json"
    path, _, tried = resolve_template(TplApp(), "drawing", "auto", lambda k: None)
    assert path is None and len(tried) >= 2


def test_create_new_part_uses_resolver(tmp_path):
    t = tmp_path / "p.prtdot"
    t.write_bytes(b"x")
    a = SolidWorksAutomation()
    app = TplApp({8: str(t)})
    app.RevisionNumber = "34.3.2"
    a._sw_app, a._connected = app, True
    r = a.create_new_part()
    assert r["success"] and app.new_docs == [str(t)]
    app.prefs = {}
    r = a.create_new_part()
    assert not r["success"] and "tried" in r["data"] and app.new_docs == [str(t)]
