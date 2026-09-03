from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from .models import (
    BOM,
    ComparisonResult,
    ExclusivePart,
    PairOverlap,
    SharedPart,
    VersionCell,
    VersionColumn,
    VersionFamily,
    VersionMatrix,
    VersionMatrixRow,
)
from .parse import family_short, is_cad_only_file, is_pcb_text, load_bom, product_family, version_label

DESIG_SPLIT = re.compile(r"[,;]+")


def _code_key(component) -> str:
    value = (component.codigo or "").strip().upper()
    if not value or value == "NO MONTAR":
        return ""
    return value


def _bom_family(bom: BOM) -> str:
    if bom.family:
        return bom.family
    stem = bom.path.stem if bom.path else ""
    return product_family(bom.product, bom.product_code, stem)


def _bom_variant(bom: BOM) -> str:
    if bom.variant:
        return bom.variant
    stem = bom.path.stem if bom.path else ""
    return version_label(bom.product, _bom_family(bom), stem)


def _split_designators(text: str) -> list[str]:
    if not text:
        return []
    return [part.strip().upper() for part in DESIG_SPLIT.split(text) if part.strip()]


def _desig_sort_key(designator: str) -> tuple:
    match = re.match(r"^([A-Z]+)(\d+)(.*)$", designator, re.I)
    if match:
        return (1, match.group(1).upper(), int(match.group(2)), match.group(3).upper())
    return (0, designator.upper(), 0, "")


def _norm_layer(layer: str) -> str:
    text = (layer or "").strip()
    folded = text.lower()
    if folded in {"top", "t", "front", "cara top"}:
        return "Top"
    if folded in {"bottom", "bot", "b", "back", "cara bottom"}:
        return "Bottom"
    return text


def _is_used(component) -> bool:
    """True si el componente se monta de verdad (no DNP ni cantidad 0)."""
    return bool(component.fitted) and float(component.quantity or 0) > 0


def _group(bom: BOM, include_dnp: bool) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for component in bom.mounted(include_dnp=include_dnp):
        if is_pcb_text(
            component.codigo,
            component.referencia,
            component.designator,
            component.descripcion,
            component.fabricante,
        ):
            continue
        if not include_dnp and not _is_used(component):
            continue
        key = _code_key(component)
        if not key:
            continue
        grouped[key].append(component)
    return grouped


def _summarize(boms: list[BOM], grouped: list[dict[str, list]], key: str) -> tuple[dict, dict, str, str, str]:
    quantities: dict[str, float] = {}
    refs: dict[str, str] = {}
    descripcion = referencia = fabricante = ""
    for i, bom in enumerate(boms):
        comps = grouped[i].get(key, [])
        if not comps:
            continue
        used = [c for c in comps if _is_used(c)]
        pick = used or comps
        if used:
            quantities[bom.label] = sum(c.quantity for c in used)
        else:
            continue
        refs[bom.label] = pick[0].referencia
        if not descripcion:
            descripcion = pick[0].descripcion
            referencia = pick[0].referencia
            fabricante = pick[0].fabricante
    return quantities, refs, descripcion, referencia, fabricante


def _placements(bom: BOM, include_dnp: bool) -> dict:
    placed = {}
    for component in bom.mounted(include_dnp=include_dnp):
        if is_pcb_text(
            component.codigo,
            component.referencia,
            component.designator,
            component.descripcion,
            component.fabricante,
        ):
            continue
        designators = _split_designators(component.designator)
        if not designators:
            continue
        qty = (component.quantity / len(designators)) if component.quantity else 1.0
        for des in designators:
            placed[des] = component.__class__(
                designator=des,
                codigo=_code_key(component),
                referencia=component.referencia,
                fabricante=component.fabricante,
                descripcion=component.descripcion,
                quantity=qty,
                footprint=component.footprint,
                fitted=component.fitted,
                layer=component.layer,
                source_row=component.source_row,
            )
    return placed


def _annotate_cells(cells: list[VersionCell]) -> None:
    codes = [c.codigo for c in cells if c.present and c.codigo]
    mode = Counter(codes).most_common(1)[0][0] if codes else ""
    distinct = len(set(codes)) > 1
    for cell in cells:
        cell.yellow = (not cell.present) or cell.fitted == "NotFitted"
        cell.code_red = bool(
            distinct and cell.present and cell.codigo and mode and cell.codigo != mode
        )


def _unique_columns(boms: list[BOM]) -> list[VersionColumn]:
    used: dict[str, int] = {}
    columns: list[VersionColumn] = []
    for bom in boms:
        label = _bom_variant(bom)
        key = label
        if key in used:
            used[key] += 1
            key = f"{label}_{used[key]}"
        else:
            used[key] = 1
        columns.append(VersionColumn(key=key, label=label, product=bom.label))
    return columns


