"""
Drawing: revision table, hole table, auxiliary view, broken-out section
------------------------------------------------------------------------
  ISheet.RevisionTable / ISheet.InsertRevisionTable2(UseAnchorPoint, X, Y, AnchorType,
      TableTemplate, Shape, AutoUpdateZoneCells)
  IRevisionTableAnnotation.AddRevision(Revision) -> row id (GetIdForRowNumber)
  IView.InsertHoleTable2(UseAnchorPoint, X, Y, AnchorType, StartValue, TableTemplate)
      with the origin vertex selected (mark 1) and the hole face(s) (mark 2)
  IDrawingDoc.CreateAuxiliaryViewAt2(X, Y, Z, NotAligned, Label, ShowArrow, Flip)
      with a view edge selected
  IDrawingDoc.CreateBreakOutSection(Depth) with a closed sketch profile selected

Notes verified on SW 2026:
  - Entities from IView.GetVisibleEntities2 are selected with Select4 and a
    SelectData whose View is that view (marks are honoured).
    swViewEntityType_e: Edge 1, Vertex 2, Face 3.
  - Edge GetCurveParams2 is in model space (map with ModelToViewTransform);
    vertex GetPoint is the model point + view translation, unrotated
    (sheet = ModelToViewTransform(raw - T)).
  - Only one revision table per sheet; templates often include one already.
  - ITableAnnotation.Text(row, col) is set with a DISPATCH_PROPERTYPUT invoke.
"""

import re
import math
import logging
import traceback
from typing import Dict, List, Optional

import pythoncom

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

MM = 0.001
_ANCHOR = {"top_left": 1, "top_right": 2, "bottom_left": 3, "bottom_right": 4}
_SHAPE = {"circle": 1, "square": 2, "triangle": 3, "hexagon": 4}


def _plain(s) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def _set_cell(table, row: int, col: int, text: str):
    ole = table._oleobj_
    did = ole.GetIDsOfNames("Text")
    ole.Invoke(did, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, row, col, text)


def _table_rows(t) -> List[List[str]]:
    return [[_plain(cu.try_call(t, "Text", r, c, default="")) for c in range(int(t.ColumnCount))]
            for r in range(int(t.RowCount))]


