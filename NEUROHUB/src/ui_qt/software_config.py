"""
Identidad visual de ATLAS: marca, paleta, tipografías y hoja de estilos global.

ATLAS (Augmented Technologies Laboratory for Advanced Surgery) es el
laboratorio de neurocirugía del Hospital Universitario San Ignacio; esta
aplicación es su plataforma de preparación y revisión de modelos 3D.

La paleta es oscura y de bajo contraste en las superficies (las imágenes
médicas se leen mejor sobre fondos neutros) con un único acento turquesa para
lo interactivo. Los colores se guardan como "#RRGGBB" porque es lo que espera
QSS; cuando hace falta un QColor se usa `qt_color()`.
"""

import os

from PySide6.QtGui import QColor, QFont

# =============================================================================
# MARCA
# =============================================================================
APP_NOMBRE = "ATLAS"
APP_LEMA = "Augmented Technologies Laboratory for Advanced Surgery"
APP_INSTITUCION = "Hospital Universitario San Ignacio · Pontificia Universidad Javeriana"
APP_DESCRIPCION = "Modelos 3D neuroquirúrgicos para realidad mixta"
APP_TITULO_VENTANA = f"{APP_NOMBRE} — {APP_DESCRIPCION}"

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets")
FUENTE_MARCA_ARCHIVO = os.path.join(_ASSETS, "fonts", "Montserrat-Bold.ttf")


def _icono(nombre):
    """Ruta de un icono de interfaz con barras normales (lo que exige QSS)."""
    return os.path.join(_ASSETS, "ui", nombre).replace("\\", "/")


# =============================================================================
# PALETA
# =============================================================================
COLOR_BG = "#0B0F14"           # fondo de la aplicación
COLOR_PANEL = "#11171F"        # paneles laterales y barras
COLOR_PANEL_ALT = "#18202A"    # tarjetas, botones, campos
COLOR_SUPERFICIE = "#1D2632"   # hover suave
COLOR_SELECCION = "#17323A"    # elemento seleccionado (acento muy apagado)
COLOR_HOVER = "#222D3A"
COLOR_BORDE = "#243041"        # separadores
COLOR_BORDE_SUAVE = "#1A2330"
COLOR_TEXTO = "#E6EDF3"
COLOR_TEXTO_SEC = "#8B98A8"
COLOR_TEXTO_TENUE = "#5C6876"
COLOR_ACENTO = "#3FB6C8"       # turquesa clínico
COLOR_ACENTO_HOVER = "#5CC9D8"
COLOR_OK = "#3FB97F"
COLOR_WARN = "#E3A63B"
COLOR_ERROR = "#E5534B"
COLOR_VOZ = "#A98BE0"

# Fondo del visor 3D: degradado vertical (VTK usa 0..1). Un degradado sutil
# separa la escena del resto de la interfaz y da profundidad sin distraer.
VIEW_BG_RGB = (0.035, 0.047, 0.063)          # abajo
VIEW_BG_TOP_RGB = (0.090, 0.114, 0.145)      # arriba

# Colores por defecto de las estructuras del pipeline clásico
COLOR_ESTRUCTURAS = {
    "cerebro": "#d4a69a",
    "craneo": "#e8e0d4",
    "tumor": "#c0256e",
    "aneurisma": "#e05a2b",
}

