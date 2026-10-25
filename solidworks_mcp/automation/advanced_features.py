"""
SolidWorks Advanced Feature Operations
--------------------------------------
Revolve / cut-revolve, shell, linear & circular pattern, mirror, reference plane.

Selection marks follow the SolidWorks API remarks for each call:
- Linear pattern : direction 1 = mark 1, direction 2 = mark 2, seed features = mark 4
- Circular pattern: axis = mark 1, seed features = mark 4
- Mirror         : mirror plane/face = mark 2, features = mark 1, bodies = mark 256
- Ref plane      : first reference = mark 0, second reference = mark 1

Parameter counts verified against IFeatureManager signatures:
FeatureRevolve2 (20), FeatureLinearPattern5 (22) / 4 (20),
FeatureCircularPattern5 (14) / 4 (7), InsertRefPlane (6).
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

# swRefPlaneReferenceConstraints_e
_RP_PARALLEL = 1
_RP_PERPENDICULAR = 2
_RP_COINCIDENT = 4
_RP_DISTANCE = 8
_RP_ANGLE = 16
_RP_MIDPLANE = 128
_RP_FLIP = 256


class AdvancedFeatureOperations:
    """
    Mixin. Requires: get_active_doc(), _result(), _units, app,
    _close_and_select_sketch() (FeatureOperations), _select_ref() (SelectionOperations),
    _filter_faces()/_face_records()/_select_record() (SelectionOperations)
    """

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _select_features(self, doc, names: List[str], mark: int) -> List[str]:
        """Append-select features by name with a mark. Returns names that failed."""
        failed = []
        for n in names:
            feat = cu.find_feature(doc, n)
            ok = False
            if feat is not None:
                try:
                    ok = bool(feat.Select2(True, mark))
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"Select2 {n} failed: {e}")
            if not ok:
                ok = cu.select_by_id(doc, n, "BODYFEATURE", 0, 0, 0, True, mark)
            if not ok:
                failed.append(n)
        return failed

    def _feature_name(self, feat) -> str:
        try:
            return str(feat.Name)
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # Revolve
    # ------------------------------------------------------------------

    def revolve_sketch(self, angle: float = 360.0, cut: bool = False,
                       mid_plane: bool = False, reverse: bool = False,
                       thin_thickness: float = None, axis: Dict = None,
                       unit: str = None) -> Dict:
        """
        Revolve the last sketch. Axis = the sketch centerline by default
        (draw_centerline). Optional `axis` reference spec for an external axis/edge.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not (0 < angle <= 360):
                return self._result(False, "angle must be in (0, 360]", SwErrors.swInvalidInput)

            ok, sketch_name, msg = self._close_and_select_sketch(doc)
            if not ok:
                return self._result(False, f"Revolve failed: {msg}", SwErrors.swFeatureError)

            ang = math.radians(angle)
            is_thin = thin_thickness is not None and thin_thickness > 0
            t = self._units.to_meters(thin_thickness, unit) if is_thin else 0.0
            dir1 = 6 if mid_plane else 0   # swEndCondMidPlane / swEndCondBlind

            def _call():
                return doc.FeatureManager.FeatureRevolve2(
                    True,        # SingleDir
                    True,        # IsSolid
                    is_thin,     # IsThin
                    cut,         # IsCut
                    reverse,     # ReverseDir
                    False,       # BothDirectionUpToSameEntity
                    dir1, 0,     # Dir1Type, Dir2Type
                    ang, 0.0,    # Dir1Angle, Dir2Angle (rad)
                    False, False,  # OffsetReverse1/2
                    0.0, 0.0,      # OffsetDistance1/2
                    0,             # ThinType (one direction)
                    t, t,          # ThinThickness1/2
                    True,          # Merge
                    False,         # UseFeatScope
                    True)          # UseAutoSelect

            feat = None
            if axis:
                # External axis: try the marks used by different SW versions.
                for axis_mark in (4, 16):
                    doc.ClearSelection2(True)
                    cu.select_by_id(doc, sketch_name, "SKETCH", 0, 0, 0, False, 0)
                    if not self._select_ref(doc, axis, True, axis_mark, unit):
                        return self._result(False, f"Could not select axis {axis}",
                                            SwErrors.swSelectionError)
                    feat, _ = cu.first_ok(_call, log_prefix="FeatureRevolve2")
                    if feat:
                        break
            else:
                feat, _ = cu.first_ok(_call, log_prefix="FeatureRevolve2")

            if not feat:
                return self._result(False,
                    f"Revolve failed on '{sketch_name}'. Requirements: closed profile, one "
                    f"centerline (or `axis` given), profile must not cross the axis"
                    + ("; cut needs an existing body" if cut else ""),
                    SwErrors.swFeatureError, {"sketch_name": sketch_name})

            kind = "Cut-Revolve" if cut else "Revolve"
            return self._result(True, f"{kind} {angle}° → {self._feature_name(feat)}",
                                SwErrors.swSuccess,
                                {"feature": self._feature_name(feat), "sketch": sketch_name,
                                 "angle_deg": angle, "mid_plane": mid_plane, "thin": is_thin})
        except Exception as e:
            logger.error(f"revolve error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def shell(self, thickness: float, face_indices: List[int] = None,
              face_normal: str = None, outward: bool = False, unit: str = None) -> Dict:
        """Shell with the given faces removed. No faces = closed hollow body."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            t = self._units.to_meters(thickness, unit)
            if t <= 0:
                return self._result(False, "thickness must be > 0", SwErrors.swInvalidInput)

            doc.ClearSelection2(True)
            removed = []
            if face_indices or face_normal:
                recs = self._filter_faces(self._face_records(doc), face_indices, None,
                                          face_normal, None, None, unit)
                if not recs:
                    return self._result(False, "No faces match for removal", SwErrors.swSelectionError)
                for r in recs:
                    if self._select_record(doc, r, "FACE", True, 0):
                        removed.append(r["index"])

            feat, used = cu.first_ok(
                lambda: doc.FeatureManager.InsertFeatureShell(t, outward),
                lambda: doc.InsertFeatureShell(t, outward),
                log_prefix="InsertFeatureShell")
            if not feat and used == -1:
                # ModelDoc2.InsertFeatureShell returns void on some versions
                last = self._last_feature(doc)
                if last and "Shell" in self._feature_type(last):
                    feat = last
            if not feat:
                return self._result(False,
                    "Shell failed: thickness too large for the geometry, or a removed face "
                    "is not adjacent to a valid wall", SwErrors.swFeatureError,
                    {"removed_faces": removed})
            unit_str = unit or self._units.default_unit.value
            return self._result(True, f"Shell t={thickness}{unit_str}, {len(removed)} face(s) removed",
                                SwErrors.swSuccess,
                                {"feature": self._feature_name(feat), "removed_faces": removed,
                                 "outward": outward})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"shell error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def _last_feature(self, doc):
        try:
            feat = cu.call(doc, "FirstFeature")
            last = None
            while feat is not None:
                last = feat
                feat = cu.call(feat, "GetNextFeature")
            return last
        except Exception:  # noqa: BLE001
            return None

    def _feature_type(self, feat) -> str:
        try:
            return str(cu.call(feat, "GetTypeName2"))
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # Linear pattern
    # ------------------------------------------------------------------

    def linear_pattern(self, features: List[str], direction1: Dict, count1: int,
                       spacing1: float, direction2: Dict = None, count2: int = 1,
                       spacing2: float = 0.0, flip1: bool = False, flip2: bool = False,
                       geometry_pattern: bool = False, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not features:
                return self._result(False, "features list is required", SwErrors.swInvalidInput)
            if count1 < 2 and count2 < 2:
                return self._result(False, "count1 or count2 must be >= 2", SwErrors.swInvalidInput)

            s1 = self._units.to_meters(spacing1, unit)
            s2 = self._units.to_meters(spacing2, unit) if direction2 else 0.0
            n2 = int(count2) if direction2 else 1

            doc.ClearSelection2(True)
            if not self._select_ref(doc, direction1, True, 1, unit):
                return self._result(False, f"Could not select direction1 {direction1}",
                                    SwErrors.swSelectionError)
            if direction2 and not self._select_ref(doc, direction2, True, 2, unit):
                return self._result(False, f"Could not select direction2 {direction2}",
                                    SwErrors.swSelectionError)
            failed = self._select_features(doc, features, 4)
            if failed:
                return self._result(False, f"Features not found: {failed}", SwErrors.swSelectionError)

            fm = doc.FeatureManager
            # 8 leading args + 10 booleans; LP5 appends (double, double, bool, bool),
            # LP4 appends (double, double)  ->  22 / 20 args
            common = (int(count1), s1, n2, s2, flip1, flip2, "NULL", "NULL",
                      geometry_pattern,  # GeometryPattern
                      False,             # VaryInstance
                      False, False,      # HasOffset1/2
                      False, False,      # CtrlByRefSurface1/2
                      False, False,      # OffsetReverse1/2
                      False, False)      # remaining flags (off)
            assert len(common) == 18
            feat, used = cu.first_ok(
                lambda: fm.FeatureLinearPattern5(*common, 0.0, 0.0, False, False),
                lambda: fm.FeatureLinearPattern4(*common, 0.0, 0.0),
                log_prefix="LinearPattern")
            if not feat:
                return self._result(False,
                    "Linear pattern failed. Check: direction is a linear edge / axis / planar face, "
                    "instances stay on the body, spacing direction (try flip1).",
                    SwErrors.swFeatureError)
            unit_str = unit or self._units.default_unit.value
            return self._result(True,
                f"Linear pattern {count1}×{spacing1}{unit_str}"
                + (f" / {n2}×{spacing2}{unit_str}" if direction2 else "")
                + f" → {self._feature_name(feat)}",
                SwErrors.swSuccess,
                {"feature": self._feature_name(feat),
                 "api_method": ["FeatureLinearPattern5", "FeatureLinearPattern4"][used]})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"linear_pattern error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # Circular pattern
    # ------------------------------------------------------------------

    def circular_pattern(self, features: List[str], axis: Dict, count: int,
                         angle: float = 360.0, equal_spacing: bool = True,
                         flip: bool = False, geometry_pattern: bool = False) -> Dict:
        """
        equal_spacing=True : `angle` is the total span (360 = full circle).
        equal_spacing=False: `angle` is the pitch between instances.
        Axis: cylindrical face (temporary axis), axis feature, linear edge.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not features or count < 2:
                return self._result(False, "features and count >= 2 are required",
                                    SwErrors.swInvalidInput)
            spacing = math.radians(angle)

            doc.ClearSelection2(True)
            if not self._select_ref(doc, axis, True, 1):
                return self._result(False, f"Could not select axis {axis}", SwErrors.swSelectionError)
            failed = self._select_features(doc, features, 4)
            if failed:
                return self._result(False, f"Features not found: {failed}", SwErrors.swSelectionError)

            fm = doc.FeatureManager
            feat, used = cu.first_ok(
                lambda: fm.FeatureCircularPattern5(
                    int(count), spacing, flip, "NULL", geometry_pattern, equal_spacing,
                    False,              # VaryInstance
                    False,              # SyncSubAssemblies
                    False,              # BDir2
                    False,              # BSymmetric
                    1, 0.0, "NULL",     # Number2, Spacing2, DName2
                    False),             # EqualSpacing2
                lambda: fm.FeatureCircularPattern4(
                    int(count), spacing, flip, "NULL", geometry_pattern, equal_spacing, False),
                log_prefix="CircularPattern")
            if not feat:
                return self._result(False,
                    "Circular pattern failed. Use a cylindrical face or axis as `axis`.",
                    SwErrors.swFeatureError)
            return self._result(True,
                f"Circular pattern {count}× over {angle}° → {self._feature_name(feat)}",
                SwErrors.swSuccess,
                {"feature": self._feature_name(feat),
                 "api_method": ["FeatureCircularPattern5", "FeatureCircularPattern4"][used]})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"circular_pattern error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # Mirror
    # ------------------------------------------------------------------

    def mirror(self, plane: Dict, features: List[str] = None, mirror_bodies: bool = False,
               merge: bool = True, geometry_pattern: bool = False) -> Dict:
        """Mirror features (default) or all solid bodies about a plane / planar face."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if not features and not mirror_bodies:
                return self._result(False, "Give features or set mirror_bodies=true",
                                    SwErrors.swInvalidInput)

            doc.ClearSelection2(True)
            if not self._select_ref(doc, plane, True, 2):
                return self._result(False, f"Could not select mirror plane {plane}",
                                    SwErrors.swSelectionError)
            if mirror_bodies:
                sel_mgr = cu.call(doc, "SelectionManager")
                for body in self._get_bodies(doc):
                    sd = cu.call(sel_mgr, "CreateSelectData")
                    sd.Mark = 256
                    body.Select2(True, sd)
            else:
                failed = self._select_features(doc, features, 1)
                if failed:
                    return self._result(False, f"Features not found: {failed}",
                                        SwErrors.swSelectionError)

            fm = doc.FeatureManager
            feat, used = cu.first_ok(
                lambda: fm.InsertMirrorFeature2(mirror_bodies, geometry_pattern, merge, False, 0),
                lambda: fm.InsertMirrorFeature(mirror_bodies, geometry_pattern, merge, False),
                log_prefix="Mirror")
            if not feat:
                return self._result(False, "Mirror failed", SwErrors.swFeatureError)
            what = "bodies" if mirror_bodies else ", ".join(features)
            return self._result(True, f"Mirrored {what} → {self._feature_name(feat)}",
                                SwErrors.swSuccess, {"feature": self._feature_name(feat)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"mirror error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------
    # Reference plane
    # ------------------------------------------------------------------

    def create_ref_plane(self, base: Dict, mode: str = "offset", distance: float = 10.0,
                         angle: float = 45.0, axis: Dict = None, second: Dict = None,
                         flip: bool = False, name: str = None, unit: str = None) -> Dict:
        """
        mode:
          offset : parallel to `base` (plane/planar face) at `distance`
          angle  : through `axis` (linear edge/axis), at `angle`° to `base`
          mid    : mid-plane between `base` and `second` (two parallel faces/planes)
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            doc.ClearSelection2(True)
            if not self._select_ref(doc, base, True, 0, unit):
                return self._result(False, f"Could not select base {base}", SwErrors.swSelectionError)

            flip_bit = _RP_FLIP if flip else 0
            if mode == "offset":
                d = self._units.to_meters(distance, unit)
                args = (_RP_DISTANCE | flip_bit, d, 0, 0, 0, 0)
            elif mode == "angle":
                if not axis:
                    return self._result(False, "mode=angle requires `axis`", SwErrors.swInvalidInput)
                if not self._select_ref(doc, axis, True, 1, unit):
                    return self._result(False, f"Could not select axis {axis}", SwErrors.swSelectionError)
                args = (_RP_ANGLE | flip_bit, math.radians(angle), _RP_COINCIDENT, 0, 0, 0)
            elif mode == "mid":
                if not second:
                    return self._result(False, "mode=mid requires `second`", SwErrors.swInvalidInput)
                if not self._select_ref(doc, second, True, 1, unit):
                    return self._result(False, f"Could not select second {second}",
                                        SwErrors.swSelectionError)
                args = (_RP_MIDPLANE, 0, _RP_MIDPLANE, 0, 0, 0)
            else:
                return self._result(False, "mode must be offset | angle | mid", SwErrors.swInvalidInput)

            feat, _ = cu.first_ok(lambda: doc.FeatureManager.InsertRefPlane(*args),
                                  log_prefix="InsertRefPlane")
            if not feat:
                return self._result(False, f"Reference plane ({mode}) failed", SwErrors.swFeatureError)
            if name:
                try:
                    feat.Name = name
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"rename plane failed: {e}")
            return self._result(True, f"Plane created ({mode}) → {self._feature_name(feat)}",
                                SwErrors.swSuccess, {"feature": self._feature_name(feat), "mode": mode})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"ref plane error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
