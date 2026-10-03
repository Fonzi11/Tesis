"""
Comprueba que la visibilidad de la escena 3D es exacta: al pedir una sola
estructura, el renderer debe quedarse con un unico actor.

    python tests/diag_visibilidad.py
"""

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from src.ui_qt.app import crear_app  # noqa: E402
from src.ui_qt.main_window import MainWindow  # noqa: E402


def asentar(app, segundos=1.2):
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.01)


def actores_en_escena(v):
    coll = v._ren.GetActors()
    return {v._pickable.get(coll.GetItemAsObject(i), "?")
            for i in range(coll.GetNumberOfItems())}


def main():
    app = crear_app([])
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    asentar(app, 2.0)

    v = w.visor_3d
    dest = os.path.join(RAIZ, "salidas", "capturas", "diag")
    os.makedirs(dest, exist_ok=True)

    casos = [
        ({"tumor"}, "solo_tumor"),
        ({"craneo"}, "solo_craneo"),
        ({"tumor", "arterias"}, "tumor_vasos"),
        ({"craneo", "cerebro", "tumor"}, "clinico"),
        (set(v._models), "todo"),
        ({"tumor"}, "vuelta_a_tumor"),
    ]
    ok = True
    for claves, nombre in casos:
        w._aplicar_visibilidad(claves)
        asentar(app, 1.0)
        en_escena = actores_en_escena(v)
        esperado = set(claves)
        bien = en_escena == esperado
        ok = ok and bien
        print(f"{'OK ' if bien else 'FALLO'} visible={sorted(esperado)} "
              f"escena={sorted(en_escena)}")
        v.guardar_imagen(os.path.join(dest, f"vis_{nombre}.png"))

    print("\nRESULTADO:", "todo correcto" if ok else "HAY DISCREPANCIAS")
    w.close()
    app.processEvents()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
