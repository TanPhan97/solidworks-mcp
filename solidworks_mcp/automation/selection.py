"""
SolidWorks Selection Operations
-------------------------------
Deterministic topology selection for parts.

Problem in the base server: fillet/chamfer operate on "selected edges" but
there was no reliable way to select anything except via execute_python.

Approach:
- list_edges / list_faces enumerate body topology with a stable index
  (order of IPartDoc.GetBodies2 -> IBody2.GetEdges/GetFaces) plus geometric
  descriptors (type, length/area, direction/normal, radius, a point on it).
- select_edges / select_faces select by index or by geometric filter
  (e.g. all linear edges parallel to Z, all circular edges R=2.5).
- Selection uses IEntity::Select4 (carries Mark), falling back to
  SelectByID2 at a point lying on the entity.

Indices are valid until the topology changes (any feature add/edit).
Re-list after modifying the model.
"""

import math
import logging
import traceback
from typing import Dict, List, Any

from ..constants import SwErrors, SwPlanes
from . import com_utils as cu

logger = logging.getLogger(__name__)

_AXES = {
    "x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
    "-x": (-1.0, 0.0, 0.0), "-y": (0.0, -1.0, 0.0), "-z": (0.0, 0.0, -1.0),
}
_PARALLEL_TOL = 1e-3      # 1 - |cos| tolerance
_POINT_TOL = 1e-8         # m, for matching midpoints


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(v):
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n) if n > 0 else (0.0, 0.0, 0.0)


def _close(p, q, tol=_POINT_TOL):
    return all(abs(a - b) <= tol for a, b in zip(p, q))


def _edge_mid(curve, params, length: float) -> List[float]:
    """
    Middle point of an edge from its curve and GetCurveParams2 data.
    Lines use the chord midpoint: Curve.Evaluate2 disagrees with GetCurveParams2
    on reversed lines (SW 2026: an edge from x=40 to x=-40 evaluated its middle at
    x=80). Curves use Evaluate2, checked against the end points.
    """
    start = [float(v) for v in params[0:3]]
    end = [float(v) for v in params[3:6]]
    chord = [(start[i] + end[i]) / 2.0 for i in range(3)]
    if cu.try_call(curve, "IsLine"):
        return chord
    t0, t1 = float(params[6]), float(params[7])
    ev = [float(v) for v in cu.as_list(cu.try_call(curve, "Evaluate2", (t0 + t1) / 2.0, 0))[:3]]
    if len(ev) == 3 and all(math.dist(ev, p) <= length + 1e-6 for p in (start, end)):
        return ev
    return chord


