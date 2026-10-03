"""
Reproduce el fallo de pintado/borrado en la vista 2D con eventos REALES de Qt.

`tests/test_pincel_2d.py` trabaja sobre `Volumen2D` sin Qt, asi que pasa aunque
el raton no llegue a pintar nada en pantalla: el fallo que se reporta es de la
CAPA DE EVENTOS, no del algoritmo de pincel. Aqui se envian QMouseEvent de
verdad (QTest) sobre el lienzo que el usuario ve y se comprueba que la mascara
cambia. Es una comprobacion de humo: imprime medidas concretas.
"""
import inspect
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import Qt, QPoint                      # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from src import volumen_2d as v2d                           # noqa: E402
from src.ui_qt import viewer_2d                             # noqa: E402


def _volumen_sintetico():
    """Volumen 30x40x50 con un 'tumor' ya delineado en el corte axial 15."""
    vol = np.zeros((30, 40, 50), dtype=np.float32)
    vol[5:25, 5:35, 5:45] = 100.0
    v = v2d.Volumen2D(volumen=vol, spacing=(1.0, 1.0, 2.0))
    v.calcular_window()
    v.pintar_tramo_2d("axial", 15, (10.0, 20.0), (40.0, 20.0), radio=4)
    return v


def _arrastrar(widget, x0, y0, x1, y1, pasos=12):
    """Trazo con eventos reales de raton (press -> moves -> release)."""
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y0))
    for i in range(1, pasos + 1):
        QTest.mouseMove(widget, QPoint(x0 + (x1 - x0) * i // pasos,
                                      y0 + (y1 - y0) * i // pasos))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(x1, y1))


def _a_pantalla(lienzo, visor, eje, vx, vy):
    """Voxel (vx, vy) del corte -> coordenadas de pantalla del widget."""
    kx, ky = visor.escala_voxel_por_eje(eje)
    return (int(lienzo._base[0] + vx * kx * lienzo._escala),
            int(lienzo._base[1] + vy * ky * lienzo._escala))


def _bytes(widget):
    return widget.pixmap().toImage().constBits().tobytes()


def main():
    app = QApplication.instance() or QApplication([])

    vol = _volumen_sintetico()
    visor = viewer_2d.Viewer2D()
    visor.set_volumen(vol)
    visor.resize(1200, 800)
    visor.show()
    app.processEvents()

    fallos = []

    # ---- 0) Con DATOS REALES: el caso que falla en la aplicacion ----
    real = Path(RAIZ).parent / "data" / "nifti" / "MRBrainTumor1.nii.gz"
    if real.exists():
        vr = v2d.Volumen2D(str(real))
        if vr.vacio:
            print(f"0) REAL {real.name}: NO SE PUDO LEER")
            fallos.append(f"no se pudo leer el volumen real {real.name}")
        else:
            print(f"0) REAL {real.name}: shape={vr.volumen.shape} "
                  f"spacing={tuple(round(s, 2) for s in vr.spacing)}")
            visor_r = viewer_2d.Viewer2D()
            visor_r.set_volumen(vr)
            visor_r.resize(1200, 800)
            visor_r.show()
            app.processEvents()
            for eje in ("axial", "coronal", "sagital"):
                visor_r.set_eje(eje)
                visor_r.set_indice(vr.indice_mas_tumor(eje))
                visor_r.set_herramienta("pintar")
                app.processEvents()
                lz = visor_r._paginators[eje]
                antes = int(vr.mascara.sum())
                sx, sy = _a_pantalla(lz, visor_r, eje, 60.0, 60.0)
                QTest.mouseClick(lz, Qt.LeftButton, Qt.NoModifier,
                                 QPoint(sx, sy))
                app.processEvents()
                tras = int(vr.mascara.sum())
                uv = lz.voxel_continuo(QPoint(sx, sy))
                print(f"   {eje:8s} total={vr.volumen.shape} cortes={visor_r.n_cortes()}"
                      f" pixmap={lz.pixmap().width()}x{lz.pixmap().height()}"
                      f" uv={None if uv is None else (round(uv[0], 1), round(uv[1], 1))}"
                      f"  {antes} -> {tras} {'OK' if tras > antes else 'FALLA: NO PINTA'}")
                if tras <= antes:
                    fallos.append(f"con datos reales, pintar no funciona en {eje}")
    else:
        print(f"0) REAL: no existe {real} (se omite)")

    visor.set_eje("axial")
    visor.set_indice(15)
    app.processEvents()
    lienzo = visor._paginators["axial"]
    pm = lienzo.pixmap()
    print(f"lienzo visible={lienzo.isVisible()} herramienta={visor.herramienta()!r} "
          f"pixmap={pm.width()}x{pm.height()}")
    if not lienzo.isVisible():
        fallos.append("el lienzo axial NO es visible: no puede recibir el raton")

    # 1) CLIC con Pincel
    visor.set_herramienta("pintar")
    visor._radio_voxel = 3
    antes = int(vol.mascara.sum())
    sx, sy = _a_pantalla(lienzo, visor, "axial", 30.0, 30.0)
    print(f"\n1) CLIC en voxel (30,30) -> pantalla ({sx},{sy})")
    QTest.mouseClick(lienzo, Qt.LeftButton, Qt.NoModifier, QPoint(sx, sy))
    app.processEvents()
    tras = int(vol.mascara.sum())
    print(f"   mascara {antes} -> {tras} "
          f"{'OK' if tras > antes else 'FALLA: el clic no pinto nada'}")
    if tras <= antes:
        try:
            uv = lienzo.voxel_continuo(QPoint(sx, sy))
            kx, ky = visor.escala_voxel_por_eje("axial")
            print(f"   voxel_continuo({sx},{sy}) = {uv}")
            print(f"   kx={kx:.3f} ky={ky:.3f} escala={lienzo._escala:.3f} "
                  f"base=({lienzo._base[0]:.1f},{lienzo._base[1]:.1f})")
        except Exception as exc:                            # noqa: BLE001
            print(f"   voxel_continuo lanzo: {type(exc).__name__}: {exc}")
        fallos.append("clic con Pincel no pinta nada")

# 2) ARRASTRE con Pincel
    visor.set_herramienta("pintar")
    antes = int(vol.mascara.sum())
    x0, y0 = _a_pantalla(lienzo, visor, "axial", 8.0, 32.0)
    x1, y1 = _a_pantalla(lienzo, visor, "axial", 42.0, 32.0)
    print(f"\n2) ARRASTRE de ({x0},{y0}) a ({x1},{y1})")
    _arrastrar(lienzo, x0, y0, x1, y1)
    app.processEvents()
    tras = int(vol.mascara.sum())
    print(f"   mascara {antes} -> {tras} "
          f"{'OK' if tras > antes else 'FALLA: el arrastre no pinto'}")
    if tras <= antes:
        fallos.append("arrastre con Pincel no pinta")

    # 3) ARRASTRE con Borrar
    visor.set_herramienta("borrar")
    antes = int(vol.mascara.sum())
    x0, y0 = _a_pantalla(lienzo, visor, "axial", 20.0, 20.0)
    x1, y1 = _a_pantalla(lienzo, visor, "axial", 30.0, 20.0)
    print(f"\n3) ARRASTRE con Borrar de ({x0},{y0}) a ({x1},{y1})")
    _arrastrar(lienzo, x0, y0, x1, y1)
    app.processEvents()
    tras = int(vol.mascara.sum())
    print(f"   mascara {antes} -> {tras} "
          f"{'OK' if tras < antes else 'FALLA: el borrador no borro nada'}")
    if tras >= antes:
        fallos.append("arrastre con Borrar no borra")

    # 4) DESHACER
    visor.set_herramienta("navegar")
    antes = int(vol.mascara.sum())
    ok = visor.deshacer()
    tras = int(vol.mascara.sum())
    print(f"\n4) DESHACER: {antes} -> {tras} "
          f"{'OK' if ok and tras != antes else 'FALLA: no revierte'}")
    if not ok or tras == antes:
        fallos.append("deshacer no revierte el ultimo trazo")

    # 5) La imagen se repinta al pintar (overlay sobre cache, no cacheado)
    visor.set_eje("coronal")
    visor.set_indice(20)
    visor.set_herramienta("pintar")
    app.processEvents()
    lz = visor._paginators["coronal"]
    px_antes = _bytes(lz)
    sx, sy = _a_pantalla(lz, visor, "coronal", 25.0, 25.0)
    QTest.mouseClick(lz, Qt.LeftButton, Qt.NoModifier, QPoint(sx, sy))
    app.processEvents()
    px_despues = _bytes(lz)
    print(f"\n5) La IMAGEN cambia al pintar: "
          f"{'OK' if px_antes != px_despues else 'FALLA: la pantalla no cambia'}")
    if px_antes == px_despues:
        fallos.append("la imagen no se repinta al pintar")

    # 6) _btn_overlay no debe acumular conexiones
    src = inspect.getsource(viewer_2d.Viewer2D.set_volumen)
    n = src.count("self._btn_overlay.toggled.connect")
    print(f"\n6) Conexiones de _btn_overlay dentro de set_volumen: {n} "
          f"{'OK' if n == 0 else 'FALLA: se conecta en cada carga'}")
    if n:
        fallos.append("_btn_overlay.toggled se conecta en cada set_volumen")

    # ---- 7) El flujo REAL de la ventana: buscar -> cargar -> pintar ----
    # Esta es la cadena que fallaba: `buscar_volumen` no encontraba el caso
    # BraTS, `set_volumen(None)` vaciaba el visor y los botones de Pincel y
    # Borrar quedaban desactivados.
    caso = Path(RAIZ).parent / "data" / "nifti" / "braTS_sample" / "BraTS2021_00000"
    if caso.exists():
        from src.ui_qt import mesh_store as ms

        vp = ms.buscar_volumen(str(caso), ms.SALIDAS_DIR)
        print(f"\n7) FLUJO DE LA VENTANA con {caso.name}")
        print(f"   buscar_volumen -> {None if not vp else Path(vp).name}")
        if not vp:
            fallos.append("buscar_volumen no encuentra un caso BraTS real")
        else:
            cand = ms.listar_mascaras_tumor(str(caso), ms.SALIDAS_DIR)
            msk = ms.buscar_mascara_compatible(cand, vp)
            print(f"   mascara compatible -> "
                  f"{None if not msk else Path(msk).name}")
            vw = v2d.Volumen2D(vp, msk)
            visor_w = viewer_2d.Viewer2D()
            visor_w.set_volumen(vw)
            visor_w.resize(1200, 800)
            visor_w.show()
            app.processEvents()
            activo = visor_w._botones_brush["pintar"].isEnabled()
            b_activo = visor_w._botones_brush["borrar"].isEnabled()
            print(f"   botones Pincel/Borrar habilitados: {activo}/{b_activo}")
            if not (activo and b_activo):
                fallos.append("los botones de Pincel y Borrar siguen desactivados")
            else:
                visor_w.set_herramienta("pintar")
                visor_w.set_indice(vw.indice_mas_tumor("axial"))
                app.processEvents()
                lz = visor_w._paginators["axial"]
                antes = int(vw.mascara.sum())
                sx, sy = _a_pantalla(lz, visor_w, "axial", 120.0, 120.0)
                _arrastrar(lz, sx, sy, sx + 60, sy + 20)
                app.processEvents()
                print(f"   pintado sobre el tumor real: {antes} -> "
                      f"{int(vw.mascara.sum())} "
                      f"{'OK' if vw.mascara.sum() != antes else 'FALLA'}")
    else:
        print(f"\n7) FLUJO: no existe {caso} (se omite)")

    print("\n" + ("OK: pintar, borrar, deshacer y repintar funcionan con raton real"
                  if not fallos else f"{len(fallos)} FALLOS:\n  - "
                  + "\n  - ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
