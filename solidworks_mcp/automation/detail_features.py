"""
Rib, draft, Hole Wizard
-----------------------
SOLIDWORKS 2026 signatures:
  IFeatureManager.InsertRib(Is2Sided, ReverseThicknessDir, Thickness, ReferenceEdgeIndex,
      ReverseMaterialDir, IsDrafted, DraftOutward, DraftAngle, IsNormToSketch, IsDraftedFromWall)
  IFeatureManager.InsertMultiFaceDraft(Angle, FlipDir, EdgeDraft, PropType, IsStepDraft, IsBodyDraft)
      neutral plane mark 1, faces to draft mark 2
  IFeatureManager.HoleWizard5(GenericHoleType, StandardIndex, FastenerTypeIndex, SSize, EndType,
      Diameter, Depth, Length, Value1..Value12, ThreadClass, RevDir, FeatureScope, AutoSelect,
      AssemblyFeatureScope, AutoSelectComponents, PropagateFeatureToParts)   (27 args)
      The hole is placed at the pick point of the pre-selected face; extra
      locations are added as sketch points in the hole's placement sketch.

Enum values (swconst.tlb 2026): swWzdCounterBore=0, swWzdCounterSink=1, swWzdHole=2, swWzdTap=4;
swStandardISO=8; ISO fastener types: SocketHeadCap=139, SocketCTSKFlatHead=140, CTSKFlatHead=141,
DrillSizes=143, ScrewClearances=144, TapDrills=145, TappedHoleBottoming=146, TappedHole=147.
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

# kind -> (GenericHoleType, ISO fastener type)
_HOLE_KINDS = {
    "tapped": (4, 147),
    "tapped_bottoming": (4, 146),
    "clearance": (2, 144),
    "drill": (2, 143),
    "counterbore": (0, 139),
    "countersink": (1, 141),
    "countersink_socket": (1, 140),
}
_PROP = {"none": 0, "tangent": 1}


def _created(owner, doc, feat, before: str, type_prefix: str):
    """
    Some Insert* calls return None although the feature was built (seen with
    InsertRib on SW 2026). Fall back to the newest tree feature of the right type.
    """
    if feat:
        return feat
    last = owner._last_feature(doc)
    if last is not None and str(cu.try_call(last, "Name", default="")) != before \
            and str(cu.try_call(last, "GetTypeName2", default="")).startswith(type_prefix):
        return last
    return None


class DetailFeatureOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, _select_ref(),
    _close_and_select_sketch(), _filter_faces(), _face_records(), _select_record(), _last_feature()"""

    def rib(self, thickness: float, two_sided: bool = True, flip_material: bool = False,
            reverse_thickness: bool = False, draft_angle: float = 0.0, draft_outward: bool = False,
            normal_to_sketch: bool = False, unit: str = None) -> Dict:
        """Rib from the last sketch (an open contour touching the body)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            ok, sketch, msg = self._close_and_select_sketch(doc)
            if not ok:
                return self._result(False, f"Rib needs a sketch: {msg}", SwErrors.swFeatureError)
            t = self._units.to_meters(thickness, unit)
            drafted = bool(draft_angle)
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            feat = doc.FeatureManager.InsertRib(two_sided, reverse_thickness, t, 0, flip_material,
                                                drafted, draft_outward, math.radians(draft_angle or 0),
                                                normal_to_sketch, False)
            feat = _created(self, doc, feat, before, "Rib")
            if not feat:
                return self._result(False,
                    f"Rib failed on '{sketch}'. The contour must reach the walls; try flip_material=true.",
                    SwErrors.swFeatureError)
            return self._result(True, f"Rib t={thickness} from {sketch} → {feat.Name}", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "sketch": sketch})
        except Exception as e:
            logger.error(f"rib error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def draft(self, angle: float, neutral: Dict, face_indices: List[int] = None,
              face_normal: str = None, face_type: str = None, min_area: float = None,
              flip: bool = False, propagation: str = "none", unit: str = None) -> Dict:
        """Neutral-plane draft on faces chosen by index or filter (e.g. face_normal='x')."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not (face_indices or face_normal or face_type):
                return self._result(False, "Choose faces: face_indices, face_normal or face_type",
                                    SwErrors.swInvalidInput)
            faces = self._filter_faces(self._face_records(doc), face_indices, face_type, face_normal,
                                       None, min_area, unit)
            if not faces:
                return self._result(False, "No faces match", SwErrors.swSelectionError)
            # Neutral: {"face_normal": "-y"} = largest planar face with that outward normal.
            # A model face is more reliable than a reference plane (SW 2026: drafting faces
            # bounded by tangent fillets failed with 'Top Plane' but worked with the bottom face).
            neutral_rec = None
            if isinstance(neutral, dict) and "face_normal" in neutral:
                cands = self._filter_faces(self._face_records(doc), None, "plane",
                                           neutral["face_normal"], None, None, unit)
                if not cands:
                    return self._result(False, f"No planar face with normal {neutral['face_normal']}",
                                        SwErrors.swSelectionError)
                neutral_rec = max(cands, key=lambda r: r.get("area", 0))

            def select_neutral():
                if neutral_rec is not None:
                    return self._select_record(doc, neutral_rec, "FACE", True, 1)
                return self._select_ref(doc, neutral, True, 1, unit)

            doc.ClearSelection2(True)
            if not select_neutral():
                return self._result(False, f"Could not select neutral {neutral}", SwErrors.swSelectionError)
            sel = [r["index"] for r in faces if self._select_record(doc, r, "FACE", True, 2)]
            # Faces bounded by tangent fillets only draft with tangent propagation, and the
            # pull direction depends on the neutral face normal: retry those two variants.
            attempts = [(flip, _PROP.get(propagation, 0))]
            if propagation != "tangent":
                attempts.append((flip, _PROP["tangent"]))
            attempts.append((not flip, attempts[-1][1]))
            feat, used = None, None
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            for fl, pr in attempts:
                if used is not None:            # reselect: a failed call can clear the selection
                    doc.ClearSelection2(True)
                    select_neutral()
                    for r in faces:
                        self._select_record(doc, r, "FACE", True, 2)
                used = (fl, pr)
                feat = doc.FeatureManager.InsertMultiFaceDraft(math.radians(angle), fl, False, pr, False, False)
                feat = _created(self, doc, feat, before, "Draft")
                if feat:
                    break
            if not feat:
                hint = "" if neutral_rec is not None else " Try neutral={\"face_normal\": \"-y\"} (a model face)."
                return self._result(False, "Draft failed (faces must not be parallel to the neutral; "
                                    "fillets need tangent propagation)." + hint, SwErrors.swFeatureError,
                                    {"faces": sel})
            return self._result(True, f"Draft {angle}° on {len(sel)} face(s) → {feat.Name}", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "faces": sel, "flipped": used[0],
                                 "propagation": "tangent" if used[1] == 1 else "none"})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"draft error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------

    def _hole_sketch(self, doc, hole_feat):
        """
        Placement sketch of a Hole Wizard feature. A hole feature owns two
        sketches: the 2D placement sketch (points only, no segments) and the
        hole profile sketch (lines/arcs). Pick the one without segments.
        """
        best = None
        sub = cu.try_call(hole_feat, "GetFirstSubFeature")
        while sub is not None:
            if str(cu.try_call(sub, "GetTypeName2", default="")) == "ProfileFeature":
                sk = cu.try_call(sub, "GetSpecificFeature2")
                nseg = len(cu.as_list(cu.try_call(sk, "GetSketchSegments"))) if sk else 999
                if best is None or nseg < best[2]:
                    best = (sub, sk, nseg)
            sub = cu.try_call(sub, "GetNextSubFeature")
        return (best[0], best[1]) if best else (None, None)

    _HOLE_PROPS = ("TapDrillDiameter", "TapDrillDepth", "ThreadDiameter", "ThreadDepth",
                   "ThruHoleDiameter", "ThruHoleDepth", "CounterBoreDiameter", "CounterBoreDepth",
                   "CounterSinkDiameter", "Diameter", "Depth")

    def _hole_props(self, d, unit=None) -> Dict:
        out = {}
        for p in self._HOLE_PROPS:
            v = cu.try_call(d, p)
            if isinstance(v, (int, float)) and v > 0:
                out[p] = round(self._units.from_meters(float(v), unit), 4)
        return out

    def hole_wizard(self, size: str, points: List[List[float]], kind: str = "tapped",
                    depth: float = None, through_all: bool = False, thread_depth: float = None,
                    standard: str = "ISO", unit: str = None) -> Dict:
        """
        ISO Hole Wizard holes. `points` = [[x, y, z], ...] model coordinates ON one
        planar face (the first point picks the face). size e.g. 'M3x0.5' (tapped) or
        'M3' (clearance/counterbore/countersink). depth / thread_depth in `unit`.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if standard.upper() != "ISO":
                return self._result(False, "Only standard='ISO' is mapped", SwErrors.swInvalidInput)
            if kind not in _HOLE_KINDS:
                return self._result(False, f"kind must be one of {sorted(_HOLE_KINDS)}", SwErrors.swInvalidInput)
            if not points:
                return self._result(False, "Give at least one point [x, y, z] on the target face",
                                    SwErrors.swInvalidInput)
            if not through_all and depth is None:
                return self._result(False, "Give depth or through_all=true", SwErrors.swInvalidInput)

            pts = [[self._units.to_meters(v, unit) for v in p[:3]] for p in points]
            doc.ClearSelection2(True)
            if not cu.select_by_id(doc, "", "FACE", pts[0][0], pts[0][1], pts[0][2], False, 0):
                return self._result(False, f"No face at {points[0]}", SwErrors.swSelectionError)

            gtype, fastener = _HOLE_KINDS[kind]
            end = 1 if through_all else 0
            dep = 0.0 if through_all else self._units.to_meters(depth, unit)
            tdep = self._units.to_meters(thread_depth, unit) if thread_depth else (dep * 0.8 if dep else 0.0)
            v = [-1.0] * 12
            if gtype == 4:            # tapped: Value1 = thread depth
                v[0] = tdep if not through_all else -1.0
            before = str(cu.try_call(self._last_feature(doc), "Name", default=""))
            feat = doc.FeatureManager.HoleWizard5(gtype, 8, fastener, size, end, -1.0, dep, -1.0, *v,
                                                  "", False, True, True, False, False, False)
            feat = _created(self, doc, feat, before, "HoleWzd")
            if not feat:
                return self._result(False,
                    f"HoleWizard5 failed for {kind} {size}. Size must match the ISO table "
                    f"(tapped: 'M3x0.5', 'M4x0.7'; clearance/cbore/csk: 'M3', 'M4').",
                    SwErrors.swFeatureError)
            name = str(feat.Name)

            added = 0
            if len(pts) > 1:
                sub, sk = self._hole_sketch(doc, feat)
                if sk is None:
                    return self._result(True, f"{name} created at 1 point; could not open its sketch for "
                                        f"the other {len(pts) - 1}", SwErrors.swSuccess, {"feature": name})
                doc.ClearSelection2(True)
                sub.Select2(False, 0)
                doc.EditSketch()
                sm = doc.SketchManager
                for p in pts[1:]:
                    x, y, _ = cu.model_to_sketch(sk, p)
                    if sm.CreatePoint(x, y, 0.0) is not None:
                        added += 1
                sm.InsertSketch(True)
                cu.rebuild(doc)

            d = cu.try_call(cu.find_feature(doc, name), "GetDefinition")
            info = {"feature": name, "holes": 1 + added, "kind": kind, "size": size,
                    "fastener": str(cu.try_call(d, "FastenerType", default="")),
                    "dimensions": self._hole_props(d, unit),
                    "unit": unit or self._units.default_unit.value}
            errors = self._rebuild_errors(doc)
            return self._result(not errors, f"{name}: {info['holes']} × {kind} {size}"
                                + (f" | rebuild errors {errors}" if errors else ""),
                                SwErrors.swSuccess if not errors else SwErrors.swFeatureError, info)
        except Exception as e:
            logger.error(f"hole_wizard error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
