"""Comparador de BOM: parseo de Excel y cruce de componentes por codigo."""

__version__ = "1.0.0"

from .compare import compare_boms
from .models import BOM, Component, ComparisonResult
from .parse import inspect_bom, load_bom
from .report import write_excel

__all__ = [
    "__version__",
    "BOM",
    "Component",
    "ComparisonResult",
    "compare_boms",
    "inspect_bom",
    "load_bom",
    "write_excel",
]
