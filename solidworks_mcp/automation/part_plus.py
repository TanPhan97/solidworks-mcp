"""
Part design additions
---------------------
Full extrude (end conditions, draft, thin, boss/cut), sketch tools (spline,
ellipse, convert/offset entities, mirror, linear/circular sketch pattern,
construction toggle), reference axis, configurations, equations /
global variables, delete / rename feature, measure.

SOLIDWORKS 2026 type-library signatures:
  FeatureExtrusion2 (23), FeatureExtrusionThin2 (30), FeatureCut4 (27)
  ISketchManager.CreateSpline2(PointData, SimulateNaturalEnds)
  ISketchManager.CreateEllipse(XC, YC, Zc, XMajor, YMajor, ZMajor, XMinor, YMinor, ZMinor)
  ISketchManager.SketchUseEdge3(Chain, InnerLoops)
  ISketchManager.SketchOffset2(Offset, BothDirections, Chain, CapEnds, MakeConstruction, AddDimensions)
  ISketchManager.CreateLinearSketchStepAndRepeat (12), CreateCircularSketchStepAndRepeat (9)
  IModelDoc2.SketchMirror(), InsertAxis2(AutoSize), GetEquationMgr()
  IConfigurationManager.AddConfiguration2(Name, Comment, AlternateName, Options, Parent, Description, Rebuild)
  IEquationMgr.Add3(Index, Equation, Solve, WhichConfigurations, ConfigNames)
  IModelDocExtension.DeleteSelection2(Options), CreateMeasure() -> IMeasure.Calculate(Entities)
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_END = {"blind": 0, "through_all": 1, "through_next": 2, "mid_plane": 6, "through_all_both": 9,
        "up_to_next": 11}


class PartPlusOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, _close_and_select_sketch(),
    _select_ref(), _select_sketch_entity(), _require_active_sketch(), _last_feature(),
    _rebuild_errors(), _edge_records(), _face_records(), _select_record()"""

    # ------------------------------------------------------------------
    # extrude
    # ------------------------------------------------------------------

    def extrude(self, depth: float = 10.0, end_condition: str = "blind", depth2: float = None,
                end_condition2: str = "blind", reverse: bool = False, draft_angle: float = 0.0,
                draft_outward: bool = False, thin_thickness: float = None, cut: bool = False,
                flip_side: bool = False, merge: bool = True, unit: str = None) -> Dict:
        """
        Extrude the last sketch with full options. depth2/end_condition2 enable a second
        direction. thin_thickness makes a thin feature (boss only).
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            for ec in (end_condition, end_condition2):
                if ec not in _END:
                    return self._result(False, f"end_condition must be one of {sorted(_END)}",
                                        SwErrors.swInvalidInput)
            ok, sketch, msg = self._close_and_select_sketch(doc)
            if not ok:
                return self._result(False, f"Extrude needs a sketch: {msg}", SwErrors.swFeatureError)
            L = lambda v: self._units.to_meters(v, unit) if v else 0.0   # noqa: E731
            two = depth2 is not None and end_condition not in ("mid_plane", "through_all_both")
            sd = not two
            t1, t2 = _END[end_condition], _END[end_condition2] if two else 0
            d1, d2 = L(depth), L(depth2)
            dchk = bool(draft_angle)
            dang = math.radians(draft_angle or 0.0)
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            fm = doc.FeatureManager
            thin = bool(thin_thickness) and not cut
            if cut:
                feat = fm.FeatureCut4(sd, flip_side, reverse, t1, t2, d1, d2, dchk, dchk and two,
                                      draft_outward, draft_outward, dang, dang, False, False, False, False,
                                      False, True, True, False, False, False, 0, 0.0, False, False)
            elif thin:
                t = L(thin_thickness)
                feat = fm.FeatureExtrusionThin2(sd, False, reverse, t1, t2, d1, d2, dchk, dchk and two,
                                                draft_outward, draft_outward, dang, dang, False, False,
                                                False, False, merge, t, t, 0.0, False, False, False, 0.0,
                                                True, True, 0, 0.0, False)
            else:
                feat = fm.FeatureExtrusion2(sd, False, reverse, t1, t2, d1, d2, dchk, dchk and two,
                                            draft_outward, draft_outward, dang, dang, False, False, False,
                                            False, merge, True, True, 0, 0.0, False)
            if not feat:
                last = self._last_feature(doc)
                if last is not None and str(cu.try_call(last, "Name", default="")) != before:
                    feat = last
            if not feat:
                return self._result(False, f"Extrude failed on {sketch} (closed profile? a cut needs a body; "
                                    f"up_to_next needs geometry in the way)", SwErrors.swFeatureError)
            kind = "Cut" if cut else ("Thin boss" if thin else "Boss")
            return self._result(True, f"{kind} {end_condition}" + (f" {depth}" if t1 in (0, 6) else "")
                                + f" → {feat.Name}", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "sketch": sketch})
        except Exception as e:
            logger.error(f"extrude error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # sketch tools
    # ------------------------------------------------------------------

    def draw_spline(self, points: List[List[float]], unit: str = None) -> Dict:
        """Spline through [[x, y], ...] in the active sketch."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            if not points or len(points) < 2:
                return self._result(False, "Give >= 2 points", SwErrors.swInvalidInput)
            flat = []
            for p in points:
                flat += [self._units.to_meters(p[0], unit), self._units.to_meters(p[1], unit), 0.0]
            seg = doc.SketchManager.CreateSpline2(cu.double_array(flat), True)
            if seg is None:
                return self._result(False, "Spline failed", SwErrors.swSketchError)
            return self._result(True, f"Spline through {len(points)} points", SwErrors.swSuccess)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"draw_spline error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def draw_ellipse(self, cx: float, cy: float, major_radius: float, minor_radius: float,
                     angle: float = 0.0, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            L = lambda v: self._units.to_meters(v, unit)   # noqa: E731
            a = math.radians(angle)
            x, y, R, r = L(cx), L(cy), L(major_radius), L(minor_radius)
            seg = doc.SketchManager.CreateEllipse(x, y, 0.0, x + R * math.cos(a), y + R * math.sin(a), 0.0,
                                                  x - r * math.sin(a), y + r * math.cos(a), 0.0)
            if seg is None:
                return self._result(False, "Ellipse failed", SwErrors.swSketchError)
            return self._result(True, f"Ellipse {2 * major_radius}×{2 * minor_radius}", SwErrors.swSuccess)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"draw_ellipse error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def _select_model_geometry(self, doc, face_index=None, edge_indices=None) -> int:
        """Select a body face (all its edges) or edges by index; returns how many selected."""
        doc.ClearSelection2(True)
        n = 0
        if face_index is not None:
            recs = [r for r in self._face_records(doc) if r["index"] == int(face_index)]
            if recs and self._select_record(doc, recs[0], "FACE", True, 0):
                n += 1
        if edge_indices:
            wanted = set(int(i) for i in edge_indices)
            for r in self._edge_records(doc):
                if r["index"] in wanted and self._select_record(doc, r, "EDGE", True, 0):
                    n += 1
        return n

    def convert_entities(self, face_index: int = None, edge_indices: List[int] = None,
                         inner_loops: bool = True) -> Dict:
        """Project model edges (a face's loops or chosen edges) into the active sketch."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            if self._select_model_geometry(doc, face_index, edge_indices) == 0:
                return self._result(False, "Nothing selected: give face_index or edge_indices",
                                    SwErrors.swSelectionError)
            ok = doc.SketchManager.SketchUseEdge3(False, bool(inner_loops))
            doc.ClearSelection2(True)
            return self._result(bool(ok), "Converted entities" if ok else "Convert entities failed",
                                SwErrors.swSuccess if ok else SwErrors.swSketchError)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"convert_entities error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def offset_entities(self, distance: float, face_index: int = None, edge_indices: List[int] = None,
                        entities: List[Dict] = None, both_directions: bool = False,
                        reverse: bool = False, unit: str = None) -> Dict:
        """
        Offset model edges (face_index / edge_indices) or sketch entities (`entities`,
        sketch-entity specs) into the active sketch. reverse flips the side.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            sm = doc.SketchManager
            make_construction = False
            if entities:
                doc.ClearSelection2(True)
                for i, spec in enumerate(entities):
                    if not self._select_sketch_entity(doc, spec, i > 0, 0, unit):
                        return self._result(False, f"Sketch entity not found: {spec}", SwErrors.swSelectionError)
            else:
                # SketchOffset2 does not take model edges on SW 2026: convert them first,
                # then offset the converted loop and turn it into construction geometry.
                sk = cu.call(sm, "ActiveSketch")
                before = {id(x) for x in cu.as_list(cu.try_call(sk, "GetSketchSegments"))}
                n_before = len(before)
                if self._select_model_geometry(doc, face_index, edge_indices) == 0:
                    return self._result(False, "Give face_index, edge_indices or entities", SwErrors.swSelectionError)
                if not sm.SketchUseEdge3(False, True):
                    return self._result(False, "Could not convert the edges", SwErrors.swSketchError)
                new = cu.as_list(cu.try_call(sk, "GetSketchSegments"))[n_before:]
                doc.ClearSelection2(True)
                for i, seg in enumerate(new):
                    cu.select_entity_object(doc, seg, i > 0, 0)
                make_construction = True
            d = self._units.to_meters(distance, unit) * (-1 if reverse else 1)
            ok = sm.SketchOffset2(d, bool(both_directions), True, 0, make_construction, True)
            doc.ClearSelection2(True)
            return self._result(bool(ok), f"Offset {distance}" if ok else "Offset failed",
                                SwErrors.swSuccess if ok else SwErrors.swSketchError)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"offset_entities error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def sketch_mirror(self, entities: List[Dict], mirror_line: Dict, unit: str = None) -> Dict:
        """Mirror sketch entities about a (center)line, both given as sketch-entity specs."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            doc.ClearSelection2(True)
            for i, spec in enumerate(list(entities) + [mirror_line]):
                if not self._select_sketch_entity(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Sketch entity not found: {spec}", SwErrors.swSelectionError)
            doc.SketchMirror()
            doc.ClearSelection2(True)
            return self._result(True, f"Mirrored {len(entities)} entit(y/ies)", SwErrors.swSuccess)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"sketch_mirror error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def sketch_pattern(self, entities: List[Dict], kind: str = "linear", count_x: int = 2,
                       spacing_x: float = 10.0, count_y: int = 1, spacing_y: float = 10.0,
                       angle_x: float = 0.0, count: int = 4, center: List[float] = None,
                       total_angle: float = 360.0, unit: str = None) -> Dict:
        """
        Sketch step-and-repeat. linear: count_x × count_y at spacing_x / spacing_y along
        angle_x (deg). circular: `count` copies over total_angle about `center` [x, y].
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            doc.ClearSelection2(True)
            for i, spec in enumerate(entities):
                if not self._select_sketch_entity(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Sketch entity not found: {spec}", SwErrors.swSelectionError)
            L = lambda v: self._units.to_meters(v, unit)   # noqa: E731
            sm = doc.SketchManager
            if kind == "linear":
                ok = sm.CreateLinearSketchStepAndRepeat(int(count_x), int(count_y), L(spacing_x), L(spacing_y),
                                                        math.radians(angle_x), math.radians(angle_x + 90),
                                                        "", True, count_y > 1, False, False, False)
                what = f"{count_x}×{count_y}"
            elif kind == "circular":
                if not center:
                    return self._result(False, "circular pattern needs center [x, y]", SwErrors.swInvalidInput)
                seed = entities[0].get("point", [0, 0])
                dx, dy = L(seed[0]) - L(center[0]), L(seed[1]) - L(center[1])
                radius, ang = math.hypot(dx, dy), math.atan2(dy, dx)
                # ArcAngle is measured from the seed towards the centre
                ok = sm.CreateCircularSketchStepAndRepeat(radius, ang + math.pi, int(count),
                                                          math.radians(total_angle), True, "", True, True, False)
                what = f"{count} × over {total_angle}°"
            else:
                return self._result(False, "kind must be linear or circular", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            return self._result(bool(ok), f"Sketch pattern {what}" if ok else "Sketch pattern failed",
                                SwErrors.swSuccess if ok else SwErrors.swSketchError)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"sketch_pattern error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def set_construction(self, entities: List[Dict], construction: bool = True, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            sm = cu.call(doc, "SelectionManager")
            n = 0
            for spec in entities:
                doc.ClearSelection2(True)
                if not self._select_sketch_entity(doc, spec, False, 0, unit):
                    continue
                seg = cu.try_call(sm, "GetSelectedObject6", 1, -1)
                if seg is not None:
                    try:
                        seg.ConstructionGeometry = bool(construction)
                        n += 1
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"construction toggle failed: {e}")
            doc.ClearSelection2(True)
            return self._result(n > 0, f"{n} entit(y/ies) set to {'construction' if construction else 'normal'}",
                                SwErrors.swSuccess if n else SwErrors.swSelectionError)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    # ------------------------------------------------------------------
    # reference axis
    # ------------------------------------------------------------------

    def create_ref_axis(self, refs: List[Dict], name: str = None, unit: str = None) -> Dict:
        """Axis from a cylindrical face, a linear edge, or two planes / two points (ref specs)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            doc.ClearSelection2(True)
            for i, spec in enumerate(refs):
                if not self._select_ref(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Could not select {spec}", SwErrors.swSelectionError)
            doc.InsertAxis2(True)
            last = self._last_feature(doc)
            if last is None or str(cu.try_call(last, "Name", default="")) == before:
                return self._result(False, "Axis not created (cylindrical face, edge, or 2 planes)",
                                    SwErrors.swFeatureError)
            if name:
                try:
                    last.Name = name
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"rename axis failed: {e}")
            return self._result(True, f"Axis {last.Name}", SwErrors.swSuccess, {"feature": str(last.Name)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"create_ref_axis error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # configurations
    # ------------------------------------------------------------------

    def list_configurations(self) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            names = [str(n) for n in cu.as_list(cu.call(doc, "GetConfigurationNames"))]
            return self._result(True, f"{len(names)} configuration(s)", SwErrors.swSuccess,
                                {"configurations": names, "active": cu.active_config_name(doc)})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_configuration(self, name: str, description: str = "", activate: bool = True) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            cm = doc.ConfigurationManager
            opts = 0 if activate else 128                                    # DontActivate
            cfg = cm.AddConfiguration2(name, "", "", opts, "", description, True)
            if cfg is None:
                return self._result(False, f"Could not add '{name}' (exists?)", SwErrors.swFeatureError)
            return self._result(True, f"Configuration {name} added" + (" and active" if activate else ""),
                                SwErrors.swSuccess, {"active": cu.active_config_name(doc)})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def activate_configuration(self, name: str) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            ok = doc.ShowConfiguration2(name)
            return self._result(bool(ok), f"Active configuration: {cu.active_config_name(doc)}",
                                SwErrors.swSuccess if ok else SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # equations / global variables
    # ------------------------------------------------------------------

    def _equations(self, mgr) -> List[Dict]:
        out = []
        for i in range(int(cu.call(mgr, "GetCount") or 0)):
            eq = str(cu.try_call(mgr, "Equation", i, default=""))
            out.append({"index": i, "equation": eq, "value": cu.try_call(mgr, "Value", i)})
        return out

    def list_equations(self) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            eqs = self._equations(cu.call(doc, "GetEquationMgr"))
            return self._result(True, f"{len(eqs)} equation(s)", SwErrors.swSuccess, {"equations": eqs})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def set_equation(self, equation: str) -> Dict:
        """
        Add or replace an equation / global variable, e.g. '"Wall" = 2' (global variable,
        model units) or '"D1@Boss-Extrude1" = "Wall" * 3'. An existing equation with the
        same left-hand side is replaced.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if "=" not in equation:
                return self._result(False, "Equation must contain '='", SwErrors.swInvalidInput)
            mgr = cu.call(doc, "GetEquationMgr")
            lhs = equation.split("=", 1)[0].strip().lower()
            for e in self._equations(mgr):
                if e["equation"].split("=", 1)[0].strip().lower() == lhs:
                    cu.try_call(mgr, "Delete", e["index"])
                    break
            idx = mgr.Add3(-1, equation, True, 2, cu.empty())      # all configurations
            if idx is None or int(idx) < 0:
                return self._result(False, f"Equation rejected: {equation}", SwErrors.swInvalidInput)
            cu.try_call(mgr, "EvaluateAll")
            cu.rebuild(doc)
            return self._result(True, f"{equation} = {cu.try_call(mgr, 'Value', int(idx))}", SwErrors.swSuccess,
                                {"equations": self._equations(mgr), "errors": self._rebuild_errors(doc)})
        except Exception as e:
            logger.error(f"set_equation error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # tree edits
    # ------------------------------------------------------------------

    def delete_feature(self, name: str, delete_children: bool = False) -> Dict:
        """Delete a feature; absorbed sketches go with it (children only if asked)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            feat = cu.find_feature(doc, name)
            if feat is None:
                return self._result(False, f"Feature '{name}' not found", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            feat.Select2(False, 0)
            ok = doc.Extension.DeleteSelection2(2 | (1 if delete_children else 0))
            return self._result(bool(ok), f"Deleted {name}" if ok else f"Could not delete {name}",
                                SwErrors.swSuccess if ok else SwErrors.swFeatureError)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def rename_feature(self, name: str, new_name: str) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            feat = cu.find_feature(doc, name)
            if feat is None:
                return self._result(False, f"Feature '{name}' not found", SwErrors.swInvalidInput)
            feat.Name = new_name
            got = str(feat.Name)
            return self._result(got == new_name, f"{name} → {got}",
                                SwErrors.swSuccess if got == new_name else SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # measure
    # ------------------------------------------------------------------

    def measure(self, entities: List[Dict], unit: str = None) -> Dict:
        """
        Measure 1 or 2 reference specs (faces, edges, vertices, planes): distance,
        normal distance, centre distance, angle, length, radius, area.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            doc.ClearSelection2(True)
            for i, spec in enumerate(entities):
                if not self._select_ref(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Could not select {spec}", SwErrors.swSelectionError)
            m = cu.call(doc.Extension, "CreateMeasure")
            if not cu.invoke_method(m, "Calculate", None):
                return self._result(False, "Measure could not evaluate this selection", SwErrors.swUnknownError)
            out = {}
            u = unit or self._units.default_unit.value
            for prop, kind in (("Distance", "L"), ("NormalDistance", "L"), ("CenterDistance", "L"),
                               ("Length", "L"), ("Radius", "L"), ("Diameter", "L"), ("Area", "A"),
                               ("Angle", "ang")):
                v = cu.try_call(m, prop)
                if not isinstance(v, (int, float)) or v < 0 or v == -1:
                    continue
                if kind == "L":
                    out[prop] = round(self._units.from_meters(v, unit), 4)
                elif kind == "A":
                    out[prop] = round(v / self._units.to_meters(1.0, unit) ** 2, 4)
                else:
                    out["Angle_deg"] = round(math.degrees(v), 4)
            doc.ClearSelection2(True)
            return self._result(True, ", ".join(f"{k}={v}" for k, v in out.items()) or "No values",
                                SwErrors.swSuccess, {"values": out, "unit": u})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"measure error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
