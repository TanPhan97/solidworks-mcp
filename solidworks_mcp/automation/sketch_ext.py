"""
SolidWorks Sketch Extensions
----------------------------
Fully-defined sketch support: smart dimensions, geometric relations, slots,
centerlines, sketch fillets.

Sketch entities are addressed by a point lying on them, in the active
sketch's 2D coordinates (same space as draw_line / draw_circle). The point is
transformed to model space (ModelToSketchTransform⁻¹) before SelectByID2, so
it works on any plane or face, not only the Front plane.

Entity spec:
  {"point": [x, y]}                              -> SKETCHSEGMENT at that point
  {"point": [x, y], "type": "SKETCHPOINT"}       -> endpoint / center point
  {"name": "Point1@Origin", "type": "EXTSKETCHPOINT"}  -> origin
  {"name": "Line1", "type": "SKETCHSEGMENT"}     -> by name
"""

import math
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu
from .com_utils import set_dimension_value

logger = logging.getLogger(__name__)

_RELATIONS = {
    "horizontal": "sgHORIZONTAL2D",
    "vertical": "sgVERTICAL2D",
    "coincident": "sgCOINCIDENT",
    "concentric": "sgCONCENTRIC",
    "coradial": "sgCORADIAL",
    "tangent": "sgTANGENT",
    "parallel": "sgPARALLEL",
    "perpendicular": "sgPERPENDICULAR",
    "collinear": "sgCOLINEAR",
    "equal": "sgSAMELENGTH",
    "midpoint": "sgATMIDDLE",
    "symmetric": "sgSYMMETRIC",
    "fixed": "sgFIXED",
}

_SW_INPUT_DIM_VAL_ON_CREATE = 10   # swUserPreferenceToggle_e.swInputDimValOnCreate


class SketchExtOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app"""

    def _require_active_sketch(self, doc):
        sk = cu.try_call(doc.SketchManager, "ActiveSketch")
        if sk is None:
            raise RuntimeError("No active sketch. Call create_sketch / create_sketch_on_face first.")
        return sk

    def _select_sketch_entity(self, doc, spec: Dict, append: bool, mark: int = 0,
                              unit: str = None) -> bool:
        if "point" in spec:
            px, py = [self._units.to_meters(v, unit) for v in list(spec["point"])[:2]]
            x, y, z = cu.sketch_to_model(self.app, doc, px, py, 0.0)
            sel_type = spec.get("type", "SKETCHSEGMENT").upper()
            return cu.select_by_id(doc, spec.get("name", ""), sel_type, x, y, z, append, mark)
        if "name" in spec:
            return cu.select_by_id(doc, spec["name"], spec.get("type", "SKETCHSEGMENT").upper(),
                                   0, 0, 0, append, mark)
        raise ValueError(f"Invalid sketch entity spec: {spec}")

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    def add_sketch_dimension(self, entities: List[Dict], value: float = None,
                             text_position: List[float] = None, unit: str = None) -> Dict:
        """
        Smart dimension.
        1 entity : line → length, circle → diameter, arc → radius
        2 entities: distance / angle between them (angle if both are non-parallel lines)
        `value` drives the geometry; unit 'deg' for angular dimensions.
        `text_position` [x, y] in sketch coords; default = near the first entity.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            if not entities or len(entities) > 2:
                return self._result(False, "entities must contain 1 or 2 items",
                                    SwErrors.swInvalidInput)

            is_angle = (unit or "").lower() in ("deg", "rad")
            len_unit = None if is_angle else unit

            doc.ClearSelection2(True)
            for i, spec in enumerate(entities):
                if not self._select_sketch_entity(doc, spec, i > 0, 0, len_unit):
                    return self._result(False, f"Could not select sketch entity {spec}",
                                        SwErrors.swSelectionError)

            if text_position:
                tx, ty = [self._units.to_meters(v, len_unit) for v in text_position[:2]]
            else:
                p0 = entities[0].get("point", [0, 0])
                tx = self._units.to_meters(p0[0], len_unit) + self._units.to_meters(5, "mm")
                ty = self._units.to_meters(p0[1], len_unit) + self._units.to_meters(5, "mm")
            mx, my, mz = cu.sketch_to_model(self.app, doc, tx, ty, 0.0)

            # Suppress the "Modify" input box that would block COM
            sw = self.app
            prev = cu.try_call(sw, "GetUserPreferenceToggle", _SW_INPUT_DIM_VAL_ON_CREATE, default=None)
            cu.try_call(sw, "SetUserPreferenceToggle", _SW_INPUT_DIM_VAL_ON_CREATE, False)
            try:
                disp_dim, used = cu.first_ok(
                    lambda: doc.AddDimension2(mx, my, mz),
                    lambda: doc.Extension.AddDimension(mx, my, mz, 0),
                    log_prefix="AddDimension")
            finally:
                if prev is not None:
                    cu.try_call(sw, "SetUserPreferenceToggle", _SW_INPUT_DIM_VAL_ON_CREATE, bool(prev))

            if not disp_dim:
                return self._result(False,
                    "Dimension not created (entity combination not dimensionable, or would "
                    "over-define the sketch)", SwErrors.swSketchError)

            dim = cu.call(disp_dim, "GetDimension2", 0)
            full_name = str(cu.try_call(dim, "FullName", default="") or cu.try_call(dim, "GetNameForSelection", default=""))

            if value is not None:
                if is_angle:
                    v = math.radians(value) if unit.lower() == "deg" else float(value)
                else:
                    v = self._units.to_meters(value, unit)
                set_ok = set_dimension_value(dim, v)
                cu.rebuild(doc)
                if not set_ok:
                    return self._result(False, f"Dimension {full_name} created but value not set",
                                        SwErrors.swSketchError, {"dimension": full_name})

            current = cu.try_call(dim, "SystemValue")
            shown = None
            if current is not None:
                shown = math.degrees(current) if is_angle and unit.lower() == "deg" else (
                    current if is_angle else self._units.from_meters(current, unit))
            return self._result(True, f"Dimension {full_name} = {shown}", SwErrors.swSuccess,
                                {"dimension": full_name, "value": shown,
                                 "unit": unit or self._units.default_unit.value})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_sketch_dimension error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------

    def add_sketch_relation(self, relation: str, entities: List[Dict], unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            key = relation.lower()
            if key not in _RELATIONS:
                return self._result(False, f"Unknown relation. Use one of {sorted(_RELATIONS)}",
                                    SwErrors.swInvalidInput)
            doc.ClearSelection2(True)
            for i, spec in enumerate(entities):
                if not self._select_sketch_entity(doc, spec, i > 0, 0, unit):
                    return self._result(False, f"Could not select sketch entity {spec}",
                                        SwErrors.swSelectionError)
            doc.SketchAddConstraints(_RELATIONS[key])
            doc.ClearSelection2(True)
            return self._result(True, f"Relation {key} added to {len(entities)} entit(y/ies)",
                                SwErrors.swSuccess, {"relation": _RELATIONS[key]})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_sketch_relation error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def draw_slot(self, x1: float, y1: float, x2: float, y2: float, width: float,
                  add_dimensions: bool = False, unit: str = None) -> Dict:
        """Straight slot, arc-center to arc-center from (x1,y1) to (x2,y2)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            c = [self._units.to_meters(v, unit) for v in (x1, y1, x2, y2, width)]
            slot = doc.SketchManager.CreateSketchSlot(
                0,               # swSketchSlotCreationType_line
                0,               # swSketchSlotLengthType_CenterCenter
                c[4],            # width
                c[0], c[1], 0.0,
                c[2], c[3], 0.0,
                0.0, 0.0, 0.0,   # 3rd point (unused for straight slot)
                1,               # CenterArcDirection
                bool(add_dimensions))
            if slot is None:
                return self._result(False, "Slot failed - ensure sketch is active", SwErrors.swSketchError)
            length = math.hypot(x2 - x1, y2 - y1)
            unit_str = unit or self._units.default_unit.value
            return self._result(True, f"Slot {length:.3f}×{width}{unit_str} (c-c × width)",
                                SwErrors.swSuccess, {"length_cc": length, "width": width, "unit": unit_str})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"draw_slot error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)

    def sketch_fillet(self, corner: List[float], radius: float, unit: str = None) -> Dict:
        """Fillet the sketch corner at `corner` [x, y] (shared endpoint of two segments)."""
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_active_sketch(doc)
            doc.ClearSelection2(True)
            if not self._select_sketch_entity(doc, {"point": corner, "type": "SKETCHPOINT"},
                                              False, 0, unit):
                return self._result(False, f"No sketch vertex at {corner}", SwErrors.swSelectionError)
            r = self._units.to_meters(radius, unit)
            res, _ = cu.first_ok(lambda: doc.SketchManager.CreateFillet(r, 1),
                                 lambda: doc.SketchFillet2(r, 1),
                                 log_prefix="SketchFillet")
            if not res:
                return self._result(False, "Sketch fillet failed (radius too large?)",
                                    SwErrors.swSketchError)
            unit_str = unit or self._units.default_unit.value
            return self._result(True, f"Sketch fillet R{radius}{unit_str} at {corner}", SwErrors.swSuccess)
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"sketch_fillet error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swSketchError)
