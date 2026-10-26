"""
COM late-binding helpers
------------------------
SolidWorks exposes some zero-argument members as properties and others as
methods, and the split differs between versions when accessed through
pywin32 dynamic dispatch. These helpers hide that difference and provide the
VARIANT wrappers needed for ByRef / empty / array parameters.
"""

import os
import types
import logging
from typing import Any, List, Sequence

import win32com.client
import pythoncom

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Member access
# ----------------------------------------------------------------------------

def call(obj, name: str, *args):
    """
    Read a COM member that may be a property or a method.

    - With args: always invoked.
    - Without args: invoked only if pywin32 returned a bound method; a
      CDispatch value (which is itself callable) is returned untouched.
    """
    attr = getattr(obj, name)
    if args or isinstance(attr, types.MethodType):
        return attr(*args)
    return attr


def invoke_method(obj, name: str, *args):
    """
    Call a COM *method* through IDispatch with DISPATCH_METHOD. Needed for objects
    that expose no type info (IMeasure, IMathUtility on SW 2026): pywin32 then reads
    `obj.Name` as a property get, so `obj.Name(args)` fails with 'Member not found'
    or "'bool' object is not callable".
    """
    ole = obj._oleobj_
    dispid = ole.GetIDsOfNames(name)
    return ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True, *args)


def try_call(obj, name: str, *args, default=None):
    """call() that returns `default` instead of raising."""
    try:
        return call(obj, name, *args)
    except Exception as e:  # noqa: BLE001 - COM raises pywintypes.com_error
        logger.debug(f"try_call {name} failed: {e}")
        return default


def first_ok(*attempts, log_prefix: str = ""):
    """
    Run zero-arg callables in order, return (result, index) of the first one
    that returns a truthy value without raising. (None, -1) if all fail.
    """
    for i, fn in enumerate(attempts):
        try:
            r = fn()
            if r:
                return r, i
        except Exception as e:  # noqa: BLE001
            logger.debug(f"{log_prefix} attempt {i} failed: {e}")
    return None, -1


# ----------------------------------------------------------------------------
# VARIANT helpers
# ----------------------------------------------------------------------------

def nothing():
    """VBA `Nothing` for object parameters (e.g. Callout)."""
    return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


def empty():
    """Empty Variant for optional array parameters."""
    return win32com.client.VARIANT(pythoncom.VT_EMPTY, None)


def byref_int(value: int = 0):
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, value)


def byref_str(value: str = ""):
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, value)


def byref_bool(value: bool = False):
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, value)


def double_array(values: Sequence[float]):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                   [float(v) for v in values])


