from __future__ import annotations

import sys
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .compare import compare_boms
from .parse import inspect_bom, is_cad_only_file, load_bom
from .report import write_excel

def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _examples_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "ejemplos"
    return Path(__file__).resolve().parents[1] / "ejemplos"


STATIC = _bundle_dir() / "static"
EXAMPLES = _examples_dir()
EXCEL_SUFFIXES = {".xls", ".xlsx"}

app = FastAPI(title="Comparador de BOM")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_TMP = Path(tempfile.gettempdir()) / "comparador_bom"
_TMP.mkdir(exist_ok=True)

STATE: dict = {"items": [], "result": None, "xlsx": None}


def _reset_result() -> None:
    STATE["result"] = None
    STATE["xlsx"] = None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/files")
def list_files():
    return {"files": STATE["items"]}


@app.post("/api/files")
async def add_files(files: list[UploadFile] = File(...)):
    added = []
    omitted = []
    for upload in files:
        suffix = Path(upload.filename or "bom.xlsx").suffix.lower()
        if suffix not in EXCEL_SUFFIXES:
            continue
        if is_cad_only_file(upload.filename or ""):
            omitted.append(upload.filename)
            continue
        token = uuid.uuid4().hex[:10]
        dest = _TMP / f"{token}_{Path(upload.filename).name}"
        dest.write_bytes(await upload.read())
        try:
            info = inspect_bom(dest)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            return JSONResponse({"error": f"{upload.filename}: {exc}"}, status_code=400)
        item = {"id": token, "path": str(dest), "name": upload.filename, **info}
        STATE["items"].append(item)
        added.append(item)
    _reset_result()
    return {"files": STATE["items"], "added": added, "omitted": omitted}


@app.post("/api/examples")
def load_examples():
    if not EXAMPLES.is_dir():
        return JSONResponse({"error": "No hay carpeta ejemplos"}, status_code=404)
    for path in sorted(EXAMPLES.iterdir()):
        if path.suffix.lower() not in EXCEL_SUFFIXES or path.name.startswith("~"):
            continue
        if is_cad_only_file(path.name):
            continue
        if any(item["name"] == path.name for item in STATE["items"]):
            continue
        token = uuid.uuid4().hex[:10]
        dest = _TMP / f"{token}_{path.name}"
        dest.write_bytes(path.read_bytes())
        info = inspect_bom(dest)
        STATE["items"].append({"id": token, "path": str(dest), "name": path.name, **info})
    _reset_result()
    return {"files": STATE["items"]}


@app.delete("/api/files/{file_id}")
def remove_file(file_id: str):
    remaining = []
    for item in STATE["items"]:
        if item["id"] == file_id:
            Path(item["path"]).unlink(missing_ok=True)
        else:
            remaining.append(item)
    STATE["items"] = remaining
    _reset_result()
    return {"files": STATE["items"]}


@app.post("/api/files/reorder")
async def reorder_files(payload: dict = Body(...)):
    ids = payload.get("ids") or []
    by_id = {item["id"]: item for item in STATE["items"]}
    ordered = [by_id[i] for i in ids if i in by_id]
    leftover = [item for item in STATE["items"] if item["id"] not in ids]
    STATE["items"] = ordered + leftover
    _reset_result()
    return {"files": STATE["items"]}


@app.delete("/api/files")
def clear_files():
    for item in STATE["items"]:
        Path(item["path"]).unlink(missing_ok=True)
    STATE["items"] = []
    _reset_result()
    return {"files": []}


def _part_row(part) -> dict:
    return {
        "clave": part.key,
        "descripcion": part.descripcion,
        "referencia": part.referencia,
        "fabricante": part.fabricante,
        "n_boms": len(part.in_boms),
        "cantidades": part.quantities,
        "en": part.in_boms,
    }


