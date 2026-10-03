"""
Captura en vivo de la interfaz PySide6 para revision visual.

    python tests/demo_ui_qt.py [carpeta_salida]

Abre la ventana REAL (no offscreen), la deja asentar el render de VTK y guarda
varias capturas: la vista general, los cortes 2D y la escena 3D con una sola
estructura visible. Sirve para comprobar el aspecto sin intervened a mano.
"""

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui_qt.app import crear_app  # noqa: E402
from src.ui_qt.main_window import MainWindow  # noqa: E402

DESTINO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "salidas", "capturas")


def asentar(app, segundos=1.2):
    """Deja correr el event loop para que VTK llegue a pintar."""
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.01)


def capturar(widget, nombre):
    """Guarda el widget como PNG y devuelve la ruta."""
    os.makedirs(DESTINO, exist_ok=True)
    ruta = os.path.join(DESTINO, nombre)
    widget.grab().save(ruta)
    print(f"  {ruta}  ({os.path.getsize(ruta)} bytes)")
    return ruta


def main():
    app = crear_app([])
    w = MainWindow()
    w.resize(1600, 1000)
    w.show()
    asentar(app, 2.0)

    print("Vista general:")
    capturar(w, "01_general.png")

    print("Estructura unica (tumor):")
    w._aplicar_visibilidad({"tumor"})
    asentar(app, 1.5)
    capturar(w, "02_3d_tumor.png")

    print("Cortes 2D:")
    w.pestanas.setCurrentIndex(1)
    asentar(app, 1.2)
    capturar(w, "03_cortes_2d.png")

    print("Vista 3D completa:")
    w.pestanas.setCurrentIndex(0)
    w._aplicar_visibilidad(set(w.panel_capas.claves()))
    asentar(app, 1.5)
    capturar(w, "04_3d_completo.png")

    # Captura con el renderer de VTK (fondo opaco, no transparente).
    ruta = w.visor_3d.guardar_imagen(os.path.join(DESTINO, "05_render_vtk.png"))
    print(f"  render VTK: {ruta}")

    w.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
