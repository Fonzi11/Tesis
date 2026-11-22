"""
Componentes de interfaz reutilizables de ATLAS.

Grupo plegable, logotipo, barra de progreso compacta, consola de registro,
tarjetas y "chips" de estado. Se escriben aquí, sin dependencias externas de
widgets, para que toda la aplicación comparta el mismo lenguaje visual.
"""

from PySide6.QtCore import Qt, QRectF, QSize, QPointF, Signal
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont,
                           QTextCharFormat, QPixmap, QIcon, QFontDatabase)
from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QTextEdit)

from .software_config import (
    APP_LEMA, APP_NOMBRE, COLOR_ACENTO, COLOR_BG, COLOR_BORDE, COLOR_BORDE_SUAVE,
    COLOR_ERROR, COLOR_OK, COLOR_PANEL, COLOR_PANEL_ALT, COLOR_TEXTO,
    COLOR_TEXTO_SEC, COLOR_TEXTO_TENUE, COLOR_WARN, FUENTE_MARCA,
    FUENTE_MARCA_ARCHIVO, FUENTE_MONO, rgba,
)


# =============================================================================
# Marca
# =============================================================================
_familia_marca = None


def familia_marca():
    """Familia tipográfica del logotipo (Montserrat Bold si está disponible)."""
    global _familia_marca
    if _familia_marca is None:
        _familia_marca = "Segoe UI"
        try:
            fid = QFontDatabase.addApplicationFont(FUENTE_MARCA_ARCHIVO)
            familias = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if familias:
                _familia_marca = familias[0]
        except Exception:
            pass
    return _familia_marca or FUENTE_MARCA


def pintar_simbolo(p, rect, color=COLOR_ACENTO, grosor=None):
    """Símbolo de ATLAS: una esfera con meridiano y ecuador (el mundo que
    sostiene Atlas), trazada en líneas finas sobre `rect`."""
    c = QColor(color)
    d = min(rect.width(), rect.height())
    g = grosor or max(1.4, d / 14.0)
    r = QRectF(rect.center().x() - d / 2 + g, rect.center().y() - d / 2 + g,
               d - 2 * g, d - 2 * g)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(c, g))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 170), g * 0.75))
    p.drawEllipse(QRectF(r.center().x() - r.width() * 0.22, r.top(),
                         r.width() * 0.44, r.height()))
    p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
    # Arco inferior: la "carga" sobre los hombros, que da lectura de marca.
    p.setPen(QPen(c, g))
    arco = QRectF(r.left() - g * 1.2, r.top() + r.height() * 0.38,
                  r.width() + g * 2.4, r.height() * 0.95)
    p.drawArc(arco, 200 * 16, 140 * 16)


def icono_aplicacion():
    """Icono de ventana generado por código (sin ficheros externos)."""
    icono = QIcon()
    for lado in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(lado, lado)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLOR_BG))
        p.drawRoundedRect(QRectF(0, 0, lado, lado), lado * 0.22, lado * 0.22)
        m = lado * 0.16
        pintar_simbolo(p, QRectF(m, m * 0.8, lado - 2 * m, lado - 2 * m))
        p.end()
        icono.addPixmap(pm)
    return icono


class LogoAtlas(QWidget):
    """Símbolo + "ATLAS" + lema. Se pinta a mano para que escale nítido."""

    def __init__(self, parent=None, compacto=False):
        super().__init__(parent)
        self._compacto = compacto
        self.setFixedHeight(40)
        self.setMinimumWidth(150 if compacto else 345)
        self.setToolTip(f"{APP_NOMBRE} · {APP_LEMA}")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        h = self.height()
        pintar_simbolo(p, QRectF(0, 3, h - 6, h - 6))
        x = h + 4
        f = QFont(familia_marca())
        f.setPixelSize(21)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor(COLOR_TEXTO))
        p.drawText(QRectF(x, 0, 200, h * 0.62), Qt.AlignLeft | Qt.AlignBottom, APP_NOMBRE)
        if not self._compacto:
            f2 = QFont("Segoe UI")
            f2.setPixelSize(10)
            f2.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
            p.setFont(f2)
            p.setPen(QColor(COLOR_TEXTO_SEC))
            p.drawText(QRectF(x + 1, h * 0.62, self.width() - x, h * 0.38),
                       Qt.AlignLeft | Qt.AlignTop, APP_LEMA)
        p.end()


