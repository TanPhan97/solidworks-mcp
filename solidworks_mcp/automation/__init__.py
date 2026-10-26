"""
SolidWorks Automation Package
-----------------------------
Complete automation class combining all operations.
"""

from .base import SolidWorksAutomation as _BaseAutomation
from .documents import DocumentOperations
from .sketches import SketchOperations
from .features import FeatureOperations
from .selection import SelectionOperations
from .sketch_ext import SketchExtOperations
from .advanced_features import AdvancedFeatureOperations
from .model_ops import ModelOperations
from .assembly import AssemblyOperations
from .drawing import DrawingOperations
from .sweep_loft import SweepLoftOperations
from .batch_import import BatchImportOperations
from .edit_ops import EditOperations
from .detail_features import DetailFeatureOperations
from .core_ops import CoreOperations
from .part_plus import PartPlusOperations
from .assembly_plus import AssemblyPlusOperations
from .part_mold import PartMoldOperations
from .assembly_tools import AssemblyToolsOperations
from .drawing_plus import DrawingPlusOperations
from .sheet_metal import SheetMetalOperations
from .surfaces import SurfaceOperations


class SolidWorksAutomation(CoreOperations, _BaseAutomation, DocumentOperations,
                           SketchOperations, FeatureOperations,
                           SelectionOperations, SketchExtOperations,
                           AdvancedFeatureOperations, ModelOperations,
                           AssemblyOperations, DrawingOperations,
                           SweepLoftOperations, BatchImportOperations,
                           EditOperations, DetailFeatureOperations,
                           PartPlusOperations, AssemblyPlusOperations,
                           PartMoldOperations, AssemblyToolsOperations,
                           DrawingPlusOperations, SheetMetalOperations,
                           SurfaceOperations):
    """
    Complete SolidWorks automation class
    
    Combines all operation mixins:
    - Base: Connection, document access, utilities
    - Documents: Create, open, save, close documents
    - Sketches: Create sketches, draw 2D geometry
    - Features: Extrude, cut, fillet, chamfer
    - Selection: Topology listing and index/filter-based selection
    - SketchExt: Dimensions, relations, slot, sketch fillet
    - AdvancedFeatures: Revolve, shell, patterns, mirror, ref planes
    - Model: Dimensions edit, suppress, mass props, material, properties, export, view
    - Assembly: Insert component, mates, component list
    
    Example:
        sw = SolidWorksAutomation()
        sw.connect()
        sw.create_new_part()
        sw.create_sketch("Front")
        sw.draw_circle(0, 0, 25)
        sw.extrude_sketch(10)
        sw.save_document("C:/Parts/MyPart.sldprt")
    """
    pass


__all__ = [
    "SolidWorksAutomation",
    "DocumentOperations",
    "SketchOperations", 
    "FeatureOperations",
    "SelectionOperations",
    "SketchExtOperations",
    "AdvancedFeatureOperations",
    "ModelOperations",
    "AssemblyOperations",
    "DrawingOperations",
    "SweepLoftOperations",
    "BatchImportOperations",
    "EditOperations",
    "DetailFeatureOperations",
    "CoreOperations",
    "PartPlusOperations",
    "AssemblyPlusOperations",
]