def _version_data(boms: list[BOM]) -> tuple[list[VersionMatrix], list[VersionFamily]]:
    groups: dict[str, list[BOM]] = {}
    order: list[str] = []
    for bom in boms:
        fam = _bom_family(bom)
        if fam not in groups:
            groups[fam] = []
            order.append(fam)
        groups[fam].append(bom)

    families: list[VersionFamily] = []
    matrices: list[VersionMatrix] = []
    for fam in order:
        members = groups[fam]
        columns = _unique_columns(members)
        families.append(
            VersionFamily(
                familia=fam,
                familia_corta=family_short(fam),
                products=[bom.label for bom in members],
                versions=columns,
            )
        )
        if len(members) < 2:
            continue
        maps = [_placements(bom, include_dnp=True) for bom in members]
        designators = sorted(set().union(*[set(mp) for mp in maps]), key=_desig_sort_key)
        rows: list[VersionMatrixRow] = []
        for des in designators:
            cells: list[VersionCell] = []
            for mp in maps:
                comp = mp.get(des)
                if not comp:
                    cells.append(
                        VersionCell(codigo="", layer="", fitted="", present=False)
                    )
                else:
                    cells.append(
                        VersionCell(
                            codigo=comp.codigo,
                            layer=_norm_layer(comp.layer),
                            fitted="Fitted" if comp.fitted else "NotFitted",
                            present=True,
                        )
                    )
            _annotate_cells(cells)
            rows.append(VersionMatrixRow(designator=des, cells=cells))
        matrices.append(
            VersionMatrix(
                familia=fam,
                familia_corta=family_short(fam),
                versions=columns,
                rows=rows,
            )
        )
    return matrices, families


def filter_matrix(matrix: VersionMatrix, keys: list[str] | None) -> VersionMatrix | None:
    if not keys:
        return matrix
    wanted = set(keys)
    idxs = [i for i, col in enumerate(matrix.versions) if col.key in wanted]
    if len(idxs) < 2:
        return None
    rows = []
    for row in matrix.rows:
        cells = [
            VersionCell(
                codigo=row.cells[i].codigo,
                layer=row.cells[i].layer,
                fitted=row.cells[i].fitted,
                present=row.cells[i].present,
            )
            for i in idxs
        ]
        _annotate_cells(cells)
        rows.append(VersionMatrixRow(designator=row.designator, cells=cells))
    return VersionMatrix(
        familia=matrix.familia,
        familia_corta=matrix.familia_corta,
        versions=[matrix.versions[i] for i in idxs],
        rows=rows,
    )


def compare_boms(
    paths: list[str | Path] | None = None,
    *,
    boms: list[BOM] | None = None,
    key_field: str = "codigo",
    include_dnp: bool = False,
) -> ComparisonResult:
    if boms is None:
        if not paths:
            raise ValueError("Indica rutas o BOM ya cargadas")
        boms = [load_bom(path) for path in paths if not is_cad_only_file(Path(path).name)]
    else:
        boms = [bom for bom in boms if not is_cad_only_file(bom.path.name if bom.path else "")]
    if len(boms) < 2:
        raise ValueError("Se necesitan al menos dos BOM para comparar")

    grouped = [_group(bom, include_dnp) for bom in boms]
    universe = sorted(set().union(*[set(g) for g in grouped]))
    matches: list[SharedPart] = []
    exclusive: list[ExclusivePart] = []
    presence: dict[str, dict[str, bool]] = {}

    for key in universe:
        in_map = {bom.label: key in grouped[i] for i, bom in enumerate(boms)}
        presence[key] = in_map
        present = [label for label, ok in in_map.items() if ok]
        quantities, refs, descripcion, referencia, fabricante = _summarize(boms, grouped, key)

        if len(present) == 1:
            label = present[0]
            exclusive.append(
                ExclusivePart(
                    key=key,
                    bom=label,
                    descripcion=descripcion,
                    referencia=referencia,
                    fabricante=fabricante,
                    quantity=quantities.get(label, 0),
                )
            )
            continue

        matches.append(
            SharedPart(
                key=key,
                descripcion=descripcion,
                referencia=referencia,
                fabricante=fabricante,
                in_boms=present,
                quantities=quantities,
                referencias_por_bom=refs,
            )
        )

    matches.sort(key=lambda p: (-len(p.in_boms), p.key))
    exclusive.sort(key=lambda p: (p.bom, p.key))

    identity_sets = [set(groups) for groups in grouped]
    unique_counts = {bom.label: len(keys) for bom, keys in zip(boms, identity_sets)}

    pairs: list[PairOverlap] = []
    for i, left in enumerate(boms):
        for j, right in enumerate(boms):
            if j <= i:
                continue
            common = identity_sets[i] & identity_sets[j]
            union = identity_sets[i] | identity_sets[j]
            pairs.append(
                PairOverlap(
                    a=left.label,
                    b=right.label,
                    n_common=len(common),
                    jaccard=round(len(common) / max(1, len(union)), 4),
                )
            )

    matrices, families = _version_data(boms)
    return ComparisonResult(
        boms=boms,
        matches=matches,
        exclusive=exclusive,
        pairs=pairs,
        presence=presence,
        unique_counts=unique_counts,
        version_matrices=matrices,
        version_families=families,
        key_field="codigo",
    )