def _payload(result) -> dict:
    labels = [bom.label for bom in result.boms]
    versions = [f"V{i+1}" for i in range(len(labels))]
    common = [_part_row(p) for p in result.shared]
    return {
        "labels": labels,
        "versions": versions,
        "stats": {
            "comunes": len(result.shared),
            "diferencias": len(result.partial),
            "exclusivos": len(result.exclusive),
            "clave": "codigo",
        },
        "boms": [
            {
                "product": bom.label,
                "file": bom.path.name,
                "format": bom.format_label,
                "sheet": bom.sheet,
                "montados": len(bom.mounted()),
                "unicos": result.unique_counts[bom.label],
                "version": f"V{i+1}",
                "familia": bom.family or "",
                "variante": bom.variant or "",
            }
            for i, bom in enumerate(result.boms)
        ],
        "pairs": [
            {
                "a": p.a,
                "b": p.b,
                "comunes": p.n_common,
                "jaccard": p.jaccard,
            }
            for p in result.pairs
        ],
        "shared": common,
        "partial": [_part_row(p) for p in result.partial],
        "exclusive": [
            {
                "clave": p.key,
                "producto": p.bom,
                "cantidad": p.quantity,
                "referencia": p.referencia,
                "fabricante": p.fabricante,
                "descripcion": p.descripcion,
            }
            for p in result.exclusive
        ],
        "version_families": [
            {
                "familia": fam.familia,
                "familia_corta": fam.familia_corta,
                "productos": fam.products,
                "n": len(fam.products),
                "versiones": [
                    {"key": col.key, "label": col.label, "product": col.product}
                    for col in fam.versions
                ],
            }
            for fam in result.version_families
        ],
        "version_matrices": [
            {
                "familia": mx.familia,
                "familia_corta": mx.familia_corta,
                "versiones": [
                    {"key": col.key, "label": col.label, "product": col.product}
                    for col in mx.versions
                ],
                "filas": [
                    {
                        "designator": row.designator,
                        "celdas": [
                            {
                                "codigo": c.codigo,
                                "layer": c.layer,
                                "fitted": c.fitted,
                                "present": c.present,
                                "yellow": c.yellow,
                                "code_red": c.code_red,
                            }
                            for c in row.cells
                        ],
                    }
                    for row in mx.rows
                ],
            }
            for mx in result.version_matrices
        ],
    }


def _usable_items() -> list:
    return [item for item in STATE["items"] if not is_cad_only_file(item.get("name") or "")]


@app.post("/api/compare")
def compare():
    items = _usable_items()
    if len(items) < 2:
        return JSONResponse(
            {"error": "Anade al menos dos BOM. Los archivos BOM CAD no se usan en el cruce."},
            status_code=400,
        )
    try:
        boms = [load_bom(item["path"]) for item in items]
        result = compare_boms(boms=boms)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    xlsx = _TMP / "comparacion_bom.xlsx"
    write_excel(result, xlsx)
    STATE["result"] = result
    STATE["xlsx"] = str(xlsx)
    return _payload(result)


@app.get("/api/download")
def download(familia: str | None = None, versiones: str | None = None):
    result = STATE.get("result")
    if result is None:
        return JSONResponse({"error": "Compara primero"}, status_code=400)
    keys = [part for part in (versiones or "").split(",") if part] or None
    xlsx = _TMP / "comparacion_bom.xlsx"
    write_excel(result, xlsx, familia=familia or None, versiones=keys)
    STATE["xlsx"] = str(xlsx)
    data = Path(xlsx).read_bytes()
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=comparacion_bom.xlsx"},
    )


def _pick_port(start: int = 8765, tries: int = 8) -> int:
    import socket

    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No hay puerto libre desde {start}")


def _alert(message: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Comparador de BOM", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def _ensure_stdio() -> None:
    """En el .exe sin consola stdout/stderr son None y uvicorn revienta al loguear."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = Path(tempfile.gettempdir()) / "comparador_bom.log"
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    import multiprocessing
    import webbrowser

    import uvicorn

    multiprocessing.freeze_support()
    _ensure_stdio()
    try:
        port = _pick_port()
    except Exception as exc:
        _alert(str(exc))
        raise SystemExit(1) from exc
    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(levelname)s: %(message)s"},
            "access": {"format": "%(message)s"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "WARNING"},
            "uvicorn.error": {"handlers": ["default"], "level": "WARNING"},
            "uvicorn.access": {"handlers": ["access"], "level": "WARNING", "propagate": False},
        },
    }
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            log_config=log_config,
        )
    except Exception as exc:
        _alert(str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
