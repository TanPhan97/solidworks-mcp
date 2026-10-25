"""
COM late-binding helpers
------------------------
SolidWorks exposes some zero-argument members as properties and others as
methods, and the split differs between versions when accessed through
pywin32 dynamic dispatch. These helpers hide that difference and provide the
VARIANT wrappers needed for ByRef / empty / array parameters.
"""

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

def sketch_to_model(sw_app, doc, x: float, y: float, z: float = 0.0) -> List[float]:
    """
    Transform a point from active-sketch coordinates (meters) to model
    coordinates (meters). SelectByID2 works in model space; SketchManager.Create*
    works in sketch space. Falls back to identity if no sketch is active.
    """
    try:
        sketch = call(doc.SketchManager, "ActiveSketch")
        if sketch is None:
            return [x, y, z]
        xform = call(sketch, "ModelToSketchTransform")
        inv = call(xform, "Inverse")
        math_util = call(sw_app, "GetMathUtility")
        pt = math_util.CreatePoint(double_array([x, y, z]))
        pt_model = pt.MultiplyTransform(inv)
        data = as_list(call(pt_model, "ArrayData"))
        return [float(data[0]), float(data[1]), float(data[2])]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"sketch_to_model fallback to identity: {e}")
        return [x, y, z]


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


def rebuild(doc, force: bool = False) -> bool:
    try:
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
