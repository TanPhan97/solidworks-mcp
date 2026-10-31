"""
Part tools for mold making and 3D printing
------------------------------------------
Sketch text, scale (shrinkage), multi-body management (list / combine / split /
delete) and cosmetic threads. Signatures from the SOLIDWORKS 2026 type library:

  IModelDoc2.InsertSketchText(Ptx, Pty, Ptz, Text, Alignment, FlipDirection,
                              HorizontalMirror, WidthFactor, SpaceBetweenChars)
  IFeatureManager.InsertScale(Type, Uniform, Xscale, YScale, ZScale)          swScaleType_e
  IFeatureManager.InsertCombineFeature(OperationType, MainBody, ToolVar)      swBodyOperationType_e
  IFeatureManager.PreSplitBody() / PostSplitBody(BodiesToMark, ConsumeCut, Origins, SavePaths)
  IFeatureManager.InsertDeleteBody2(KeepBodies)
  IFeatureManager.InsertCosmeticThread3(Standard, StandardType, Size, Diameter, EndType, Depth, Note)

Verified live on SW 2026: PostSplitBody needs Origins / SavePaths arrays with one
(null / empty) entry per body; in ISO mode InsertCosmeticThread3 ignores Size and
picks a size from the geometry, so threads are created in non-standard mode with
an explicit diameter and callout.
"""

import re
import logging
import traceback
from typing import Dict, List

import pythoncom
import win32com.client

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_SCALE_ABOUT = {"centroid": 0, "origin": 1}
_COMBINE = {"add": 15903, "subtract": 15902, "common": 15901}
_ALIGN = {"left": 0, "center": 1, "right": 2, "full": 3}
_THREAD_END = {"blind": 0, "up_to_next": 1, "through": 2}
# ISO coarse pitch for "M6" style sizes without an explicit pitch
_ISO_COARSE = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5,
               12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5}


def _dispatch_array(objs):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(objs))


def parse_metric(size: str):
    """'M6x1.0' / 'M6' / 'm8x1.25' -> (major_mm, pitch_mm); None if not metric."""
    m = re.fullmatch(r"\s*[mM]\s*(\d+(?:\.\d+)?)\s*(?:[xX×]\s*(\d+(?:\.\d+)?))?\s*", size or "")
    if not m:
        return None
    d = float(m.group(1))
    p = float(m.group(2)) if m.group(2) else _ISO_COARSE.get(d if d != int(d) else int(d))
    return (d, p) if p else None


class PartMoldOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _select_ref(), _require_active_sketch()"""

    # ------------------------------------------------------------------ helpers
    def _require_part(self, doc):
        if cu.doc_type(doc) != 1:
            raise RuntimeError("Active document is not a part")

    def _bodies(self, doc) -> List:
        return cu.as_list(cu.try_call(doc, "GetBodies2", 0, True))     # swSolidBody, visible only

    def _body_info(self, i, b, unit) -> Dict:
        mp = cu.as_list(cu.try_call(b, "GetMassProperties", 1.0))    # [cx, cy, cz, V, A, m, ...]
        f = self._units.from_meters(1.0, unit)
        return {"index": i, "name": str(cu.try_call(b, "Name", default="")),
                "faces": int(cu.try_call(b, "GetFaceCount", default=0) or 0),
                "volume": round(mp[3] * f ** 3, 4) if len(mp) > 3 else None,
                "centroid": [round(v * f, 4) for v in mp[:3]] if len(mp) > 2 else None}

    def _find_body(self, doc, ref):
        bodies = self._bodies(doc)
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            i = int(ref)
            return bodies[i] if 0 <= i < len(bodies) else None
        for b in bodies:
            if str(cu.try_call(b, "Name", default="")) == str(ref):
                return b
        return None

    # ------------------------------------------------------------------ tools
    def sketch_text(self, text: str, x: float = 0.0, y: float = 0.0, height: float = 5.0,
                    font: str = None, bold: bool = False, italic: bool = False,
                    alignment: str = "left", width_factor: float = 100.0, spacing: float = 0.0,
                    unit: str = None) -> Dict:
        """Text in the active sketch at sketch point (x, y); extrude / cut it afterwards."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            if not text:
                return self._result(False, "text is required", SwErrors.swInvalidInput)
            px, py = self._units.to_meters(x, unit), self._units.to_meters(y, unit)
            st = doc.InsertSketchText(px, py, 0.0, text, _ALIGN.get(alignment, 0), 0, 0,
                                      int(width_factor), int(spacing))
            if st is None:
                return self._result(False, "InsertSketchText failed", SwErrors.swSketchError)
            tf = cu.try_call(st, "GetTextFormat")
            if tf is not None:
                tf.CharHeight = self._units.to_meters(height, unit)
                if font:
                    tf.TypeFaceName = font
                tf.Bold, tf.Italic = bool(bold), bool(italic)
                cu.try_call(st, "SetTextFormat", False, tf)
            cu.try_call(doc, "GraphicsRedraw2")
            return self._result(True, f"Text '{text}' h={height} at ({x}, {y})", SwErrors.swSuccess,
                                {"text": text, "height": height})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"sketch_text error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def scale_part(self, factor: float = None, x: float = None, y: float = None, z: float = None,
                   about: str = "centroid") -> Dict:
        """Scale feature: uniform `factor` (e.g. 1.006 for 0.6 % shrinkage) or per-axis x/y/z."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            cu.close_active_sketch(doc)
            uniform = factor is not None
            sx, sy, sz = (factor,) * 3 if uniform else tuple(1.0 if v is None else v for v in (x, y, z))
            if min(sx, sy, sz) <= 0:
                return self._result(False, "Scale factors must be > 0", SwErrors.swInvalidInput)
            v0 = cu.try_call(cu.try_call(doc.Extension, "CreateMassProperty"), "Volume", default=None)
            doc.ClearSelection2(True)
            feat = doc.FeatureManager.InsertScale(_SCALE_ABOUT.get(about, 0), uniform, sx, sy, sz)
            if feat is None:
                return self._result(False, "Scale failed", SwErrors.swFeatureError)
            v1 = cu.try_call(cu.try_call(doc.Extension, "CreateMassProperty"), "Volume", default=None)
            ratio = round(v1 / v0, 6) if v0 and v1 else None
            return self._result(True, f"{feat.Name}: ×{sx:g}, {sy:g}, {sz:g} about {about}",
                                SwErrors.swSuccess, {"feature": str(feat.Name), "volume_ratio": ratio})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"scale_part error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def list_bodies(self, kind: str = "solid", unit: str = None) -> Dict:
        """kind: solid (indices used by combine / delete_body), surface, or all."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            out = []
            if kind in ("solid", "all"):
                out += [dict(self._body_info(i, b, unit), kind="solid") for i, b in enumerate(self._bodies(doc))]
            if kind in ("surface", "all"):
                sheets = cu.as_list(cu.try_call(doc, "GetBodies2", 1, True))
                out += [{"index": i, "name": str(cu.try_call(b, "Name", default="")), "kind": "surface",
                         "faces": int(cu.try_call(b, "GetFaceCount", default=0) or 0)} for i, b in enumerate(sheets)]
            return self._result(True, f"{len(out)} {kind} bod{'y' if len(out) == 1 else 'ies'}",
                                SwErrors.swSuccess, {"bodies": out,
                                                     "unit": unit or self._units.default_unit.value})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def combine_bodies(self, main_body, tool_bodies: List, operation: str = "add") -> Dict:
        """Combine: add / subtract (tool bodies from main) / common. Bodies by name or index."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            op = _COMBINE.get(operation)
            if op is None:
                return self._result(False, f"operation must be one of {sorted(_COMBINE)}", SwErrors.swInvalidInput)
            main = self._find_body(doc, main_body)
            tools = [self._find_body(doc, t) for t in tool_bodies or []]
            if main is None or not tools or any(t is None for t in tools):
                return self._result(False, "Body not found (list_bodies)", SwErrors.swInvalidInput,
                                    {"bodies": [str(b.Name) for b in self._bodies(doc)]})
            doc.ClearSelection2(True)
            feat = doc.FeatureManager.InsertCombineFeature(op, main, _dispatch_array(tools))
            if feat is None:
                return self._result(False, "Combine failed (bodies must touch / overlap for add/common)",
                                    SwErrors.swFeatureError)
            return self._result(True, f"{feat.Name}: {operation} → {len(self._bodies(doc))} bod(ies)",
                                SwErrors.swSuccess, {"feature": str(feat.Name),
                                                     "bodies": [str(b.Name) for b in self._bodies(doc)]})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"combine_bodies error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def split_body(self, tool: Dict, unit: str = None) -> Dict:
        """Split the solid bodies with a plane / planar face (reference spec)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            cu.close_active_sketch(doc)
            n0 = len(self._bodies(doc))
            doc.ClearSelection2(True)
            if not self._select_ref(doc, tool, False, 0, unit):
                return self._result(False, f"Could not select split tool {tool}", SwErrors.swSelectionError)
            fm = doc.FeatureManager
            res = cu.as_list(cu.try_call(fm, "PreSplitBody"))
            if not res:
                return self._result(False, "The tool does not cut any body", SwErrors.swFeatureError)
            n = len(res)
            feat = fm.PostSplitBody(_dispatch_array(res), False, _dispatch_array([None] * n),
                                    win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [""] * n))
            if feat is None:
                return self._result(False, "Split failed", SwErrors.swFeatureError)
            bodies = [str(b.Name) for b in self._bodies(doc)]
            return self._result(True, f"{feat.Name}: {n0} → {len(bodies)} bodies", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "bodies": bodies})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"split_body error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def delete_body(self, bodies: List, keep: bool = False) -> Dict:
        """Delete the listed bodies (or keep only them with keep=true). Names or indices."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            objs = [self._find_body(doc, b) for b in bodies or []]
            if not objs or any(o is None for o in objs):
                return self._result(False, "Body not found (list_bodies)", SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            for i, o in enumerate(objs):
                o.Select2(i > 0, 0)
            feat = doc.FeatureManager.InsertDeleteBody2(bool(keep))
            if feat is None:
                return self._result(False, "Delete/Keep body failed", SwErrors.swFeatureError)
            left = [str(b.Name) for b in self._bodies(doc)]
            return self._result(True, f"{feat.Name}: {len(left)} bod(ies) left", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "bodies": left})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"delete_body error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def cosmetic_thread(self, edge: Dict, size: str = None, diameter: float = None, depth: float = None,
                        end: str = "blind", internal: bool = False, callout: str = None,
                        unit: str = None) -> Dict:
        """
        Cosmetic thread on a circular edge. size 'M6x1.0' / 'M6' computes the thread
        diameter (external: minor = D - 1.22687·P; internal: major = D); or give diameter.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_part(doc)
            cu.close_active_sketch(doc)
            if size:
                mp = parse_metric(size)
                if mp is None:
                    return self._result(False, f"Size {size!r} not understood (use 'M6x1.0' or diameter)",
                                        SwErrors.swInvalidInput)
                d_mm = mp[0] if internal else round(mp[0] - 1.22687 * mp[1], 3)
                dia = d_mm / 1000.0
                given = size.strip().upper().replace(" ", "").replace("×", "X")
                callout = callout or (given.replace("X", "x") if "X" in given else f"M{mp[0]:g}x{mp[1]:g}")
            elif diameter:
                dia = self._units.to_meters(diameter, unit)
            else:
                return self._result(False, "Give size (e.g. 'M6x1.0') or diameter", SwErrors.swInvalidInput)
            end_t = _THREAD_END.get(end, 0)
            if end_t == 0 and not depth:
                return self._result(False, "depth is required for a blind thread", SwErrors.swInvalidInput)
            dep = self._units.to_meters(depth, unit) if depth else 0.0
            doc.ClearSelection2(True)
            if not self._select_ref(doc, edge, False, 0, unit):
                return self._result(False, f"Could not select edge {edge}", SwErrors.swSelectionError)
            feat = doc.FeatureManager.InsertCosmeticThread3(0, "", "", dia, end_t, dep, callout or "")
            if feat is None:
                return self._result(False, "Cosmetic thread failed (select a circular edge)", SwErrors.swFeatureError)
            return self._result(True, f"{feat.Name}: {callout or ''} Ø{dia * 1000:g} mm "
                                      f"{'internal' if internal else 'external'}", SwErrors.swSuccess,
                                {"feature": str(feat.Name), "diameter_mm": round(dia * 1000, 4),
                                 "callout": callout})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"cosmetic_thread error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)
