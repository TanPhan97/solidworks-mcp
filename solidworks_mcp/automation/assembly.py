"""
SolidWorks Assembly Operations
------------------------------
Insert components, add standard mates, list components.

Mate entity spec (any of):
  {"component": "Bracket-1", "plane": "Front"}      -> "Front Plane@Bracket-1@<Asm>"
  {"plane": "Top"}                                  -> assembly's own plane
  {"point": [x, y, z], "type": "FACE"|"EDGE"|"VERTEX"}  (assembly coords, user units)
  {"name": "Axis1@Shaft-1@Asm1", "type": "AXIS"}
"""

import os
import math
import logging
import traceback
from typing import Dict

from ..constants import SwErrors, SwPlanes, SwMateTypes
from . import com_utils as cu

logger = logging.getLogger(__name__)

_MATE_TYPES = {
    "coincident": SwMateTypes.swMateCOINCIDENT,
    "concentric": SwMateTypes.swMateCONCENTRIC,
    "perpendicular": SwMateTypes.swMatePERPENDICULAR,
    "parallel": SwMateTypes.swMatePARALLEL,
    "tangent": SwMateTypes.swMateTANGENT,
    "distance": SwMateTypes.swMateDISTANCE,
    "angle": SwMateTypes.swMateANGLE,
    "lock": SwMateTypes.swMateLOCK,
}
_ALIGN = {"aligned": 0, "anti_aligned": 1, "closest": 2}
_ADD_MATE_ERRORS = {0: "unknown", 1: "no error", 2: "incorrect mate type", 3: "incorrect alignment",
                    4: "incorrect selections", 5: "over-defined / conflicting", 6: "invalid distance/angle"}


class AssemblyOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, _select_ref()"""

    def _require_assembly(self, doc):
        if cu.doc_type(doc) != 2:
            raise RuntimeError("Active document is not an assembly (create_new_assembly / open_document)")

    def _asm_title_no_ext(self, doc) -> str:
        title = str(cu.try_call(doc, "GetTitle", default=""))
        return os.path.splitext(title)[0] if title.lower().endswith(".sldasm") else title

    def _select_mate_entity(self, doc, spec: Dict, append: bool, mark: int, unit=None) -> bool:
        if "component" in spec and "plane" in spec:
            p = str(spec["plane"])
            pname = SwPlanes.get(p) if p.lower() in ("front", "top", "right") else p
            name = f"{pname}@{spec['component']}@{self._asm_title_no_ext(doc)}"
            return cu.select_by_id(doc, name, "PLANE", 0, 0, 0, append, mark)
        return self._select_ref(doc, spec, append, mark, unit)

    def insert_component(self, filepath: str, x: float = 0, y: float = 0, z: float = 0,
                         config: str = "", unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            path = os.path.abspath(os.path.expanduser(filepath))
            if not os.path.exists(path):
                return self._result(False, f"File not found: {path}", SwErrors.swFileNotFoundError)
            ext = os.path.splitext(path)[1].lower()
            if ext not in (".sldprt", ".sldasm"):
                return self._result(False, "Component must be .sldprt or .sldasm", SwErrors.swInvalidFileType)

            sw = self.app
            asm_title = str(cu.call(doc, "GetTitle"))
            # AddComponent requires the model to be loaded in memory
            e1, w1 = cu.byref_int(0), cu.byref_int(0)
            cu.try_call(sw, "OpenDoc6", path, 1 if ext == ".sldprt" else 2, 1, config or "", e1, w1)
            cu.try_call(sw, "ActivateDoc3", asm_title, False, 0, cu.byref_int(0))
            asm = cu.call(sw, "ActiveDoc")

            xm, ym, zm = (self._units.to_meters(v, unit) for v in (x, y, z))
            comp, used = cu.first_ok(
                lambda: asm.AddComponent5(path, 0, "", bool(config), config or "", xm, ym, zm),
                lambda: asm.AddComponent4(path, config or "", xm, ym, zm),
                log_prefix="AddComponent")
            if not comp:
                return self._result(False, "AddComponent failed", SwErrors.swFileLoadError)
            cname = str(cu.try_call(comp, "Name2", default="") or "")
            cu.rebuild(asm)
            return self._result(True, f"Inserted {cname}", SwErrors.swSuccess,
                                {"component": cname, "path": path})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"insert_component error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def add_mate(self, mate_type: str, entity1: Dict, entity2: Dict,
                 alignment: str = "closest", flip: bool = False,
                 distance: float = 0.0, angle: float = 0.0, unit: str = None) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            mt = _MATE_TYPES.get(mate_type.lower())
            if mt is None:
                return self._result(False, f"mate_type must be one of {sorted(_MATE_TYPES)}",
                                    SwErrors.swInvalidInput)
            al = _ALIGN.get(alignment.lower(), 2)

            doc.ClearSelection2(True)
            for i, spec in enumerate((entity1, entity2)):
                if not self._select_mate_entity(doc, spec, i > 0, 1, unit):
                    return self._result(False, f"Could not select entity{i + 1}: {spec}",
                                        SwErrors.swSelectionError)

            d = self._units.to_meters(distance, unit) if mt == SwMateTypes.swMateDISTANCE else 0.0
            a = math.radians(angle) if mt == SwMateTypes.swMateANGLE else 0.0
            err_ref = cu.byref_int(0)
            mate, used = cu.first_ok(
                lambda: doc.AddMate5(int(mt), al, flip, d, d, d, 0, 0, a, a, a, False, False, 0, err_ref),
                lambda: doc.AddMate3(int(mt), al, flip, d, d, d, 0, 0, a, a, a, False, err_ref),
                log_prefix="AddMate")
            if isinstance(mate, tuple):
                mate = mate[0]
            code = int(getattr(err_ref, "value", 0) or 0)
            if not mate:
                return self._result(False,
                    f"Mate failed: {_ADD_MATE_ERRORS.get(code, code)}", SwErrors.swFeatureError,
                    {"error_status": code})
            cu.rebuild(doc)
            doc.ClearSelection2(True)
            extra = f" d={distance}" if mt == SwMateTypes.swMateDISTANCE else (
                f" {angle}°" if mt == SwMateTypes.swMateANGLE else "")
            return self._result(True, f"{mate_type} mate added{extra}", SwErrors.swSuccess,
                                {"mate_type": mate_type, "alignment": alignment})
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_mate error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    def list_components(self, top_level_only: bool = True) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            comps = []
            for c in cu.as_list(doc.GetComponents(bool(top_level_only))):
                comps.append({
                    "name": str(cu.try_call(c, "Name2", default="")),
                    "path": str(cu.try_call(c, "GetPathName", default="")),
                    "config": str(cu.try_call(c, "ReferencedConfiguration", default="")),
                    "suppressed": bool(cu.try_call(c, "IsSuppressed", default=False)),
                    "fixed": bool(cu.try_call(c, "IsFixed", default=False)),
                })
            return self._result(True, f"{len(comps)} component(s)", SwErrors.swSuccess,
                                {"components": comps})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"list_components error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