def as_list(value) -> List[Any]:
    """Normalize COM SAFEARRAY results (tuple / None / scalar) to a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ----------------------------------------------------------------------------
# Selection helpers
# ----------------------------------------------------------------------------

def select_by_id(doc, name: str, sel_type: str, x: float = 0.0, y: float = 0.0,
                 z: float = 0.0, append: bool = False, mark: int = 0) -> bool:
    """IModelDocExtension::SelectByID2 with the Callout fallback chain."""
    ext = doc.Extension
    for callout in (nothing(), pythoncom.Nothing):
        try:
            if ext.SelectByID2(name, sel_type, x, y, z, append, mark, callout, 0):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"SelectByID2({name!r},{sel_type}) failed: {e}")
    return False


def select_entity_object(doc, entity, append: bool, mark: int) -> bool:
    """IEntity::Select4 with a SelectData carrying the mark."""
    try:
        sel_mgr = call(doc, "SelectionManager")
        sel_data = call(sel_mgr, "CreateSelectData")
        sel_data.Mark = mark
        return bool(entity.Select4(append, sel_data))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Select4 failed: {e}")
        return False


def selected_count(doc) -> int:
    try:
        return int(call(call(doc, "SelectionManager"), "GetSelectedObjectCount2", -1))
    except Exception:  # noqa: BLE001
        return 0


# ----------------------------------------------------------------------------
# Sketch space <-> model space
# ----------------------------------------------------------------------------

def transform_point(xform, p, inverse: bool = False) -> List[float]:
    """
    Apply an IMathTransform to point p (metres) using its ArrayData:
    [R (3x3, row-major), T (3), scale, unused (3)], row-vector convention
    p' = s * (p . R) + T   (verified on SOLIDWORKS 2026).
    Computed in Python because IMathUtility.CreatePoint is not callable through
    pywin32 late binding (the object exposes no type info -> 'Member not found').
    """
    a = [float(v) for v in as_list(call(xform, "ArrayData"))]
    R = [a[0:3], a[3:6], a[6:9]]
    T, s = a[9:12], (a[12] or 1.0)
    if not inverse:
        return [s * sum(p[i] * R[i][j] for i in range(3)) + T[j] for j in range(3)]
    q = [(p[j] - T[j]) / s for j in range(3)]
    return [sum(q[j] * R[i][j] for j in range(3)) for i in range(3)]   # q . R^T


def sketch_to_model(sw_app, doc, x: float, y: float, z: float = 0.0) -> List[float]:
    """
    Active-sketch coordinates -> model coordinates (metres). SelectByID2 works in
    model space; SketchManager.Create* in sketch space. Identity if no sketch.
    """
    try:
        sketch = call(doc.SketchManager, "ActiveSketch")
        if sketch is None:
            return [x, y, z]
        return transform_point(call(sketch, "ModelToSketchTransform"), [x, y, z], inverse=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"sketch_to_model fell back to identity: {e}")
        return [x, y, z]


def model_to_sketch(sketch, p) -> List[float]:
    """Model point (metres) -> coordinates in `sketch` (an ISketch)."""
    return transform_point(call(sketch, "ModelToSketchTransform"), list(p))


def set_dimension_value(dim, value_si: float) -> bool:
    """
    Set an IDimension value in SI units (m / rad) for the active configuration.
    SetSystemValue3 returns swSetValueReturnStatus_e (0 = success).
    """
    try:
        status = dim.SetSystemValue3(value_si, 1, empty())   # swSetValue_InThisConfiguration
        if status == 0 or status is None:
            return True
        logger.debug(f"SetSystemValue3 status={status}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"SetSystemValue3 failed: {e}")
    try:
        dim.SystemValue = value_si
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug(f"SystemValue setter failed: {e}")
        return False


def merge_sketch_endpoints(doc, tol: float = 1e-8) -> int:
    """
    Merge coincident endpoints of the ACTIVE sketch (sgMERGEPOINTS).

    With sketch inference off (common with API sketching), separate Create*
    calls leave duplicate points where segments meet: a line + arc path or a
    polyline profile is then *not connected*, and sweeps / extrusions of it
    fail. Verified on SW 2026: a line+arc sweep path failed until the shared
    endpoint was merged. Returns the number of merged point groups.
    """
    sketch = try_call(doc.SketchManager, "ActiveSketch")
    if sketch is None:
        return 0
    ends = []
    for seg in as_list(try_call(sketch, "GetSketchSegments")):
        for name in ("GetStartPoint2", "GetEndPoint2"):
            p = try_call(seg, name)
            if p is not None:
                ends.append(p)
    groups = []
    for p in ends:
        try:
            xyz = (float(call(p, "X")), float(call(p, "Y")), float(call(p, "Z")))
        except Exception:  # noqa: BLE001
            continue
        for g in groups:
            if all(abs(a - b) <= tol for a, b in zip(g[0], xyz)):
                g[1].append(p)
                break
        else:
            groups.append((xyz, [p]))
    merged = 0
    for _xyz, pts in groups:
        if len(pts) < 2:
            continue
        doc.ClearSelection2(True)
        if all(select_entity_object(doc, p, i > 0, 0) for i, p in enumerate(pts)):
            try:
                doc.SketchAddConstraints("sgMERGEPOINTS")
                merged += 1
            except Exception as e:  # noqa: BLE001
                logger.debug(f"merge points failed: {e}")
    if merged:
        doc.ClearSelection2(True)
    return merged


def close_active_sketch(doc) -> bool:
    """Merge coincident endpoints, then exit the active sketch. True if one was open."""
    if try_call(doc.SketchManager, "ActiveSketch") is None:
        return False
    merge_sketch_endpoints(doc)
    try:
        doc.SketchManager.InsertSketch(True)
    except Exception:  # noqa: BLE001
        try_call(doc, "InsertSketch2", True)
    return True


def open_doc_paths(sw_app) -> set:
    """normcase'd paths of every document SolidWorks has loaded (incl. referenced)."""
    out = set()
    for d in as_list(try_call(sw_app, "GetDocuments")):
        p = str(try_call(d, "GetPathName", default="") or "")
        if p:
            out.add(os.path.normcase(os.path.abspath(p)))
    return out


def find_open_doc(sw_app, path: str):
    """Loaded document for `path` (by full path, then by scanning GetDocuments)."""
    doc = try_call(sw_app, "GetOpenDocumentByName", path)
    if doc is not None:
        return doc
    key = os.path.normcase(os.path.abspath(path))
    for d in as_list(try_call(sw_app, "GetDocuments")):
        p = str(try_call(d, "GetPathName", default="") or "")
        if p and os.path.normcase(os.path.abspath(p)) == key:
            return d
    return None


