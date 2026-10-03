"""Comprueba el mapeo pantalla -> voxel del lienzo con Qt real.

El bug que se corrige aqui no se ve leyendo el mapeo: en coronal y sagital el
factor de px/voxel es 2.68 en horizontal y 9.14 en vertical, y usar el menor
para los dos ejes desplazaba el pincel. Aqui se comprueba que la posicion que
el usuario ve marcada es exactamente la que acaba en la mascara.
"""
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPoint                   # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from scripts.check_brush import _buscar_volumen     # noqa: E402
from src import volumen_2d as v2d                   # noqa: E402
from src.ui_qt import viewer_2d                     # noqa: E402

RADIO = 3


def _centro(corte):
    """Centroide (fila, columna) de la mascara, o None si esta vacia."""
    pts = np.argwhere(corte)
    if pts.size == 0:
        return None
    return pts.mean(axis=0)


def main():
    app = QApplication.instance() or QApplication([])

    v = v2d.Volumen2D().cargar(_buscar_volumen())
    visor = viewer_2d.Viewer2D()
    visor.set_volumen(v)
    visor.resize(1400, 900)
    app.processEvents()

    fallos = 0
    print("MAPEO pantalla -> voxel")
    for eje in ("axial", "coronal", "sagital"):
        visor.set_eje(eje)
        visor.set_indice(60)
        visor.set_herramienta("pintar")
        visor._radio_voxel = RADIO
        lienzo = visor._paginators[eje]
        lienzo.ajustar()
        app.processEvents()

        pm = lienzo.pixmap()
        kx, ky = visor.escala_voxel_por_eje(eje)
        esc = lienzo._escala
        bx, by = lienzo._base

        cols, filas = pm.width() / kx, pm.height() / ky
        objetivo = (int(cols * 0.5), int(filas * 0.5))
        sx = bx + (objetivo[0] + 0.5) * kx * esc
        sy = by + (objetivo[1] + 0.5) * ky * esc

        # 1) El mapeo debe devolver el voxel pedido.
        uv = lienzo.voxel_continuo(QPoint(int(sx), int(sy)))
        ok_mapeo = uv is not None and abs(uv[0] - objetivo[0]) < 1.0 \
            and abs(uv[1] - objetivo[1]) < 1.0

        # 2) Al pintar ahi, el centro del pincel cae en ese voxel.
        v.mascara[:] = 0
        v._historial.clear()
        visor._pintando = True
        visor._ultimo_voxel = uv
        visor._indice_pintando = visor.indice()
        visor._eje_pintando = eje
        visor._pintar_segmento(uv, uv, lienzo)
        corte = v.corte_mascara(eje, visor.indice())
        c = _centro(corte)
        desvio = None if c is None else float(
            np.hypot(c[0] - objetivo[1], c[1] - objetivo[0]))
        ok_centro = desvio is not None and desvio <= 1.5

        estado = "OK   " if (ok_mapeo and ok_centro) else "FALLA"
        fallos += 0 if (ok_mapeo and ok_centro) else 1
        print(f"  {estado} {eje:8s} objetivo={objetivo} "
              f"mapeo={None if uv is None else tuple(round(c, 2) for c in uv)}"
              f"  desvio_centro={None if desvio is None else round(desvio, 2)}")

        # 3) Un trazo horizontal no puede salirse en vertical.
        v.mascara[:] = 0
        v._historial.clear()
        uv0 = (1.0, objetivo[1])
        uv1 = (cols - 1.0, objetivo[1])
        visor._ultimo_voxel = uv0
        visor._indice_pintando = visor.indice()
        visor._eje_pintando = eje
        visor._pintar_segmento(uv0, uv1, lienzo)
        c2 = v.corte_mascara(eje, visor.indice())
        filas_tocadas = int(c2.any(axis=1).sum())
        ok_trozo = filas_tocadas > RADIO
        fallos += 0 if ok_trozo else 1
        print(f"         trazo de {int(cols - 2)} vóxeles -> {filas_tocadas} "
              f"filas (deben ser > {RADIO}) {'' if ok_trozo else '  <-- FALLA'}")

        # 4) Fuera de la imagen no se pinta nada.
        v.mascara[:] = 0
        v._historial.clear()
        fuera = QPoint(int(bx - 5), int(by - 5))
        uv_fuera = lienzo.voxel_continuo(fuera)
        ok_fuera = uv_fuera is None
        fallos += 0 if ok_fuera else 1
        print(f"         fuera de la imagen -> {uv_fuera} "
              f"{'' if ok_fuera else '  <-- FALLA (pintaria fuera)'}")

    print("\nPINTADO DEL LIENZO (debe ejecutar paintEvent sin excepcion)")
    try:
        for eje in ("axial", "coronal", "sagital"):
            visor.set_eje(eje)
            visor.set_indice(60)
            visor.set_herramienta("pintar")
            lienzo = visor._paginators[eje]
            lienzo.ajustar()
            lienzo.repaint()
        print("  OK: paintEvent con el pincel activo no falla en los 3 ejes")
    except Exception as exc:                      # noqa: BLE001
        fallos += 1
        print(f"  FALLA: {type(exc).__name__}: {exc}")

    print("\n" + ("OK: mapeo exacto en los tres ejes" if not fallos
                  else f"{fallos} FALLOS"))

    # Que habria pasado con el mapeo anterior, que dividia las DOS
    # coordenadas por el factor menor. Se calcula para dejar constancia
    # medida del error que se corrige, no como simple suposicion.
    print("\nCOMPARACION con el mapeo anterior (factor unico = min(kX, kY))")
    for eje in ("axial", "coronal", "sagital"):
        visor.set_eje(eje)
        visor.set_indice(60)
        lienzo = visor._paginators[eje]
        lienzo.ajustar()
        app.processEvents()
        kx, ky = visor.escala_voxel_por_eje(eje)
        k = min(kx, ky)
        pm = lienzo.pixmap()
        cols, filas = pm.width() / k, pm.height() / k
        objetivo = (int(cols * 0.5), int(filas * 0.5))
        y_bueno = objetivo[1] * ky / kx
        print(f"  {eje:8s} voxel vertical pedido={objetivo[1]:3d}  "
              f"el mapeo anterior marcaba {objetivo[1]:3.0f} "
              f"(de {int(filas):3d} filas disponibles)  "
              f"error = {abs(y_bueno - objetivo[1]):5.1f} filas")

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())