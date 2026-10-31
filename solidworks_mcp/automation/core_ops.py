"""
Core operations that used to live as ad-hoc handlers in server.py:
installation info, units, sketch close / status, feature list, execute_python.
"""

import io
import sys
import json
import math
import logging
import traceback
from typing import Dict

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)


class CoreOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, app, connect(), is_connected"""

    def get_solidworks_info(self) -> Dict:
        from ..utils import get_solidworks_info
        info = get_solidworks_info()
        if self.is_connected:
            info["running_version"] = str(cu.try_call(self.app, "RevisionNumber", default=""))
        found = bool(info.get("found"))
        return self._result(found, f"SolidWorks {'found' if found else 'not found'}",
                            SwErrors.swSuccess if found else SwErrors.swSolidWorksNotFound, info)

    def set_units(self, unit: str) -> Dict:
        from ..utils import set_default_unit
        try:
            self._units.default_unit = unit
            set_default_unit(unit)
        except Exception as e:  # noqa: BLE001
            return self._result(False, f"Unknown unit {unit!r}: {e}", SwErrors.swInvalidInput)
        return self._result(True, f"Default unit set to: {unit}", SwErrors.swSuccess, {"unit": unit})

    def list_features(self) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            features = []
            feat = cu.call(doc, "FirstFeature")
            while feat is not None:
                features.append({"name": str(cu.try_call(feat, "Name", default="")),
                                 "type": str(cu.try_call(feat, "GetTypeName2", default="")),
                                 "suppressed": bool(cu.try_call(feat, "IsSuppressed", default=False))})
                feat = cu.try_call(feat, "GetNextFeature")
            return self._result(True, f"{len(features)} features found", SwErrors.swSuccess,
                                {"features": features, "count": len(features)})
        except Exception as e:
            logger.error(f"list_features error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def close_sketch(self) -> Dict:
        doc, err = self.get_active_doc()
        if err:
            return err
        was_open = cu.close_active_sketch(doc)
        return self._result(True, "Sketch closed" if was_open else "No active sketch to close",
                            SwErrors.swSuccess, {"had_active_sketch": was_open})

    def get_sketch_status(self) -> Dict:
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            active = cu.try_call(doc.SketchManager, "ActiveSketch")
            info = {"has_active_sketch": active is not None, "sketch_names": [], "feature_count": 0}
            if active is not None:
                info["active_sketch_name"] = str(cu.try_call(active, "Name", default=""))
                info["active_sketch_segments"] = len(cu.as_list(cu.try_call(active, "GetSketchSegments")))
            feat = cu.call(doc, "FirstFeature")
            while feat is not None:
                info["feature_count"] += 1
                if str(cu.try_call(feat, "GetTypeName2", default="")) == "ProfileFeature":
                    info["sketch_names"].append(str(feat.Name))
                feat = cu.try_call(feat, "GetNextFeature")
            state = "OPEN" if active is not None else "CLOSED"
            return self._result(True, f"Sketch {state}; sketches: {info['sketch_names']}", SwErrors.swSuccess, info)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def execute_python(self, code: str) -> Dict:
        """
        Run Python with `sw` (application), `doc` (active document), `automation`
        (this object), win32com, pythoncom, math, os, json in scope. stdout/stderr
        and a `result` variable are returned. Full access to the machine: trusted use only.
        """
        if not code:
            return self._result(False, "Code is required", SwErrors.swInvalidInput)
        if not self.is_connected:
            r = self.connect()
            if not r["success"]:
                return r
        import os
        import win32com
        import pythoncom
        g = {"sw": self.app, "doc": cu.try_call(self.app, "ActiveDoc"), "automation": self,
             "win32com": win32com, "pythoncom": pythoncom, "math": math, "os": os, "json": json,
             "result": None}
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out, err
            exec(code, g)
        except Exception as e:  # noqa: BLE001
            sys.stdout, sys.stderr = old
            tb = traceback.format_exc()
            return self._result(False, f"Execution error: {e}\n\n{tb}", SwErrors.swUnknownError,
                                {"error_type": type(e).__name__, "stdout": out.getvalue(), "traceback": tb})
        finally:
            sys.stdout, sys.stderr = old
        parts = []
        if out.getvalue():
            parts.append(f"=== Output ===\n{out.getvalue().rstrip()}")
        if err.getvalue():
            parts.append(f"=== Stderr ===\n{err.getvalue().rstrip()}")
        if g.get("result") is not None:
            parts.append(f"=== Result ===\n{g['result']}")
        return self._result(True, "\n\n".join(parts) or "Code executed (no output)", SwErrors.swSuccess,
                            {"stdout": out.getvalue(), "stderr": err.getvalue(),
                             "result": None if g.get("result") is None else str(g["result"])})
