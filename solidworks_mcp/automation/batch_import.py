"""
Batch export, neutral-format import, document activation
--------------------------------------------------------
  ISldWorks.OpenDoc6(FileName, Type, Options, Configuration, Errors, Warnings)
  ISldWorks.LoadFile4(FileName, ArgString, ImportData, Errors)
  ISldWorks.GetImportFileData(FileName)
  ISldWorks.ActivateDoc3(Name, UseUserPreferences, Option, Errors)
  IModelDocExtension.SaveAs(Name, Version, Options, ExportData, Errors, Warnings)
"""

import os
import time
import logging
import traceback
from typing import Dict, List

from ..constants import SwErrors
from . import com_utils as cu

logger = logging.getLogger(__name__)

_FMT = {"step": ".step", "stp": ".stp", "iges": ".igs", "igs": ".igs", "parasolid": ".x_t",
        "x_t": ".x_t", "x_b": ".x_b", "stl": ".stl", "3mf": ".3mf", "acis": ".sat", "sat": ".sat",
        "pdf": ".pdf", "dxf": ".dxf", "dwg": ".dwg", "edrawings": None, "png": ".png", "jpg": ".jpg"}
_EDRW = {1: ".eprt", 2: ".easm", 3: ".edrw"}
_DOC_EXT = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}
_IMPORT_EXT = {".step", ".stp", ".igs", ".iges", ".x_t", ".x_b", ".sat", ".stl", ".3mf", ".obj",
               ".ipt", ".iam", ".catpart", ".catproduct", ".prt", ".asm", ".par", ".psm",
               ".3dm", ".jt", ".dxf", ".dwg", ".wrl", ".vda", ".ifc"}
_MODEL_ONLY = {".step", ".stp", ".igs", ".x_t", ".x_b", ".stl", ".3mf", ".sat"}
_DRAWING_ONLY = {".pdf", ".dxf", ".dwg"}