_MESH_EXTS = {".stl", ".3mf", ".amf", ".wrl"}
# swUserPreferenceToggle_e (SW 2026 swconst.tlb)
_STL_ONE_FILE, _STL_INFO_DIALOG, _STL_PREVIEW = 72, 70, 191
_PDF_VIEW_ON_SAVE = 617          # swPDFViewOnSave: opens the PDF in a viewer, which locks it


def save_copy(sw_app, doc, path: str):
    """
    Save a copy of `doc` to `path` (format from extension), document keeps its
    own path. For mesh formats the STL info / preview dialogs (which block COM)
    are switched off and assembly components are merged into one file; for PDF
    "view on save" is switched off (the viewer locks the file); the selection is
    cleared (otherwise only selected entities are exported). User preferences are
    restored afterwards. Returns (ok, errors, warnings); errors is a str when the
    target file is locked.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if os.path.exists(path):
        try:
            open(path, "r+b").close()
        except OSError:
            return False, "target file is locked (open in another program)", None
    saved_prefs = {}
    prev_active = None
    ext = os.path.splitext(path)[1].lower()
    mesh = ext in _MESH_EXTS and sw_app is not None
    toggles = []
    if mesh:
        toggles = [(_STL_INFO_DIALOG, False), (_STL_PREVIEW, False), (_STL_ONE_FILE, True)]
    elif ext == ".pdf" and sw_app is not None:
        toggles = [(_PDF_VIEW_ON_SAVE, False)]
    for key, val in toggles:
        old = try_call(sw_app, "GetUserPreferenceToggle", key)
        if old is not None:
            saved_prefs[key] = bool(old)
            try_call(sw_app, "SetUserPreferenceToggle", key, val)
    # A leftover selection (e.g. a face from the last feature) makes STEP / STL
    # export only the selected entities: SW 2026 wrote a 4.5 KB STEP of a plate.
    try_call(doc, "ClearSelection2", True)
    if mesh:
        # The mesh translator exports the ACTIVE document, not `doc` (SW 2026: an STL
        # "of a part" contained the components of the active assembly).
        active = try_call(sw_app, "ActiveDoc")
        title = str(try_call(doc, "GetTitle", default="") or "")
        if active is not None and str(try_call(active, "GetTitle", default="")) != title:
            prev_active = str(try_call(active, "GetTitle", default="") or "")
            try_call(sw_app, "ActivateDoc3", title, False, 0, byref_int(0))
    e, w = byref_int(0), byref_int(0)
    ok = False
    try:
        r = doc.Extension.SaveAs(path, 0, 1 | 2, nothing(), e, w)      # Silent | Copy
        ok = bool(r[0] if isinstance(r, tuple) else r)
    except Exception as ex:  # noqa: BLE001
        logger.debug(f"Extension.SaveAs {path} failed: {ex}")
    if not ok:
        try:
            ok = doc.SaveAs3(path, 0, 1 | 2) == 0
        except Exception as ex:  # noqa: BLE001
            logger.debug(f"SaveAs3 {path} failed: {ex}")
    for key, val in saved_prefs.items():
        try_call(sw_app, "SetUserPreferenceToggle", key, val)
    if prev_active:
        try_call(sw_app, "ActivateDoc3", prev_active, False, 0, byref_int(0))
    return ok and os.path.isfile(path), getattr(e, "value", None), getattr(w, "value", None)


def rebuild(doc, force: bool = False) -> bool:
    """
    Rebuild the model. While a sketch is being edited only redraw: EditRebuild3
    there exits the sketch (like Ctrl+B), which breaks follow-up sketch calls.
    """
    try:
        if try_call(try_call(doc, "SketchManager"), "ActiveSketch") is not None:
            try_call(doc, "GraphicsRedraw2")
            return True
        if force:
            return bool(doc.ForceRebuild3(False))
        return bool(doc.EditRebuild3())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"rebuild failed: {e}")
        return False


def doc_type(doc) -> int:
    """1=part, 2=assembly, 3=drawing, 0=unknown"""
    try:
        return int(call(doc, "GetType"))
    except Exception:  # noqa: BLE001
        return 0


def active_config_name(doc) -> str:
    try:
        cfg = call(doc.ConfigurationManager, "ActiveConfiguration")
        return str(cfg.Name)
    except Exception:  # noqa: BLE001
        return ""


def find_feature(doc, name: str):
    """Feature object by name (FeatureByName, then tree walk)."""
    feat = try_call(doc, "FeatureByName", name)
    if feat is not None:
        return feat
    try:
        feat = call(doc, "FirstFeature")
        while feat is not None:
            if str(feat.Name) == name:
                return feat
            feat = call(feat, "GetNextFeature")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"find_feature walk failed: {e}")
    return None
