"""
Inspecciona las mallas STL de cada estructura: caras, dimensiones y si el
actor llega a tener geometria visible. Sirve para explicar por que el craneo y
el cerebro no se ven aunque esten en la escena.

    python tests/diag_mallas.py
"""

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from src.ui_qt import mesh_store  # noqa: E402
from src.ui_qt.pbr import resolve_pbr  # noqa: E402


def main():
    modelos = mesh_store.escanear_mallas()
    print(f"{'clave':<12}{'caras':>10}  {'extents (x,y,z)':<28}{'watertight':<10}archivo")
    for key, meta in modelos.items():
        stl = meta["stl"]
        if not stl or not os.path.isfile(stl):
            print(f"{key:<12}  SIN ARCHIVO  {stl}")
            continue
        try:
            import trimesh
            m = trimesh.load(stl, force="mesh")
            ext = m.extents
            print(f"{key:<12}{len(m.faces):>10,}  "
                  f"({ext[0]:7.1f},{ext[1]:7.1f},{ext[2]:7.1f})   "
                  f"{str(m.is_watertight):<10}{os.path.basename(stl)}")
        except Exception as e:
            print(f"{key:<12}  ERROR leyendo: {e}")

    print("\nPresupuesto de caras por estructura (nivel high):")
    from src.ui_qt.viewer_3d import Viewer3D
    v = Viewer3D.__new__(Viewer3D)      # sin Qt: solo el metodo de calculo
    for key in modelos:
        ob = v._quality_faces(key, "high")
        print(f"  {key:<12} techo={ob:>9,}")

    print("\nNombres de archivo y su material:")
    for key in modelos:
        print(f"  {key:<12} color={resolve_pbr(key).get('color_rgba')} "
              f"label={resolve_pbr(key).get('label')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
