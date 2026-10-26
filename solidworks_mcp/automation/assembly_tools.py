"""
Advanced mates, BOM export, Pack and Go
---------------------------------------
Advanced / mechanical mates use IAssemblyDoc.CreateMateData(type) + CreateMate(data)
(typed entity properties instead of AddMate5's selection marks):

  ISymmetricMateFeatureData : EntitiesToMate, SymmetryPlane, MateAlignment
  IWidthMateFeatureData     : WidthSelection, TabSelection, ConstraintType, DistanceFromEnd, PercentDistanceFromEnd
  IGearMateFeatureData      : EntitiesToMate, GearRatioNumerator, GearRatioDenominator, Reverse
  ISlotMateFeatureData      : EntitiesToMate, Constraint, Distance, Percent, MateAlignment
  IHingeMateFeatureData     : EntitiesToMate, AngleSelection, Angle, MinVal, MaxVal
  IDistanceMateFeatureData  : EntitiesToMate, Distance, IsAdvancedMate, MinimumDistance, MaximumDistance
  IAngleMateFeatureData     : EntitiesToMate, Angle, IsAdvancedMate, MinimumAngle, MaximumAngle

Pack and Go: IModelDocExtension.GetPackAndGo / SavePackAndGo(PackAndGo).
"""

import os
import csv
import shutil
import math
import logging
import traceback
from typing import Dict, List

import pythoncom
import win32com.client

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_MATE = {"symmetric": 8, "gear": 10, "width": 11, "slot": 21, "hinge": 22,
         "limit_distance": 5, "limit_angle": 6}
_ALIGN = {"aligned": 0, "anti_aligned": 1, "closest": 2}
_WIDTH_C = {"centered": 0, "free": 1, "distance": 2, "percent": 3}
_SLOT_C = {"free": 0, "centered": 1, "distance": 2, "percent": 3}
_N_ENTITIES = {"symmetric": 2, "gear": 2, "slot": 2, "hinge": 4, "limit_distance": 2, "limit_angle": 2}


def _arr(objs):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(objs))


