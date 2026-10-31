"""
Loft and sweep (boss and cut)
-----------------------------
Signatures from the SOLIDWORKS 2026 type library:
  InsertProtrusionBlend2 (18): Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
      StartMatchingType, EndMatchingType, StartTangentLength, EndTangentLength,
      StartTangentDir, EndTangentDir, IsThinBody, Thickness1, Thickness2, ThinType,
      Merge, UseFeatScope, UseAutoSelect, GuideCurveInfluence
  InsertCutBlend (12): Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
      StartMatchingType, EndMatchingType, IsThinBody, Thickness1, Thickness2, ThinType,
      UseFeatScope, UseAutoSelect
  InsertProtrusionSwept4 (20) / InsertCutSwept5 (22) — see calls below.

Selection marks: loft profiles = 1, guide curves = 2;
                 sweep profile = 1, guide curves = 2, path = 4.
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_TANGENCY = {"none": 0, "normal": 1, "direction": 2, "all_faces": 3}   # swTangencyType_e


class SweepLoftOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _select_ref(), _last_feature()"""

    def _exit_sketch(self, doc):
        cu.close_active_sketch(doc)

    def _select_curve(self, doc, spec, mark: int, unit=None) -> bool:
        """Sketch name (str) or a reference spec dict (edge_index, name/type...)."""
        if isinstance(spec, str):
            return cu.select_by_id(doc, spec, "SKETCH", 0, 0, 0, True, mark)
        return self._select_ref(doc, spec, True, mark, unit)

    def _new_feature_name(self, doc, before: str) -> str:
        last = self._last_feature(doc)
        name = str(cu.try_call(last, "Name", default="")) if last is not None else ""
        return name if name and name != before else ""

    # ------------------------------------------------------------------

    def loft(self, profiles: List[str], guides: List = None, cut: bool = False,
             closed: bool = False, start_tangency: str = "none", end_tangency: str = "none",
             thin_thickness: float = None, merge: bool = True, unit: str = None) -> Dict:
        """Loft through >= 2 profile sketches (in order), optional guide curves."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not profiles or len(profiles) < 2:
                return self._result(False, "Give at least 2 profile sketch names, in order",
                                    SwErrors.swInvalidInput)
            self._exit_sketch(doc)
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            doc.ClearSelection2(True)
            for p in profiles:
                if not self._select_curve(doc, p, 1, unit):
                    return self._result(False, f"Profile '{p}' not found", SwErrors.swSelectionError)
            for g in guides or []:
                if not self._select_curve(doc, g, 2, unit):
                    return self._result(False, f"Guide '{g}' not found", SwErrors.swSelectionError)

            st, en = _TANGENCY.get(start_tangency, 0), _TANGENCY.get(end_tangency, 0)
            thin = thin_thickness is not None and thin_thickness > 0
            t = self._units.to_meters(thin_thickness, unit) if thin else 0.0
            fm = doc.FeatureManager
            if cut:
                feat = fm.InsertCutBlend(closed, False, False, 1.0, st, en, thin, t, t, 0, True, True)
            else:
                feat = fm.InsertProtrusionBlend2(closed, False, False, 1.0, st, en, 1.0, 1.0,
                                                 True, True, thin, t, t, 0, merge, True, True, 0)
            name = str(cu.try_call(feat, "Name", default="")) if feat else self._new_feature_name(doc, before)
            if not name:
                return self._result(False,
                    "Loft failed. Check: closed profiles on different planes, matching start points, "
                    "guides touch every profile.", SwErrors.swFeatureError)
            return self._result(True, f"{'Cut-' if cut else ''}Loft through {len(profiles)} profiles → {name}",
                                SwErrors.swSuccess, {"feature": name, "profiles": profiles,
                                                     "guides": guides or []})
        except Exception as e:
            logger.error(f"loft error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def sweep(self, path, profile: str = None, circular_diameter: float = None,
              guides: List = None, cut: bool = False, twist_angle: float = 0.0,
              keep_normal_constant: bool = False, thin_thickness: float = None,
              merge: bool = True, unit: str = None) -> Dict:
        """
        Sweep `profile` sketch (or a circle of `circular_diameter`) along `path`
        (sketch name or edge reference). twist_angle in degrees along the path.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not profile and not circular_diameter:
                return self._result(False, "Give profile (sketch name) or circular_diameter",
                                    SwErrors.swInvalidInput)
            self._exit_sketch(doc)
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            doc.ClearSelection2(True)
            if profile and not cu.select_by_id(doc, profile, "SKETCH", 0, 0, 0, True, 1):
                return self._result(False, f"Profile '{profile}' not found", SwErrors.swSelectionError)
            if not self._select_curve(doc, path, 4, unit):
                return self._result(False, f"Path {path!r} not found", SwErrors.swSelectionError)
            for g in guides or []:
                if not self._select_curve(doc, g, 2, unit):
                    return self._result(False, f"Guide '{g}' not found", SwErrors.swSelectionError)

            circ = bool(circular_diameter) and not profile
            dia = self._units.to_meters(circular_diameter, unit) if circ else 0.0
            if twist_angle:
                twist = 9 if keep_normal_constant else 8     # ...ConstantTwistAlongPath
            else:
                twist = 1 if keep_normal_constant else 0     # KeepNormalConstant / FollowPath
            tw = math.radians(twist_angle or 0.0)
            thin = thin_thickness is not None and thin_thickness > 0
            t = self._units.to_meters(thin_thickness, unit) if thin else 0.0
            fm = doc.FeatureManager
            if cut:
                feat = fm.InsertCutSwept5(False, True, twist, False, False, 0, 0, thin, t, t, 0, 0,
                                          True, True, tw, True, False, False, False, circ, dia, 0)
            else:
                feat = fm.InsertProtrusionSwept4(False, True, twist, False, False, 0, 0, thin, t, t, 0, 0,
                                                 merge, True, True, tw, True, circ, dia, 0)
            name = str(cu.try_call(feat, "Name", default="")) if feat else self._new_feature_name(doc, before)
            if not name:
                return self._result(False,
                    "Sweep failed. Check: profile is closed and pierces the path start; path has no "
                    "radius smaller than the profile; guides pierce the profile.", SwErrors.swFeatureError)
            what = f"Ø{circular_diameter}" if circ else profile
            return self._result(True, f"{'Cut-' if cut else ''}Sweep {what} along {path} → {name}",
                                SwErrors.swSuccess, {"feature": name})
        except Exception as e:
            logger.error(f"sweep error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