class DrawingPlusOperations:
    """Mixin. Requires DrawingOperations helpers (_require_drawing, _find_view, _views, _sheet_info,
    _to_view_sketch, _relocate, _table_template)."""

    # ------------------------------------------------------------------ helpers
    def _view_or_error(self, drw, name: Optional[str], prefer_type=None):
        if name:
            v = self._find_view(drw, name)
            if v is None:
                raise ValueError(f"View '{name}' not found (list_drawing_views)")
            return v
        views = self._views(drw)
        if not views:
            raise ValueError("The sheet has no views")
        return views[0]

    def _sheet_point(self, view, p):
        """Point from a view entity -> sheet (m): model->view transform, or raw if that lands outside."""
        ol = [float(x) for x in cu.as_list(cu.try_call(view, "GetOutline"))[:4]]
        xf = cu.try_call(view, "ModelToViewTransform")
        cands = []
        if xf is not None:
            try:
                cands.append(cu.transform_point(xf, p[:3]))
            except Exception:  # noqa: BLE001
                pass
        cands.append(list(p[:3]))
        tol = 0.002
        for c in cands:
            if ol and ol[0] - tol <= c[0] <= ol[2] + tol and ol[1] - tol <= c[1] <= ol[3] + tol:
                return c
        return cands[0]

    def _vertex_sheet_points(self, view, verts) -> List[List[float]]:
        """
        Sheet positions of view vertices. On SW 2026 IVertex.GetPoint (from
        GetVisibleEntities2) returns the model point already offset by the view's
        translation but NOT rotated, so: sheet = ModelToViewTransform(raw - T).
        (Feeding raw straight into the transform, or using raw as sheet coordinates,
        put a hole-table origin in the wrong corner.)
        """
        xf = cu.try_call(view, "ModelToViewTransform")
        raw = [[float(c) for c in cu.as_list(cu.call(p, "GetPoint"))[:3]] for p in verts]
        if xf is None:
            return raw
        t = [float(c) for c in cu.as_list(xf.ArrayData)[9:12]]
        return [cu.transform_point(xf, [q[i] - t[i] for i in range(3)]) for q in raw]

    def _select_in_view(self, drw, view, entity, append: bool, mark: int = 0) -> bool:
        sd = drw.SelectionManager.CreateSelectData
        sd.View = view
        if mark:
            sd.Mark = mark
        return bool(entity.Select4(append, sd))

    # ------------------------------------------------------------------ revision
    def add_revision(self, revision: str, description: str = "", approved: str = "",
                     template: str = None, anchor: str = "top_right") -> Dict:
        """Add a revision row (date filled automatically). Inserts a revision table if the sheet has none."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            sheet = cu.call(drw, "GetCurrentSheet")
            t = cu.try_call(sheet, "RevisionTable")
            inserted = False
            if t is None:
                tpl = self._table_template("sldrevtbt", template, ("revision", "standard"))
                if not tpl:
                    return self._result(False, "Revision table template (.sldrevtbt) not found; pass template",
                                        SwErrors.swTemplateNotFound)
                t = sheet.InsertRevisionTable2(False, 0.0, 0.0, _ANCHOR.get(anchor, 2), tpl, 1, True)
                if t is None:
                    return self._result(False, "InsertRevisionTable2 failed", SwErrors.swFeatureError,
                                        {"template": tpl})
                inserted = True
            rid = t.AddRevision(str(revision))
            if not rid or int(rid) <= 0:
                return self._result(False, f"AddRevision('{revision}') failed (duplicate?)", SwErrors.swFeatureError)
            rows = _table_rows(t)
            hdr = next((r for r, cells in enumerate(rows) if "revision" in [c.lower() for c in cells]), None)
            row = next((r for r in range(len(rows)) if cu.try_call(t, "GetIdForRowNumber", r) == rid), None)
            if hdr is not None and row is not None:
                cols = {c.lower(): i for i, c in enumerate(rows[hdr])}
                dcol = next((cols[k] for k in ("description", "reason", "desc", "change") if k in cols), None)
                if description and dcol is not None:
                    _set_cell(t, row, dcol, description)
                acol = next((cols[k] for k in ("approved", "approval", "by") if k in cols), None)
                if approved and acol is not None:
                    _set_cell(t, row, acol, approved)
            cu.rebuild(drw)
            final = _table_rows(t)
            return self._result(True, f"Revision {revision} added" + (" (table inserted)" if inserted else ""),
                                SwErrors.swSuccess, {"row": final[row] if row is not None else None,
                                                     "table": final})
        except Exception as e:
            logger.error(f"add_revision error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------ hole table
    def insert_hole_table(self, view: str = None, x: float = None, y: float = None,
                          template: str = None, start_tag: str = "A") -> Dict:
        """
        Hole table of the view's hole face (the face with most loops), origin at
        the bottom-left vertex of the view. x, y = table top-left on the sheet (mm).
        """
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            if view:
                v = self._view_or_error(drw, view)
            else:                                   # the view showing the face with most holes
                def holes(vw):
                    fs = cu.as_list(cu.try_call(vw, "GetVisibleEntities2", cu.nothing(), 3))
                    return max([int(cu.try_call(f, "GetLoopCount", default=0) or 0) for f in fs] or [0])
                cands = [(holes(vw), vw) for vw in self._views(drw)]
                if not cands:
                    raise ValueError("The sheet has no views")
                v = max(cands, key=lambda t: t[0])[1]
            tpl = self._table_template("sldholtbt", template, ("hole", "standard"))
            if not tpl:
                return self._result(False, "Hole table template (.sldholtbt) not found; pass template",
                                    SwErrors.swTemplateNotFound)
            verts = cu.as_list(v.GetVisibleEntities2(cu.nothing(), 2))
            faces = cu.as_list(v.GetVisibleEntities2(cu.nothing(), 3))
            if not verts or not faces:
                return self._result(False, "No vertices / faces visible in the view", SwErrors.swSelectionError)
            pts = sorted(zip(self._vertex_sheet_points(v, verts), verts), key=lambda t: t[0][0] + t[0][1])
            face = max(faces, key=lambda f: int(cu.try_call(f, "GetLoopCount", default=0) or 0))
            if int(cu.try_call(face, "GetLoopCount", default=0) or 0) < 2:
                return self._result(False, "No face with holes visible in this view", SwErrors.swSelectionError)
            drw.ClearSelection2(True)
            if not (self._select_in_view(drw, v, pts[0][1], False, 1)
                    and self._select_in_view(drw, v, face, True, 2)):
                return self._result(False, "Could not select origin / face", SwErrors.swSelectionError)
            info = self._sheet_info(drw)
            tx = x * MM if x is not None else 0.015
            ty = y * MM if y is not None else info["height"] - 0.015
            ht = v.InsertHoleTable2(True, tx, ty, 1, start_tag or "A", tpl)
            drw.ClearSelection2(True)
            if ht is None:
                return self._result(False, "InsertHoleTable2 failed", SwErrors.swFeatureError, {"template": tpl})
            rows = _table_rows(ht)
            return self._result(True, f"Hole table: {max(len(rows) - 1, 0)} hole(s)", SwErrors.swSuccess,
                                {"template": tpl, "rows": rows,
                                 "origin_mm": [round(c / MM, 2) for c in pts[0][0][:2]]})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"insert_hole_table error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------ auxiliary view
    def add_auxiliary_view(self, parent_view: str, edge_point: List[float] = None, label: str = None) -> Dict:
        """
        Auxiliary view normal to an inclined edge of `parent_view`. edge_point [x, y]
        (sheet mm) picks the edge nearest that point; default = the longest inclined edge.
        """
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            v = self._view_or_error(drw, parent_view)
            xf = cu.try_call(v, "ModelToViewTransform")
            best = None
            for e in cu.as_list(v.GetVisibleEntities2(cu.nothing(), 1)):
                p = cu.as_list(cu.try_call(e, "GetCurveParams2"))
                if len(p) < 6:
                    continue
                a = self._sheet_point(v, p[0:3]) if xf is not None else p[0:3]
                b = self._sheet_point(v, p[3:6]) if xf is not None else p[3:6]
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = math.hypot(dx, dy)
                if length < 1e-4:
                    continue
                if edge_point:
                    q = (edge_point[0] * MM, edge_point[1] * MM)
                    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (length ** 2)))
                    score = -math.hypot(a[0] + t * dx - q[0], a[1] + t * dy - q[1])
                else:
                    ang = math.degrees(math.atan2(abs(dy), abs(dx)))
                    if min(ang, 90 - ang) < 0.5:
                        continue
                    score = length
                if best is None or score > best[0]:
                    best = (score, e)
            if best is None:
                return self._result(False, "No inclined edge in this view (give edge_point)", SwErrors.swSelectionError)
            drw.ClearSelection2(True)
            if not self._select_in_view(drw, v, best[1], False):
                return self._result(False, "Could not select the edge", SwErrors.swSelectionError)
            ol = [float(c) for c in cu.as_list(v.GetOutline)[:4]]
            av = drw.CreateAuxiliaryViewAt2(ol[2] + 0.03, (ol[1] + ol[3]) / 2, 0.0, False, label or "", True, False)
            drw.ClearSelection2(True)
            if av is None:
                return self._result(False, "CreateAuxiliaryViewAt2 failed", SwErrors.swFeatureError)
            self._relocate(drw, av, ol)
            cu.rebuild(drw)
            return self._result(True, f"Auxiliary view {av.GetName2}", SwErrors.swSuccess,
                                self._view_record(av))
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_auxiliary_view error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    # ------------------------------------------------------------------ broken-out section
    def add_broken_out_section(self, view: str, center: List[float], radius: float, depth: float) -> Dict:
        """Circular broken-out section: centre [x, y] on the sheet (mm), radius (sheet mm), depth (model mm)."""
        try:
            drw, err = self._require_drawing()
            if err:
                return err
            v = self._view_or_error(drw, view)
            name = str(v.GetName2)
            if not drw.ActivateView(name):
                return self._result(False, f"Cannot activate view {name}", SwErrors.swUnknownError)
            vx, vy = self._to_view_sketch(v, center[0] * MM, center[1] * MM)
            sm = drw.SketchManager
            c = sm.CreateCircleByRadius(vx, vy, 0.0, radius * MM)
            if c is None:
                return self._result(False, "Could not sketch the profile", SwErrors.swSketchError)
            drw.ClearSelection2(True)
            c.Select4(False, cu.nothing())
            ok = drw.CreateBreakOutSection(depth * MM)
            drw.ClearSelection2(True)
            cu.rebuild(drw)
            if not ok:
                return self._result(False, "CreateBreakOutSection failed (profile must be inside the view)",
                                    SwErrors.swFeatureError)
            return self._result(True, f"Broken-out section in {name}, depth {depth} mm", SwErrors.swSuccess,
                                {"view": name})
        except ValueError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_broken_out_section error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
