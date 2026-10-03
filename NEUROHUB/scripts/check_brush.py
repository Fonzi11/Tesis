"""Comprueba el mapeo del pincel y mide la fluidez del trazo.

No es un test unitario: es una comprobacion de humo que imprime medidas
concretas, porque los dos fallos que corrigio este cambio (descentrado en
coronal/sagital y lentitud) no se ven leyendo el codigo.
"""
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import volumen_2d as v2d          # noqa: E402

NOMBRES = ("MRBrainTumor1.nii.gz", "BraTS2021_00000_flair.nii.gz")


def _buscar_volumen():
    """Primer NIfTI de los conocidos, en las carpetas de datos de siempre.

    El repositorio y los datos no cuelgan del mismo directorio padre, asi que
    se busca en los dos sitios en vez de fijar una ruta que se rompe al mover
    el arbol.
    """
    for nombre in NOMBRES:
        for base in (RAIZ / "data" / "nifti", RAIZ.parent / "data" / "nifti"):
            ruta = base / nombre
            if ruta.exists():
                return ruta
    raise FileNotFoundError(
        f"No se encontro ningun volumen de prueba en "
        f"{[str(b) for b in (RAIZ / 'data/nifti', RAIZ.parent / 'data/nifti')]}")


def _verde(a):
    """Fraccion de pixeles con tinte verde del tumor."""
    return float((a[..., 1] > a[..., 0] + 5).mean())


def main():
    v = v2d.Volumen2D().cargar(_buscar_volumen())
    print(f"volumen  {v.volumen_path}")
    print(f"shape {v.volumen.shape}  spacing "
          f"{tuple(round(s, 3) for s in v.spacing)}\n")

    print("ESCALA POR EJE (debe diferir entre X e Y en coronal/sagital)")
    for e in ("axial", "coronal", "sagital"):
        kx, ky = v.escala_voxeles(e, 1024)
        otros = [i for i in (0, 1, 2) if i != v2d.eje_indice(e)]
        print(f"  {e:8s} kX={kx:6.2f}  kY={ky:6.2f}  "
              f"min={min(kx, ky):6.2f}   (cols={v.volumen.shape[otros[1]]}, "
              f"filas={v.volumen.shape[otros[0]]})")

    print("\nTRAZO: una linea de 200 vóxeles con un solo evento de raton")
    for e in ("axial", "coronal", "sagital"):
        v.mascara[:] = 0
        v._historial.clear()
        kx, ky = v.escala_voxeles(e, 1024)
        n = v.pintar_tramo_2d(e, 60, (10.0, 20.0), (210.0, 20.0), kx, ky, radio=3)
        corte = v.corte_mascara(e, 60)
        por_fila = corte.sum(axis=1)
        filas = np.flatnonzero(por_fila)
        # La fila del trazo es la que mas voxels tiene, no la central: el
        # criterio de huecos tiene que mirar la fila realmente pintada.
        fila = int(filas[np.argmax(por_fila[filas])]) if len(filas) else -1
        cols = np.flatnonzero(corte[fila]) if fila >= 0 else np.array([], int)
        huecos = int((np.diff(cols) > 1).sum()) if len(cols) > 1 else -1
        print(f"  {e:8s} voxels={n:6d}  filas_pintadas={len(filas):2d}  "
              f"huecos={huecos}")
        assert huecos == 0, f"{e}: el trazo sale punteado"
        # El pincel sigue siendo un circulo en vóxeles: 2*radio filas, ni una
        # mas (seria el pelo que salia al compensar la anisotropia) ni una
        # menos (seria un circulo recortado de lado a lado).
        assert len(filas) >= 2 * 3, \
            f"{e}: el pincel sale mas estrecho que un circulo de {3} vóxeles"

    print("\nFLUIDEZ (ms por paso de raton: pintar tramo + repintar)")
    for e in ("axial", "coronal", "sagital"):
        v.mascara[:] = 0
        v._historial.clear()
        kx, ky = v.escala_voxeles(e, 1024)
        v.render_corte(e, 60, alto=1024, overlay=True)      # calentar
        t = time.perf_counter()
        n = 60
        for i in range(n):
            v.pintar_tramo_2d(e, 60, (10.0, 20.0 + i * 2),
                              (14.0, 22.0 + i * 2), kx, ky, radio=3)
            v.render_corte(e, 60, alto=1024, overlay=True)
        ms = (time.perf_counter() - t) / n * 1000
        print(f"  {e:8s} {ms:6.1f} ms  ->  {1000 / max(ms, 0.01):5.1f} fps")

    print("\nDESHACER: un trazo = un paso")
    v.mascara[:] = 0
    v._historial.clear()
    kx, ky = v.escala_voxeles("coronal", 1024)
    for i in range(5):
        v.pintar_tramo_2d("coronal", 60, (10.0, 20.0 + i),
                          (40.0, 30.0 + i), kx, ky, radio=3)
    antes = int(v.mascara.sum())
    pasos = len(v._historial)
    ok = v.deshacer()
    print(f"  pasos de historial tras 5 trazos = {pasos}, "
          f"deshacer={ok}, voxels {antes} -> {int(v.mascara.sum())}")

    print("\nCACHE: la ventana la invalida, y no se contamina con el tumor")
    v.mascara[:] = 0
    v.render_corte("coronal", 60, alto=1024)
    print(f"  entradas tras pintar = {len(v._cache_base)}")
    base_sin, _ = v.render_corte("coronal", 60, alto=1024, overlay=True)
    v.mascara[:] = 0
    v.pintar_tramo_2d("coronal", 60, (10.0, 20.0), (210.0, 20.0),
                      radio=3)
    base_con, _ = v.render_corte("coronal", 60, alto=1024, overlay=True)
    v.mascara[:] = 0
    base_despues, _ = v.render_corte("coronal", 60, alto=1024, overlay=True)
    # El umbral de "pixel verde" no puede ser 0: la propia RM tiene pixeles
    # donde el canal verde domina (0.0036 aqui). Lo que importa es que al
    # borrar se vuelva EXACTAMENTE a la imagen sin tumor.
    print(f"  pixeles verdidos sin tumor={_verde(base_sin):.4f}  "
          f"con tumor={_verde(base_con):.4f}  al borrar={_verde(base_despues):.4f}")
    assert _verde(base_con) > _verde(base_sin) + 0.01, \
        "el tumor no se ve: el overlay no se pinta"
    assert _verde(base_despues) == _verde(base_sin), \
        "el tumor se ha quedado pegado a la imagen cacheada: no se puede borrar"
    v.calcular_window((1.0, 99.0))
    print(f"  entradas tras recalcular ventana = {len(v._cache_base)}")
    assert not v._cache_base, "la cache sobrevive a un cambio de ventana"
    print("\nOK")


if __name__ == "__main__":
    main()