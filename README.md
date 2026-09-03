# Comparador de BOM

Compara listas de materiales electrónicas en Excel (`.xls` / `.xlsx`) en el propio PC. El cruce de componentes es por **código interno**. La referencia de fabricante se muestra, pero no se usa para emparejar.

---

## Arranque

```bat
abrir_comparador.bat
```

o `python -m bom_compare --web`. Se abre `http://127.0.0.1:8765` (si el puerto está ocupado, prueba el siguiente).

Arrastra los Excel o púlsalos para elegirlos. Con al menos dos listas válidas se compara solo.

Por consola:

```bat
python -m bom_compare archivo1.xlsx archivo2.xls --out comparacion_bom.xlsx
```

Ejecutable (PC sin Python): `build_exe.bat` → `dist\ComparadorBOM\ComparadorBOM.exe`. Copia **toda** esa carpeta.

---

## Uso

1. Añade los Excel.
2. Revisa **Archivos cargados** (producto + Quitar; **Quitar todos** arriba a la derecha).
3. El resultado tiene cuatro pestañas. Los recuadros de estadísticas cambian de pestaña.
4. Filtra por designator o código.
5. **Descargar Excel** exporta la comparativa. **Imprimir** saca la pestaña visible.

Los archivos cuyo nombre es `BOM CAD …` (con espacio) son solo colocación: se omiten del cruce.

| Pestaña | Criterio |
| --- | --- |
| **Comunes** | El código está montado (`qty > 0`) en **todas** las listas. |
| **Diferencias** | Está montado en **algunas**, no en todas. |
| **Exclusivos** | Está montado en **una sola** lista. |
| **Versiones** | Revisiones de la **misma familia**. Cruce por designator. Solo filas con cambios. |

En Versiones: amarillo = ausente o no montado; código en rojo = distinto del más frecuente.

---

## Reglas

- Cuenta como presente solo si está montado (`qty > 0` y no es DNP). Las versiones sí muestran las posiciones no montadas.
- Se ignoran filas de circuito impreso (`IMP-…`) y hojas de histórico.
- El producto se toma del Excel o del nombre de archivo. Se descartan etiquetas genéricas (`PCB`, `CAD`, `BOM`…).
- Familia = código base (`CE-BOARD-AX-001` → `CE-BOARD`). La etiqueta de versión es el resto (`AX_001`).
- El parser detecta hoja y columnas aunque cambien de sitio: código, referencia, cantidad, designator, capa, montaje, etc.

---

## Excel de salida

Hojas **Comunes**, **Diferencias**, **Exclusivos** y **Versiones** (una por familia si hay varias). Incluyen código, descripción, referencia, fabricante y cantidades.

---

## Proyecto

```
bom_compare/           Paquete (parseo, cruce, API, interfaz)
tests/                 Pruebas sintéticas
abrir_comparador.bat   Arranque web
build_exe.bat          Empaquetado
comparador.spec        Receta del .exe
launch_comparador.py   Entrada del ejecutable
requirements.txt
```

La sesión web vive en memoria. Los archivos subidos se copian a `%TEMP%\comparador_bom`.

API local en `127.0.0.1` (sin autenticación): `/api/files`, `/api/compare`, `/api/download`.

```bat
python -m pip install -r requirements.txt
python -m unittest tests.test_compare
python -m bom_compare --web
```

`dist/`, `build/` y el Excel de salida no van al repositorio.
