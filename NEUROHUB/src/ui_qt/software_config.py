"""
Paleta de colores, tipografias y hoja de estilos global de NEUROHUB.

Sustituye al diccionario COLORS de la interfaz Tk y al bloque de estilos de
`main.py`. Se mantiene separado para que cambiar el tema no toque la logica.

Los colores se guardan como cadenas "#RRGGBB" porque es lo que espera
QSS; cuando hace falta un QColor se usa `qt_color()`.
"""

from PySide6.QtGui import QColor, QFont

# =============================================================================
# PALETA
# =============================================================================
# Color2..Color7 replican los roles de Raidionics (fondo, widget, presion,
# hover, borde, texto) para que la interfaz se lea igual.
COLOR_BG = "#10141c"          # fondo de la aplicacion
COLOR_PANEL = "#171e29"       # fondo de paneles
COLOR_PANEL_ALT = "#202b3a"   # alternativa / tarjetas
COLOR_SELECCION = "#263b52"   # item seleccionado
COLOR_HOVER = "#2d4964"       # hover fuerte
COLOR_BORDE = "#33485d"       # separadores
COLOR_TEXTO = "#e5edf5"       # texto principal
COLOR_TEXTO_SEC = "#91a4b7"
COLOR_ACENTO = "#41d7e8"      # cian clínico
COLOR_OK = "#48e39a"
COLOR_WARN = "#ffbe5c"
COLOR_ERROR = "#ff5c5c"
COLOR_VOZ = "#b06ad4"         # violeta: convencion radiologica para voz

# Fondo del renderizador 3D. VTK no admite "#RRGGBB", asi que se guarda la
# forma normalizada (0..1) equivalente al COLOR_BG de la interfaz: el visor
# queda integrado en el mismo tono oscuro en lugar de un gris claro.
VIEW_BG_RGB = (0.047, 0.047, 0.055)

# Estructuras segmentadas (se reutilizan los colores de segmentacion_completa)
COLOR_ESTRUCTURAS = {
    "cerebro": "#d4a69a",
    "craneo": "#e8e0d4",
    "tumor": "#c0256e",
    "aneurisma": "#e05a2b",
}

# =============================================================================
# TIPOGRAFIAS
# =============================================================================
FUENTE_UI = "Segoe UI"
FUENTE_MONO = "Consolas"

FUENTE_TITULO = (FUENTE_UI, 15, "bold")
FUENTE_SUBTITULO = (FUENTE_UI, 10, "bold")
FUENTE_CUERPO = (FUENTE_UI, 9)
FUENTE_PEQUENA = (FUENTE_UI, 8)


def qt_color(color, alpha=255):
    """Convierte "#RRGGBB" (o un nombre) en un QColor con alfa opcional."""
    c = QColor(color)
    if alpha != 255:
        c.setAlpha(alpha)
    return c


def rgba(color, alpha):
    """Devuelve la forma 'rgba(r,g,b,a)' que entiende QSS."""
    c = QColor(color)
    return "rgba({0}, {1}, {2}, {3})".format(c.red(), c.green(), c.blue(), alpha)


# =============================================================================
# HOJA DE ESTILOS GLOBAL
# =============================================================================
def stylesheet():
    """Devuelve la hoja QSS global de la aplicacion.

    Se aplica UNA sola vez sobre QApplication, de forma que los widgets solo
    necesitan overrides puntuales (como el de las capas de modelo).
    """
    return f"""
QWidget {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXTO};
    font-family: "{FUENTE_UI}";
    font-size: 12px;
}}

QMainWindow, QDialog {{ background-color: {COLOR_BG}; }}

/* ---------------------------------------------------------------- GroupBox */
QGroupBox {{
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 8px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {COLOR_TEXTO};
}}

/* ------------------------------------------------------------------ Botones */
QPushButton {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    padding: 6px 13px;
    color: {COLOR_TEXTO};
    min-height: 22px;
}}
QPushButton:hover {{ background-color: {COLOR_HOVER}; }}
QPushButton:pressed {{ background-color: {COLOR_SELECCION}; }}
QPushButton:disabled {{
    color: {COLOR_TEXTO_SEC};
    background-color: {COLOR_PANEL};
    border-color: {COLOR_PANEL_ALT};
}}
QPushButton:checked {{
    background-color: {COLOR_SELECCION};
    border-color: {COLOR_ACENTO};
}}

/* Boton de icono plano (el de los timestamps/capas, estilo Raidionics) */
QPushButton[flatButton="true"] {{
    background: transparent;
    border: none;
    padding: 2px;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}}
QPushButton[flatButton="true"]:hover {{ border: 1px solid {rgba(COLOR_BORDE, 200)}; }}
QPushButton[flatButton="true"]:pressed {{ background-color: {COLOR_SELECCION}; }}

/* ------------------------------------------------------------- Entrada de texto */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {COLOR_ACENTO};
    selection-color: {COLOR_BG};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border-color: {COLOR_ACENTO}; }}

/* ----------------------------------------------------------------- Combos */
QComboBox {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    border-radius: 4px;
    padding: 3px 6px;
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {COLOR_ACENTO}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    selection-background-color: {COLOR_SELECCION};
    selection-color: {COLOR_TEXTO};
    outline: none;
}}

/* ---------------------------------------------------------------- Listas */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDE};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 4px 6px;
    border-radius: 3px;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {COLOR_PANEL_ALT}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {COLOR_SELECCION};
    color: {COLOR_TEXTO};
}}

/* --------------------------------------------------------------- Sliders */
QSlider::groove:horizontal {{
    height: 4px; background: {COLOR_PANEL_ALT}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {COLOR_ACENTO}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {COLOR_TEXTO}; width: 12px; margin: -5px 0; border-radius: 6px;
}}

/* --------------------------------------------------------------- Checkbox */
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{
    border: 1px solid {COLOR_BORDE}; border-radius: 3px; background: {COLOR_PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    border: 1px solid {COLOR_ACENTO}; border-radius: 3px; background: {COLOR_ACENTO};
}}

/* ------------------------------------------------------------- Separadores */
QSplitter::handle {{ background: {COLOR_BORDE}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QTabWidget::pane {{ border: 1px solid {COLOR_BORDE}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{
    background: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDE};
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    background: {COLOR_PANEL_ALT};
    border-bottom-color: {COLOR_PANEL_ALT};
    color: {COLOR_ACENTO};
}}

/* ----------------------------------------------------------------- Tooltip */
QToolTip {{
    background-color: {COLOR_PANEL_ALT};
    color: {COLOR_TEXTO};
    border: 1px solid {COLOR_BORDE};
    padding: 4px;
}}

QScrollBar:vertical {{
    background: {COLOR_BG};
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDE};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{ background: {COLOR_ACENTO}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {COLOR_BG};
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {COLOR_BORDE};
    min-width: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{ background: {COLOR_ACENTO}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* --------------------------------------------------------------- Consola */
QTextEdit#consola {{
    background-color: {COLOR_BG};
    font-family: "{FUENTE_MONO}";
    font-size: 11px;
    border: 1px solid {COLOR_BORDE};
}}
"""


def fuente(tupla):
    """Convierte una tupla de Qt en un QFont."""
    f = QFont(tupla[0])
    f.setPointSize(tupla[1])
    if len(tupla) > 2 and tupla[2] == "bold":
        f.setBold(True)
    return f
