from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Component:
    designator: str
    codigo: str
    referencia: str
    fabricante: str
    descripcion: str
    quantity: float = 1.0
    footprint: str = ""
    fitted: bool = True
    layer: str = ""
    source_row: int = 0


@dataclass
class BOM:
    path: Path
    product: str
    product_code: str
    date: str
    sheet: str
    components: list[Component] = field(default_factory=list)
    format_label: str = ""
    columns_found: list[str] = field(default_factory=list)
    family: str = ""
    variant: str = ""

    @property
    def label(self) -> str:
        return self.product or self.path.stem

    def mounted(self, include_dnp: bool = False) -> list[Component]:
        if include_dnp:
            return list(self.components)
        return [c for c in self.components if c.fitted]


@dataclass
class SharedPart:
    key: str
    descripcion: str
    referencia: str
    fabricante: str
    in_boms: list[str]
    quantities: dict[str, float]
    referencias_por_bom: dict[str, str]


@dataclass
class ExclusivePart:
    key: str
    bom: str
    descripcion: str
    referencia: str
    fabricante: str
    quantity: float


@dataclass
class PairOverlap:
    a: str
    b: str
    n_common: int
    jaccard: float


@dataclass
class VersionCell:
    codigo: str
    layer: str
    fitted: str
    present: bool
    yellow: bool = False
    code_red: bool = False


@dataclass
class VersionColumn:
    key: str
    label: str
    product: str


@dataclass
class VersionMatrixRow:
    designator: str
    cells: list[VersionCell]


@dataclass
class VersionFamily:
    familia: str
    familia_corta: str
    products: list[str]
    versions: list[VersionColumn]


@dataclass
class VersionMatrix:
    familia: str
    familia_corta: str
    versions: list[VersionColumn]
    rows: list[VersionMatrixRow]


@dataclass
class ComparisonResult:
    boms: list[BOM]
    matches: list[SharedPart]
    exclusive: list[ExclusivePart]
    pairs: list[PairOverlap]
    presence: dict[str, dict[str, bool]]
    unique_counts: dict[str, int]
    version_matrices: list[VersionMatrix] = field(default_factory=list)
    version_families: list[VersionFamily] = field(default_factory=list)
    key_field: str = "codigo"

    @property
    def shared(self) -> list[SharedPart]:
        n = len(self.boms)
        return [p for p in self.matches if len(p.in_boms) == n]

    @property
    def partial(self) -> list[SharedPart]:
        n = len(self.boms)
        return [p for p in self.matches if len(p.in_boms) < n]

    @property
    def all_parts(self) -> list[SharedPart]:
        extras = [
            SharedPart(
                key=p.key,
                descripcion=p.descripcion,
                referencia=p.referencia,
                fabricante=p.fabricante,
                in_boms=[p.bom],
                quantities={p.bom: p.quantity},
                referencias_por_bom={p.bom: p.referencia},
            )
            for p in self.exclusive
        ]
        return [*self.matches, *extras]
