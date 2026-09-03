from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from .models import BOM, Component

NAV_RE = re.compile(r"^(E\d{5,}|\d{10,14})$", re.I)
DESIGNATOR_RE = re.compile(
    r"^[A-Z]{1,5}\d{1,4}[A-Z]?\d*(?:\s*,\s*[A-Z]{1,5}\d{1,4}[A-Z]?\d*)*$",
    re.I,
)
DNP_TOKENS = ("no montar", "not fitted", "dnp", "do not place", "no fit")
SKIP_SHEETS = ("historico", "histórico", "history", "changelog")
# Pick & place cuyo nombre es "BOM CAD …" (con espacio): no sirve para el cruce.
CAD_ONLY_NAME = re.compile(r"(?i)(?:^|[\s_\-])BOM[\s_\-]+CAD(?:[\s_\-]|$)")
# Referencias de circuito impreso (prefijo IMP-). Se excluyen del parseo y del cruce.
PCB_RE = re.compile(r"imp\s*[-–—_‐‑]", re.I)
GENERIC_PRODUCT_NAMES = frozenset({
    "pcb", "pcba", "cad", "bom", "bomcad", "lista",
    "historico", "codigo", "sheet", "hoja", "assembly", "placa",
})
# Codigo de producto en celdas o en el nombre de archivo.
PRODUCT_TOKEN = re.compile(
    r"(CE-[A-Z0-9+._-]+|[A-Z]{3,}\d{2,}[A-Z0-9+]*)",
    re.I,
)

COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "designator": (
        "designator", "designators", "ref", "item", "posicion", "posicion",
        "location", "locator", "reference designator", "desig",
    ),
    "referencia": (
        "referencia", "reference", "mpn", "part number", "partnumber",
        "part no", "p n", "pn", "mfg pn", "manufacturer pn", "manuf pn",
        "manufacturer part",
    ),
    "codigo": (
        "codigo", "código", "code", "erp", "ipn", "internal pn",
        "item code", "part code", "id interno",
    ),
    "fabricante": (
        "fabricante", "manufacturer", "mfr", "mfg", "vendor", "maker",
    ),
    "descripcion": (
        "descripcion", "description", "desc", "comment", "comments",
        "detalle",
    ),
    "quantity": (
        "quantity", "qty", "cantidad", "cant", "qpa", "count",
    ),
    "footprint": (
        "footprint", "package", "encapsulado", "case", "pcb footprint",
    ),
    "fitted": (
        "fitted", "fit", "montar", "dnp", "populated", "install",
    ),
    "layer": ("layer", "side", "capa", "face"),
    "center_x": ("center x mm", "center x", "x mm", "pos x", "mid x"),
    "center_y": ("center y mm", "center y", "y mm", "pos y", "mid y"),
}

# "Ref." is a designator header in these BOMs; never treat it as MPN.
EXACT_HEADER = {
    "ref.": "designator",
    "ref": "designator",
}


def is_cad_only_file(name: str) -> bool:
    """True si el Excel es solo colocacion (nombre 'BOM CAD …'), no una lista de materiales."""
    stem = Path(name).stem.replace("+", " ")
    return bool(CAD_ONLY_NAME.search(stem))


