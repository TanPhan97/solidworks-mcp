"""
SolidWorks Document Operations
------------------------------
Create, open, save, and manage SolidWorks documents.
"""

import os
import logging
import traceback
from typing import Optional, Dict

import win32com.client
import pythoncom

from ..constants import SwErrors, SwDocumentTypes, SwFileTypes
from ..utils import find_template
from .templates import resolve_template
from . import com_utils as cu

logger = logging.getLogger(__name__)


class DocumentOperations:
    """
    Mixin class for document operations
    
    Requires parent class to have:
    - self._sw_app: SolidWorks application object
    - self.is_connected: Connection status property
    - self.connect(): Connection method
    - self._result(): Result factory method
    - self._units: UnitConverter instance
    """
    
    def _new_document(self, kind: str):
        """
        Resolve the template for `kind` and call NewDocument.
        Returns (doc, template_path, error_result).
        """
        configured = getattr(self._config, f"{kind}_template", "auto")
        template, source, tried = resolve_template(self._sw_app, kind, configured, find_template)
        if not template:
            return None, None, self._result(False,
                f"No {kind} template found. Set \"{kind}_template\" in solidworks_mcp/config.json "
                f"to a .{'prtdot' if kind == 'part' else 'asmdot' if kind == 'assembly' else 'drwdot'} "
                f"path, or set Tools > Options > Default Templates in SolidWorks.",
                SwErrors.swTemplateNotFound, {"tried": tried})
        logger.info(f"{kind} template ({source}): {template}")
        doc = self._sw_app.NewDocument(template, 0, 0, 0)
        if doc is None:
            return None, template, self._result(False,
                f"NewDocument returned nothing for template {template}",
                SwErrors.swFileLoadError, {"template": template, "source": source})
        return doc, template, None

    def create_new_part(self) -> Dict:
        """
        Create a new part document
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            doc, template, err = self._new_document("part")
            if err:
                return err
            
            # Set view
            try:
                doc.ShowNamedView2("*Isometric", 7)
                cu.call(doc, "ViewZoomtofit2")
            except:
                pass
            
            title = self._get_doc_title(doc)
            
            return self._result(True, f"Created part: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Part", "template": template})
            
        except Exception as e:
            logger.error(f"Create part error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def create_new_assembly(self) -> Dict:
        """
        Create a new assembly document
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            doc, template, err = self._new_document("assembly")
            if err:
                return err
            
            try:
                doc.ShowNamedView2("*Isometric", 7)
                cu.call(doc, "ViewZoomtofit2")
            except:
                pass
            
            title = self._get_doc_title(doc)
            
            return self._result(True, f"Created assembly: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Assembly"})
            
        except Exception as e:
            logger.error(f"Create assembly error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def create_new_drawing(self, paper_size: str = "A4") -> Dict:
        """
        Create a new drawing document
        
        Args:
            paper_size: Paper size (A4, A3, A2, A1, Letter)
        
        Returns:
            Result dictionary with document info
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            doc, template, err = self._new_document("drawing")
            if err:
                return err
            
            title = self._get_doc_title(doc)
            
            return self._result(True, f"Created drawing: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "type": "Drawing", "paper_size": paper_size})
            
        except Exception as e:
            logger.error(f"Create drawing error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def open_document(self, filepath: str) -> Dict:
        """
        Open an existing document
        
        Args:
            filepath: Path to SolidWorks file
        
        Returns:
            Result dictionary
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            if not os.path.exists(filepath):
                return self._result(False, f"File not found: {filepath}",
                                  SwErrors.swFileNotFoundError)
            
            # Determine document type from extension
            ext = os.path.splitext(filepath)[1].lower()
            type_map = {
                ".sldprt": SwDocumentTypes.swDocPART,
                ".sldasm": SwDocumentTypes.swDocASSEMBLY,
                ".slddrw": SwDocumentTypes.swDocDRAWING,
            }
            doc_type = type_map.get(ext, SwDocumentTypes.swDocPART)
            
            # Open document
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            
            doc = self._sw_app.OpenDoc6(filepath, int(doc_type), 0, "", errors, warnings)
            
            if doc is None or errors.value != 0:
                return self._result(False, f"Failed to open (error {errors.value})",
                                  SwErrors.swFileLoadError)
            
            title = self._get_doc_title(doc)
            
            return self._result(True, f"Opened: {title}",
                              SwErrors.swSuccess,
                              {"name": title, "path": filepath})
            
        except Exception as e:
            logger.error(f"Open document error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileLoadError)
    
    def save_document(self, filepath: str = None) -> Dict:
        """
        Save the active document (silently: never opens a dialog).
        filepath given → Save As (extension added from the document type if missing);
        no filepath → save in place.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            e, w = cu.byref_int(0), cu.byref_int(0)
            if filepath:
                filepath = os.path.abspath(os.path.expanduser(filepath))
                ext = {1: ".SLDPRT", 2: ".SLDASM", 3: ".SLDDRW"}.get(cu.doc_type(doc))
                if ext and os.path.splitext(filepath)[1].lower() not in (".sldprt", ".sldasm", ".slddrw"):
                    filepath += ext
                os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
                # swSaveAsCurrentVersion=0, swSaveAsOptions_Silent=1
                r = doc.Extension.SaveAs(filepath, 0, 1, cu.nothing(), e, w)
                ok = bool(r[0] if isinstance(r, tuple) else r) and os.path.isfile(filepath)
            else:
                if not self._get_doc_path(doc):
                    return self._result(False, "Document was never saved: give filepath",
                                        SwErrors.swInvalidInput)
                r = doc.Save3(1, e, w)
                ok = bool(r[0] if isinstance(r, tuple) else r)
                filepath = self._get_doc_path(doc)
            if not ok:
                return self._result(False, f"Save failed (swFileSaveError {getattr(e, 'value', '?')}, "
                                           f"warnings {getattr(w, 'value', '?')})", SwErrors.swFileSaveError)
            return self._result(True, f"Saved: {filepath}", SwErrors.swSuccess,
                                {"path": filepath, "warnings": getattr(w, "value", 0)})
        except Exception as e:
            logger.error(f"Save error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swFileSaveError)

    def close_document(self, save: bool = False, discard_changes: bool = False) -> Dict:
        """
        Close the active document. Unsaved changes are never dropped silently:
        save=True saves first (silent); otherwise a modified document is only
        closed with discard_changes=True.
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return self._result(True, "No document to close")
            title = self._get_doc_title(doc)
            dirty = bool(cu.try_call(doc, "GetSaveFlag", default=False))
            if save and dirty:
                if not self._get_doc_path(doc):
                    return self._result(False, f"'{title}' was never saved: save_document(filepath) first",
                                        SwErrors.swInvalidInput)
                e, w = cu.byref_int(0), cu.byref_int(0)
                r = doc.Save3(1, e, w)
                if not bool(r[0] if isinstance(r, tuple) else r):
                    return self._result(False, f"Save failed (swFileSaveError {getattr(e, 'value', '?')}); "
                                               "document left open", SwErrors.swFileSaveError)
            elif dirty and not discard_changes:
                return self._result(False, f"'{title}' has unsaved changes: use save=true, or "
                                           "discard_changes=true to close without saving",
                                    SwErrors.swInvalidInput, {"document": title})
            self._sw_app.CloseDoc(title)
            return self._result(True, f"Closed: {title}", SwErrors.swSuccess, {"document": title})
        except Exception as e:
            logger.error(f"Close error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)

    def get_document_info(self) -> Dict:
        """
        Get information about the active document
        
        Returns:
            Result dictionary with document details
        """
        try:
            doc, err = self.get_active_doc()
            if err:
                return err
            
            type_names = {
                0: "None",
                1: "Part",
                2: "Assembly",
                3: "Drawing"
            }
            
            doc_type = cu.doc_type(doc)
            title = self._get_doc_title(doc)
            path = self._get_doc_path(doc)
            
            info = {
                "title": title,
                "path": path if path else "Not saved",
                "type": type_names.get(doc_type, "Unknown"),
                "type_code": doc_type,
            }
            
            return self._result(True, f"{title} ({info['type']})",
                              SwErrors.swSuccess, info)
            
        except Exception as e:
            logger.error(f"Get info error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
    
    def list_open_documents(self) -> Dict:
        """
        List all open documents
        
        Returns:
            Result dictionary with document list
        """
        try:
            if not self.is_connected:
                r = self.connect()
                if not r["success"]:
                    return r
            
            docs = []
            doc = cu.call(self._sw_app, "GetFirstDocument")
            
            while doc:
                try:
                    title = str(cu.call(doc, "GetTitle"))
                    doc_type = cu.doc_type(doc)
                    
                    type_names = {1: "Part", 2: "Assembly", 3: "Drawing"}
                    
                    docs.append({
                        "title": title,
                        "type": type_names.get(doc_type, "Unknown")
                    })
                except:
                    pass
                
                doc = cu.try_call(doc, "GetNext")
            
            return self._result(True, f"{len(docs)} document(s) open",
                              SwErrors.swSuccess, {"documents": docs})
            
        except Exception as e:
            logger.error(f"List documents error: {e}\n{traceback.format_exc()}")
            return self._result(False, f"Error: {e}", SwErrors.swUnknownError)
