"""
Diagnostico del color en el visor 3D: comprueba que el actor de cada
estructura receives el color de PBR_COLORS y no un gris por defecto.

    python tests/diag_color.py
"""

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from src.ui_qt.app import crear_app  # noqa: E402
from src.ui_qt.main_window import MainWindow  # noqa: E402
from src.ui_qt.pbr import resolve_pbr  # noqa: E402


def asentar(app, segundos=2.0):
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = crear_app([])
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    asentar(app, 2.5)

    v = w.visor_3d
    print("modelo declarado -> color_rgba | color del actor | opacity")
    for key in sorted(v._models):
        meta = v._models[key]
        pbr = resolve_pbr(key)
        esperado = pbr.get("color_rgba")
        actor = (v._actors.get(key) or {}).get("high", {}).get("actor")
        if actor is None:
            print(f"  {key:12s} SIN ACTOR")
            continue
        prop = actor.GetProperty()
        print(f"  {key:12s} modelo={meta.get('color_rgba')} "
              f"pbr={esperado} actor={tuple(round(c,3) for c in prop.GetColor())} "
              f"op={round(prop.GetOpacity(),3)} "
              f"espec={round(prop.GetSpecular(),2)} "
              f"interp={prop.GetInterpolation()} "
              f"lighting={prop.GetLighting()}")

    # Rasterizado de una sola estructura: tumor a solas, sin traslucidos.
    w._aplicar_visibilidad({"tumor"})
    asentar(app, 1.5)
    out = os.path.join(RAIZ, "salidas", "capturas", "diag", "e_solo_tumor.png")
    v.guardar_imagen(out)
    print(f"\nTumor solo -> {out}")

    # Escala de grises vs color: muestrea el pixel mas saturado.
    try:
        from PIL import Image
        import numpy as np
        with Image.open(out) as im:
            a = np.asarray(im.convert("RGB"), dtype=np.int16)
        mx = a.max(axis=2)
        sat = mx - a.min(axis=2)
        i = int(np.argmax(sat))
        y, x = np.unravel_index(i, sat.shape)
        print(f"pixel mas saturado ({x},{y}) = {tuple(int(c) for c in a[y, x])} "
              f"saturacion={int(sat[y, x])}")
        print("el tumor deberia ser violeta (R bajo, B alto)")
    except ImportError:
        pass

    w.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
