"""
Punto de entrada de la interfaz PySide6 de NEUROHUB.

    python -m src.ui_qt.app

Crea la `QApplication`, aplica la hoja de estilos global de `software_config` y
muestra la ventana principal. VTK se inicializa ANTES de crear la ventana: el
interactor de VTK-Qt necesita un contexto de OpenGL valido, y si se crea el
widget antes de que exista la `QApplication` el render sale negro o vacio.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .software_config import stylesheet


def crear_app(argv=None):
    """Crea (o reutiliza) la QApplication con el tema aplicado."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("NEUROHUB")
    app.setOrganizationName("NEUROHUB")
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    return app


def main(argv=None):
    """Arranca la aplicacion. Devuelve el codigo de salida del proceso."""
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: F401
    except Exception as e:  # pragma: no cover - solo diagnostico
        print(f"Aviso: no se pudo preparar el soporte OpenGL ({e})")

    app = crear_app(argv)

    # El visor 3D se importa aqui (y no arriba) para que un fallo de VTK no
    # impida abrir la ventana: `Viewer3D` ya muestra un aviso en su lienzo.
    from .main_window import MainWindow

    ventana = MainWindow()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