# =============================================================================
# QCollapsibleGroupBox
# =============================================================================
class QCollapsibleGroupBox(QWidget):
    """Sección con cabecera pulsable que pliega o despliega su contenido."""

    toggled = Signal(bool)

    def __init__(self, title="", expanded=True, parent=None):
        super().__init__(parent)
        self._expanded = expanded

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self._header = QWidget()
        self._header.setObjectName("seccionCabecera")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setFixedHeight(26)
        self._header.setStyleSheet("#seccionCabecera { background: transparent; }")
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(2, 0, 2, 0)
        self._header_layout.setSpacing(6)

        self._arrow = QLabel()
        self._arrow.setFixedWidth(10)
        self._arrow.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 9px;")
        self._title = QLabel(title.upper())
        self._title.setStyleSheet(
            f"color: {COLOR_TEXTO_SEC}; font-size: 10px; font-weight: 700;"
            " letter-spacing: 1.2px;")
        self._header_layout.addWidget(self._arrow)
        self._header_layout.addWidget(self._title)
        self._header_layout.addStretch(1)
        self._extra = QHBoxLayout()
        self._extra.setSpacing(4)
        self._header_layout.addLayout(self._extra)

        self._content = QFrame()
        self._content.setObjectName("seccionCuerpo")
        self._content.setStyleSheet("#seccionCuerpo { background: transparent; border: none; }")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(2, 0, 2, 2)
        self._content_layout.setSpacing(6)

        self._layout.addWidget(self._header)
        self._layout.addWidget(self._content)

        self._header.mousePressEvent = self._toggle
        self.set_expanded(expanded)

    def add_header_widget(self, widget):
        """Widget a la derecha de la cabecera (contador, botón...)."""
        self._extra.addWidget(widget)

    def set_expanded(self, expanded):
        self._expanded = bool(expanded)
        self._content.setVisible(self._expanded)
        self._arrow.setText("▾" if self._expanded else "▸")
        self.toggled.emit(self._expanded)

    def _toggle(self, _event):
        self.set_expanded(not self._expanded)

    def set_title(self, title):
        self._title.setText(title.upper())

    def body(self):
        """Layout vertical donde va el contenido."""
        return self._content_layout

    def is_expanded(self):
        return self._expanded


