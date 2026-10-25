"""
SolidWorks Model Operations
---------------------------
Parametric edit (dimensions), feature suppression, rebuild/undo, mass
properties, material, custom properties, neutral-format export and view
capture (returns a PNG so the model can be inspected visually).
"""

import os
import math
import base64
import logging
import tempfile
import traceback
from typing import Dict, List

from ..constants import SwErrors, SwViews
from . import com_utils as cu
from .com_utils import set_dimension_value

logger = logging.getLogger(__name__)

_EXPORT_EXTS = {".step", ".stp", ".igs", ".iges", ".x_t", ".x_b", ".sat", ".stl",
                ".3mf", ".amf", ".wrl", ".eprt", ".easm", ".edrw", ".pdf", ".dxf",
                ".dwg", ".jpg", ".tif", ".png", ".sldprt", ".sldasm", ".slddrw"}


class ModelOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app"""

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_kind(dim) -> str:
        """
        'length' | 'angle' | 'count'.
        Verified on SW 2026: IDimension.GetType returns 2 for integer dims
        (pattern instance counts). Linear vs angular is decided from the ratio
        Value (document units) / SystemValue (m or rad): ~57.2958 => degrees.
        """
        t = int(cu.try_call(dim, "GetType", default=0) or 0)
        if t == 2:
            return "count"
        sysv = cu.try_call(dim, "SystemValue")
        docv = cu.try_call(dim, "Value")
        try:
            sysv, docv = float(sysv), float(docv)
            if abs(sysv) > 1e-12:
                ratio = docv / sysv
                if abs(ratio - 180.0 / math.pi) < 1e-3:
                    return "angle"
                return "length"
        except (TypeError, ValueError):
            pass
        return "angle" if t == 3 else "length"

    def _dim_show(self, kind: str, v_si, unit: str = None):
        if v_si is None:
            return None
        if kind == "count":
            return int(round(v_si))
        if kind == "angle":
            return round(math.degrees(v_si), 6)
        return round(self._units.from_meters(v_si, unit), 6)

    def _dim_unit(self, kind: str, unit: str = None) -> str:
        return {"count": "", "angle": "deg"}.get(kind, unit or self._units.default_unit.value)

    def list_dimensions(self, feature: str = None, unit: str = None) -> Dict:
        """All driving dimensions (FullName = 'D1@Sketch1@Part1.SLDPRT'). Angles reported in degrees."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            dims = []
            feat = cu.call(doc, "FirstFeature")
            while feat is not None:
                fname = str(feat.Name)
                if feature is None or fname == feature:
                    dd = cu.try_call(feat, "GetFirstDisplayDimension")
                    while dd is not None:
                        try:
                            dim = cu.call(dd, "GetDimension2", 0)
                            v = float(cu.call(dim, "SystemValue"))
                            name = str(cu.call(dim, "FullName"))
                            kind = self._dim_kind(dim)
                            dims.append({
                                "name": "@".join(name.split("@")[:2]),   # usable with set_dimension
                                "full_name": name,
                                "feature": fname,
                                "kind": kind,
                                "value": self._dim_show(kind, v, unit),
                                "unit": self._dim_unit(kind, unit),
                            })
                        except Exception as e:  # noqa: BLE001
                            logger.debug(f"dimension read failed: {e}")
                        dd = cu.try_call(feat, "GetNextDisplayDimension", dd)
                feat = cu.call(feat, "GetNextFeature")
            return self._result(True, f"{len(dims)} dimension(s)", SwErrors.swSuccess, {"dimensions": dims})
        except Exception as e:
            logger.error(f"list_dimensions error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def set_dimension(self, name: str, value: float, unit: str = None) -> Dict:
        """
        Change a dimension by name ('D1@Sketch1' or 'D1@Boss-Extrude1') and rebuild.
        The dimension kind is detected: angles take degrees (unit='rad' for
        radians), counts take an integer, lengths use `unit`.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            dim = cu.try_call(doc, "Parameter", name)
            if dim is None:
                return self._result(False, f"Dimension '{name}' not found. Use list_dimensions.",
                                    SwErrors.swInvalidInput)
            kind = self._dim_kind(dim)
            len_unit = None if (unit or "").lower() in ("deg", "rad") else unit
            if kind == "angle":
                v = float(value) if (unit or "").lower() == "rad" else math.radians(value)
            elif kind == "count":
                if float(value) != int(value) or int(value) < 1:
                    return self._result(False, f"{name} is a count; give a positive integer",
                                        SwErrors.swInvalidInput)
                v = float(int(value))
            else:
                v = self._units.to_meters(value, len_unit)
            old = cu.try_call(dim, "SystemValue")
            if not set_dimension_value(dim, v):
                return self._result(False, f"Could not set {name}", SwErrors.swFeatureError)
            rebuilt = cu.rebuild(doc)
            new = cu.try_call(dim, "SystemValue")

            def show(x):
                return self._dim_show(kind, x, len_unit)

            errors = self._rebuild_errors(doc)
            return self._result(not errors, f"{name}: {show(old)} → {show(new)}"
                                + (f" | rebuild errors: {errors}" if errors else ""),
                                SwErrors.swSuccess if not errors else SwErrors.swFeatureError,
                                {"name": name, "kind": kind, "unit": self._dim_unit(kind, len_unit),
                                 "old": show(old), "new": show(new),
                                 "rebuild_ok": rebuilt, "errors": errors})
        except Exception as e:
            logger.error(f"set_dimension error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def _rebuild_errors(self, doc) -> List[Dict]:
        """Features with rebuild errors (IFeature.GetErrorCode2 != 0)."""
        errs = []
        try:
            feat = cu.call(doc, "FirstFeature")
            while feat is not None:
                code = cu.try_call(feat, "GetErrorCode2", cu.byref_bool(False))
                if isinstance(code, tuple):
                    code = code[0]
                if code:
                    errs.append({"feature": str(feat.Name), "code": int(code)})
                feat = cu.call(feat, "GetNextFeature")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"_rebuild_errors failed: {e}")
        return errs

    # ------------------------------------------------------------------
    # Feature state
    # ------------------------------------------------------------------

    def suppress_feature(self, name: str, suppress: bool = True) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            feat = cu.find_feature(doc, name)
            if feat is None:
                return self._result(False, f"Feature '{name}' not found", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            feat.Select2(False, 0)
            ok, _ = cu.first_ok(
                (lambda: doc.EditSuppress2()) if suppress else (lambda: doc.EditUnsuppress2()),
                # swFeatureSuppressionAction_e: 0 suppress, 1 unsuppress; 1 = this configuration
                lambda: feat.SetSuppression2(0 if suppress else 1, 1, cu.empty()),
                log_prefix="Suppress")
            doc.ClearSelection2(True)
            if not ok:
                return self._result(False, f"Could not {'suppress' if suppress else 'unsuppress'} {name}",
                                    SwErrors.swFeatureError)
            return self._result(True, f"{name} {'suppressed' if suppress else 'unsuppressed'}",
                                SwErrors.swSuccess)
        except Exception as e:
            logger.error(f"suppress error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def rebuild_model(self, force: bool = False) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            ok = cu.rebuild(doc, force)
            errors = self._rebuild_errors(doc)
            return self._result(ok and not errors,
                                "Rebuilt" + (f" with errors: {errors}" if errors else ""),
                                SwErrors.swSuccess if ok and not errors else SwErrors.swFeatureError,
                                {"errors": errors})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def undo(self, steps: int = 1) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            doc.EditUndo2(int(steps))
            return self._result(True, f"Undid {steps} step(s)", SwErrors.swSuccess)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # Mass properties / material
    # ------------------------------------------------------------------

    def get_mass_properties(self, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            ext = doc.Extension
            mp, _ = cu.first_ok(lambda: cu.call(ext, "CreateMassProperty2"),
                                lambda: cu.call(ext, "CreateMassProperty"),
                                log_prefix="CreateMassProperty")
            if not mp:
                return self._result(False, "No solid body for mass properties", SwErrors.swUnknownError)
            try:
                mp.UseSystemUnits = True
            except Exception:  # noqa: BLE001
                pass

            u = unit or self._units.default_unit.value
            L = self._units.from_meters(1.0, unit)          # m -> unit
            mass = float(cu.call(mp, "Mass"))                # kg
            vol = float(cu.call(mp, "Volume"))               # m^3
            area = float(cu.call(mp, "SurfaceArea"))         # m^2
            dens = float(cu.try_call(mp, "Density", default=0.0) or 0.0)  # kg/m^3
            com = [float(v) * L for v in cu.as_list(cu.call(mp, "CenterOfMass"))[:3]]
            pmoi = [float(v) for v in cu.as_list(cu.try_call(mp, "PrincipleMomentsOfInertia"))[:3]]
            moi = [float(v) for v in cu.as_list(cu.try_call(mp, "GetMomentOfInertia", 0))[:9]]  # at CoM

            data = {
                "mass_kg": round(mass, 6),
                "mass_g": round(mass * 1000, 3),
                "volume": round(vol * L ** 3, 4), "volume_unit": f"{u}^3",
                "surface_area": round(area * L ** 2, 4), "area_unit": f"{u}^2",
                "density_kg_m3": round(dens, 2),
                "center_of_mass": [round(v, 4) for v in com], "length_unit": u,
                "principal_moi_kg_m2": [float(f"{v:.6e}") for v in pmoi],
                "moi_at_com_kg_m2": [float(f"{v:.6e}") for v in moi],
                "material": self._get_material_name(doc),
            }
            return self._result(True, f"m={data['mass_g']} g, V={data['volume']} {u}^3",
                                SwErrors.swSuccess, data)
        except Exception as e:
            logger.error(f"mass props error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def _get_material_name(self, doc) -> str:
        if cu.doc_type(doc) != 1:
            return ""
        cfg = cu.active_config_name(doc)
        db = cu.byref_str("")
        r = cu.try_call(doc, "GetMaterialPropertyName2", cfg, db, default="")
        if isinstance(r, tuple):
            r = r[0]
        return str(r or "")

    def set_material(self, material: str, database: str = "SOLIDWORKS Materials",
                     config: str = None) -> Dict:
        """Assign material by exact name in the material database (e.g. 'AISI 304', '6061-T6 (SS)')."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if cu.doc_type(doc) != 1:
                return self._result(False, "Material can only be set on a part", SwErrors.swInvalidInput)
            cfg = config if config is not None else cu.active_config_name(doc)
            doc.SetMaterialPropertyName2(cfg, database, material)
            got = self._get_material_name(doc)
            if got.lower() != material.lower():
                return self._result(False,
                    f"Material '{material}' not applied (current: '{got}'). Name must match the "
                    f"'{database}' library exactly.", SwErrors.swInvalidInput, {"current": got})
            return self._result(True, f"Material = {got}", SwErrors.swSuccess,
                                {"material": got, "config": cfg})
        except Exception as e:
            logger.error(f"set_material error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # Custom properties
    # ------------------------------------------------------------------

    def _cpm(self, doc, config: str):
        return doc.Extension.CustomPropertyManager(config or "")

    def set_custom_property(self, name: str, value: str, config: str = "") -> Dict:
        """Add or overwrite a text custom property (config '' = file-level)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            cpm = self._cpm(doc, config)
            status = None
            try:
                # Add3(FieldName, swCustomInfoText=30, Value, swCustomPropertyReplaceValue=2)
                # returns swCustomInfoAddResult_e (0 = AddedOrChanged)
                status = cpm.Add3(name, 30, str(value), 2)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Add3 failed: {e}")
            if status not in (0, None):
                cu.try_call(doc, "DeleteCustomInfo2", config or "", name)
                cu.try_call(doc, "AddCustomInfo3", config or "", name, 30, str(value))
            current = self._read_custom_property(cpm, name)
            if current is None or str(current) != str(value):
                return self._result(False, f"Could not set property {name} (read back: {current!r})",
                                    SwErrors.swUnknownError)
            return self._result(True, f"{name} = {value}", SwErrors.swSuccess,
                                {"name": name, "value": value, "config": config or "(file)"})
        except Exception as e:
            logger.error(f"set_custom_property error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def _read_custom_property(self, cpm, name: str, resolved: bool = False):
        val, res = cu.byref_str(""), cu.byref_str("")
        try:
            r = cpm.Get4(name, False, val, res)
            if isinstance(r, tuple):                  # pywin32 returns out-params in a tuple
                return r[2] if resolved else r[1]
            return res.value if resolved else val.value
        except Exception:  # noqa: BLE001
            return cu.try_call(cpm, "Get", name)

    def get_custom_properties(self, config: str = "") -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            cpm = self._cpm(doc, config)
            names = [str(n) for n in cu.as_list(cu.try_call(cpm, "GetNames"))]
            props = {n: {"value": self._read_custom_property(cpm, n),
                         "resolved": self._read_custom_property(cpm, n, resolved=True)}
                     for n in names}
            return self._result(True, f"{len(props)} propert(y/ies)", SwErrors.swSuccess,
                                {"config": config or "(file)", "properties": props})
        except Exception as e:
            logger.error(f"get_custom_properties error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_document(self, filepath: str) -> Dict:
        """
        Export a copy of the active document; format from extension
        (STEP/IGES/Parasolid/STL/3MF/eDrawings/PDF/DXF...). The open document
        keeps its original path (swSaveAsOptions_Silent | Copy).
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            path = os.path.abspath(os.path.expanduser(filepath))
            ext = os.path.splitext(path)[1].lower()
            if ext not in _EXPORT_EXTS:
                return self._result(False, f"Unsupported extension {ext}. Use one of {sorted(_EXPORT_EXTS)}",
                                    SwErrors.swInvalidFileType)
            os.makedirs(os.path.dirname(path), exist_ok=True)

            errs, warns = cu.byref_int(0), cu.byref_int(0)
            options = 1 | 2   # Silent | Copy
            ok = False
            try:
                r = doc.Extension.SaveAs(path, 0, options, cu.nothing(), errs, warns)
                ok = bool(r[0] if isinstance(r, tuple) else r)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Extension.SaveAs failed: {e}")
            if not ok:
                try:
                    ok = doc.SaveAs3(path, 0, options) == 0
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"SaveAs3 failed: {e}")
            if not ok or not os.path.exists(path):
                return self._result(False, f"Export failed (errors={getattr(errs, 'value', '?')})",
                                    SwErrors.swExportError, {"path": path})
            size_kb = round(os.path.getsize(path) / 1024, 1)
            return self._result(True, f"Exported {ext[1:].upper()} → {path} ({size_kb} KB)",
                                SwErrors.swSuccess,
                                {"path": path, "format": ext[1:], "size_kb": size_kb,
                                 "warnings": getattr(warns, "value", 0)})
        except Exception as e:
            logger.error(f"export error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swExportError)

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    def set_view(self, view: str = "isometric", zoom_to_fit: bool = True) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            vname, vid = SwViews.get(view)
            cu.try_call(doc, "ShowNamedView2", vname, vid)
            if zoom_to_fit:
                cu.try_call(doc, "ViewZoomtofit2")
            return self._result(True, f"View {vname}", SwErrors.swSuccess)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def capture_view(self, view: str = None, width: int = 1280, height: int = 800,
                     save_path: str = None) -> Dict:
        """
        Render the active viewport to PNG. Result data contains `_image_png_b64`
        which the MCP server returns as an image block.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            if view:
                vname, vid = SwViews.get(view)
                cu.try_call(doc, "ShowNamedView2", vname, vid)
                cu.try_call(doc, "ViewZoomtofit2")
            cu.try_call(doc, "GraphicsRedraw2")

            tmp_dir = tempfile.mkdtemp(prefix="swmcp_")
            bmp = os.path.join(tmp_dir, "view.bmp")
            if not doc.SaveBMP(bmp, int(width), int(height)) or not os.path.exists(bmp):
                return self._result(False, "SaveBMP failed", SwErrors.swExportError)

            png = save_path or os.path.join(tmp_dir, "view.png")
            try:
                from PIL import Image
                with Image.open(bmp) as im:
                    im.convert("RGB").save(png, "PNG", optimize=True)
            except ImportError:
                return self._result(True, f"Saved BMP (install pillow for inline image): {bmp}",
                                    SwErrors.swSuccess, {"path": bmp})
            with open(png, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return self._result(True, f"Captured {width}×{height}", SwErrors.swSuccess,
                                {"path": png, "_image_png_b64": b64})
        except Exception as e:
            logger.error(f"capture_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swExportError)
