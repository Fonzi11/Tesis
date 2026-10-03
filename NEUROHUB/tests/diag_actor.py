"""
Por que el craneo y el cerebro no se dibujan aunque su actor este en la escena:
comprueba los limites, el numero de puntos y la visibilidad efectiva de cada
actor, y compara contra una malla de control que si se ve (el tumor).

    python tests/diag_actor.py
"""

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from src.ui_qt.app import crear_app  # noqa: E402
from src.ui_qt.main_window import MainWindow  # noqa: E402


def asentar(app, segundos=1.5):
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = crear_app([])
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    asentar(app, 2.0)
    v = w.visor_3d

    w._aplicar_visibilidad({"craneo", "cerebro", "tumor"})
    asentar(app, 1.5)

    print(f"{'clave':<10}{'pts':>10}{'celdas':>10}{'op':>6}{'vis':>6}"
          f"  {'bounds z':<22}{'backface':>9}{'lighting':>9}")
    coll = v._ren.GetActors()
    for i in range(coll.GetNumberOfItems()):
        a = coll.GetItemAsObject(i)
        key = v._pickable.get(a, "?")
        prop = a.GetProperty()
        pd = a.GetMapper().GetInput()
        b = a.GetBounds()
        npts = pd.GetNumberOfPoints() if pd else 0
        ncell = pd.GetNumberOfCells() if pd else 0
        print(f"{key:<10}{npts:>10,}{ncell:>10,}"
              f"{prop.GetOpacity():>6.2f}"
              f"{str(a.GetVisibility()):>6}"
              f"  ({b[2]:8.1f},{b[3]:8.1f})   "
              f"{str(prop.GetBackfaceCulling()):>9}"
              f"{str(prop.GetLighting()):>9}")

    # Desactivando el depth peeling: si asi aparecen las envolventes, el
    # problema es la mezcla por capas, no la geometria.
    dest = os.path.join(RAIZ, "salidas", "capturas", "diag")
    os.makedirs(dest, exist_ok=True)

    v._ren_win.Render()
    v.guardar_imagen(os.path.join(dest, "f_con_peeling.png"))

    try:
        v._ren.SetUseDepthPeeling(0)
    except Exception as e:
        print("no se pudo desactivar depth peeling:", e)
    v._ren_win.Render()
    v.guardar_imagen(os.path.join(dest, "g_sin_peeling.png"))

    # Volviendo a opacidad solida, sin translucidez.
    for k in ("craneo", "cerebro"):
        d = (v._actors.get(k) or {}).get("high")
        if d:
            d["actor"].GetProperty().SetOpacity(1.0)
    v._ren_win.Render()
    v.guardar_imagen(os.path.join(dest, "h_opacidad_solida.png"))
    print("\nEscritas f_con_peeling / g_sin_peeling / h_opacidad_solida")

    w.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