# =============================================================================
# Progreso
# =============================================================================
class QCircularProgressBar(QWidget):
    """Arco de progreso con el porcentaje en el centro."""

    def __init__(self, parent=None, diameter=140):
        super().__init__(parent)
        self.progress_ratio = 0.0
        self.display_header = "Progreso"
        self.display_status = "Inactivo"
        self.setFixedSize(QSize(diameter, diameter))
        self._width = max(3, diameter // 16)

    def set_ratio(self, ratio, status=None):
        self.progress_ratio = max(0.0, min(1.0, float(ratio)))
        if status is not None:
            self.display_status = status
        self.update()

    def set_status(self, status):
        self.display_status = status
        self.update()

    def reset(self, status="Inactivo"):
        self.progress_ratio = 0.0
        self.display_status = status
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        m = self._width + 2
        lado = self.width() - 2 * m
        if lado <= 0:
            return
        caja = QRectF(m, m, lado, lado)
        pen = QPen(QColor(COLOR_BORDE))
        pen.setWidth(self._width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(caja, 0, 360 * 16)
        if self.progress_ratio > 0:
            path = QPainterPath()
            path.moveTo(caja.center().x(), caja.top())
            path.arcTo(caja, 90, -360 * self.progress_ratio)
            pen.setColor(QColor(COLOR_ACENTO))
            painter.setPen(pen)
            painter.strokePath(path, pen)
        painter.setPen(QColor(COLOR_TEXTO))
        f = QFont("Segoe UI")
        f.setPixelSize(max(9, int(lado * 0.28)))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(caja, Qt.AlignCenter, f"{int(round(self.progress_ratio * 100))}%")


class BarraEstadoProceso(QWidget):
    """Indicador compacto para la cabecera: punto de estado, texto y barra fina.

    Sustituye al progreso circular grande: ocupa una línea y sigue diciendo
    las tres cosas que importan (qué se hace, cómo va y si terminó bien).
    """

    _COLORES = {"inactivo": COLOR_TEXTO_TENUE, "activo": COLOR_ACENTO,
                "ok": COLOR_OK, "aviso": COLOR_WARN, "error": COLOR_ERROR}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(210, 40)
        self._ratio = 0.0
        self._texto = "Sin procesos en curso"
        self._estado = "inactivo"
        self.display_status = self._texto
        self.progress_ratio = 0.0

    def set_ratio(self, ratio, status=None):
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self.progress_ratio = self._ratio
        if status is not None:
            self._texto = status
            self.display_status = status
        self._estado = "ok" if self._ratio >= 1.0 else "activo"
        self.update()

    def set_status(self, status, estado=None):
        self._texto = status
        self.display_status = status
        if estado:
            self._estado = estado
        elif status.lower().startswith(("error",)):
            self._estado = "error"
        elif status.lower().startswith(("cancel",)):
            self._estado = "aviso"
        self.update()

    def reset(self, status="Sin procesos en curso"):
        self._ratio = 0.0
        self.progress_ratio = 0.0
        self._texto = status
        self.display_status = status
        self._estado = "activo" if status and not status.startswith("Sin") else "inactivo"
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(self._COLORES.get(self._estado, COLOR_TEXTO_TENUE))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(0, 9, 7, 7))
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(COLOR_TEXTO if self._estado != "inactivo" else COLOR_TEXTO_SEC))
        pct = f"  {int(round(self._ratio * 100))}%" if self._estado == "activo" else ""
        p.drawText(QRectF(14, 2, self.width() - 14, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   self._texto + pct)
        p.setBrush(QColor(COLOR_BORDE))
        p.drawRoundedRect(QRectF(14, 27, self.width() - 16, 3), 1.5, 1.5)
        if self._ratio > 0:
            p.setBrush(color)
            p.drawRoundedRect(QRectF(14, 27, (self.width() - 16) * self._ratio, 3), 1.5, 1.5)
        p.end()


# =============================================================================
# LogConsole
# =============================================================================
class LogConsole(QTextEdit):
    """Consola de registro con color por nivel."""

    NIVELES = {
        "INFO": COLOR_TEXTO_SEC,
        "SUCCESS": COLOR_OK,
        "WARNING": COLOR_WARN,
        "ERROR": COLOR_ERROR,
        "HEADER": COLOR_ACENTO,
        "PROGRESS": COLOR_ACENTO,
    }
    nuevo_mensaje = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("consola")
        self.setReadOnly(True)
        self.setFont(QFont(FUENTE_MONO, 9))
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.document().setMaximumBlockCount(5000)

    def _formato(self, color, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
        return fmt

    def log(self, mensaje, nivel="INFO"):
        """Añade un mensaje con la hora y el color del nivel."""
        from datetime import datetime

        tag = nivel.upper()
        if tag not in self.NIVELES:
            tag = "INFO"
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.setCharFormat(self._formato(COLOR_TEXTO_TENUE))
        cursor.insertText(f"{datetime.now().strftime('%H:%M:%S')}  ")
        bold = tag in ("HEADER", "PROGRESS")
        cursor.setCharFormat(self._formato(self.NIVELES[tag], bold))
        cursor.insertText(f"{mensaje}\n")
        self.ensureCursorVisible()
        self.nuevo_mensaje.emit(str(mensaje), tag)

    def limpiar(self):
        self.clear()


# =============================================================================
# Tarjetas y chips
# =============================================================================
class Card(QFrame):
    """Tarjeta compacta de estado: etiqueta pequeña y valor."""

    def __init__(self, titulo, valor="—", parent=None, accent=None):
        super().__init__(parent)
        self._accent = accent or COLOR_ACENTO
        self.setObjectName("statusCard")
        self.setStyleSheet(
            f"QFrame#statusCard {{ background: transparent; border: none;"
            f" border-left: 1px solid {COLOR_BORDE}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 2, 8, 2)
        lay.setSpacing(0)
        self._titulo = QLabel(titulo.upper())
        self._titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_TENUE}; font-size: 9px; font-weight: 700;"
            " letter-spacing: 1px;")
        self._valor = QLabel(valor)
        self._estilo_valor(self._accent)
        self._detalle = QLabel("")
        self._detalle.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 10px;")
        lay.addWidget(self._titulo)
        lay.addWidget(self._valor)
        lay.addWidget(self._detalle)
        self._detalle.hide()

    def _estilo_valor(self, color):
        self._valor.setStyleSheet(
            f"color: {COLOR_TEXTO}; font-size: 15px; font-weight: 600;")
        self._color = color

    def set_value(self, valor, color=None, detalle=None):
        self._valor.setText(valor)
        if color:
            self._estilo_valor(color)
        if detalle is not None:
            self._detalle.setText(detalle)
            self.setToolTip(detalle)


class Chip(QLabel):
    """Etiqueta en forma de píldora (tipo de lesión, origen del caso...)."""

    def __init__(self, texto="", color=COLOR_ACENTO, parent=None):
        super().__init__(texto, parent)
        self.set_color(color)

    def set_color(self, color):
        self.setStyleSheet(
            f"QLabel {{ color: {color}; background: {rgba(color, 28)};"
            f" border: 1px solid {rgba(color, 80)}; border-radius: 9px;"
            " padding: 1px 8px; font-size: 10px; font-weight: 600; }")


class Separador(QFrame):
    """Línea divisoria de 1 px."""

    def __init__(self, vertical=False, parent=None):
        super().__init__(parent)
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)
        self.setStyleSheet(f"background: {COLOR_BORDE_SUAVE}; border: none;")


class Panel(QFrame):
    """Contenedor con fondo de panel y borde suave redondeado."""

    def __init__(self, parent=None, radio=10):
        super().__init__(parent)
        self.setObjectName("panelAtlas")
        self.setStyleSheet(
            f"QFrame#panelAtlas {{ background: {COLOR_PANEL};"
            f" border: 1px solid {COLOR_BORDE_SUAVE}; border-radius: {radio}px; }}")


__all__ = ["QCollapsibleGroupBox", "QCircularProgressBar", "BarraEstadoProceso",
           "LogConsole", "Card", "Chip", "Separador", "Panel", "LogoAtlas",
           "icono_aplicacion", "pintar_simbolo", "familia_marca", "COLOR_PANEL_ALT",
           "COLOR_PANEL"]