class AssemblyToolsOperations:
    """Mixin. Requires: get_active_doc(), _result(), _units, _require_assembly(), _select_mate_entity()"""

    def _mate_objects(self, doc, specs: List[Dict], unit) -> List:
        """Select each spec and return the selected COM entity objects, in order."""
        objs = []
        sm = doc.SelectionManager
        for spec in specs:
            doc.ClearSelection2(True)
            if not self._select_mate_entity(doc, spec, False, 0, unit):
                raise ValueError(f"Could not select {spec}")
            o = cu.try_call(sm, "GetSelectedObject6", 1, -1)
            if o is None:
                raise ValueError(f"Selected {spec} but got no object")
            objs.append(o)
        doc.ClearSelection2(True)
        return objs

    def add_advanced_mate(self, mate_type: str, entities: List[Dict] = None, symmetry_plane: Dict = None,
                          width_entities: List[Dict] = None, tab_entities: List[Dict] = None,
                          constraint: str = None, distance: float = None, percent: float = None,
                          ratio: List[float] = None, reverse: bool = False,
                          min_value: float = None, max_value: float = None, value: float = None,
                          alignment: str = "closest", unit: str = None) -> Dict:
        """
        symmetric : entities [2] + symmetry_plane
        width     : width_entities [2] (outer faces) + tab_entities [2]; constraint centered|free|distance|percent
        gear      : entities [2] (cylindrical faces / edges); ratio [n, m]; reverse
        slot      : entities [slot face, pin face]; constraint free|centered|distance|percent
        hinge     : entities [cyl1, cyl2, face1, face2] (concentric pair, coincident pair)
        limit_distance / limit_angle : entities [2]; value + min_value / max_value (unit / deg)
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            mt = (mate_type or "").lower()
            if mt not in _MATE:
                return self._result(False, f"mate_type must be one of {sorted(_MATE)}", SwErrors.swInvalidInput)
            to_m = lambda v: self._units.to_meters(v, unit)
            data = doc.CreateMateData(_MATE[mt])
            if data is None:
                return self._result(False, "CreateMateData failed", SwErrors.swFeatureError)

            if mt == "width":
                if len(width_entities or []) != 2 or len(tab_entities or []) != 2:
                    return self._result(False, "width needs width_entities [2] and tab_entities [2]",
                                        SwErrors.swInvalidInput)
                data.WidthSelection = _arr(self._mate_objects(doc, width_entities, unit))
                data.TabSelection = _arr(self._mate_objects(doc, tab_entities, unit))
                c = _WIDTH_C.get(constraint or "centered", 0)
                data.ConstraintType = c
                if c == 2 and distance is not None:
                    data.DistanceFromEnd = to_m(distance)
                if c == 3 and percent is not None:
                    data.PercentDistanceFromEnd = float(percent) / 100.0
            else:
                need = _N_ENTITIES[mt]
                if len(entities or []) != need:
                    return self._result(False, f"{mt} needs entities [{need}]", SwErrors.swInvalidInput)
                objs = self._mate_objects(doc, entities, unit)
                if mt == "hinge":
                    # IHingeMateFeatureData.EntitiesToMate(EntityType) is a parameterised property:
                    # swHingeMateEntityType_e Concentric = 0, Coincident = 1
                    ole = data._oleobj_
                    did = ole.GetIDsOfNames("EntitiesToMate")
                    ole.Invoke(did, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, 0, _arr(objs[:2]))
                    ole.Invoke(did, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, 1, _arr(objs[2:]))
                else:
                    data.EntitiesToMate = _arr(objs)
                if mt in ("symmetric", "slot", "hinge", "limit_distance", "limit_angle"):
                    try:
                        data.MateAlignment = _ALIGN.get(alignment, 2)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"MateAlignment not set: {e}")
                if mt == "symmetric":
                    if not symmetry_plane:
                        return self._result(False, "symmetric needs symmetry_plane", SwErrors.swInvalidInput)
                    data.SymmetryPlane = self._mate_objects(doc, [symmetry_plane], unit)[0]
                elif mt == "gear":
                    n, m = (ratio or [1, 1])[:2]
                    data.GearRatioNumerator, data.GearRatioDenominator = to_m(n), to_m(m)
                    data.Reverse = bool(reverse)
                elif mt == "slot":
                    c = _SLOT_C.get(constraint or "free", 0)
                    data.Constraint = c
                    if c == 2 and distance is not None:
                        data.Distance = to_m(distance)
                    if c == 3 and percent is not None:
                        data.Percent = float(percent) / 100.0
                elif mt == "limit_distance":
                    if min_value is None or max_value is None:
                        return self._result(False, "limit_distance needs min_value and max_value",
                                            SwErrors.swInvalidInput)
                    data.IsAdvancedMate = True
                    data.Distance = to_m(value if value is not None else min_value)
                    data.MinimumDistance, data.MaximumDistance = to_m(min_value), to_m(max_value)
                elif mt == "limit_angle":
                    if min_value is None or max_value is None:
                        return self._result(False, "limit_angle needs min_value and max_value",
                                            SwErrors.swInvalidInput)
                    data.IsAdvancedMate = True
                    data.Angle = math.radians(value if value is not None else min_value)
                    data.MinimumAngle, data.MaximumAngle = math.radians(min_value), math.radians(max_value)

            mate = doc.CreateMate(data)
            cu.rebuild(doc)
            if mate is None:
                return self._result(False, f"{mt} mate failed: check entity types / order (see tool description)",
                                    SwErrors.swFeatureError)
            name = str(cu.try_call(mate, "Name", default="") or "")
            errors = self._rebuild_errors(doc)
            msg = f"{mt} mate added{(' → ' + name) if name else ''}"
            data = {"mate_type": mt, "name": name}
            if errors:
                fixed = [str(cu.try_call(c, "Name2", default="")) for c in cu.as_list(doc.GetComponents(True))
                         if cu.try_call(c, "IsFixed", default=False)]
                msg += f" — WARNING: mate errors {errors}; fixed components {fixed} (over-defined?)"
                data.update(errors=errors, fixed_components=fixed)
            return self._result(True, msg, SwErrors.swSuccess, data)
        except (RuntimeError, ValueError) as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"add_advanced_mate error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFeatureError)

    # ------------------------------------------------------------------ BOM
    def _comp_props(self, comp, names: List[str]) -> Dict:
        model = cu.try_call(comp, "GetModelDoc2")
        out = {}
        if model is None:
            return {n: "" for n in names}
        cfg = str(cu.try_call(comp, "ReferencedConfiguration", default="") or "")
        for scope in (cfg, ""):
            cpm = cu.try_call(model.Extension, "CustomPropertyManager", scope)
            for n in names:
                if out.get(n):
                    continue
                v = self._read_custom_property(cpm, n, resolved=True) if cpm is not None else ""
                if v:
                    out[n] = v
        return {n: out.get(n, "") for n in names}

    def export_bom(self, filepath: str, mode: str = "parts_only", properties: List[str] = None,
                   include_suppressed: bool = False) -> Dict:
        """
        BOM of the active assembly to CSV (UTF-8, opens in Excel). mode: parts_only
        (flat list of parts, total quantities), top_level, or indented (sub-assemblies
        expanded, quantity per parent).
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            self._require_assembly(doc)
            props = properties if properties is not None else ["PartNo", "Description", "Material"]
            path = os.path.abspath(os.path.expanduser(filepath))
            if not path.lower().endswith(".csv"):
                path += ".csv"
            os.makedirs(os.path.dirname(path), exist_ok=True)

            def alive(c):
                return include_suppressed or not cu.try_call(c, "IsSuppressed", default=False)

            def key(c):
                return (os.path.normcase(str(cu.try_call(c, "GetPathName", default=""))),
                        str(cu.try_call(c, "ReferencedConfiguration", default="")))

            rows = []
            if mode == "indented":
                def walk(comps, level, prefix):
                    groups = {}
                    for c in comps:
                        if alive(c) and not cu.try_call(c, "IsEnvelope", default=False):
                            groups.setdefault(key(c), []).append(c)
                    for i, (k, cs) in enumerate(groups.items(), 1):
                        item = f"{prefix}{i}"
                        rows.append((item, level, cs[0], len(cs)))
                        kids = cu.as_list(cu.try_call(cs[0], "GetChildren"))
                        if kids:
                            walk(kids, level + 1, item + ".")
                top = [c for c in cu.as_list(doc.GetComponents(True))]
                walk(top, 1, "")
            else:
                comps = cu.as_list(doc.GetComponents(mode != "parts_only"))
                groups = {}
                for c in comps:
                    if not alive(c) or cu.try_call(c, "IsEnvelope", default=False):
                        continue
                    if mode == "parts_only" and not str(cu.try_call(c, "GetPathName", default="")).lower().endswith(".sldprt"):
                        continue
                    groups.setdefault(key(c), []).append(c)
                for i, cs in enumerate(groups.values(), 1):
                    rows.append((str(i), 1, cs[0], len(cs)))

            header = ["Item", "Level", "File", "Configuration", "Qty"] + props
            out = []
            for item, level, c, qty in rows:
                p = str(cu.try_call(c, "GetPathName", default=""))
                out.append([item, level, os.path.basename(p), str(cu.try_call(c, "ReferencedConfiguration", default="")),
                            qty] + list(self._comp_props(c, props).values()))
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                w.writerows(out)
            return self._result(True, f"BOM ({mode}): {len(out)} line(s) → {path}", SwErrors.swSuccess,
                                {"path": path, "lines": len(out), "header": header, "rows": out[:50]})
        except RuntimeError as e:
            return self._result(False, str(e), SwErrors.swInvalidInput)
        except Exception as e:
            logger.error(f"export_bom error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swExportError)

    # ------------------------------------------------------------------ Pack and Go
    def pack_and_go(self, destination: str, prefix: str = "", suffix: str = "",
                    include_drawings: bool = False, flatten: bool = True) -> Dict:
        """
        Copy the active (saved) model and every referenced file to `destination`, with
        optional prefix / suffix, and re-point the copies to each other.
        ISldWorks.GetDocumentDependencies2 lists the references; files are copied, then
        ISldWorks.ReplaceReferencedDocument re-points each copied assembly / drawing
        (works on closed files, so the open originals are untouched). CopyDocument fails
        while the sources are open.
        IModelDocExtension.GetPackAndGo is not used: on SW 2026 it fails through late-bound
        COM ('Parameter not optional' / 'Type mismatch').
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            src = str(cu.try_call(doc, "GetPathName", default="") or "")
            if not src:
                return self._result(False, "Save the document first", SwErrors.swInvalidInput)
            if cu.try_call(doc, "GetSaveFlag", default=False):
                return self._result(False, "The document has unsaved changes: save it first",
                                    SwErrors.swInvalidInput)
            sw = self.app
            dest = os.path.abspath(os.path.expanduser(destination))
            os.makedirs(dest, exist_ok=True)
            deps = [str(x) for x in cu.as_list(sw.GetDocumentDependencies2(src, True, True, False))]
            files = [src] + [deps[i + 1] for i in range(0, len(deps) - 1, 2) if deps[i + 1]]
            files = list(dict.fromkeys(os.path.abspath(f) for f in files if os.path.isfile(f)))
            if include_drawings:
                for f in list(files):
                    drw = os.path.splitext(f)[0] + ".SLDDRW"
                    for cand in (drw, os.path.splitext(f)[0] + ".slddrw"):
                        if os.path.isfile(cand) and cand not in files:
                            files.append(os.path.abspath(cand))
                            break
            root = os.path.dirname(src)

            def target(f):
                stem, ext = os.path.splitext(os.path.basename(f))
                sub = "" if flatten else os.path.relpath(os.path.dirname(f), root)
                folder = os.path.normpath(os.path.join(dest, sub)) if sub and not sub.startswith("..") else dest
                os.makedirs(folder, exist_ok=True)
                return os.path.join(folder, f"{prefix}{stem}{suffix}{ext}")

            mapping = {f: target(f) for f in files}
            done, failed, relinked = [], [], 0
            for f, t in mapping.items():            # plain file copy: works while the sources are open
                try:
                    shutil.copy2(f, t)
                    done.append(os.path.basename(t))
                except OSError as e:
                    failed.append(f"{os.path.basename(t)}: {e}")
            for f, t in mapping.items():            # re-point the copies (closed files) to each other
                if os.path.splitext(f)[1].lower() == ".sldprt" or not os.path.isfile(t):
                    continue
                for old, new in mapping.items():
                    if old != f and cu.try_call(sw, "ReplaceReferencedDocument", t, old, new, default=False):
                        relinked += 1
            return self._result(not failed, f"Pack and Go: {len(done)} file(s), {relinked} reference(s) "
                                f"re-pointed → {dest}" + (f", {len(failed)} failed" if failed else ""),
                                SwErrors.swSuccess if not failed else SwErrors.swFileSaveError,
                                {"destination": dest, "files": done, "failed": failed, "relinked": relinked})
        except Exception as e:
            logger.error(f"pack_and_go error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileSaveError)
