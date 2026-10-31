"""
Assembly additions
------------------
Move / rotate, fix / float, suppress, show / hide, replace components;
component linear / circular pattern; mate listing with errors; interference
detection; exploded view.

SOLIDWORKS 2026 type-library facts used:
  IComponent2.Transform2 (get/put IMathTransform), IMathTransform.ArrayData (get/put)
  IComponent2.SetSuppression2(State) — swComponentSuppressed=0, swComponentResolved=3
  IAssemblyDoc.FixComponent() / UnfixComponent() on the selection
  IAssemblyDoc.ReplaceComponents2(FileName, ConfigName, ReplaceAllInstance, UseConfigChoice, ReAttachMates)
  IAssemblyDoc.InterferenceDetectionManager -> GetInterferences() -> IInterference(Volume, Components)
  IAssemblyDoc.CreateExplodedView(); IConfiguration.AddExplodeStep2(ExplDist, ExplDirIndex,
      ReverseDir, ExplAng, RotAxisIndex, ReverseAng, RotateAboutOrigin, AutoSpace, Error)
      ExplDirIndex: 0=X, 1=Y, 2=Z of the assembly
  swMateType_e: 0 coincident ... 6 angle, 8 symmetric, 10 gear, 11 width, 16 lock, 17 screw, 22 hinge, 23 slider
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_MATE_NAMES = {0: "coincident", 1: "concentric", 2: "perpendicular", 3: "parallel", 4: "tangent",
               5: "distance", 6: "angle", 8: "symmetric", 9: "cam", 10: "gear", 11: "width",
               12: "lock_to_sketch", 13: "rack_pinion", 15: "path", 16: "lock", 17: "screw",
               18: "linear_coupler", 19: "universal_joint", 20: "coordinate", 21: "slot",
               22: "hinge", 23: "slider", 24: "profile_center", 25: "magnetic"}
_AXIS = {"x": 0, "y": 1, "z": 2}


def _rot(axis: str, ang: float):
    c, s = math.cos(ang), math.sin(ang)
    if axis == "x":
        return [[1, 0, 0], [0, c, s], [0, -s, c]]
    if axis == "y":
        return [[c, 0, -s], [0, 1, 0], [s, 0, c]]
    return [[c, s, 0], [-s, c, 0], [0, 0, 1]]


class AssemblyPlusOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, _require_assembly(),
    _select_ref(), _asm_title_no_ext()"""

    def _component(self, doc, name: str):
        for c in cu.as_list(doc.GetComponents(False)):
            if str(cu.try_call(c, "Name2", default="")) == name:
                return c
        return None

    def _select_component(self, doc, comp, append: bool = False, mark: int = 0) -> bool:
        """
        Select a component. With a mark, SelectByID2 is used: IComponent2.Select4
        ignores marks, and e.g. explode steps need components at mark 1 (SW 2026).
        """
        name = f"{cu.try_call(comp, 'Name2')}@{self._asm_title_no_ext(doc)}"
        if mark and cu.select_by_id(doc, name, "COMPONENT", 0, 0, 0, append, mark):
            return True
        try:
            if comp.Select4(append, cu.nothing(), False):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Select4 component failed: {e}")
        return cu.select_by_id(doc, name, "COMPONENT", 0, 0, 0, append, mark)

    def _need_components(self, doc, names: List[str]):
        comps = []
        for n in names:
            c = self._component(doc, n)
            if c is None:
                raise ValueError(f"Component '{n}' not found (list_components)")
            comps.append(c)
        return comps

    # ------------------------------------------------------------------

    def move_component(self, name: str, dx: float = 0, dy: float = 0, dz: float = 0,
                       rotate_axis: str = None, rotate_angle: float = 0.0, unit: str = None) -> Dict:
        """
        Translate (and optionally rotate about the assembly X/Y/Z axis through the
        component origin) a component that is not fixed or fully mated.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            comp = self._need_components(doc, [name])[0]
            if cu.try_call(comp, "IsFixed", default=False):
                return self._result(False, f"{name} is fixed; fix_component(fixed=false) first",
                                    SwErrors.swInvalidInput)
            xf = cu.call(comp, "Transform2")
            a = [float(v) for v in cu.as_list(cu.call(xf, "ArrayData"))]
            if rotate_axis and rotate_angle:
                R = [a[0:3], a[3:6], a[6:9]]
                M = _rot(rotate_axis.lower(), math.radians(rotate_angle))
                Rn = [[sum(R[i][k] * M[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
                a[0:9] = [v for row in Rn for v in row]
            L = lambda v: self._units.to_meters(v, unit)   # noqa: E731
            a[9] += L(dx)
            a[10] += L(dy)
            a[11] += L(dz)
            xf.ArrayData = cu.double_array(a)
            comp.Transform2 = xf
            cu.rebuild(doc)
            after = [round(self._units.from_meters(float(v), unit), 4)
                     for v in cu.as_list(cu.call(cu.call(comp, "Transform2"), "ArrayData"))[9:12]]
            return self._result(True, f"{name} origin now at {after}", SwErrors.swSuccess,
                                {"origin": after, "unit": unit or self._units.default_unit.value,
                                 "note": "mates win on rebuild: a fully mated component snaps back"})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"move_component error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def fix_component(self, names: List[str], fixed: bool = True) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            comps = self._need_components(doc, names)
            doc.ClearSelection2(True)
            for i, c in enumerate(comps):
                self._select_component(doc, c, i > 0)
            (doc.FixComponent if fixed else doc.UnfixComponent)()
            doc.ClearSelection2(True)
            state = {n: bool(cu.try_call(c, "IsFixed", default=False)) for n, c in zip(names, comps)}
            ok = all(v == fixed for v in state.values())
            return self._result(ok, f"{'Fixed' if fixed else 'Floating'}: {names}",
                                SwErrors.swSuccess if ok else SwErrors.swFeatureError, {"fixed": state})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def set_component_state(self, names: List[str], suppressed: bool = None, visible: bool = None) -> Dict:
        """Suppress / resolve and/or hide / show components."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            comps = self._need_components(doc, names)
            for c in comps:
                if suppressed is not None:
                    c.SetSuppression2(0 if suppressed else 3)
                if visible is not None:
                    c.Visible = 1 if visible else 0
            cu.rebuild(doc)
            return self._result(True, f"{names}: " + ", ".join(
                x for x in (None if suppressed is None else ("suppressed" if suppressed else "resolved"),
                            None if visible is None else ("visible" if visible else "hidden")) if x),
                SwErrors.swSuccess)
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def replace_component(self, name: str, filepath: str, all_instances: bool = False,
                          reattach_mates: bool = True) -> Dict:
        import os
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            path = os.path.abspath(os.path.expanduser(filepath))
            if not os.path.isfile(path):
                return self._result(False, f"File not found: {path}", SwErrors.swFileNotFoundError)
            comp = self._need_components(doc, [name])[0]
            doc.ClearSelection2(True)
            self._select_component(doc, comp)
            ok = doc.ReplaceComponents2(path, "", bool(all_instances), 0, bool(reattach_mates))
            cu.rebuild(doc)
            return self._result(bool(ok), f"Replaced {name} with {os.path.basename(path)}" if ok
                                else "Replace failed", SwErrors.swSuccess if ok else SwErrors.swFeatureError)
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------

    def component_pattern(self, components: List[str], kind: str = "linear", direction: Dict = None,
                          count: int = 3, spacing: float = 20.0, axis: Dict = None,
                          total_angle: float = 360.0, unit: str = None) -> Dict:
        """
        Linear (direction = edge/axis/plane ref, spacing) or circular (axis ref,
        total_angle, equal spacing) pattern of components.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            comps = self._need_components(doc, components)
            before = {str(cu.try_call(c, "Name2")) for c in cu.as_list(doc.GetComponents(True))}
            fm = doc.FeatureManager
            for comp_mark in (1, 4):                      # SW versions differ on the seed mark
                doc.ClearSelection2(True)
                ref = direction if kind == "linear" else axis
                if not ref:
                    return self._result(False, f"{kind} pattern needs {'direction' if kind == 'linear' else 'axis'}",
                                        SwErrors.swInvalidInput)
                if not self._select_ref(doc, ref, True, 2 if comp_mark == 1 else 1, unit):
                    return self._result(False, f"Could not select {ref}", SwErrors.swSelectionError)
                for c in comps:
                    self._select_component(doc, c, True, comp_mark)
                if kind == "linear":
                    feat = cu.try_call(fm, "FeatureLinearPattern5", int(count), self._units.to_meters(spacing, unit),
                                       1, 0.0, False, False, "NULL", "NULL", False, False, False, False,
                                       False, False, False, False, False, False, 0.0, 0.0, False, False)
                else:
                    feat = cu.try_call(fm, "FeatureCircularPattern5", int(count), math.radians(total_angle),
                                       False, "NULL", False, True, False, False, False, False, 1, 0.0,
                                       "NULL", False)
                after = {str(cu.try_call(c, "Name2")) for c in cu.as_list(doc.GetComponents(True))}
                new = sorted(after - before)
                if feat or new:
                    return self._result(True, f"{kind} component pattern: {len(new)} new instance(s)",
                                        SwErrors.swSuccess, {"feature": str(cu.try_call(feat, "Name", default="")),
                                                             "new_components": new})
            return self._result(False, "Component pattern failed", SwErrors.swFeatureError)
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"component_pattern error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------

    def list_mates(self) -> Dict:
        """Mates with type, components, and error state (over-defined / not solved)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            mates = []
            feat = cu.call(doc, "FirstFeature")
            while feat is not None:
                if str(cu.try_call(feat, "GetTypeName2", default="")) == "MateGroup":
                    sub = cu.try_call(feat, "GetFirstSubFeature")
                    while sub is not None:
                        m = cu.try_call(sub, "GetSpecificFeature2")
                        rec = {"name": str(cu.try_call(sub, "Name", default="")),
                               "suppressed": bool(cu.try_call(sub, "IsSuppressed", default=False))}
                        t = cu.try_call(m, "Type")
                        if t is not None:
                            rec["type"] = _MATE_NAMES.get(int(t), int(t))
                            comps = []
                            for i in range(int(cu.try_call(m, "GetMateEntityCount", default=0) or 0)):
                                me = cu.try_call(m, "MateEntity", i)
                                rc = cu.try_call(me, "ReferenceComponent")
                                comps.append(str(cu.try_call(rc, "Name2", default="(assembly)")) if rc else "(assembly)")
                            rec["components"] = comps
                        code = cu.try_call(sub, "GetErrorCode2", cu.byref_bool(False))
                        if isinstance(code, tuple):
                            code = code[0]
                        if code:
                            rec["error_code"] = int(code)
                        mates.append(rec)
                        sub = cu.try_call(sub, "GetNextSubFeature")
                feat = cu.try_call(feat, "GetNextFeature")
            errs = [m for m in mates if m.get("error_code")]
            return self._result(True, f"{len(mates)} mate(s)" + (f", {len(errs)} with errors" if errs else ""),
                                SwErrors.swSuccess, {"mates": mates})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"list_mates error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def check_interference(self, treat_coincidence: bool = False, unit: str = None) -> Dict:
        """All interferences in the active assembly with the components and volume."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            mgr = cu.call(doc, "InterferenceDetectionManager")
            try:
                mgr.TreatCoincidenceAsInterference = bool(treat_coincidence)
            except Exception:  # noqa: BLE001
                pass
            items = []
            for it in cu.as_list(cu.call(mgr, "GetInterferences")):
                comps = [str(cu.try_call(c, "Name2", default="")) for c in cu.as_list(cu.try_call(it, "Components"))]
                vol = float(cu.try_call(it, "Volume", default=0.0) or 0.0)
                items.append({"components": comps,
                              "volume": round(vol / self._units.to_meters(1.0, unit) ** 3, 4)})
            cu.try_call(mgr, "Done")
            u = unit or self._units.default_unit.value
            return self._result(True, f"{len(items)} interference(s)", SwErrors.swSuccess,
                                {"interferences": items, "volume_unit": f"{u}^3"})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"check_interference error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def create_exploded_view(self, steps: List[Dict], unit: str = None) -> Dict:
        """
        steps = [{"components": ["Part1-1"], "direction": "x|y|z", "distance": 50,
                  "reverse": false}, ...] — distances in `unit`, along assembly axes.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            if not steps:
                return self._result(False, "Give at least one step", SwErrors.swInvalidInput)
            cfg = cu.call(doc.ConfigurationManager, "ActiveConfiguration")
            n0 = int(cu.try_call(cfg, "GetNumberOfExplodeSteps", default=0) or 0)
            if n0 == 0:
                cu.invoke_method(doc, "CreateExplodedView")
            done = []
            for i, st in enumerate(steps):
                comps = self._need_components(doc, st.get("components", []))
                dir_idx = _AXIS.get(str(st.get("direction", "z")).lower())
                if dir_idx is None:
                    return self._result(False, f"step {i}: direction must be x, y or z", SwErrors.swInvalidInput)
                doc.ClearSelection2(True)
                for j, c in enumerate(comps):
                    self._select_component(doc, c, j > 0, mark=1)     # explode needs mark 1
                e = cu.byref_int(0)
                step = cfg.AddExplodeStep2(self._units.to_meters(st.get("distance", 50), unit), dir_idx,
                                           bool(st.get("reverse", False)), 0.0, -1, False, False, False, e)
                code = getattr(e, "value", 0)
                done.append({"step": i, "ok": step is not None and not code, "error": code})
            doc.ClearSelection2(True)
            total = int(cu.try_call(cfg, "GetNumberOfExplodeSteps", default=0) or 0)
            ok = all(d["ok"] for d in done)
            return self._result(ok, f"Exploded view: {total} step(s)", SwErrors.swSuccess if ok else
                                SwErrors.swFeatureError, {"steps": done,
                                                          "errors": "0 ok, 2 no exploded view, 3 no components"})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"create_exploded_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
