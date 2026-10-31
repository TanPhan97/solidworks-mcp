"""
SolidWorks Drawing Operations
-----------------------------
Create drawings with projected standard views and an isometric view,
section / detail / extra views, model dimensions, BOM, auto balloons,
and a view listing.

Signatures verified against the SOLIDWORKS 2026 type library (sldworks.tlb):
  IDrawingDoc.Create1stAngleViews2(ModelName) / Create3rdAngleViews2(ModelName)
  IDrawingDoc.CreateDrawViewFromModelView3(ModelName, ViewName, LocX, LocY, LocZ)
  IDrawingDoc.CreateSectionViewAt5(X, Y, Z, SectionLabel, Options, ExcludedComponents, SectionDepth)
  IDrawingDoc.CreateDetailViewAt4(X, Y, Z, Style, Scale1, Scale2, LabelIn, Showtype,
                                  FullOutline, JaggedOutline, NoOutline, ShapeIntensity)
  IDrawingDoc.InsertModelAnnotations3(Option, Types, AllViews, DuplicateDims,
                                      HiddenFeatureDims, UsePlacementInSketch)
  IDrawingDoc.AutoBalloon5(BalloonOptions) + CreateAutoBalloonOptions()
  IView.InsertBomTable4(UseAnchorPoint, X, Y, AnchorType, BomType, Configuration,
                        TableTemplate, Hidden, IndentedNumberingType, DetailedCutList)
  ISheet.GetProperties2() -> (PaperSize, Template, Scale1, Scale2, FirstAngle, Width, Height, ...)
  ISheet.SetProperties2(PaperSz, Templ, Scale1, Scale2, FirstAngle, Width, Height, SameCustomProp)

Sheet coordinates exposed to the user are in mm from the sheet's lower-left corner.
"""

import os
import glob
import logging
import traceback
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from ..constants import SwErrors
from . import com_utils as cu
from .templates import resolve_template

logger = logging.getLogger(__name__)

MM = 0.001
_VIEW_NAMES = {
    "front": "*Front", "back": "*Back", "left": "*Left", "right": "*Right",
    "top": "*Top", "bottom": "*Bottom", "isometric": "*Isometric",
    "iso": "*Isometric", "trimetric": "*Trimetric", "dimetric": "*Dimetric",
}
_BOM_TYPES = {"parts_only": 1, "top_level": 2, "indented": 3}
_ANCHORS = {"top_left": 1, "top_right": 2, "bottom_left": 3, "bottom_right": 4}
# swInsertAnnotation_e
_ANNOT = {
    "dimensions_marked": 32768, "dimensions_all": 8, "hole_callouts": 1048576,
    "cosmetic_threads": 1, "datums": 2, "gtols": 32, "notes": 64,
    "surface_finish": 128, "axes": 512, "center_of_mass": 33554432,
    "hole_wizard_locations": 131072, "hole_wizard_profiles": 65536,
}
# Standard drawing scales, largest first
_SCALES = [(10, 1), (5, 1), (4, 1), (2, 1), (1, 1), (1, 2), (1, 2.5), (1, 4), (1, 5),
           (1, 10), (1, 20), (1, 25), (1, 50), (1, 100)]


def _parse_scale(s) -> Optional[Tuple[float, float]]:
    if s is None or s == "" or str(s).lower() == "auto":
        return None
    if isinstance(s, (int, float)):
        f = Fraction(float(s)).limit_denominator(100)
        return float(f.numerator), float(f.denominator)
    a, _, b = str(s).replace(" ", "").partition(":")
    return float(a), float(b or 1)


class DrawingOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, _config"""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _require_drawing(self):
        doc, err = self.get_active_doc()
        if err:
            return None, err
        if cu.doc_type(doc) != 3:
            return None, self._result(False, "Active document is not a drawing. Use create_drawing "
                                             "or open a .slddrw first.", SwErrors.swInvalidInput)
        return doc, None

    def _sheet_info(self, drw) -> Dict:
        sheet = cu.call(drw, "GetCurrentSheet")
        props = cu.as_list(cu.call(sheet, "GetProperties2"))
        return {"sheet": sheet, "props": props,
                "name": str(cu.try_call(sheet, "GetName", default="")),
                "paper": int(props[0]), "template": int(props[1]),
                "scale": (float(props[2]), float(props[3])), "first_angle": bool(props[4]),
                "width": float(props[5]), "height": float(props[6])}

    def _views(self, drw) -> List:
        """Drawing views on the current sheet (skips the sheet pseudo-view)."""
        out = []
        v = cu.call(drw, "GetFirstView")          # sheet
        v = cu.try_call(v, "GetNextView") if v is not None else None
        while v is not None:
            out.append(v)
            v = cu.try_call(v, "GetNextView")
        return out

    def _find_view(self, drw, name: str):
        for v in self._views(drw):
            if str(cu.try_call(v, "GetName2", default="")) == name:
                return v
        return None

    def _view_record(self, v) -> Dict:
        ol = [float(x) for x in cu.as_list(cu.try_call(v, "GetOutline"))[:4]] or [0, 0, 0, 0]
        pos = cu.as_list(cu.try_call(v, "Position"))
        sc = cu.as_list(cu.try_call(v, "ScaleRatio"))
        return {
            "name": str(cu.try_call(v, "GetName2", default="")),
            "type": int(cu.try_call(v, "Type", default=0) or 0),
            "model": str(cu.try_call(v, "GetReferencedModelName", default="")),
            "scale": f"{sc[0]:g}:{sc[1]:g}" if len(sc) >= 2 else None,
            "outline_mm": [round(x / MM, 2) for x in ol],
            "center_mm": [round(float(pos[0]) / MM, 2), round(float(pos[1]) / MM, 2)] if len(pos) >= 2 else None,
        }

    def _to_view_sketch(self, view, x: float, y: float) -> Tuple[float, float]:
        """
        Sheet coordinates (m) -> coordinates in the view's sketch. After
        ActivateView, SketchManager.Create* works in the view sketch, which is
        offset by the view position (verified on SW 2026: ModelToSketchTransform
        translation = -view.Position).
        """
        sk = cu.try_call(view, "GetSketch")
        xf = cu.try_call(sk, "ModelToSketchTransform") if sk is not None else None
        if xf is not None:
            try:
                q = cu.transform_point(xf, [x, y, 0.0])
                return q[0], q[1]
            except Exception as e:  # noqa: BLE001
                logger.debug(f"view sketch transform failed: {e}")
        pos = cu.as_list(cu.try_call(view, "Position"))
        return (x - float(pos[0]), y - float(pos[1])) if len(pos) >= 2 else (x, y)

    def _free_spot(self, drw, parent_outline, w: float, h: float, lock: str = None,
                   current=None, exclude=None) -> Optional[Tuple[float, float]]:
        """
        Centre for a w x h (m) view as close as possible to `parent_outline`
        without overlapping other views or the title-block band. Grid search over
        the sheet. lock='y' keeps y = current[1] (aligned section of a vertical cut),
        lock='x' keeps x = current[0]. `exclude` = view object to ignore (itself).
        """
        info = self._sheet_info(drw)
        W, H = info["width"], info["height"]
        px0, py0, px1, py1 = parent_outline
        pc = ((px0 + px1) / 2, (py0 + py1) / 2)
        boxes = []
        for vw in self._views(drw):
            if exclude is not None and str(cu.try_call(vw, "GetName2", default="")) == \
                    str(cu.try_call(exclude, "GetName2", default="?")):
                continue
            ol = [float(v) for v in cu.as_list(cu.try_call(vw, "GetOutline"))[:4]]
            if len(ol) == 4:
                boxes.append(ol)
        lo_x, hi_x, lo_y, hi_y = 0.03 * W, 0.97 * W, 0.24 * H, 0.95 * H
        m = 0.008                                    # clearance for labels / dimensions

        def fits(cx, cy):
            bx0, by0, bx1, by1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            if bx0 < lo_x or bx1 > hi_x or by0 < lo_y or by1 > hi_y:
                return False
            return not any(bx0 < b[2] + m and bx1 > b[0] - m and by0 < b[3] + m and by1 > b[1] - m
                           for b in boxes)

        step = 0.004
        xs = [current[0]] if lock == "x" and current else \
            [lo_x + w / 2 + i * step for i in range(int(max(0, (hi_x - lo_x - w)) / step) + 1)]
        ys = [current[1]] if lock == "y" and current else \
            [lo_y + h / 2 + j * step for j in range(int(max(0, (hi_y - lo_y - h)) / step) + 1)]
        best = None
        for cx in xs:
            for cy in ys:
                if fits(cx, cy):
                    dist = (cx - pc[0]) ** 2 + (cy - pc[1]) ** 2
                    if best is None or dist < best[0]:
                        best = (dist, cx, cy)
        return (best[1], best[2]) if best else None

    def _relocate(self, drw, view, parent_outline, lock: str = None) -> bool:
        """Move `view` (by its real outline) to the nearest free spot."""
        ol = [float(v) for v in cu.as_list(cu.try_call(view, "GetOutline"))[:4]]
        pos = [float(v) for v in cu.as_list(cu.try_call(view, "Position"))[:2]]
        if len(ol) < 4 or len(pos) < 2:
            return False
        w, h = ol[2] - ol[0], ol[3] - ol[1]
        oc = ((ol[0] + ol[2]) / 2, (ol[1] + ol[3]) / 2)
        spot = self._free_spot(drw, parent_outline, w, h, lock=lock, current=oc, exclude=view)
        if spot is None or (abs(spot[0] - oc[0]) < 1e-4 and abs(spot[1] - oc[1]) < 1e-4):
            return False
        try:
            view.Position = cu.double_array([pos[0] + spot[0] - oc[0], pos[1] + spot[1] - oc[1]])
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"relocate failed: {e}")
            return False

    def _select_view(self, drw, name: str, append: bool = False, mark: int = 0) -> bool:
        return cu.select_by_id(drw, name, "DRAWINGVIEW", 0, 0, 0, append, mark)

    def _model_box(self, model_doc) -> Optional[List[float]]:
        """[dx, dy, dz] in metres (model axes)."""
        box = None
        t = cu.doc_type(model_doc)
        if t == 1:
            box = cu.try_call(model_doc, "GetPartBox", True)
        elif t == 2:
            box = cu.try_call(model_doc, "GetBox", 0)
        b = cu.as_list(box)
        if len(b) < 6:
            return None
        return [abs(float(b[3]) - float(b[0])), abs(float(b[4]) - float(b[1])), abs(float(b[5]) - float(b[2]))]

    def _auto_scale(self, box, sheet_w, sheet_h) -> Tuple[float, float]:
        dx, dy, dz = box
        # 3-view layout: columns [x-extent, z-extent], rows [y-extent, z-extent] plus a
        # dimension gap between views; ~30 % width kept for the iso view, ~22 % height
        # for the title block.
        gap = self._view_gap(sheet_w)
        avail_w, avail_h = sheet_w * 0.58 - gap, sheet_h * 0.60 - gap
        for n, d in _SCALES:
            s = n / d
            if s * (dx + dz) <= avail_w and s * (dy + dz) <= avail_h:
                return float(n), float(d)
        return 1.0, 100.0

    def _set_sheet_scale(self, drw, n: float, d: float) -> bool:
        info = self._sheet_info(drw)
        p = info["props"]
        ok = cu.try_call(info["sheet"], "SetProperties2", int(p[0]), int(p[1]), float(n), float(d),
                         bool(p[4]), float(p[5]), float(p[6]), True)
        if not ok:
            ok = cu.try_call(info["sheet"], "SetScale", float(n), float(d), True, False)
        return bool(ok)

    def _resolve_model(self, model_path: Optional[str]):
        """Return (model_path, model_doc) — uses the active part/assembly if no path."""
        sw = self.app
        if model_path:
            path = os.path.abspath(os.path.expanduser(model_path))
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Model not found: {path}")
            doc = cu.find_open_doc(sw, path)
            if doc is not None:
                open_path = str(cu.try_call(doc, "GetPathName", default="") or "")
                if open_path and os.path.normcase(os.path.abspath(open_path)) != os.path.normcase(path):
                    raise ValueError(f"A different file with the same name is open ({open_path}). "
                                     f"SolidWorks resolves drawing references by name: close it first.")
            if doc is None:
                ext = os.path.splitext(path)[1].lower()
                e, w = cu.byref_int(0), cu.byref_int(0)
                doc = sw.OpenDoc6(path, 2 if ext == ".sldasm" else 1, 1, "", e, w)
                if doc is None and getattr(e, "value", 0) == 65536:
                    raise ValueError("A different file with the same name is already open; close it first.")
            return path, doc
        doc = cu.call(sw, "ActiveDoc")
        if doc is None or cu.doc_type(doc) not in (1, 2):
            raise ValueError("Give model_path, or make a part/assembly the active document")
        path = str(cu.call(doc, "GetPathName") or "")
        if not path:
            raise ValueError("The active model has never been saved. Save it first (save_document) "
                             "— drawings reference models by file path.")
        return path, doc

    def _table_template(self, ext: str, explicit: Optional[str] = None,
                        prefer: Tuple[str, ...] = ("standard",)) -> str:
        """
        Table template (.sldbomtbt / .sldrevtbt / .sldholtbt). Search order: explicit
        path; company template folders (next to the default part / assembly /
        drawing templates, one and two levels down, e.g. 'TABLE - VULCAN'); File
        Locations; the SolidWorks install (lang/english). Within a folder group a
        name containing a `prefer` word wins.
        """
        if explicit:
            return explicit
        sw = self.app
        groups = []
        tpl_dirs = []
        for k in (8, 9, 10):        # default part / assembly / drawing template
            t = str(cu.try_call(sw, "GetUserPreferenceStringValue", k, default="") or "")
            if t and os.path.dirname(t) not in tpl_dirs:
                tpl_dirs.append(os.path.dirname(t))
        folders = str(cu.try_call(sw, "GetUserPreferenceStringValue", 0, default="") or "")
        tpl_dirs += [f.strip() for f in folders.split(";") if f.strip()]
        user = []
        for d in tpl_dirs:
            for pat in ("*." + ext, os.path.join("*", "*." + ext), os.path.join("*", "*", "*." + ext)):
                user += glob.glob(os.path.join(d, pat))
        groups.append(user)
        exe_dir = str(cu.try_call(sw, "GetExecutablePath", default="") or "")
        if exe_dir:
            groups.append(glob.glob(os.path.join(exe_dir, "lang", "english", "*." + ext)))
        for cands in groups:
            cands = sorted(dict.fromkeys(cands))
            for word in prefer:
                for c in cands:
                    if word in os.path.basename(c).lower():
                        return c
            if cands:
                return cands[0]
        return ""

    def _bom_template(self, explicit: Optional[str]) -> str:
        return self._table_template("sldbomtbt", explicit, ("standard",))

    def create_drawing(self, model_path: str = None, views: List[str] = None,
                       scale: str = "auto", template: str = None,
                       include_iso: bool = True, model_dimensions: bool = False,
                       center_marks: bool = True, save_path: str = None) -> Dict:
        """
        New drawing of a part/assembly. Default: projected Front/Top/Right
        (1st or 3rd angle per the sheet format) + isometric, auto-scaled.
        `views` instead gives independent named views, e.g. ["front", "isometric"].
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            try:
                mpath, mdoc = self._resolve_model(model_path)
            except (FileNotFoundError, ValueError) as e:
                return self._result(False, str(e), SwErrors.swInvalidInput)

            configured = template or getattr(self._config, "drawing_template", "auto")
            tpl, src, tried = resolve_template(self.app, "drawing", configured)
            if not tpl:
                return self._result(False, "No drawing template found (set drawing_template in "
                                    "config.json or pass template)", SwErrors.swTemplateNotFound,
                                    {"tried": tried})
            drw = self.app.NewDocument(tpl, 0, 0, 0)
            if drw is None:
                return self._result(False, f"NewDocument failed for {tpl}", SwErrors.swFileLoadError)

            info = self._sheet_info(drw)
            W, H = info["width"], info["height"]
            box = self._model_box(mdoc)
            sc = _parse_scale(scale)
            if sc is None:
                sc = self._auto_scale(box, W, H) if box else (1.0, 1.0)
            self._set_sheet_scale(drw, *sc)
            s = sc[0] / sc[1]

            created = []
            if not views:
                fn = "Create1stAngleViews2" if info["first_angle"] else "Create3rdAngleViews2"
                ok = cu.try_call(drw, fn, mpath)
                if not ok:
                    return self._result(False, f"{fn} failed for {mpath}", SwErrors.swFeatureError)
                std = self._views(drw)
                created = [str(cu.try_call(v, "GetName2")) for v in std]
                if box and len(std) >= 3:
                    self._layout_standard(std[:3], box, s, W, H, info["first_angle"])
                if include_iso:
                    ix, iy = W * 0.80, H * 0.70
                    iv = drw.CreateDrawViewFromModelView3(mpath, "*Isometric", ix, iy, 0.0)
                    if iv is not None:
                        created.append(str(cu.try_call(iv, "GetName2")))
            else:
                n = len(views)
                for i, name in enumerate(views):
                    key = _VIEW_NAMES.get(str(name).lower(), str(name))
                    x = W * (0.15 + 0.7 * (i % 2)) if n > 1 else W * 0.45
                    y = H * (0.70 - 0.35 * (i // 2))
                    v = drw.CreateDrawViewFromModelView3(mpath, key, x, y, 0.0)
                    if v is not None:
                        created.append(str(cu.try_call(v, "GetName2")))

            if model_dimensions:
                cu.try_call(drw, "InsertModelAnnotations3", 0, _ANNOT["dimensions_marked"],
                            True, False, False, True)
            if center_marks:
                for v in self._views(drw):
                    cu.try_call(v, "AutoInsertCenterMarks2", 1 | 4, 0, True, True, True, 0.0025, 0.0015,
                                True, True, 0.0)
            cu.try_call(drw, "ViewZoomtofit2")
            cu.rebuild(drw)

            saved = None
            if save_path:
                saved = self._save_drawing(drw, save_path)

            return self._result(True,
                f"Drawing with {len(created)} view(s), scale {sc[0]:g}:{sc[1]:g}",
                SwErrors.swSuccess,
                {"title": str(cu.try_call(drw, "GetTitle", default="")), "model": mpath,
                 "template": tpl, "views": created, "scale": f"{sc[0]:g}:{sc[1]:g}",
                 "sheet_mm": [round(W / MM, 1), round(H / MM, 1)],
                 "projection": "first angle" if info["first_angle"] else "third angle",
                 "saved": saved})
        except Exception as e:
            logger.error(f"create_drawing error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    @staticmethod
    def _view_gap(sheet_w: float) -> float:
        """Room between views for dimensions (~25 mm on A3, ~18 mm on A4)."""
        return max(0.018, 0.06 * sheet_w)

    def _layout_standard(self, views, box, s, W, H, first_angle: bool):
        """Space Front/Top/Right using the model extents (projected views keep alignment)."""
        dx, dy, dz = box
        gap = self._view_gap(W)
        fx = 0.07 * W + gap / 2 + (s * dz + gap if first_angle else 0) + s * dx / 2
        fy = 0.24 * H + gap / 2 + (s * dz + gap if first_angle else 0) + s * dy / 2
        top_y = fy - (s * dy / 2 + gap + s * dz / 2) if first_angle else fy + (s * dy / 2 + gap + s * dz / 2)
        side_x = fx - (s * dx / 2 + gap + s * dz / 2) if first_angle else fx + (s * dx / 2 + gap + s * dz / 2)
        targets = [(fx, fy), (fx, top_y), (side_x, fy)]
        for v, (x, y) in zip(views, targets):
            try:
                v.Position = cu.double_array([x, y])
            except Exception as e:  # noqa: BLE001
                logger.debug(f"view position failed: {e}")

    def _save_drawing(self, drw, save_path: str) -> Optional[str]:
        path = os.path.abspath(os.path.expanduser(save_path))
        if not path.lower().endswith(".slddrw"):
            path += ".SLDDRW"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        e, w = cu.byref_int(0), cu.byref_int(0)
        r = cu.try_call(drw.Extension, "SaveAs", path, 0, 1, cu.nothing(), e, w)
        ok = r[0] if isinstance(r, tuple) else r
        return path if ok and os.path.isfile(path) else None

    # ------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------

    def list_drawing_views(self) -> Dict:
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            info = self._sheet_info(drw)
            views = [self._view_record(v) for v in self._views(drw)]
            sheets = [str(n) for n in cu.as_list(cu.try_call(drw, "GetSheetNames"))]
            return self._result(True, f"{len(views)} view(s) on sheet '{info['name']}'", SwErrors.swSuccess,
                                {"sheet": info["name"], "sheets": sheets,
                                 "sheet_mm": [round(info["width"] / MM, 1), round(info["height"] / MM, 1)],
                                 "scale": f"{info['scale'][0]:g}:{info['scale'][1]:g}",
                                 "projection": "first angle" if info["first_angle"] else "third angle",
                                 "views": views})
        except Exception as e:
            logger.error(f"list_drawing_views error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_drawing_view(self, view: str, x: float, y: float, model_path: str = None,
                         scale: str = None) -> Dict:
        """Named model view at sheet position (x, y) mm."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            if model_path:
                mpath = os.path.abspath(os.path.expanduser(model_path))
            else:
                existing = self._views(drw)
                mpath = str(cu.try_call(existing[0], "GetReferencedModelName", default="")) if existing else ""
                if not mpath:
                    return self._result(False, "No model referenced yet; give model_path", SwErrors.swInvalidInput)
            key = _VIEW_NAMES.get(view.lower(), view)
            v = drw.CreateDrawViewFromModelView3(mpath, key, x * MM, y * MM, 0.0)
            if v is None:
                return self._result(False, f"Could not create view {key}", SwErrors.swFeatureError)
            sc = _parse_scale(scale)
            if sc:
                try:
                    v.ScaleRatio = cu.double_array(list(sc))
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"scale set failed: {e}")
            cu.rebuild(drw)
            return self._result(True, f"View {self._view_record(v)['name']} ({key})", SwErrors.swSuccess,
                                self._view_record(v))
        except Exception as e:
            logger.error(f"add_drawing_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_section_view(self, parent_view: str, direction: str = "vertical",
                         position: float = 0.5, x: float = None, y: float = None,
                         label: str = "A", flip: bool = False) -> Dict:
        """
        Full section through `parent_view`. direction=vertical cuts with a vertical
        line at `position` (0..1 across the view width); horizontal likewise in height.
        Placement (x, y) mm defaults to beside / below the parent.
        """
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            pv = self._find_view(drw, parent_view)
            if pv is None:
                return self._result(False, f"View '{parent_view}' not found (list_drawing_views)",
                                    SwErrors.swInvalidInput)
            xmin, ymin, xmax, ymax = [float(v) for v in cu.as_list(cu.call(pv, "GetOutline"))[:4]]
            ext = 0.004
            cu.call(drw, "ActivateView", parent_view)
            sm = cu.call(drw, "SketchManager")
            if direction == "vertical":
                xc = xmin + (xmax - xmin) * position
                a = self._to_view_sketch(pv, xc, ymin - ext)
                b = self._to_view_sketch(pv, xc, ymax + ext)
                line = sm.CreateLine(a[0], a[1], 0.0, b[0], b[1], 0.0)
                fx, fy = xmax + self._view_gap(self._sheet_info(drw)["width"]), (ymin + ymax) / 2
            else:
                yc = ymin + (ymax - ymin) * position
                a = self._to_view_sketch(pv, xmin - ext, yc)
                b = self._to_view_sketch(pv, xmax + ext, yc)
                line = sm.CreateLine(a[0], a[1], 0.0, b[0], b[1], 0.0)
                fx, fy = (xmin + xmax) / 2, ymin - self._view_gap(self._sheet_info(drw)["width"])
            px = (x * MM) if x is not None else fx
            py = (y * MM) if y is not None else fy
            if line is None:
                return self._result(False, "Could not sketch the cutting line", SwErrors.swSketchError)
            drw.ClearSelection2(True)
            line.Select4(False, cu.nothing())
            opts = 4 if flip else 0   # swCreateSectionView_ChangeDirection
            sv = drw.CreateSectionViewAt5(px, py, 0.0, label, opts, cu.empty(), 0.0)
            if sv is None:
                return self._result(False, "Section view failed (cutting line must cross the model)",
                                    SwErrors.swFeatureError)
            cu.rebuild(drw)
            if x is None and y is None:      # place by real size; stays aligned with the parent
                if self._relocate(drw, sv, (xmin, ymin, xmax, ymax), lock="y" if direction == "vertical" else "x"):
                    cu.rebuild(drw)
            return self._result(True, f"Section {label}-{label} → {self._view_record(sv)['name']}",
                                SwErrors.swSuccess, self._view_record(sv))
        except Exception as e:
            logger.error(f"add_section_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_detail_view(self, parent_view: str, center: List[float], radius: float,
                        scale: str = "2:1", x: float = None, y: float = None,
                        label: str = "B") -> Dict:
        """Detail circle at sheet point `center` [x, y] mm (inside the parent view), radius mm."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            pv = self._find_view(drw, parent_view)
            if pv is None:
                return self._result(False, f"View '{parent_view}' not found", SwErrors.swInvalidInput)
            cx, cy = center[0] * MM, center[1] * MM
            r = radius * MM
            cu.call(drw, "ActivateView", parent_view)
            vx, vy = self._to_view_sketch(pv, cx, cy)
            circ = cu.call(drw, "SketchManager").CreateCircle(vx, vy, 0.0, vx + r, vy, 0.0)
            if circ is None:
                return self._result(False, "Could not sketch the detail circle", SwErrors.swSketchError)
            drw.ClearSelection2(True)
            circ.Select4(False, cu.nothing())
            n, d = _parse_scale(scale) or (2.0, 1.0)
            xmin, ymin, xmax, ymax = [float(v) for v in cu.as_list(cu.call(pv, "GetOutline"))[:4]]
            px = (x * MM) if x is not None else xmax + 0.04
            py = (y * MM) if y is not None else ymin
            dv = drw.CreateDetailViewAt4(px, py, 0.0, 0, float(n), float(d), label, 1, True, False, False, 5)
            if dv is None:
                return self._result(False, "Detail view failed", SwErrors.swFeatureError)
            cu.rebuild(drw)
            if x is None and y is None and self._relocate(drw, dv, (xmin, ymin, xmax, ymax)):
                cu.rebuild(drw)
            return self._result(True, f"Detail {label} ({n:g}:{d:g}) → {self._view_record(dv)['name']}",
                                SwErrors.swSuccess, self._view_record(dv))
        except Exception as e:
            logger.error(f"add_detail_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # annotations
    # ------------------------------------------------------------------

    def insert_model_annotations(self, types: List[str] = None, views: List[str] = None) -> Dict:
        """Import model items. Default: dimensions marked for drawing + hole callouts."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            types = types or ["dimensions_marked", "hole_callouts"]
            bad = [t for t in types if t not in _ANNOT]
            if bad:
                return self._result(False, f"Unknown types {bad}; use {sorted(_ANNOT)}", SwErrors.swInvalidInput)
            mask = 0
            for t in types:
                mask |= _ANNOT[t]
            all_views = not views
            if views:
                drw.ClearSelection2(True)
                for i, v in enumerate(views):
                    if not self._select_view(drw, v, i > 0):
                        return self._result(False, f"View '{v}' not found", SwErrors.swSelectionError)
            # Option 0 = swImportModelItemsFromEntireModel
            res = drw.InsertModelAnnotations3(0, mask, all_views, False, False, True)
            n = sum(len(cu.as_list(x)) if isinstance(x, (list, tuple)) else 1 for x in cu.as_list(res))
            cu.rebuild(drw)
            return self._result(True, f"Inserted {n} annotation(s): {', '.join(types)}", SwErrors.swSuccess,
                                {"count": n, "types": types, "views": views or "all"})
        except Exception as e:
            logger.error(f"insert_model_annotations error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def insert_bom(self, view: str = None, bom_type: str = "parts_only", template: str = None,
                   anchor: str = "top_right", configuration: str = "") -> Dict:
        """BOM table attached to a view (default: first view), placed at a sheet corner."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            vs = self._views(drw)
            v = self._find_view(drw, view) if view else (vs[0] if vs else None)
            if v is None:
                return self._result(False, "No view to attach the BOM to", SwErrors.swInvalidInput)
            tpl = self._bom_template(template)
            if not tpl:
                return self._result(False, "BOM template (.sldbomtbt) not found; pass template",
                                    SwErrors.swTemplateNotFound)
            info = self._sheet_info(drw)
            W, H = info["width"], info["height"]
            corner = {"top_left": (0.01, H - 0.01), "top_right": (W - 0.01, H - 0.01),
                      "bottom_left": (0.01, 0.01), "bottom_right": (W - 0.01, 0.01)}[anchor]
            t = v.InsertBomTable4(False, corner[0], corner[1], _ANCHORS[anchor], _BOM_TYPES[bom_type],
                                  configuration, tpl, False, 0, False)
            if t is None:
                return self._result(False, "InsertBomTable4 returned nothing", SwErrors.swFeatureError,
                                    {"template": tpl})
            rows = int(cu.try_call(t, "RowCount", default=0) or 0)
            cu.rebuild(drw)
            return self._result(True, f"BOM ({bom_type}) inserted, {rows} row(s)", SwErrors.swSuccess,
                                {"template": tpl, "rows": rows, "view": str(cu.try_call(v, "GetName2"))})
        except Exception as e:
            logger.error(f"insert_bom error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def auto_balloon(self, views: List[str] = None, layout: str = "square",
                     style: str = "circular") -> Dict:
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            layouts = {"square": 1, "circle": 2, "top": 3, "bottom": 4, "right": 5, "left": 6}
            styles = {"circular": 1, "triangle": 2, "hexagon": 3, "box": 4, "diamond": 5, "split_circle": 7}
            drw.ClearSelection2(True)
            names = views or [str(cu.try_call(v, "GetName2")) for v in self._views(drw)]
            for i, n in enumerate(names):
                self._select_view(drw, n, i > 0)
            opts = cu.call(drw, "CreateAutoBalloonOptions")
            opts.Layout = layouts.get(layout, 1)
            opts.Style = styles.get(style, 1)
            opts.IgnoreMultiple = True
            opts.UpperTextContent = 1    # item number
            res = cu.as_list(drw.AutoBalloon5(opts))
            cu.rebuild(drw)
            return self._result(bool(res), f"{len(res)} balloon(s)",
                                SwErrors.swSuccess if res else SwErrors.swFeatureError,
                                {"count": len(res), "views": names})
        except Exception as e:
            logger.error(f"auto_balloon error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------
    # sheets, notes, center marks
    # ------------------------------------------------------------------

    def add_sheet(self, name: str = None, scale: str = None, copy_format: bool = True) -> Dict:
        """
        New sheet using the current sheet's paper size and sheet format (title block),
        then make it active. IDrawingDoc.NewSheet4 (16 args).
        A sheet format path that no longer exists makes SolidWorks open a modal
        "Sheet Format/Size" dialog (which blocks COM), so the format embedded in the
        current sheet is exported with ISheet.SaveFormat and used instead.
        """
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            info = self._sheet_info(drw)
            p = info["props"]
            sc = _parse_scale(scale) or info["scale"]
            fmt = _sheet_format_file(info["sheet"], info["name"]) if copy_format else ""
            names = [str(n) for n in cu.as_list(cu.try_call(drw, "GetSheetNames"))]
            name = name or f"Sheet{len(names) + 1}"
            if name in names:
                return self._result(False, f"Sheet '{name}' exists", SwErrors.swInvalidInput)
            ok = drw.NewSheet4(name, int(p[0]), 12 if fmt else 13, float(sc[0]), float(sc[1]), bool(p[4]),
                               fmt, float(p[5]), float(p[6]), "Default", 0.0, 0.0, 0.0, 0.0, 0, 0)
            if not ok:
                return self._result(False, "NewSheet4 failed", SwErrors.swFeatureError)
            cu.try_call(drw, "ActivateSheet", name)
            return self._result(True, f"Sheet {name} added ({sc[0]:g}:{sc[1]:g})", SwErrors.swSuccess,
                                {"sheets": [str(n) for n in cu.as_list(cu.try_call(drw, "GetSheetNames"))],
                                 "format": fmt or None})
        except Exception as e:
            logger.error(f"add_sheet error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def activate_sheet(self, name: str) -> Dict:
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            ok = drw.ActivateSheet(name)
            return self._result(bool(ok), f"Active sheet: {self._sheet_info(drw)['name']}",
                                SwErrors.swSuccess if ok else SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_note(self, text: str, x: float, y: float) -> Dict:
        """Free text note at sheet position (x, y) mm. Use \\n for new lines."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            drw.ClearSelection2(True)
            note = drw.InsertNote(text)
            if note is None:
                return self._result(False, "InsertNote failed", SwErrors.swFeatureError)
            ann = cu.call(note, "GetAnnotation")
            ann.SetPosition2(x * MM, y * MM, 0.0)
            drw.ClearSelection2(True)
            cu.try_call(drw, "GraphicsRedraw2")
            return self._result(True, f"Note at ({x}, {y}) mm", SwErrors.swSuccess)
        except Exception as e:
            logger.error(f"add_note error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def insert_center_marks(self, views: List[str] = None, holes: bool = True, fillets: bool = False,
                            slots: bool = True) -> Dict:
        """IView.AutoInsertCenterMarks2 on the listed views (default: all)."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            kinds = (1 if holes else 0) | (2 if fillets else 0) | (4 if slots else 0)
            targets = [v for v in self._views(drw)
                       if not views or str(cu.try_call(v, "GetName2", default="")) in views]
            added, skipped = {}, []
            for v in targets:
                name = str(cu.try_call(v, "GetName2", default=""))
                before = _center_mark_count(v)
                if before:                       # already marked: avoid duplicates
                    skipped.append(name)
                    continue
                cu.try_call(v, "AutoInsertCenterMarks2", kinds, 0, True, True, True, 0.0025, 0.0015,
                            True, True, 0.0)
                n = _center_mark_count(v) - before
                if n > 0:
                    added[name] = n
            cu.rebuild(drw)
            total = sum(added.values())
            msg = f"{total} center mark(s) in {len(added)} view(s)" + (
                f"; {len(skipped)} view(s) already had marks" if skipped else "")
            return self._result(bool(added) or bool(skipped), msg,
                                SwErrors.swSuccess if added or skipped else SwErrors.swFeatureError,
                                {"added": added, "skipped": skipped})
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)


def _center_mark_count(view) -> int:
    n, cm = 0, cu.try_call(view, "GetFirstCenterMark2")
    while cm is not None and n < 10000:
        n += 1
        cm = cu.try_call(cm, "GetNext")
    return n


def _sheet_format_file(sheet, sheet_name: str) -> str:
    """Existing .slddrt for `sheet`; exports the embedded format when the file is missing."""
    import tempfile
    path = str(cu.try_call(sheet, "GetTemplateName", default="") or "")
    if path and os.path.isfile(path):
        return path
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in sheet_name)
    tmp = os.path.join(tempfile.gettempdir(), f"swmcp_fmt_{safe}.slddrt")
    if cu.try_call(sheet, "SaveFormat", tmp, default=False) and os.path.isfile(tmp):
        return tmp
    return ""
