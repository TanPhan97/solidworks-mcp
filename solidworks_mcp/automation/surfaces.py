"""
Surface modelling
-----------------
Extrude / revolve / planar / offset / loft surfaces, knit (optionally to a solid),
thicken, cut with surface, delete face (delete / patch / fill), list surface bodies.

  IFeatureManager.FeatureExtruRefSurface3(Sd, Dir, StartCond, OffsetVal, T1, T2, D1, D2,
      Dchk1, Dchk2, Ddir1, Ddir2, Dang1, Dang2, OffsetReverse1, OffsetReverse2,
      TranslateSurface1, TranslateSurface2, CapEnd1, CapEnd2, DeleteOriginalFace, KnitResult)
  IFeatureManager.InsertRevolvedRefSurface(Angle, ReverseDir, Angle2, RevType)
  IModelDoc2.InsertPlanarRefSurface() / InsertOffsetSurface(Thickness, Reverse)
  IModelDoc2.InsertLoftRefSurface2(Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
      StartMatchingType, EndMatchingType)
  IFeatureManager.InsertSewRefSurface(UseGapFilters, TryToFormSolid, MergeEntities,
      KnitTolerance, MaxValueForGapRange)
  IFeatureManager.FeatureBossThicken(Thickness, Direction, FaceIndex, FillVolume, Merge,
      UseFeatScope, UseAutoSelect)
  IFeatureManager.InsertCutSurface(Flip, KeepPieceIndex, UseFeatScope, UseAutoSelect, Bodies, Error)
  IModelDoc2.InsertDeleteFace2(Refill); IDeleteFaceFeatureData.Options (swFaceDeleteOption_e)

Verified on SW 2026 (each one only works this way):
  - knit and thicken need the surface bodies selected with mark 1 (mark 0 -> no feature);
  - InsertSewRefSurface ignores its boolean arguments: "try to form solid" is set
    afterwards through ISurfaceKnitFeatureData.UseTryToFormSolid;
  - FeatureExtruRefSurface3 / InsertLoftRefSurface2 build the feature but return None,
    so the result is read from the feature tree;
  - InsertDeleteFace2 always deletes; patch / fill is set through IDeleteFaceFeatureData.Options.
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_END = {"blind": 0, "through_all": 1, "mid_plane": 6}
_THICKEN_SIDE = {"side1": 0, "side2": 1, "both": 2}
_DELETE_OPT = {"delete": 0, "patch": 1, "fill": 2}


class SurfaceOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _select_ref(), _last_feature()"""

    # ------------------------------------------------------------------ helpers
    def _surf_doc(self):
        doc, err = self.get_active_doc()
        if err:
            return None, err
        if cu.doc_type(doc) != 1:
            return None, self._result(False, "Active document is not a part", SwErrors.swInvalidInput)
        cu.close_active_sketch(doc)
        return doc, None

    def _last_name(self, doc) -> str:
        f = self._last_feature(doc)
        return str(cu.try_call(f, "Name", default="")) if f is not None else ""

    def _last_sketch(self, doc) -> str:
        name, f = "", cu.try_call(doc, "FirstFeature")
        while f is not None:
            if str(cu.try_call(f, "GetTypeName2", default="")) == "ProfileFeature":
                name = str(cu.try_call(f, "Name", default=""))
            f = cu.try_call(f, "GetNextFeature")
        return name

    def _select_sketch(self, doc, sketch, mark: int = 0) -> str:
        name = sketch or self._last_sketch(doc)
        doc.ClearSelection2(True)
        if not name or not cu.select_by_id(doc, name, "SKETCH", 0, 0, 0, False, mark):
            raise ValueError(f"Sketch '{name}' not found")
        return name

    def _sheet_bodies(self, doc) -> List:
        return cu.as_list(cu.try_call(doc, "GetBodies2", 1, True))

    def _new_feature_or_fail(self, doc, before: str, what: str):
        after = self._last_name(doc)
        if after and after != before:
            return after, None
        return None, self._result(False, f"{what} failed", SwErrors.swFeatureError)

    def _select_surfaces(self, doc, names: List[str], mark: int) -> List[str]:
        names = names or [str(b.Name) for b in self._sheet_bodies(doc)]
        if not names:
            raise ValueError("No surface bodies in the part")
        doc.ClearSelection2(True)
        for i, n in enumerate(names):
            if not cu.select_by_id(doc, n, "SURFACEBODY", 0, 0, 0, i > 0, mark):
                raise ValueError(f"Surface body '{n}' not found (list_bodies kind='surface')")
        return names

    # ------------------------------------------------------------------ create
    def surface_extrude(self, depth: float, sketch: str = None, end_condition: str = "blind",
                        depth2: float = None, reverse: bool = False, unit: str = None) -> Dict:
        """Extruded surface from an open or closed sketch (no caps)."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            name = self._select_sketch(doc, sketch)
            before = self._last_name(doc)
            d1 = self._units.to_meters(depth, unit)
            two = depth2 is not None and depth2 > 0
            d2 = self._units.to_meters(depth2, unit) if two else 0.0
            t1 = _END.get(end_condition, 0)
            doc.FeatureManager.FeatureExtruRefSurface3(not two, bool(reverse), 0, 0.0, t1, 0, d1, d2,
                                                       False, False, False, False, 0.0, 0.0, False, False,
                                                       False, False, False, False, False, False)
            feat, fail = self._new_feature_or_fail(doc, before, "Surface extrude")
            if fail:
                return fail
            return self._result(True, f"{feat}: {depth}{' + ' + str(depth2) if two else ''} from {name}",
                                SwErrors.swSuccess, {"feature": feat, "sketch": name})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"surface_extrude error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def surface_revolve(self, angle: float = 360.0, sketch: str = None, reverse: bool = False) -> Dict:
        """Revolved surface; the sketch needs a centerline (the axis)."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            name = self._select_sketch(doc, sketch)
            f = doc.FeatureManager.InsertRevolvedRefSurface(math.radians(angle), bool(reverse), 0.0, 0)
            if f is None:
                return self._result(False, "Surface revolve failed (sketch needs a centerline)",
                                    SwErrors.swFeatureError)
            return self._result(True, f"{f.Name}: {angle}° from {name}", SwErrors.swSuccess,
                                {"feature": str(f.Name)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"surface_revolve error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def planar_surface(self, sketch: str = None) -> Dict:
        """Planar surface bounded by a closed sketch."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            name = self._select_sketch(doc, sketch)
            before = self._last_name(doc)
            cu.call(doc, "InsertPlanarRefSurface")
            feat, fail = self._new_feature_or_fail(doc, before, "Planar surface (closed planar sketch needed)")
            if fail:
                return fail
            return self._result(True, f"{feat} from {name}", SwErrors.swSuccess, {"feature": feat})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def offset_surface(self, faces: List[Dict], distance: float, reverse: bool = False,
                       unit: str = None) -> Dict:
        """Offset copies of faces (reference specs; distance 0 = copy surface)."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            doc.ClearSelection2(True)
            for i, spec in enumerate(faces or []):
                if not self._select_ref(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Could not select {spec}", SwErrors.swSelectionError)
            before = self._last_name(doc)
            cu.call(doc, "InsertOffsetSurface", self._units.to_meters(distance, unit), bool(reverse))
            feat, fail = self._new_feature_or_fail(doc, before, "Offset surface")
            if fail:
                return fail
            return self._result(True, f"{feat}: offset {distance}", SwErrors.swSuccess, {"feature": feat})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def loft_surface(self, profiles: List[str], closed: bool = False) -> Dict:
        """Lofted surface through >= 2 sketches (open or closed profiles), in order."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            if len(profiles or []) < 2:
                return self._result(False, "Give at least 2 profile sketches", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            for i, p in enumerate(profiles):
                if not cu.select_by_id(doc, p, "SKETCH", 0, 0, 0, i > 0, 1):
                    return self._result(False, f"Profile '{p}' not found", SwErrors.swSelectionError)
            before = self._last_name(doc)
            cu.call(doc, "InsertLoftRefSurface2", bool(closed), True, False, 1.0, 0, 0)
            feat, fail = self._new_feature_or_fail(doc, before, "Loft surface")
            if fail:
                return fail
            return self._result(True, f"{feat} through {len(profiles)} profiles", SwErrors.swSuccess,
                                {"feature": feat})
        except Exception as e:
            logger.error(f"loft_surface error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------ combine / convert
    def knit_surfaces(self, surfaces: List[str] = None, form_solid: bool = False,
                      tolerance: float = 0.0025, unit: str = None) -> Dict:
        """Knit surface bodies (all if none given); form_solid=true makes a solid from a closed set."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            names = self._select_surfaces(doc, surfaces, 1)
            solids0 = len(cu.as_list(doc.GetBodies2(0, True)))
            tol = self._units.to_meters(tolerance, unit)
            f = doc.FeatureManager.InsertSewRefSurface(False, bool(form_solid), False, tol, tol)
            if f is None:
                return self._result(False, "Knit failed", SwErrors.swFeatureError)
            if form_solid:
                d = f.GetDefinition
                d.AccessSelections(doc, cu.nothing())
                d.UseTryToFormSolid = True
                f.ModifyDefinition(d, doc, cu.nothing())
                cu.rebuild(doc)
            solid = len(cu.as_list(doc.GetBodies2(0, True))) > solids0
            if form_solid and not solid:
                return self._result(False, f"{f.Name} knitted but did not form a solid (gaps / open edges)",
                                    SwErrors.swFeatureError, {"feature": str(f.Name)})
            return self._result(True, f"{f.Name}: {len(names)} surface(s) knitted" + (" → solid" if solid else ""),
                                SwErrors.swSuccess, {"feature": str(f.Name), "solid": solid})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"knit_surfaces error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def thicken_surface(self, surface: str, thickness: float, side: str = "side1",
                        merge: bool = True, unit: str = None) -> Dict:
        """Thicken a surface body into a solid (side1 / side2 / both)."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            self._select_surfaces(doc, [surface], 1)
            has_solid = bool(cu.as_list(doc.GetBodies2(0, True)))
            f = doc.FeatureManager.FeatureBossThicken(self._units.to_meters(thickness, unit),
                                                      _THICKEN_SIDE.get(side, 0), 0, False,
                                                      bool(merge and has_solid), True, True)
            if f is None:
                return self._result(False, "Thicken failed (self-intersection? try the other side)",
                                    SwErrors.swFeatureError)
            return self._result(True, f"{f.Name}: t={thickness} ({side})", SwErrors.swSuccess,
                                {"feature": str(f.Name)})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"thicken_surface error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def cut_with_surface(self, surface: str, flip: bool = False) -> Dict:
        """Cut the solid bodies with a surface body; flip keeps the other side."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            self._select_surfaces(doc, [surface], 0)
            v0 = cu.try_call(cu.try_call(doc.Extension, "CreateMassProperty"), "Volume", default=None)
            e = cu.byref_int(0)
            f = doc.FeatureManager.InsertCutSurface(bool(flip), 0, False, True, cu.nothing(), e)
            cu.rebuild(doc)
            if f is None:
                return self._result(False, f"Cut with surface failed (error {e.value})", SwErrors.swFeatureError)
            v1 = cu.try_call(cu.try_call(doc.Extension, "CreateMassProperty"), "Volume", default=None)
            ratio = round(v1 / v0, 4) if v0 and v1 else None
            return self._result(True, f"{f.Name}: kept {ratio if ratio is not None else '?'} of the volume",
                                SwErrors.swSuccess, {"feature": str(f.Name), "volume_ratio": ratio})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"cut_with_surface error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def delete_face(self, faces: List[Dict], mode: str = "patch", unit: str = None) -> Dict:
        """Delete faces: delete (body becomes a surface), patch (heal, stays solid) or fill."""
        try:
            doc, err = self._surf_doc()
            if err:
                return err
            doc.ClearSelection2(True)
            for i, spec in enumerate(faces or []):
                if not self._select_ref(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Could not select {spec}", SwErrors.swSelectionError)
            before = self._last_name(doc)
            cu.call(doc, "InsertDeleteFace2", False)
            name, fail = self._new_feature_or_fail(doc, before, "Delete face")
            if fail:
                return fail
            opt = _DELETE_OPT.get(mode, 1)
            if opt:
                f = cu.find_feature(doc, name)
                d = f.GetDefinition
                d.AccessSelections(doc, cu.nothing())
                d.Options = opt
                f.ModifyDefinition(d, doc, cu.nothing())
                cu.rebuild(doc)
            solids = len(cu.as_list(doc.GetBodies2(0, True)))
            return self._result(True, f"{name}: {len(faces)} face(s), {mode} → {solids} solid bod(ies)",
                                SwErrors.swSuccess, {"feature": name, "solid_bodies": solids})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"delete_face error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
