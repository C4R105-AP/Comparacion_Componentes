"""Comparador de BOM: parseo de Excel y cruce de componentes por codigo."""

from .compare import compare_boms
from .models import BOM, Component, ComparisonResult
from .parse import inspect_bom, load_bom
from .report import write_excel

__all__ = [
    "BOM",
    "Component",
    "ComparisonResult",
    "compare_boms",
    "inspect_bom",
    "load_bom",
    "write_excel",
]
