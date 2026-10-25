"""
Document template resolution
----------------------------
The original finder only looked for 'Part.prtdot' in a few hard-coded
folders (up to SW 2025) and then passed "" to NewDocument, which returns
None. This resolver asks SolidWorks itself first, so custom template
folders and SW 2026+ work.

Order (first existing file wins):
  1. config.json  <kind>_template  (explicit path, unless "auto")
  2. Tools > Options > Default Templates  (GetUserPreferenceStringValue)
  3. ISldWorks.GetDocumentTemplate        (SW's own default for the doc type)
  4. Tools > Options > File Locations > Document Templates  (scan *.prtdot ...)
  5. ProgramData\\SOLIDWORKS\\SOLIDWORKS <year>\\templates   (any year, newest first)
  6. Legacy finder (install dir)
"""

import os
import glob
import logging
from typing import List, Optional, Tuple

from . import com_utils as cu

logger = logging.getLogger(__name__)

# swUserPreferenceStringValue_e
_PREF_DEFAULT_TEMPLATE = {"part": 8, "assembly": 9, "drawing": 10}
_PREF_TEMPLATE_FOLDERS = 0            # swFileLocationsDocumentTemplates
_DOC_TYPE = {"part": 1, "assembly": 2, "drawing": 3}
_EXT = {"part": ".prtdot", "assembly": ".asmdot", "drawing": ".drwdot"}
PROGRAMDATA_ROOTS = (r"C:\ProgramData\SOLIDWORKS", r"C:\ProgramData\SolidWorks")
_PREFERRED_NAMES = {"part": ("part",), "assembly": ("assembly", "assem", "asm"),
                    "drawing": ("drawing", "drw")}


def _existing(path) -> Optional[str]:
    if path and isinstance(path, str):
        p = os.path.expandvars(path.strip().strip('"'))
        if os.path.isfile(p):
            return p
    return None


def _scan_folder(folder: str, kind: str) -> Optional[str]:
    """Pick a template of the right type in `folder` (one level of subfolders)."""
    ext = _EXT[kind]
    files = sorted(glob.glob(os.path.join(folder, "*" + ext))
                   + glob.glob(os.path.join(folder, "*", "*" + ext)))
    if not files:
        return None
    for key in _PREFERRED_NAMES[kind]:
        for f in files:
            if key in os.path.basename(f).lower():
                return f
    return files[0]


def resolve_template(sw_app, kind: str, configured: str = "auto",
                     legacy_finder=None) -> Tuple[Optional[str], str, List[str]]:
    """
    Returns (path, source, tried). `tried` lists every location checked,
    for the error message when nothing is found.
    """
    kind = kind.lower()
    tried: List[str] = []

    # 1. explicit config
    if configured and configured != "auto":
        tried.append(f"config: {configured}")
        p = _existing(configured)
        if p:
            return p, "config.json", tried

    # 2. default template preference
    pref = cu.try_call(sw_app, "GetUserPreferenceStringValue", _PREF_DEFAULT_TEMPLATE[kind])
    tried.append(f"Options>Default Templates: {pref!r}")
    p = _existing(pref)
    if p:
        return p, "SolidWorks default template", tried

    # 3. SW's own default for this document type
    gdt = cu.try_call(sw_app, "GetDocumentTemplate", _DOC_TYPE[kind], "", 0, 0.0, 0.0)
    tried.append(f"GetDocumentTemplate: {gdt!r}")
    p = _existing(gdt)
    if p:
        return p, "GetDocumentTemplate", tried

    # 4. template folders from File Locations
    folders = cu.try_call(sw_app, "GetUserPreferenceStringValue", _PREF_TEMPLATE_FOLDERS) or ""
    for folder in [f for f in str(folders).split(";") if f.strip()]:
        tried.append(f"File Locations folder: {folder}")
        p = _scan_folder(folder.strip(), kind)
        if p:
            return p, f"template folder {folder}", tried

    # 5. ProgramData, any version, newest first
    for root in PROGRAMDATA_ROOTS:
        for folder in sorted(glob.glob(os.path.join(root, "SOLIDWORKS *", "templates")), reverse=True):
            tried.append(f"ProgramData: {folder}")
            p = _scan_folder(folder, kind)
            if p:
                return p, f"ProgramData {folder}", tried

    # 6. legacy finder
    if legacy_finder:
        p = _existing(legacy_finder(kind))
        tried.append("legacy install-dir search")
        if p:
            return p, "install dir", tried

    return None, "", tried