class SelectionOperations:
    """
    Mixin for topology enumeration and selection.

    Requires: get_active_doc(), _result(), _units, app
    """

    # ======================================================================
    # Topology enumeration (internal)
    # ======================================================================

    def _get_bodies(self, doc) -> List[Any]:
        if cu.doc_type(doc) != 1:
            raise ValueError("Topology listing is supported on part documents only")
        # Solid bodies first (indices of solid-only parts stay stable), then surface
        # (sheet) bodies so surface faces / edges can be listed and selected too.
        return cu.as_list(doc.GetBodies2(0, True)) + cu.as_list(doc.GetBodies2(1, True))

    def _edge_records(self, doc) -> List[Dict]:
        records = []
        idx = 0
        for b_i, body in enumerate(self._get_bodies(doc)):
            for edge in cu.as_list(cu.call(body, "GetEdges")):
                rec = {"index": idx, "body": b_i, "_obj": edge}
                try:
                    curve = cu.call(edge, "GetCurve")
                    params = cu.as_list(cu.call(edge, "GetCurveParams2"))
                    start, end = params[0:3], params[3:6]
                    t0, t1 = float(params[6]), float(params[7])
                    rec["start"] = [float(v) for v in start]
                    rec["end"] = [float(v) for v in end]

                    rec["length"] = float(cu.try_call(curve, "GetLength3", t0, t1, default=0.0) or 0.0)
                    rec["mid"] = _edge_mid(curve, params, rec["length"])

                    if cu.try_call(curve, "IsLine"):
                        lp = cu.as_list(cu.call(curve, "LineParams"))
                        rec["type"] = "line"
                        rec["direction"] = list(_norm(lp[3:6]))
                    elif cu.try_call(curve, "IsCircle"):
                        cp = cu.as_list(cu.call(curve, "CircleParams"))
                        closed = _close(rec["start"], rec["end"], 1e-9)
                        rec["type"] = "circle" if closed else "arc"
                        rec["center"] = [float(v) for v in cp[0:3]]
                        rec["axis"] = list(_norm(cp[3:6]))
                        rec["radius"] = float(cp[6])
                    else:
                        rec["type"] = "other"
                except Exception as e:  # noqa: BLE001
                    rec["type"] = "unknown"
                    rec["error"] = str(e)
                records.append(rec)
                idx += 1
        return records

    def _face_records(self, doc) -> List[Dict]:
        records = []
        idx = 0
        for b_i, body in enumerate(self._get_bodies(doc)):
            for face in cu.as_list(cu.call(body, "GetFaces")):
                rec = {"index": idx, "body": b_i, "_obj": face}
                try:
                    surf = cu.call(face, "GetSurface")
                    rec["area"] = float(cu.try_call(face, "GetArea", default=0.0) or 0.0)
                    if cu.try_call(surf, "IsPlane"):
                        rec["type"] = "plane"
                        rec["normal"] = list(_norm(cu.as_list(cu.call(face, "Normal"))))
                    elif cu.try_call(surf, "IsCylinder"):
                        cp = cu.as_list(cu.call(surf, "CylinderParams"))
                        rec["type"] = "cylinder"
                        rec["origin"] = [float(v) for v in cp[0:3]]
                        rec["axis"] = list(_norm(cp[3:6]))
                        rec["radius"] = float(cp[6])
                    elif cu.try_call(surf, "IsCone"):
                        rec["type"] = "cone"
                    elif cu.try_call(surf, "IsSphere"):
                        rec["type"] = "sphere"
                    elif cu.try_call(surf, "IsTorus"):
                        rec["type"] = "torus"
                    else:
                        rec["type"] = "other"
                    # A point guaranteed to lie on the face: centroid of the
                    # first tessellation triangle.
                    tess = cu.as_list(cu.try_call(face, "GetTessTriangles", True))
                    if len(tess) >= 9:
                        rec["point"] = [
                            (float(tess[0]) + float(tess[3]) + float(tess[6])) / 3.0,
                            (float(tess[1]) + float(tess[4]) + float(tess[7])) / 3.0,
                            (float(tess[2]) + float(tess[5]) + float(tess[8])) / 3.0,
                        ]
                    rec["_edge_mids"] = []
                    for e in cu.as_list(cu.try_call(face, "GetEdges")):
                        try:
                            p = cu.as_list(cu.call(e, "GetCurveParams2"))
                            c = cu.call(e, "GetCurve")
                            ln = float(cu.try_call(c, "GetLength3", float(p[6]), float(p[7]), default=0.0) or 0.0)
                            rec["_edge_mids"].append(_edge_mid(c, p, ln))
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as e:  # noqa: BLE001
                    rec["type"] = "unknown"
                    rec["error"] = str(e)
                records.append(rec)
                idx += 1
        return records

    # ======================================================================
    # Filtering
    # ======================================================================

    def _filter_edges(self, records: List[Dict], doc, indices=None, edge_type=None,
                      parallel_to=None, axis_parallel_to=None, radius=None,
                      min_length=None, max_length=None, on_face_index=None,
                      unit=None) -> List[Dict]:
        tol_len = self._units.to_meters(0.001, "mm")  # 1 µm
        out = records
        if indices:
            wanted = set(int(i) for i in indices)
            out = [r for r in out if r["index"] in wanted]
        if edge_type and edge_type != "all":
            out = [r for r in out if r.get("type") == edge_type
                   or (edge_type == "circular" and r.get("type") in ("circle", "arc"))]
        if parallel_to:
            ax = _AXES[parallel_to.lower()]
            out = [r for r in out if r.get("type") == "line"
                   and 1 - abs(_dot(r["direction"], ax)) < _PARALLEL_TOL]
        if axis_parallel_to:
            ax = _AXES[axis_parallel_to.lower()]
            out = [r for r in out if r.get("type") in ("circle", "arc")
                   and 1 - abs(_dot(r["axis"], ax)) < _PARALLEL_TOL]
        if radius is not None:
            r_m = self._units.to_meters(radius, unit)
            out = [r for r in out if "radius" in r and abs(r["radius"] - r_m) <= tol_len]
        if min_length is not None:
            lm = self._units.to_meters(min_length, unit)
            out = [r for r in out if r.get("length", 0) >= lm - tol_len]
        if max_length is not None:
            lm = self._units.to_meters(max_length, unit)
            out = [r for r in out if r.get("length", 0) <= lm + tol_len]
        if on_face_index is not None:
            faces = self._face_records(doc)
            face = next((f for f in faces if f["index"] == int(on_face_index)), None)
            if face is None:
                raise ValueError(f"face_index {on_face_index} out of range (0..{len(faces) - 1})")
            mids = face["_edge_mids"]
            out = [r for r in out if "mid" in r and any(_close(r["mid"], m, 1e-7) for m in mids)]
        return out

    def _filter_faces(self, records: List[Dict], indices=None, face_type=None,
                      normal=None, radius=None, min_area=None, unit=None) -> List[Dict]:
        out = records
        if indices:
            wanted = set(int(i) for i in indices)
            out = [r for r in out if r["index"] in wanted]
        if face_type and face_type != "all":
            out = [r for r in out if r.get("type") == face_type]
        if normal:
            # "z" = normal along ±Z; "+z" / "-z" = outward normal in that sense only
            key = normal.lower()
            signed = key[0] in "+-"
            ax = _AXES[key.lstrip("+")]

            def ok(r):
                if r.get("type") != "plane":
                    return False
                d = _dot(r["normal"], ax)
                return (1 - d < _PARALLEL_TOL) if signed else (1 - abs(d) < _PARALLEL_TOL)
            out = [r for r in out if ok(r)]
        if radius is not None:
            r_m = self._units.to_meters(radius, unit)
            tol = self._units.to_meters(0.001, "mm")
            out = [r for r in out if "radius" in r and abs(r["radius"] - r_m) <= tol]
        if min_area is not None:
            # min_area given in unit^2
            scale = self._units.to_meters(1.0, unit) ** 2
            out = [r for r in out if r.get("area", 0) >= min_area * scale]
        return out

    # ======================================================================
    # Presentation
    # ======================================================================

    def _fmt_len(self, v_m: float, unit=None) -> float:
        return round(self._units.from_meters(v_m, unit), 4)

    def _fmt_pt(self, p, unit=None):
        return [self._fmt_len(v, unit) for v in p]

    def _public_edge(self, r: Dict, unit=None) -> Dict:
        d = {"index": r["index"], "body": r["body"], "type": r.get("type")}
        if "length" in r:
            d["length"] = self._fmt_len(r["length"], unit)
        if "mid" in r:
            d["mid"] = self._fmt_pt(r["mid"], unit)
        if "direction" in r:
            d["direction"] = [round(v, 4) for v in r["direction"]]
        if "radius" in r:
            d["radius"] = self._fmt_len(r["radius"], unit)
            d["center"] = self._fmt_pt(r["center"], unit)
            d["axis"] = [round(v, 4) for v in r["axis"]]
        return d

    def _public_face(self, r: Dict, unit=None) -> Dict:
        scale = self._units.to_meters(1.0, unit) ** 2
        d = {"index": r["index"], "body": r["body"], "type": r.get("type"),
             "area": round(r.get("area", 0) / scale, 4)}
        if "normal" in r:
            d["normal"] = [round(v, 4) for v in r["normal"]]
        if "radius" in r:
            d["radius"] = self._fmt_len(r["radius"], unit)
            d["axis"] = [round(v, 4) for v in r["axis"]]
        if "point" in r:
            d["point"] = self._fmt_pt(r["point"], unit)
        return d

    # ======================================================================
    # Selection primitives
    # ======================================================================

    def _select_record(self, doc, rec: Dict, sel_type: str, append: bool, mark: int) -> bool:
        if cu.select_entity_object(doc, rec["_obj"], append, mark):
            return True
        pt = rec.get("mid") if sel_type == "EDGE" else rec.get("point")
        if pt is None:
            return False
        return cu.select_by_id(doc, "", sel_type, pt[0], pt[1], pt[2], append, mark)

    def _select_ref(self, doc, spec: Dict, append: bool, mark: int, unit=None) -> bool:
        """
        Select one reference entity from a spec dict:
          {"plane": "Front"|"Top"|"Right"|"<custom plane name>"}
          {"edge_index": n} | {"face_index": n}
          {"name": "Axis1", "type": "AXIS"}
          {"point": [x, y, z], "type": "FACE"|"EDGE"|"VERTEX"}  (user units)
        """
        if not isinstance(spec, dict):
            raise ValueError(f"Reference spec must be an object, got {spec!r}")
        if "plane" in spec:
            p = str(spec["plane"])
            name = SwPlanes.get(p) if p.lower() in ("front", "top", "right") else p
            return cu.select_by_id(doc, name, "PLANE", 0, 0, 0, append, mark)
        if "edge_index" in spec:
            recs = [r for r in self._edge_records(doc) if r["index"] == int(spec["edge_index"])]
            if not recs:
                raise ValueError(f"edge_index {spec['edge_index']} not found")
            return self._select_record(doc, recs[0], "EDGE", append, mark)
        if "face_index" in spec:
            recs = [r for r in self._face_records(doc) if r["index"] == int(spec["face_index"])]
            if not recs:
                raise ValueError(f"face_index {spec['face_index']} not found")
            return self._select_record(doc, recs[0], "FACE", append, mark)
        if "point" in spec:
            x, y, z = [self._units.to_meters(v, spec.get("unit", unit)) for v in spec["point"]]
            return cu.select_by_id(doc, spec.get("name", ""), spec.get("type", "FACE").upper(),
                                   x, y, z, append, mark)
        if "name" in spec:
            return cu.select_by_id(doc, spec["name"], spec.get("type", "").upper(),
                                   0, 0, 0, append, mark)
        raise ValueError(f"Unrecognized reference spec: {spec}")

    # ======================================================================
    # Public tools
    # ======================================================================

    def list_edges(self, edge_type: str = "all", parallel_to: str = None,
                   axis_parallel_to: str = None, radius: float = None,
                   min_length: float = None, max_length: float = None,
                   on_face_index: int = None, limit: int = 200, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            recs = self._edge_records(doc)
            total = len(recs)
            recs = self._filter_edges(recs, doc, None, edge_type, parallel_to, axis_parallel_to,
                                      radius, min_length, max_length, on_face_index, unit)
            out = [self._public_edge(r, unit) for r in recs[:limit]]
            unit_str = unit or self._units.default_unit.value
            return self._result(True, f"{len(recs)} of {total} edges match (showing {len(out)}), unit={unit_str}",
                                SwErrors.swSuccess,
                                {"total_edges": total, "matched": len(recs), "edges": out, "unit": unit_str})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"list_edges error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def list_faces(self, face_type: str = "all", normal: str = None, radius: float = None,
                   min_area: float = None, limit: int = 200, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            recs = self._face_records(doc)
            total = len(recs)
            recs = self._filter_faces(recs, None, face_type, normal, radius, min_area, unit)
            out = [self._public_face(r, unit) for r in recs[:limit]]
            unit_str = unit or self._units.default_unit.value
            return self._result(True, f"{len(recs)} of {total} faces match (showing {len(out)}), unit={unit_str}",
                                SwErrors.swSuccess,
                                {"total_faces": total, "matched": len(recs), "faces": out, "unit": unit_str})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"list_faces error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def select_edges(self, indices: List[int] = None, edge_type: str = "all",
                     parallel_to: str = None, axis_parallel_to: str = None,
                     radius: float = None, min_length: float = None,
                     max_length: float = None, on_face_index: int = None,
                     append: bool = False, mark: int = 0, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            has_filter = any(v not in (None, "all") for v in
                             (edge_type, parallel_to, axis_parallel_to, radius,
                              min_length, max_length, on_face_index))
            if not indices and not has_filter:
                return self._result(False,
                    "Specify indices or at least one filter (use edge_type='all' with "
                    "min_length=0 to select every edge).", SwErrors.swInvalidInput)
            recs = self._filter_edges(self._edge_records(doc), doc, indices, edge_type,
                                      parallel_to, axis_parallel_to, radius,
                                      min_length, max_length, on_face_index, unit)
            if not recs:
                return self._result(False, "No edges match the criteria", SwErrors.swSelectionError)
            if not append:
                doc.ClearSelection2(True)
            ok, failed = [], []
            for r in recs:
                (ok if self._select_record(doc, r, "EDGE", True, mark) else failed).append(r["index"])
            return self._result(bool(ok),
                f"Selected {len(ok)} edge(s)" + (f", failed {len(failed)}" if failed else ""),
                SwErrors.swSuccess if ok else SwErrors.swSelectionError,
                {"selected": ok, "failed": failed, "mark": mark,
                 "selection_count": cu.selected_count(doc)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"select_edges error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def select_faces(self, indices: List[int] = None, face_type: str = "all",
                     normal: str = None, radius: float = None, min_area: float = None,
                     append: bool = False, mark: int = 0, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            has_filter = any(v not in (None, "all") for v in (face_type, normal, radius, min_area))
            if not indices and not has_filter:
                return self._result(False, "Specify indices or at least one filter",
                                    SwErrors.swInvalidInput)
            recs = self._filter_faces(self._face_records(doc), indices, face_type,
                                      normal, radius, min_area, unit)
            if not recs:
                return self._result(False, "No faces match the criteria", SwErrors.swSelectionError)
            if not append:
                doc.ClearSelection2(True)
            ok, failed = [], []
            for r in recs:
                (ok if self._select_record(doc, r, "FACE", True, mark) else failed).append(r["index"])
            return self._result(bool(ok),
                f"Selected {len(ok)} face(s)" + (f", failed {len(failed)}" if failed else ""),
                SwErrors.swSuccess if ok else SwErrors.swSelectionError,
                {"selected": ok, "failed": failed, "mark": mark,
                 "selection_count": cu.selected_count(doc)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"select_faces error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def select_entity(self, entity_type: str, name: str = "", point: List[float] = None,
                      append: bool = False, mark: int = 0, sketch_coords: bool = False,
                      unit: str = None) -> Dict:
        """
        Generic SelectByID2. `point` is in user units; with sketch_coords=True it
        is interpreted in the active sketch's 2D space (z ignored) and transformed.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            sel_type = entity_type.upper()
            if sel_type == "PLANE" and name.lower() in ("front", "top", "right"):
                name = SwPlanes.get(name)
            x = y = z = 0.0
            if point:
                pts = [self._units.to_meters(v, unit) for v in (list(point) + [0, 0, 0])[:3]]
                if sketch_coords:
                    pts = cu.sketch_to_model(self.app, doc, pts[0], pts[1], 0.0)
                x, y, z = pts
            ok = cu.select_by_id(doc, name, sel_type, x, y, z, append, mark)
            if not ok:
                return self._result(False,
                    f"Nothing selected (type={sel_type}, name={name!r}, point={point})",
                    SwErrors.swSelectionError)
            return self._result(True, f"Selected {sel_type} {name or point}", SwErrors.swSuccess,
                                {"selection_count": cu.selected_count(doc), "mark": mark})
        except Exception as e:
            logger.error(f"select_entity error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def clear_selection(self) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            doc.ClearSelection2(True)
            return self._result(True, "Selection cleared", SwErrors.swSuccess)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)

    def get_selection(self, unit: str = None) -> Dict:
        # swSelectType_e subset for readability
        type_names = {1: "EDGE", 2: "FACE", 3: "VERTEX", 4: "DATUMPLANE", 5: "DATUMAXIS",
                      9: "SKETCHSEGMENT", 11: "SKETCHPOINT", 20: "COMPONENT",
                      22: "BODYFEATURE", 24: "SKETCH", 76: "SOLIDBODY"}
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            sm = cu.call(doc, "SelectionManager")
            n = cu.selected_count(doc)
            items = []
            for i in range(1, n + 1):
                t = int(cu.try_call(sm, "GetSelectedObjectType3", i, -1, default=0) or 0)
                item = {"i": i, "type": type_names.get(t, t),
                        "mark": cu.try_call(sm, "GetSelectedObjectMark", i)}
                pt = cu.as_list(cu.try_call(sm, "GetSelectionPoint2", i, -1))
                if len(pt) >= 3:
                    item["point"] = self._fmt_pt(pt[:3], unit)
                items.append(item)
            return self._result(True, f"{n} selected", SwErrors.swSuccess, {"items": items})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swSelectionError)
