"""
Sheet metal: base flange, edge flange, flatten, flat-pattern DXF
-----------------------------------------------------------------
  IFeatureManager.CreateCustomBendAllowance -> ICustomBendAllowance (Type, KFactor)
  IFeatureManager.InsertSheetMetalBaseFlange2(Thickness, ThickenDir, Radius, ExtrudeDist1,
      ExtrudeDist2, FlipExtruDir, EndCondition1, EndCondition2, DirToUse, PCBA,
      UseDefaultRelief, ReliefType, ReliefWidth, ReliefDepth, ReliefRatio, UseReliefRatio,
      Merge, UseFeatScope, UseAutoSelect)
  IModelDoc2.InsertSketchForEdgeFlange(FlangeEdge, DAngle, FlipDir) -> profile sketch
  IFeatureManager.InsertSheetMetalEdgeFlange2(FlangeEdges, SketchFeats, BooleanOptions,
      FlangeAngle, FlangeRadius, BendPosition, FlangeOffsetDist, ReliefType, ReliefRatio,
      ReliefWidth, ReliefDepth, FlangeSharpType, CustomBendAllowance)
  IEdgeFlangeFeatureData.OffsetDistance = flange length (blind)
  IPartDoc.ExportToDWG2(FilePath, ModelName, Action=1 sheet metal, ExportToSingleFile,
      Alignment, IsXDirFlipped, IsYDirFlipped, SheetMetalOptions, Views)

Verified on SW 2026: PCBA must be a real CustomBendAllowance (Nothing -> no feature);
DirToUse 0 and Merge False for the first (base) flange; an edge flange needs the
profile sketch from InsertSketchForEdgeFlange (error SketchNotSpecified otherwise)
and its length is set afterwards through OffsetDistance.
"""

import os
import math
import logging
import traceback
from typing import Dict

import pythoncom
import win32com.client

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_BEND_POS = {"material_inside": 1, "material_outside": 2, "bend_outside": 3, "bend_centerline": 4}
_RELIEF = {"rectangular": 1, "tear": 2, "obround": 3}
# ExportToDWG2 SheetMetalOptions bits: 1 geometry, 4 bend lines, 8 sketches, 32 forming tools...
_SM_GEOMETRY, _SM_BEND_LINES = 1, 4


def _arr(objs):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(objs))


class SheetMetalOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _select_ref(), _last_feature()"""

    def _bend_allowance(self, fm, k_factor: float):
        cba = fm.CreateCustomBendAllowance
        cba.Type = 2                                   # swBendAllowanceKFactor
        cba.KFactor = float(k_factor)
        return cba

    def _flat_pattern(self, doc):
        f = cu.try_call(doc, "FirstFeature")
        while f is not None:
            if str(cu.try_call(f, "GetTypeName2", default="")) == "FlatPattern":
                return f
            f = cu.try_call(f, "GetNextFeature")
        return None

    def base_flange(self, thickness: float, bend_radius: float = None, k_factor: float = 0.5,
                    sketch: str = None, depth: float = None, reverse: bool = False,
                    relief: str = "rectangular", unit: str = None) -> Dict:
        """
        Base flange from the last sketch (or `sketch`). Closed profile -> flat plate;
        open profile -> bent section extruded `depth` (mid-plane not supported here).
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if cu.doc_type(doc) != 1:
                return self._result(False, "Active document is not a part", SwErrors.swInvalidInput)
            cu.close_active_sketch(doc)
            name = sketch
            if not name:
                f = cu.try_call(doc, "FirstFeature")
                while f is not None:
                    if str(cu.try_call(f, "GetTypeName2", default="")) == "ProfileFeature":
                        name = str(cu.try_call(f, "Name", default=""))
                    f = cu.try_call(f, "GetNextFeature")
            doc.ClearSelection2(True)
            if not name or not cu.select_by_id(doc, name, "SKETCH", 0, 0, 0, False, 0):
                return self._result(False, f"Sketch '{name}' not found", SwErrors.swSelectionError)
            t = self._units.to_meters(thickness, unit)
            r = self._units.to_meters(bend_radius, unit) if bend_radius else t
            d1 = self._units.to_meters(depth, unit) if depth else 0.0
            fm = doc.FeatureManager
            feat = fm.InsertSheetMetalBaseFlange2(t, bool(reverse), r, d1, 0.0, False, 0, 0, 0,
                                                  self._bend_allowance(fm, k_factor), True,
                                                  _RELIEF.get(relief, 1), 0.0, 0.0, 0.5, True,
                                                  False, True, True)
            if feat is None:
                return self._result(False, "Base flange failed (closed profile, or open profile + depth)",
                                    SwErrors.swFeatureError)
            return self._result(True, f"{feat.Name}: t={thickness} R={bend_radius or thickness} K={k_factor}",
                                SwErrors.swSuccess, {"feature": str(feat.Name), "sketch": name,
                                                     "flat_pattern": str(cu.try_call(self._flat_pattern(doc), "Name", default=""))})
        except Exception as e:
            logger.error(f"base_flange error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def edge_flange(self, edge: Dict, length: float, angle: float = 90.0, bend_radius: float = None,
                    position: str = "material_inside", flip: bool = False, unit: str = None) -> Dict:
        """Edge flange on a linear edge of a sheet-metal part (edge reference spec)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            cu.close_active_sketch(doc)
            doc.ClearSelection2(True)
            if not self._select_ref(doc, edge, False, 0, unit):
                return self._result(False, f"Could not select edge {edge}", SwErrors.swSelectionError)
            eo = doc.SelectionManager.GetSelectedObject6(1, -1)
            doc.ClearSelection2(True)
            a = math.radians(angle)
            sk = doc.InsertSketchForEdgeFlange(eo, a, bool(flip))
            cu.close_active_sketch(doc)
            if sk is None:
                return self._result(False, "Could not create the flange profile (is this a sheet-metal edge?)",
                                    SwErrors.swFeatureError)
            opts = 128 | (0 if bend_radius else 1)           # default relief (+ default radius)
            r = self._units.to_meters(bend_radius, unit) if bend_radius else 0.0
            fm = doc.FeatureManager
            feat = fm.InsertSheetMetalEdgeFlange2(_arr([eo]), _arr([sk]), opts, a, r,
                                                  _BEND_POS.get(position, 1), 0.0, 1, 0.5, 0.0, 0.0, 1,
                                                  cu.nothing())
            if feat is None:
                return self._result(False, "Edge flange failed", SwErrors.swFeatureError)
            d = feat.GetDefinition
            d.AccessSelections(doc, cu.nothing())
            d.OffsetDistance = self._units.to_meters(length, unit)
            ok = feat.ModifyDefinition(d, doc, cu.nothing())
            cu.rebuild(doc)
            got = cu.try_call(feat.GetDefinition, "OffsetDistance", default=None)
            got_u = round(self._units.from_meters(got, unit), 4) if got is not None else None
            return self._result(bool(ok), f"{feat.Name}: L={got_u} @ {angle}°", SwErrors.swSuccess if ok else SwErrors.swFeatureError,
                                {"feature": str(feat.Name), "length": got_u})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"edge_flange error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def flatten(self, flat: bool = True) -> Dict:
        """Show the flat pattern (flat=true) or the formed part."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            fp = self._flat_pattern(doc)
            if fp is None:
                return self._result(False, "No flat pattern: not a sheet-metal part", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            fp.Select2(False, 0)
            ok = cu.call(doc, "EditUnsuppress2" if flat else "EditSuppress2")
            doc.ClearSelection2(True)
            cu.rebuild(doc)
            return self._result(bool(ok), "Flattened" if flat else "Formed", SwErrors.swSuccess)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def export_flat_pattern(self, filepath: str, bend_lines: bool = True) -> Dict:
        """Flat pattern of the active (saved) sheet-metal part to .dxf / .dwg."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if self._flat_pattern(doc) is None:
                return self._result(False, "No flat pattern: not a sheet-metal part", SwErrors.swInvalidInput)
            model = str(cu.try_call(doc, "GetPathName", default="") or "")
            if not model:
                return self._result(False, "Save the part first", SwErrors.swInvalidInput)
            path = os.path.abspath(os.path.expanduser(filepath))
            if os.path.splitext(path)[1].lower() not in (".dxf", ".dwg"):
                path += ".dxf"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            opts = _SM_GEOMETRY | (_SM_BEND_LINES if bend_lines else 0)
            ok = doc.ExportToDWG2(path, model, 1, True, cu.nothing(), False, False, opts, cu.nothing())
            if not ok or not os.path.isfile(path):
                return self._result(False, "ExportToDWG2 failed", SwErrors.swExportError)
            return self._result(True, f"Flat pattern → {path} ({round(os.path.getsize(path) / 1024, 1)} KB)",
                                SwErrors.swSuccess, {"path": path})
        except Exception as e:
            logger.error(f"export_flat_pattern error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swExportError)
