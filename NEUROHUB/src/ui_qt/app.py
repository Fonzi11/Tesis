"""
Punto de entrada de la interfaz de ATLAS.

    python -m src.ui_qt.app        (desde la carpeta del proyecto)
    python launcher.py             (forma recomendada)

Crea la `QApplication`, aplica la hoja de estilos global de `software_config`
y muestra la ventana principal. VTK se importa después de crear la
`QApplication`: el interactor de VTK-Qt necesita un contexto OpenGL válido y,
si el widget se crea antes, el render sale negro.
"""

import sys

from PySide6.QtWidgets import QApplication

from .software_config import APP_NOMBRE, stylesheet


def crear_app(argv=None):
    """Crea (o reutiliza) la QApplication con el tema de ATLAS."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NOMBRE)
    app.setOrganizationName("ATLAS · HUSI")
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    from .widgets import familia_marca, icono_aplicacion
    familia_marca()
    app.setWindowIcon(icono_aplicacion())
    return app


def main(argv=None):
    """Arranca la aplicación. Devuelve el código de salida del proceso."""
    try:
        from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: F401
    except Exception as e:  # pragma: no cover - solo diagnóstico
        print(f"Aviso: no se pudo preparar el soporte OpenGL ({e})")

    if sys.platform == "win32":
        # Agrupa la ventana en la barra de tareas con su propio icono.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ATLAS.HUSI.Planificacion")
        except Exception:
            pass

    app = crear_app(argv)
    from .main_window import MainWindow

    ventana = MainWindow()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
