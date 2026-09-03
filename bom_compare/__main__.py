from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compare import compare_boms
from .report import write_excel

EXCEL_SUFFIXES = {".xls", ".xlsx"}


def _collect_paths(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            files.extend(
                sorted(
                    p
                    for p in path.iterdir()
                    if p.suffix.lower() in EXCEL_SUFFIXES and not p.name.startswith("~")
                )
            )
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    if len(files) < 2:
        raise SystemExit("Indica al menos dos archivos BOM o una carpeta con varios Excel.")
    return files


def _print_summary(result) -> None:
    print("Cruce: codigo interno")
    print(f"BOM comparadas: {len(result.boms)}")
    for bom in result.boms:
        print(
            f"  - {bom.label:32}  hoja={bom.sheet:8}  "
            f"lineas={len(bom.components):4}  montados={len(bom.mounted()):4}  "
            f"unicos={result.unique_counts[bom.label]:3}  prod={bom.product_code}"
        )
    print(
        f"Comunes (en todas): {len(result.shared)}   "
        f"Diferencias: {len(result.partial)}   "
        f"Exclusivos: {len(result.exclusive)}"
    )
    if result.version_matrices:
        print("\nComparativa de versiones (por designator):")
        for matrix in result.version_matrices:
            labels = ", ".join(col.label for col in matrix.versions)
            print(f"  {matrix.familia_corta}: {len(matrix.rows)} posiciones · {labels}")
    elif result.version_families:
        print("\nVersiones: ninguna familia tiene 2 o mas BOM.")
        for fam in result.version_families:
            print(f"  {fam.familia}: {len(fam.products)} archivo(s)")
    if result.pairs:
        print("\nSolape por pares:")
        for pair in result.pairs:
            print(
                f"  {pair.a}  x  {pair.b}:  "
                f"{pair.n_common} comunes  Jaccard={pair.jaccard}"
            )
    if not result.shared:
        return
    print()
    print(f"{'Codigo':<18} {'n':>2} {'qty tot':>8}  Referencia")
    print("-" * 80)
    for part in result.shared:
        qty = sum(part.quantities.values())
        print(
            f"{part.key:<18} {len(part.in_boms):>2} {qty:>8g}  {part.referencia}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compara archivos BOM y escribe un Excel con componentes comunes."
    )
    parser.add_argument("inputs", nargs="*", help="Archivos Excel o carpeta")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Abre la aplicacion local para anadir archivos y comparar",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("comparacion_bom.xlsx"),
        help="Excel de salida (por defecto comparacion_bom.xlsx)",
    )
    args = parser.parse_args(argv)

    if args.web:
        from .app import main as web_main

        web_main()
        return 0
    if not args.inputs:
        parser.error("Indica archivos BOM o usa --web")

    try:
        paths = _collect_paths(args.inputs)
        result = compare_boms(paths)
        out = write_excel(result, args.out)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_summary(result)
    print(f"\nEscrito {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
