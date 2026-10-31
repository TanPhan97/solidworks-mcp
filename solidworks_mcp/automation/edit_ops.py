"""
Edit existing features through their feature-data definition
-------------------------------------------------------------
IFeature.GetDefinition -> I*FeatureData -> AccessSelections(TopDoc, Component)
-> change -> IFeature.ModifyDefinition(Data, TopDoc, Component).

Members used (SOLIDWORKS 2026 type library):
  IExtrudeFeatureData2 : GetDepth/SetDepth(Forward, Depth), GetEndCondition/SetEndCondition,
                         SetDraftAngle(Forward, Angle), SetDraftWhileExtruding(Forward, b),
                         ReverseDirection, BothDirections
  IRevolveFeatureData2 : GetRevolutionAngle/SetRevolutionAngle(Forward, Angle)
  ISimpleFilletFeatureData2 : DefaultRadius
  IChamferFeatureData2 : GetEdgeChamferDistance/SetEdgeChamferDistance(Side, D), EdgeChamferAngle
  IShellFeatureData    : Thickness
  ILinearPatternFeatureData   : D1TotalInstances, D1Spacing, D1ReverseDirection, D2...
  ICircularPatternFeatureData : TotalInstances, Spacing, EqualSpacing, ReverseDirection
  IRibFeatureData2     : Thickness
  IWizardHoleFeatureData2 : Diameter, Depth, ThreadDepth (read only here)
"""

import math
import logging
import traceback
from typing import Dict, Any

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_EXTRUDE = {"Extrusion", "Boss", "BossThin", "Cut", "ICE", "CutThin", "Extrusion2"}
_REVOLVE = {"Revolution", "RevCut", "RevolutionThin", "RevCutThin"}
_END = {"blind": 0, "through_all": 1, "through_next": 2, "up_to_vertex": 3, "up_to_surface": 4,
        "offset_from_surface": 5, "mid_plane": 6, "up_to_body": 7, "through_all_both": 9,
        "up_to_next": 11}
_END_NAME = {v: k for k, v in _END.items()}


class EditOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _rebuild_errors()"""

    def _kind(self, type_name: str) -> str:
        if type_name in _EXTRUDE:
            return "extrude"
        if type_name in _REVOLVE:
            return "revolve"
        return {"Fillet": "fillet", "Chamfer": "chamfer", "Shell": "shell", "LPattern": "linear_pattern",
                "CirPattern": "circular_pattern", "Rib": "rib", "HoleWzd": "hole"}.get(type_name, "")

    def _read_params(self, kind: str, d, unit=None) -> Dict[str, Any]:
        L = lambda v: None if v is None else round(self._units.from_meters(float(v), unit), 6)  # noqa: E731
        A = lambda v: None if v is None else round(math.degrees(float(v)), 6)                 # noqa: E731
        g = cu.try_call
        if kind == "extrude":
            p = {"depth": L(g(d, "GetDepth", True)),
                 "end_condition": _END_NAME.get(g(d, "GetEndCondition", True), g(d, "GetEndCondition", True)),
                 "both_directions": g(d, "BothDirections"), "reverse": g(d, "ReverseDirection")}
            if p["both_directions"]:
                p["depth2"] = L(g(d, "GetDepth", False))
                p["end_condition2"] = _END_NAME.get(g(d, "GetEndCondition", False))
            return p
        if kind == "revolve":
            return {"angle": A(g(d, "GetRevolutionAngle", True)), "angle2": A(g(d, "GetRevolutionAngle", False)),
                    "reverse": g(d, "ReverseDirection")}
        if kind == "fillet":
            return {"radius": L(g(d, "DefaultRadius"))}
        if kind == "chamfer":
            return {"distance": L(g(d, "GetEdgeChamferDistance", 0)), "angle": A(g(d, "EdgeChamferAngle"))}
        if kind == "shell":
            return {"thickness": L(g(d, "Thickness"))}
        if kind == "linear_pattern":
            return {"count1": g(d, "D1TotalInstances"), "spacing1": L(g(d, "D1Spacing")),
                    "reverse1": g(d, "D1ReverseDirection"), "count2": g(d, "D2TotalInstances"),
                    "spacing2": L(g(d, "D2Spacing")), "reverse2": g(d, "D2ReverseDirection")}
        if kind == "circular_pattern":
            return {"count": g(d, "TotalInstances"), "angle": A(g(d, "Spacing")),
                    "equal_spacing": g(d, "EqualSpacing"), "reverse": g(d, "ReverseDirection")}
        if kind == "rib":
            return {"thickness": L(g(d, "Thickness"))}
        if kind == "hole":
            out = {"size": g(d, "FastenerSize"), "fastener": g(d, "FastenerType")}
            for p in ("TapDrillDiameter", "TapDrillDepth", "ThreadDepth", "ThruHoleDiameter",
                      "ThruHoleDepth", "CounterBoreDiameter", "CounterBoreDepth", "Diameter", "Depth"):
                v = g(d, p)
                if isinstance(v, (int, float)) and v > 0:
                    out[p] = L(v)
            return out
        return {}

    def get_feature_info(self, name: str, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            feat = cu.find_feature(doc, name)
            if feat is None:
                return self._result(False, f"Feature '{name}' not found", SwErrors.swInvalidInput)
            tname = str(cu.call(feat, "GetTypeName2"))
            kind = self._kind(tname)
            params = {}
            if kind:
                d = cu.call(feat, "GetDefinition")
                params = self._read_params(kind, d, unit)
            return self._result(True, f"{name}: {tname}" + (f" ({kind})" if kind else " (not editable here)"),
                                SwErrors.swSuccess,
                                {"name": name, "type": tname, "kind": kind or None, "params": params,
                                 "suppressed": bool(cu.try_call(feat, "IsSuppressed", default=False)),
                                 "unit": unit or self._units.default_unit.value})
        except Exception as e:
            logger.error(f"get_feature_info error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def edit_feature(self, name: str, params: Dict[str, Any], unit: str = None) -> Dict:
        """
        Change feature parameters. Lengths in `unit`, angles in degrees.
          extrude : depth, depth2, end_condition(2), reverse, draft_angle
          revolve : angle, angle2
          fillet  : radius        chamfer: distance, angle      shell/rib: thickness
          linear_pattern  : count1, spacing1, reverse1, count2, spacing2, reverse2
          circular_pattern: count, angle, equal_spacing, reverse
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            feat = cu.find_feature(doc, name)
            if feat is None:
                return self._result(False, f"Feature '{name}' not found", SwErrors.swInvalidInput)
            tname = str(cu.call(feat, "GetTypeName2"))
            kind = self._kind(tname)
            if not kind or kind == "hole":
                return self._result(False, f"Editing '{tname}' is not supported; use set_dimension "
                                    f"with list_dimensions", SwErrors.swInvalidInput)
            if not params:
                return self._result(False, "params is empty", SwErrors.swInvalidInput)

            L = lambda v: self._units.to_meters(float(v), unit)   # noqa: E731
            A = lambda v: math.radians(float(v))                  # noqa: E731
            d = cu.call(feat, "GetDefinition")
            before = self._read_params(kind, d, unit)
            if not cu.try_call(d, "AccessSelections", doc, cu.nothing(), default=False):
                cu.try_call(d, "AccessSelections", doc, None)

            applied, unknown = [], []

            def put(attr, value):
                setattr(d, attr, value)

            try:
                for k, v in params.items():
                    if kind == "extrude":
                        if k == "depth":
                            d.SetDepth(True, L(v))
                        elif k == "depth2":
                            d.SetDepth(False, L(v))
                        elif k in ("end_condition", "end_condition2"):
                            if v not in _END:
                                raise ValueError(f"end_condition must be one of {sorted(_END)}")
                            d.SetEndCondition(k == "end_condition", _END[v])
                        elif k == "reverse":
                            put("ReverseDirection", bool(v))
                        elif k == "both_directions":
                            put("BothDirections", bool(v))
                        elif k == "draft_angle":
                            d.SetDraftWhileExtruding(True, float(v) != 0)
                            d.SetDraftAngle(True, A(v))
                        else:
                            unknown.append(k); continue
                    elif kind == "revolve":
                        if k in ("angle", "angle2"):
                            d.SetRevolutionAngle(k == "angle", A(v))
                        elif k == "reverse":
                            put("ReverseDirection", bool(v))
                        else:
                            unknown.append(k); continue
                    elif kind == "fillet" and k == "radius":
                        put("DefaultRadius", L(v))
                    elif kind == "chamfer" and k == "distance":
                        d.SetEdgeChamferDistance(0, L(v))
                    elif kind == "chamfer" and k == "angle":
                        put("EdgeChamferAngle", A(v))
                    elif kind in ("shell", "rib") and k == "thickness":
                        put("Thickness", L(v))
                    elif kind == "linear_pattern" and k in ("count1", "count2"):
                        put("D1TotalInstances" if k == "count1" else "D2TotalInstances", int(v))
                    elif kind == "linear_pattern" and k in ("spacing1", "spacing2"):
                        put("D1Spacing" if k == "spacing1" else "D2Spacing", L(v))
                    elif kind == "linear_pattern" and k in ("reverse1", "reverse2"):
                        put("D1ReverseDirection" if k == "reverse1" else "D2ReverseDirection", bool(v))
                    elif kind == "circular_pattern" and k == "count":
                        put("TotalInstances", int(v))
                    elif kind == "circular_pattern" and k == "angle":
                        put("Spacing", A(v))
                    elif kind == "circular_pattern" and k == "equal_spacing":
                        put("EqualSpacing", bool(v))
                    elif kind == "circular_pattern" and k == "reverse":
                        put("ReverseDirection", bool(v))
                    else:
                        unknown.append(k); continue
                    applied.append(k)
            except ValueError as e:
                cu.try_call(d, "ReleaseSelectionAccess")
                return self._result(False, str(e), SwErrors.swInvalidInput)

            if not applied:
                cu.try_call(d, "ReleaseSelectionAccess")
                return self._result(False, f"No supported params for {kind}: {unknown}", SwErrors.swInvalidInput,
                                    {"supported_now": list(before)})
            ok = cu.try_call(feat, "ModifyDefinition", d, doc, cu.nothing(), default=None)
            if ok is None:
                ok = cu.try_call(feat, "ModifyDefinition", d, doc, None, default=False)
            if not ok:
                cu.try_call(d, "ReleaseSelectionAccess")
                return self._result(False, f"ModifyDefinition rejected {applied} on {name}",
                                    SwErrors.swFeatureError, {"before": before})
            cu.rebuild(doc)
            after = self._read_params(kind, cu.call(cu.find_feature(doc, name), "GetDefinition"), unit)
            errors = self._rebuild_errors(doc)
            return self._result(not errors, f"{name}: updated {applied}"
                                + (f" | ignored {unknown}" if unknown else "")
                                + (f" | rebuild errors {errors}" if errors else ""),
                                SwErrors.swSuccess if not errors else SwErrors.swFeatureError,
                                {"before": before, "after": after, "errors": errors})
        except Exception as e:
            logger.error(f"edit_feature error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