class BatchImportOperations:
    """Mixin. Requires: get_active_doc(), _result(), app, is_connected, connect()"""

    def batch_export(self, folder: str, formats: List[str] = None, recursive: bool = False,
                     output_dir: str = None, file_types: List[str] = None,
                     overwrite: bool = False, max_files: int = 100) -> Dict:
        """
        Export every SolidWorks file in `folder` to each format. Files already open
        stay open; files opened here are closed afterwards. Output mirrors the folder
        structure under output_dir (default: <folder>/export).
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            sw = self.app
            src = os.path.abspath(os.path.expanduser(folder))
            if not os.path.isdir(src):
                return self._result(False, f"Folder not found: {src}", SwErrors.swFileNotFoundError)
            formats = [f.lower().lstrip(".") for f in (formats or ["step"])]
            bad = [f for f in formats if f not in _FMT]
            if bad:
                return self._result(False, f"Unknown formats {bad}; use {sorted(_FMT)}", SwErrors.swInvalidInput)
            types = {"." + t.lower().lstrip(".") for t in (file_types or ["sldprt", "sldasm"])}
            out_root = os.path.abspath(os.path.expanduser(output_dir)) if output_dir else os.path.join(src, "export")

            files = []
            for root, dirs, names in os.walk(src):
                if os.path.abspath(root).startswith(out_root):
                    continue
                for n in sorted(names):
                    if n.startswith("~$"):
                        continue
                    if os.path.splitext(n)[1].lower() in types:
                        files.append(os.path.join(root, n))
                if not recursive:
                    break
            if not files:
                return self._result(False, f"No {sorted(types)} files in {src}", SwErrors.swFileNotFoundError)
            skipped_limit = max(0, len(files) - max_files)
            files = files[:max_files]

            t0 = time.time()
            done, failed, skipped = [], [], []
            # Never close what was loaded before the batch (user documents, or parts loaded
            # as references of an open assembly / drawing) — CloseDoc does not save.
            preloaded = cu.open_doc_paths(sw)
            for path in files:
                ext = os.path.splitext(path)[1].lower()
                dtype = _DOC_EXT[ext]
                key = os.path.normcase(os.path.abspath(path))
                doc = cu.find_open_doc(sw, path)
                opened_here = doc is None and key not in preloaded
                if doc is None:
                    err = None
                    for opts in (1 | 2, 1):                     # Silent|ReadOnly, then Silent
                        e, w = cu.byref_int(0), cu.byref_int(0)
                        doc = cu.try_call(sw, "OpenDoc6", path, dtype, opts, "", e, w)
                        err = getattr(e, "value", None)
                        if doc is not None:
                            break
                    if doc is None:
                        failed.append({"file": path, "error": f"could not open (swFileLoadError {err})"})
                        continue
                rel = os.path.relpath(os.path.dirname(path), src)
                stem = os.path.splitext(os.path.basename(path))[0]
                for f in formats:
                    out_ext = _EDRW[dtype] if f == "edrawings" else _FMT[f]
                    if dtype == 3 and out_ext in _MODEL_ONLY or dtype != 3 and out_ext in _DRAWING_ONLY:
                        skipped.append({"file": path, "format": f, "reason": "not applicable"})
                        continue
                    out = os.path.normpath(os.path.join(out_root, rel, stem + out_ext))
                    if os.path.exists(out) and not overwrite:
                        skipped.append({"file": path, "format": f, "reason": "exists"})
                        continue
                    ok, errs, warns = cu.save_copy(sw, doc, out)
                    if ok:
                        done.append({"file": os.path.basename(path), "out": out,
                                     "kb": round(os.path.getsize(out) / 1024, 1)})
                    else:
                        failed.append({"file": path, "format": f, "errors": errs})
                if opened_here and not cu.try_call(doc, "GetSaveFlag", default=False):
                    cu.try_call(sw, "CloseDoc", str(cu.try_call(doc, "GetTitle", default="")))

            msg = (f"{len(done)} export(s) from {len(files)} file(s) in {time.time() - t0:.0f}s"
                   + (f", {len(failed)} failed" if failed else "")
                   + (f", {skipped_limit} file(s) beyond max_files not processed" if skipped_limit else ""))
            return self._result(not failed or bool(done), msg,
                                SwErrors.swSuccess if not failed else SwErrors.swExportError,
                                {"output_dir": out_root, "exported": done, "failed": failed,
                                 "skipped": skipped, "not_processed": skipped_limit})
        except Exception as e:
            logger.error(f"batch_export error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swExportError)

    def import_file(self, filepath: str, save_as: str = None) -> Dict:
        """
        Open a neutral / foreign CAD file (STEP, IGES, Parasolid, STL, Inventor,
        CATIA, NX…) through SolidWorks import or 3D Interconnect (per Options).
        Optionally save it as .sldprt / .sldasm.
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            sw = self.app
            path = os.path.abspath(os.path.expanduser(filepath))
            if not os.path.isfile(path):
                return self._result(False, f"File not found: {path}", SwErrors.swFileNotFoundError)
            ext = os.path.splitext(path)[1].lower()
            if ext in _DOC_EXT:
                return self.open_document(path)
            if ext not in _IMPORT_EXT:
                return self._result(False, f"Unsupported extension {ext}", SwErrors.swInvalidFileType)

            # SolidWorks cannot open two documents with the same title: importing
            # plate.step while plate.SLDPRT is open fails with error 1. Load a renamed copy.
            renamed = None
            stem = os.path.splitext(os.path.basename(path))[0].lower()
            open_stems = {os.path.splitext(str(cu.try_call(d, "GetTitle", default="")))[0].lower()
                          for d in cu.as_list(cu.try_call(sw, "GetDocuments"))}
            if stem in open_stems:
                import shutil
                import tempfile
                base, ext2 = os.path.splitext(os.path.basename(path))
                n = 1
                while f"{base}_import{n}".lower() in open_stems:
                    n += 1
                renamed = os.path.join(tempfile.gettempdir(), f"{base}_import{n}{ext2}")
                shutil.copy2(path, renamed)
                path = renamed
            data = cu.try_call(sw, "GetImportFileData", path)
            errs = cu.byref_int(0)
            t0 = time.time()
            doc = sw.LoadFile4(path, "r", data if data is not None else cu.nothing(), errs)
            if isinstance(doc, tuple):
                doc = doc[0]
            if doc is None:
                return self._result(False, f"Import failed (error {getattr(errs, 'value', '?')})",
                                    SwErrors.swFileLoadError)
            dtype = cu.doc_type(doc)
            info = {"title": str(cu.try_call(doc, "GetTitle", default="")),
                    "type": {1: "part", 2: "assembly", 3: "drawing"}.get(dtype, dtype),
                    "seconds": round(time.time() - t0, 1)}
            if renamed:
                info["renamed_copy"] = renamed
            if dtype == 1:
                info["solid_bodies"] = len(cu.as_list(cu.try_call(doc, "GetBodies2", 0, True)))
            elif dtype == 2:
                info["components"] = len(cu.as_list(cu.try_call(doc, "GetComponents", False)))

            if save_as:
                target = os.path.abspath(os.path.expanduser(save_as))
                want = ".sldasm" if dtype == 2 else ".sldprt"
                if not target.lower().endswith(want):
                    target += want
                os.makedirs(os.path.dirname(target), exist_ok=True)
                e, w = cu.byref_int(0), cu.byref_int(0)
                r = doc.Extension.SaveAs(target, 0, 1, cu.nothing(), e, w)
                ok = bool(r[0] if isinstance(r, tuple) else r) and os.path.isfile(target)
                info["saved_as"] = target if ok else None
                if not ok:
                    return self._result(False, f"Imported but save failed (error {getattr(e, 'value', '?')})",
                                        SwErrors.swFileSaveError, info)
            return self._result(True, f"Imported {os.path.basename(path)} as {info['type']}", SwErrors.swSuccess, info)
        except Exception as e:
            logger.error(f"import_file error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)

    def activate_document(self, name: str) -> Dict:
        """Bring an open document to front by title (e.g. 'Part2', 'Bracket.SLDPRT')."""
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            errs = cu.byref_int(0)
            doc = self.app.ActivateDoc3(name, False, 0, errs)
            if isinstance(doc, tuple):
                doc = doc[0]
            if doc is None:
                return self._result(False, f"'{name}' is not open (list_open_documents)", SwErrors.swInvalidInput)
            return self._result(True, f"Active: {cu.try_call(doc, 'GetTitle', default=name)}", SwErrors.swSuccess)
        except Exception as e:
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
