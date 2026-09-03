from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from bom_compare import compare_boms
from bom_compare.models import BOM, Component
from bom_compare.parse import (
    _product_meta,
    inspect_bom,
    is_cad_only_file,
    is_pcb_text,
    load_bom,
    product_family,
)
import pandas as pd


def _part(designator, codigo, referencia="", qty=1, fitted=True, layer="Top"):
    return Component(
        designator=designator,
        codigo=codigo,
        referencia=referencia,
        fabricante="",
        descripcion="",
        quantity=qty,
        fitted=fitted,
        layer=layer,
    )


def _bom(name, parts, family="CE-BOARD", variant=""):
    return BOM(
        path=Path(name + ".xlsx"),
        product=name,
        product_code="E101000",
        date="",
        sheet="CAD",
        family=family,
        variant=variant or name,
        components=list(parts),
    )


def _write_xlsx(path: Path, headers, rows, sheet="Lista"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class CadOnlyNameTests(unittest.TestCase):
    def test_placement_files_are_skipped(self):
        self.assertTrue(is_cad_only_file("BOM CAD PROD-A.xls"))
        self.assertTrue(is_cad_only_file("BOM_CAD_PROD-B.xlsx"))
        self.assertFalse(is_cad_only_file("BOMCAD-PROD-A.xlsx"))
        self.assertFalse(is_cad_only_file("BOM LIST PROD-A.xls"))


class CompareLogicTests(unittest.TestCase):
    def test_shared_partial_and_exclusive(self):
        a = _bom("A", [
            _part("R1", "CODE1", "RC0402", 2, True),
            _part("R2", "CODE0", "DNP-PART", 0, False),
        ])
        b = _bom("B", [
            _part("R1", "CODE1", "RC0402", 2, True),
            _part("R2", "CODE0", "DNP-PART", 0, False),
            _part("R3", "CODE2", "USED-IN-B", 1, True),
        ])
        result = compare_boms(boms=[a, b])
        self.assertEqual({p.key for p in result.shared}, {"CODE1"})
        self.assertEqual({p.key for p in result.exclusive}, {"CODE2"})
        self.assertNotIn("CODE0", {p.key for p in result.matches})
        self.assertNotIn("CODE0", {p.key for p in result.exclusive})

    def test_common_requires_qty(self):
        a = _bom("A", [_part("R1", "CODE1", qty=2)])
        b = _bom("B", [_part("R1", "CODE1", qty=2)])
        result = compare_boms(boms=[a, b])
        self.assertEqual(len(result.shared), 1)
        self.assertTrue(all(q > 0 for q in result.shared[0].quantities.values()))

    def test_versions_compare_designators_in_family(self):
        v1 = _bom("CE-BOARD-AX-001", [
            _part("R1", "1003A", layer="Top"),
            _part("C1", "1003B", layer="Bottom"),
            _part("U1", "1003C", layer="Top"),
            _part("B10", "1003D", fitted=False, layer="Top"),
        ], family="CE-BOARD", variant="AX_001")
        v2 = _bom("CE-BOARD-AX-002", [
            _part("R1", "1003Z", layer="Top"),
            _part("C1", "1003B", layer="Bottom"),
            _part("C2", "1003E", layer="Top"),
            _part("B10", "1003D", fitted=False, layer="Top"),
        ], family="CE-BOARD", variant="AX_002")
        result = compare_boms(boms=[v1, v2])
        self.assertEqual(len(result.version_matrices), 1)
        matrix = result.version_matrices[0]
        self.assertEqual(matrix.familia_corta, "BOARD")
        self.assertEqual([col.label for col in matrix.versions], ["AX_001", "AX_002"])
        by_des = {row.designator: row for row in matrix.rows}
        self.assertEqual(by_des["R1"].cells[0].codigo, "1003A")
        self.assertNotEqual(by_des["R1"].cells[0].codigo, by_des["R1"].cells[1].codigo)
        self.assertTrue(by_des["R1"].cells[0].code_red or by_des["R1"].cells[1].code_red)
        self.assertTrue(by_des["U1"].cells[0].present)
        self.assertFalse(by_des["U1"].cells[1].present)
        self.assertTrue(by_des["U1"].cells[1].yellow)
        self.assertTrue(by_des["C2"].cells[1].present)
        self.assertFalse(by_des["C2"].cells[0].present)
        self.assertEqual(by_des["B10"].cells[0].fitted, "NotFitted")
        self.assertTrue(by_des["B10"].cells[0].yellow)

    def test_cad_only_files_are_ignored_in_compare(self):
        with TemporaryDirectory() as tmp:
            usable = Path(tmp) / "lista-a.xlsx"
            skipped = Path(tmp) / "BOM CAD PROD-A.xlsx"
            _write_xlsx(
                usable,
                ["Designator", "Codigo", "Referencia", "Quantity"],
                [["R1", "1003020100001", "RC0402", 1]],
            )
            _write_xlsx(
                skipped,
                ["Designator", "Codigo", "Referencia", "Quantity"],
                [["R9", "1003020100999", "SKIP", 1]],
            )
            other = Path(tmp) / "lista-b.xlsx"
            _write_xlsx(
                other,
                ["Designator", "Codigo", "Referencia", "Quantity"],
                [["R1", "1003020100001", "RC0402", 1]],
            )
            result = compare_boms([usable, skipped, other])
            self.assertEqual(len(result.boms), 2)
            self.assertEqual({p.key for p in result.shared}, {"1003020100001"})


class ParseTests(unittest.TestCase):
    def test_pcb_marker(self):
        self.assertTrue(is_pcb_text("IMP-BOARD-A"))
        self.assertTrue(is_pcb_text("imp-board-b"))
        self.assertFalse(is_pcb_text("Circuito impreso"))
        self.assertFalse(is_pcb_text("RC0402JR-07100KL"))

    def test_pcb_rows_are_excluded(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lista.xlsx"
            _write_xlsx(
                path,
                ["Designator", "Codigo", "Referencia", "Quantity"],
                [
                    ["R1", "1003020100001", "RC0402", 2],
                    ["PCB1", "IMP-BOARD-A", "PCB", 1],
                ],
            )
            bom = load_bom(path)
            blob = " ".join(
                f"{c.designator} {c.codigo} {c.referencia}" for c in bom.components
            ).lower()
            self.assertNotIn("imp-", blob)
            self.assertEqual(len(bom.mounted()), 1)

    def test_parser_reads_codigo_and_product(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "CE-BOARD-AX-001.xlsx"
            _write_xlsx(
                path,
                ["Designator", "Codigo", "Referencia", "Quantity", "Fitted", "Layer"],
                [["R1", "1003020100001", "RC0402", 2, "Fitted", "Top"]],
                sheet="CAD",
            )
            bom = load_bom(path)
            self.assertIn("BOARD", bom.product.upper())
            self.assertIn("codigo", bom.columns_found)
            self.assertIn("referencia", bom.columns_found)
            self.assertGreater(len(bom.mounted()), 0)
            info = inspect_bom(path)
            self.assertGreaterEqual(info["unicos_codigo"], 1)

    def test_generic_pcb_label_does_not_hide_product(self):
        frame = pd.DataFrame([
            ["PCB", "Rev A"],
            ["Designator", "Codigo", "Referencia"],
        ])
        product, _, _ = _product_meta(frame, Path("CE-BOARD-AX-001.xls"))
        self.assertIn("BOARD", product.upper())
        self.assertNotEqual(product.strip().upper(), "PCB")
        self.assertEqual(product_family(product, stem="CE-BOARD-AX-001"), "CE-BOARD")


if __name__ == "__main__":
    unittest.main()