def _norm(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().strip()
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _norm_nav(value) -> str:
    text = _norm(value).upper()
    text = re.sub(r"^NAV\s*[:.]?\s*", "", text)
    return text.strip()


def _looks_nav(value: str) -> bool:
    return bool(NAV_RE.match(_norm_nav(value)))


def _header_score(cell: str, target: str) -> float:
    folded = _fold(cell)
    if not folded:
        return 0.0
    exact = EXACT_HEADER.get(folded) or EXACT_HEADER.get(cell.strip().lower())
    if exact:
        return 1.0 if exact == target else 0.0
    best = 0.0
    for syn in COLUMN_SYNONYMS[target]:
        if folded == syn:
            return 1.0
        if len(syn) >= 4 and (syn in folded or folded in syn):
            best = max(best, 0.92)
        best = max(best, SequenceMatcher(None, folded, syn).ratio())
    return best


def map_headers(cells: list[str]) -> list[str]:
    """Map each header cell to a canonical field or ''."""
    taken: dict[str, tuple[int, float]] = {}
    assigned = [""] * len(cells)
    candidates: list[tuple[float, int, str]] = []
    for idx, cell in enumerate(cells):
        for target in COLUMN_SYNONYMS:
            score = _header_score(cell, target)
            if score >= 0.78:
                candidates.append((score, idx, target))
    candidates.sort(reverse=True)
    used_idx: set[int] = set()
    for score, idx, target in candidates:
        if idx in used_idx:
            continue
        prev = taken.get(target)
        if prev and prev[1] >= score:
            continue
        if prev:
            assigned[prev[0]] = ""
            used_idx.discard(prev[0])
        assigned[idx] = target
        taken[target] = (idx, score)
        used_idx.add(idx)
    return assigned


def _is_header_row(cells: list[str]) -> bool:
    mapped = [c for c in map_headers(cells) if c]
    return len(set(mapped)) >= 2


def is_pcb_text(*parts: str) -> bool:
    """True si el texto es una PCB (contiene ``IMP-`` o variante de guion)."""
    return any(bool(PCB_RE.search(part or "")) for part in parts)


def _is_skip_row(cells: list[str]) -> bool:
    nonempty = [c for c in cells if c]
    if not nonempty:
        return True
    joined = " ".join(nonempty).lower()
    if joined in {"ref.", "ref"}:
        return True
    if any(_looks_nav(c) for c in nonempty):
        return False
    if DESIGNATOR_RE.match(nonempty[0]):
        return False
    short = [c for c in nonempty if len(c) <= 32]
    if len(short) < 2:
        return False
    return _is_header_row(short)


def _looks_dnp(record: dict[str, str], raw_row: list[str]) -> bool:
    fitted = record.get("fitted", "").lower()
    if fitted in {"not fitted", "dnp", "no", "unfitted"}:
        return True
    blob = " ".join(raw_row).lower()
    if any(token in blob for token in DNP_TOKENS):
        return True
    qty = record.get("quantity", "")
    if qty:
        try:
            if float(str(qty).replace(",", ".")) == 0:
                return True
        except ValueError:
            pass
    return False


def _parse_qty(value: str, fitted: bool) -> float:
    text = _norm(value)
    if not text:
        return 1.0 if fitted else 0.0
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return 1.0 if fitted else 0.0


def _infer_missing_columns(frame: pd.DataFrame, header_idx: int, mapped: list[str]) -> list[str]:
    """Fill gaps by looking at cell patterns under each column."""
    mapped = list(mapped)
    have = {name for name in mapped if name}
    sample = []
    for i in range(header_idx + 1, min(header_idx + 40, len(frame))):
        sample.append([_norm(v) for v in frame.iloc[i].tolist()])
    if not sample:
        return mapped

    width = max(len(mapped), max(len(row) for row in sample))
    while len(mapped) < width:
        mapped.append("")

    def col_values(j: int) -> list[str]:
        return [row[j] for row in sample if j < len(row) and row[j]]

    if "codigo" not in have:
        best_j, best_n = -1, 0
        for j in range(width):
            if mapped[j]:
                continue
            vals = col_values(j)
            n = sum(1 for v in vals if _looks_nav(v))
            if vals and n / max(1, len(vals)) >= 0.4 and n > best_n:
                best_j, best_n = j, n
        if best_j >= 0:
            mapped[best_j] = "codigo"
            have.add("codigo")

    if "designator" not in have:
        best_j, best_n = -1, 0
        for j in range(width):
            if mapped[j]:
                continue
            vals = col_values(j)
            n = sum(1 for v in vals if DESIGNATOR_RE.match(v or ""))
            if vals and n / max(1, len(vals)) >= 0.4 and n > best_n:
                best_j, best_n = j, n
        if best_j >= 0:
            mapped[best_j] = "designator"

    return mapped


def _find_header_row(frame: pd.DataFrame) -> int:
    best_i, best_n = 0, -1
    for i in range(min(20, len(frame))):
        cells = [_norm(v) for v in frame.iloc[i].tolist()]
        mapped = [c for c in map_headers(cells) if c]
        n = len(set(mapped))
        if n > best_n:
            best_i, best_n = i, n
        if n >= 3:
            return i
    return best_i


def _product_from_text(text: str) -> str:
    """Extrae un codigo de producto; ignora etiquetas genericas como PCB."""
    if not text:
        return ""
    if _fold(text) in GENERIC_PRODUCT_NAMES or is_pcb_text(text):
        return ""
    match = PRODUCT_TOKEN.search(text)
    if not match:
        return ""
    token = match.group(1).strip("-_.")
    if _looks_nav(token) or _fold(token) in GENERIC_PRODUCT_NAMES:
        return ""
    return token


def _product_meta(frame: pd.DataFrame, path: Path) -> tuple[str, str, str]:
    product = product_code = date = ""
    for i in range(min(6, len(frame))):
        row = [_norm(v) for v in frame.iloc[i].tolist()]
        nonempty = [c for c in row if c]
        if not nonempty:
            continue
        if not date and re.match(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}", nonempty[0]):
            date = nonempty[0][:10]
        if not product:
            for cell in nonempty:
                cand = _product_from_text(cell)
                if cand:
                    product = cand
                    break
            for cell in nonempty[1:]:
                if _looks_nav(cell):
                    product_code = _norm_nav(cell)
                    break
    if not product:
        product = _product_from_text(path.stem) or path.stem
    return product, product_code, date


def product_family(product: str, product_code: str = "", stem: str = "") -> str:
    """Codigo base de producto: CE-BOARD-AX-001 -> CE-BOARD."""
    for text in (product, stem):
        token = _product_from_text(text or "")
        if not token:
            continue
        match = re.search(r"(CE-[A-Z0-9+]+)", token, re.I)
        if match:
            return match.group(1).upper()
        match = re.search(r"([A-Z]{3,}\d{2,}[A-Z0-9]*)", token, re.I)
        if match:
            return match.group(1).upper()
        return token.upper()
    return (product_code or product or stem or "SIN-FAMILIA").strip().upper()


def family_short(family: str) -> str:
    return re.sub(r"^CE-", "", family or "", flags=re.I)


def version_label(product: str, family: str = "", stem: str = "") -> str:
    """CE-BOARD-AX-001 -> AX_001."""
    family = family or product_family(product, stem=stem)
    text = product or stem or ""
    rest = text
    if family and text.upper().startswith(family.upper()):
        rest = text[len(family):]
    rest = re.sub(r"[- ]+", "_", rest.strip("-_ "))
    return (rest or stem or text).upper()


def _format_label(sheet: str, mapped: list[str]) -> str:
    fields = {c for c in mapped if c}
    name = _fold(sheet)
    has_xy = "center_x" in fields or "center_y" in fields
    if name in SKIP_SHEETS:
        return "Historico"
    if has_xy and "fitted" in fields:
        return "CAD con colocacion"
    if has_xy:
        return "CAD legado"
    if fields >= {"designator", "codigo", "referencia", "quantity"} and not has_xy:
        return "Lista de materiales"
    if "codigo" in fields and "referencia" not in fields:
        return "Solo codigo"
    return "BOM generico"


def _sheet_penalty(name: str) -> int:
    folded = _fold(name)
    if folded in SKIP_SHEETS:
        return -100
    return 0


def _score_sheet(name: str, frame: pd.DataFrame) -> tuple[int, int, list[str]]:
    if frame.empty:
        return -100, 0, []
    header_idx = _find_header_row(frame)
    cells = [_norm(v) for v in frame.iloc[header_idx].tolist()]
    mapped = _infer_missing_columns(frame, header_idx, map_headers(cells))
    fields = {c for c in mapped if c}
    score = _sheet_penalty(name)
    score += 12 * len(fields)
    if "codigo" in fields:
        score += 40
    if "referencia" in fields:
        score += 25
    if "designator" in fields:
        score += 15
    if "quantity" in fields:
        score += 5
    if fields <= {"codigo", "quantity"} and "referencia" not in fields:
        score -= 35
    folded = _fold(name)
    if folded in {"bomcad", "cad", "hoja1", "bom"}:
        score += 12
    data_rows = max(0, len(frame) - header_idx - 1)
    score += min(20, data_rows // 8)
    return score, header_idx, mapped


def _choose_sheet(path: Path) -> tuple[str, pd.DataFrame, int, list[str]]:
    best: tuple[int, str, pd.DataFrame, int, list[str]] | None = None
    with pd.ExcelFile(path) as xl:
        names = [name for name in xl.sheet_names if _fold(name) not in SKIP_SHEETS]
        if not names:
            names = list(xl.sheet_names)
        frames = {
            name: pd.read_excel(path, sheet_name=name, header=None).fillna("").astype(str)
            for name in names
        }
    for name, frame in frames.items():
        score, header_idx, mapped = _score_sheet(name, frame)
        if best is None or score > best[0]:
            best = (score, name, frame, header_idx, mapped)
    assert best is not None
    return best[1], best[2], best[3], best[4]


def load_bom(path: str | Path) -> BOM:
    path = Path(path)
    sheet, frame, header_idx, mapped = _choose_sheet(path)
    product, product_code, date = _product_meta(frame, path)

    components: list[Component] = []
    for i in range(header_idx + 1, len(frame)):
        raw = [_norm(v) for v in frame.iloc[i].tolist()]
        if _is_skip_row(raw) or is_pcb_text(*raw):
            continue
        rec = {mapped[j]: raw[j] if j < len(raw) else "" for j in range(len(mapped)) if mapped[j]}
        code = _norm_nav(rec.get("codigo", ""))
        ref = _norm(rec.get("referencia", ""))
        des = _norm(rec.get("designator", ""))
        descripcion = _norm(rec.get("descripcion", ""))
        fabricante = _norm(rec.get("fabricante", ""))
        if is_pcb_text(code, ref, des, descripcion, fabricante):
            continue
        if not code and not ref and not des:
            continue
        if code == "NO MONTAR" and not des:
            continue
        fitted = not _looks_dnp(rec, raw)
        if code in {"NO MONTAR", ""}:
            code = ""
        components.append(
            Component(
                designator=des,
                codigo=code,
                referencia=ref,
                fabricante=fabricante,
                descripcion=descripcion,
                quantity=_parse_qty(rec.get("quantity", ""), fitted),
                footprint=_norm(rec.get("footprint", "")),
                fitted=fitted,
                layer=_norm(rec.get("layer", "")),
                source_row=i + 1,
            )
        )

    columns_found = [c for c in dict.fromkeys(mapped) if c]
    fam = product_family(product, product_code, path.stem)
    return BOM(
        path=path,
        product=product,
        product_code=product_code,
        date=date,
        sheet=sheet,
        components=components,
        format_label=_format_label(sheet, mapped),
        columns_found=columns_found,
        family=fam,
        variant=version_label(product, fam, path.stem),
    )


def inspect_bom(path: str | Path) -> dict:
    bom = load_bom(path)
    return {
        "file": bom.path.name,
        "product": bom.label,
        "product_code": bom.product_code,
        "familia": bom.family,
        "variante": bom.variant,
        "date": bom.date,
        "sheet": bom.sheet,
        "format": bom.format_label,
        "columns": bom.columns_found,
        "lineas": len(bom.components),
        "montados": len(bom.mounted()),
        "unicos_codigo": len({c.codigo for c in bom.mounted() if c.codigo}),
    }