# =============================================================================
# TIPOGRAFÍAS
# =============================================================================
FUENTE_UI = "Segoe UI"
FUENTE_MONO = "Cascadia Mono"
FUENTE_MARCA = "Montserrat"

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
    """Hoja QSS global. Se aplica una sola vez sobre QApplication."""
    check = _icono("check.svg")
    flecha = _icono("chevron_down.svg")
    return f"""
QWidget {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXTO};
    font-family: "{FUENTE_UI}";
    font-size: 12px;
}}
QMainWindow, QDialog {{ background-color: {COLOR_BG}; }}
QLabel {{ background: transparent; }}

/* ------------------------------------------------------------------ Botones */
QPushButton, QToolButton {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    padding: 5px 12px;
    color: {COLOR_TEXTO};
    min-height: 20px;
}}
QPushButton:hover, QToolButton:hover {{
    background-color: {COLOR_SUPERFICIE};
    border-color: {rgba(COLOR_ACENTO, 140)};
}}
QPushButton:pressed, QToolButton:pressed {{ background-color: {COLOR_SELECCION}; }}
QPushButton:checked, QToolButton:checked {{
    background-color: {COLOR_SELECCION};
    border-color: {COLOR_ACENTO};
    color: {COLOR_ACENTO_HOVER};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {COLOR_TEXTO_TENUE};
    background-color: {COLOR_PANEL};
    border-color: {COLOR_BORDE_SUAVE};
}}
QPushButton#primario {{
    background-color: {COLOR_ACENTO};
    border: 1px solid {COLOR_ACENTO};
    color: {COLOR_BG};
    font-weight: 600;
}}
QPushButton#primario:hover {{ background-color: {COLOR_ACENTO_HOVER}; }}
QPushButton#primario:disabled {{
    background-color: {COLOR_PANEL_ALT};
    border-color: {COLOR_BORDE_SUAVE};
    color: {COLOR_TEXTO_TENUE};
}}
QPushButton#headerAction, QPushButton#fantasma, QToolButton#fantasma {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {COLOR_TEXTO_SEC};
    padding: 5px 10px;
}}
QPushButton#headerAction:hover, QPushButton#fantasma:hover, QToolButton#fantasma:hover {{
    background-color: {COLOR_PANEL_ALT};
    border-color: {COLOR_BORDE};
    color: {COLOR_TEXTO};
}}
QPushButton#headerAction:disabled, QPushButton#fantasma:disabled {{
    color: {COLOR_TEXTO_TENUE};
    background: transparent;
    border-color: transparent;
}}
/* Control segmentado (Axial / Coronal / Sagital, vistas 3D) */
QPushButton#segmento {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: {COLOR_TEXTO_SEC};
    padding: 4px 12px;
}}
QPushButton#segmento:hover {{ color: {COLOR_TEXTO}; background: {COLOR_SUPERFICIE}; }}
QPushButton#segmento:checked {{
    background: {COLOR_SELECCION};
    border-color: {rgba(COLOR_ACENTO, 160)};
    color: {COLOR_ACENTO_HOVER};
}}
QFrame#grupoSegmentado {{
    background: {COLOR_BG};
    border: 1px solid {COLOR_BORDE};
    border-radius: 7px;
}}

/* ------------------------------------------------------------- Entrada de texto */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {COLOR_BG};
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {COLOR_ACENTO};
    selection-color: {COLOR_BG};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{ border-color: {COLOR_ACENTO}; }}
QLineEdit:read-only {{ color: {COLOR_TEXTO_SEC}; }}

/* ----------------------------------------------------------------- Combos */
QComboBox {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {rgba(COLOR_ACENTO, 140)}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url({flecha}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    selection-background-color: {COLOR_SELECCION};
    selection-color: {COLOR_TEXTO};
    outline: none;
    padding: 4px;
}}

/* ---------------------------------------------------------------- Listas */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDE};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background-color: {COLOR_PANEL_ALT}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {COLOR_SELECCION};
    color: {COLOR_TEXTO};
}}

/* --------------------------------------------------------------- Sliders */
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{
    height: 4px; background: {COLOR_BORDE}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {COLOR_ACENTO}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {COLOR_TEXTO}; width: 12px; height: 12px;
    margin: -4px 0; border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {COLOR_ACENTO_HOVER}; }}
QSlider::groove:horizontal:disabled {{ background: {COLOR_BORDE_SUAVE}; }}
QSlider::sub-page:horizontal:disabled {{ background: {COLOR_BORDE}; }}
QSlider::handle:horizontal:disabled {{ background: {COLOR_TEXTO_TENUE}; }}

/* --------------------------------------------------------------- Checkbox */
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{
    border: 1px solid {COLOR_TEXTO_TENUE}; border-radius: 4px; background: {COLOR_BG};
}}
QCheckBox::indicator:unchecked:hover {{ border-color: {COLOR_ACENTO}; }}
QCheckBox::indicator:checked {{
    border: 1px solid {COLOR_ACENTO}; border-radius: 4px;
    background: {COLOR_ACENTO}; image: url({check});
}}
QCheckBox::indicator:indeterminate {{
    border: 1px solid {COLOR_ACENTO}; border-radius: 4px; background: {rgba(COLOR_ACENTO, 90)};
}}
QCheckBox:disabled {{ color: {COLOR_TEXTO_TENUE}; }}

/* ------------------------------------------------------------- Separadores */
QSplitter::handle {{ background: {COLOR_BG}; }}
QSplitter::handle:hover {{ background: {COLOR_BORDE}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}

/* --------------------------------------------------------------- Pestañas */
QTabWidget::pane {{ border: none; background: {COLOR_BG}; top: 0px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {COLOR_TEXTO_SEC};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 9px 18px 8px 18px;
    margin-right: 4px;
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {COLOR_TEXTO}; }}
QTabBar::tab:selected {{ color: {COLOR_TEXTO}; border-bottom-color: {COLOR_ACENTO}; }}

/* ----------------------------------------------------------------- Tooltip */
QToolTip {{
    background-color: {COLOR_PANEL_ALT};
    color: {COLOR_TEXTO};
    border: 1px solid {COLOR_BORDE};
    border-radius: 4px;
    padding: 6px 8px;
}}

/* --------------------------------------------------------------- Scroll */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {COLOR_BORDE}; min-height: 28px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: {COLOR_TEXTO_TENUE}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {COLOR_BORDE}; min-width: 28px; border-radius: 4px; }}
QScrollBar::handle:horizontal:hover {{ background: {COLOR_TEXTO_TENUE}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* --------------------------------------------------------------- Consola */
QTextEdit#consola {{
    background-color: {COLOR_BG};
    font-family: "{FUENTE_MONO}", "Consolas";
    font-size: 11px;
    border: none;
    border-radius: 0px;
    padding: 6px 10px;
}}

/* --------------------------------------------------------------- Barra de estado */
QStatusBar {{
    background: {COLOR_PANEL};
    color: {COLOR_TEXTO_SEC};
    border-top: 1px solid {COLOR_BORDE_SUAVE};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}

QMenu {{
    background: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDE};
    padding: 4px;
}}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {COLOR_SELECCION}; }}
"""


def fuente(tupla):
    """Convierte una tupla de Qt en un QFont."""
    f = QFont(tupla[0])
    f.setPointSize(tupla[1])
    if len(tupla) > 2 and tupla[2] == "bold":
        f.setBold(True)
    return f
