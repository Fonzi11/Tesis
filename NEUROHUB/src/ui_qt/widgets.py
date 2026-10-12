"""
Widgets reutilizables de NEUROHUB.

Recoge las piezas que se usan en varios paneles: el grupo plegable del panel
de capas, la barra de progreso circular (estilo Raidionics) y la consola de
log con colores por nivel. Se escriben aqui de forma autonoma para no
acoplar el paquete a una dependencia externa de widgets.
"""

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QTextCharFormat
from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QTextEdit)

from .software_config import (COLOR_ACENTO, COLOR_BORDE, COLOR_ERROR, COLOR_OK,
                              COLOR_PANEL, COLOR_PANEL_ALT, COLOR_TEXTO,
                              COLOR_TEXTO_SEC, COLOR_WARN, FUENTE_MONO)


# =============================================================================
# QCollapsibleGroupBox
# =============================================================================
class QCollapsibleGroupBox(QWidget):
    """Grupo con cabecera pulsable que pliega/despliega su contenido.

    Sustituye a los grupos estaticos de `main.py` para ganar espacio en el
    panel de capas, que es la parte mas densa de la interfaz.
    """

    def __init__(self, title="", expanded=True, parent=None):
        super().__init__(parent)
        self._expanded = expanded

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        # Cabecera: flecha + titulo, con el fondo del panel.
        self._header = QWidget()
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setFixedHeight(24)
        self._header.setStyleSheet(
            f"background-color: {COLOR_PANEL};"
            f"border-bottom: 1px solid {COLOR_BORDE};")
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(4, 0, 4, 0)
        self._header_layout.setSpacing(4)

        self._arrow = QLabel()
        self._arrow.setFixedWidth(12)
        self._title = QLabel(title)
        self._title.setStyleSheet(
            f"color: {COLOR_TEXTO}; font-weight: bold; background: transparent;")
        self._header_layout.addWidget(self._arrow)
        self._header_layout.addWidget(self._title)
        self._header_layout.addStretch(1)

        # Contenido plegable.
        self._content = QFrame()
        self._content.setStyleSheet(
            f"background-color: {COLOR_PANEL}; border: none;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(3)

        self._layout.addWidget(self._header)
        self._layout.addWidget(self._content)

        self._header.mousePressEvent = self._toggle
        self.set_expanded(expanded)

    # ------------------------------------------------------------------
    def set_expanded(self, expanded):
        self._expanded = bool(expanded)
        self._content.setVisible(self._expanded)
        self._arrow.setText("▾" if self._expanded else "▸")

    def _toggle(self, _event):
        self.set_expanded(not self._expanded)

    def set_title(self, title):
        self._title.setText(title)

    def body(self):
        """Devuelve el layout vertical donde meter el contenido."""
        return self._content_layout

    def is_expanded(self):
        return self._expanded


# =============================================================================
# QCircularProgressBar
# =============================================================================
class QCircularProgressBar(QWidget):
    """Arco de progreso con el porcentaje en el centro.

    Mismo lenguaje visual que el indicador de Raidionics, reimplementado
    sobre QPainter para no depender de su paquete de widgets.
    """

    def __init__(self, parent=None, diameter=140):
        super().__init__(parent)
        self.progress_ratio = 0.0
        self.display_header = "Progreso"
        self.display_status = "Inactivo"
        self.setFixedSize(QSize(diameter, diameter))

        self._frame_color = QColor(COLOR_PANEL)
        self._progress_color = QColor(COLOR_ACENTO)
        self._text_color = QColor(COLOR_TEXTO)
        self._sub_color = QColor(COLOR_TEXTO_SEC)
        self._margin = 10
        self._width = 8

    # ------------------------------------------------------------------
    def set_ratio(self, ratio, status=None):
        """Actualiza el progreso (0..1) y opcionalmente el texto de estado."""
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

    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._frame_color)

        lado = self.width() - 2 * self._margin
        if lado <= 0:
            return
        caja = QRectF(self._margin, self._margin, lado, lado)

        # Arco de fondo.
        pen = QPen(self._frame_color.lighter(160))
        pen.setWidth(self._width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(caja, 0, 360 * 16)

        # Arco de progreso (sentido antihorario, como el original).
        if self.progress_ratio > 0:
            path = QPainterPath()
            path.moveTo(caja.center().x(), caja.top())
            path.arcTo(caja, 90, -360 * self.progress_ratio)
            pen.setColor(self._progress_color)
            painter.setPen(pen)
            painter.strokePath(path, pen)

        # Porcentaje central.
        painter.setPen(self._text_color)
        f = QFont("Segoe UI")
        f.setPointSize(max(10, lado // 8))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(caja, Qt.AlignCenter,
                         f"{int(round(self.progress_ratio * 100))}%")

        # Estado bajo el porcentaje.
        f2 = QFont("Segoe UI")
        f2.setPointSize(max(7, lado // 14))
        painter.setFont(f2)
        painter.setPen(self._sub_color)
        painter.drawText(QRectF(caja.left(), caja.center().y() + lado * 0.16,
                                caja.width(), lado * 0.3),
                         Qt.AlignCenter, self.display_status)


# =============================================================================
# LogConsole
# =============================================================================
class LogConsole(QTextEdit):
    """Consola de texto con color por nivel de mensaje.

    Sustituye a `LogConsole` de `main.py`. El color se aplica con
    QTextCharFormat por fragmento (no con tags), que es lo que permite pintar
    la hora en un color y el mensaje en otro.
    """

    NIVELES = {
        "INFO": COLOR_TEXTO,
        "SUCCESS": COLOR_OK,
        "WARNING": COLOR_WARN,
        "ERROR": COLOR_ERROR,
        "HEADER": COLOR_ACENTO,
        "PROGRESS": COLOR_ACENTO,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("consola")
        self.setReadOnly(True)
        self.setFont(QFont(FUENTE_MONO, 9))
        self.setLineWrapMode(QTextEdit.NoWrap)
        # Limita el buffer para que una sesion larga no consuma toda la RAM.
        self.document().setMaximumBlockCount(5000)

    # ------------------------------------------------------------------
    def _formato(self, color, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        return fmt

    def log(self, mensaje, nivel="INFO"):
        """Anade un mensaje con la hora y el color del nivel."""
        from datetime import datetime

        tag = nivel.upper()
        if tag not in self.NIVELES:
            tag = "INFO"

        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.setCharFormat(self._formato(COLOR_TEXTO_SEC))
        cursor.insertText(f"[{datetime.now().strftime('%H:%M:%S')}] ")

        bold = tag in ("HEADER", "PROGRESS")
        cursor.setCharFormat(self._formato(self.NIVELES[tag], bold))
        cursor.insertText(f"{mensaje}\n")

        self.ensureCursorVisible()

    def limpiar(self):
        self.clear()


# =============================================================================
# Card
# =============================================================================
class Card(QFrame):
    """Tarjeta compacta de estado (equivalente a StatusCard de main.py)."""

    def __init__(self, titulo, valor="—", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_PANEL_ALT};"
            f" border: 1px solid {COLOR_BORDE}; border-radius: 9px; }}"
            f"QFrame:hover {{ border-color: {COLOR_ACENTO}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(2)

        self._titulo = QLabel(titulo)
        self._titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SEC}; font-size: 10px; border: none;")
        self._valor = QLabel(valor)
        self._valor.setStyleSheet(
            f"color: {COLOR_ACENTO}; font-size: 16px; font-weight: bold;"
            f" border: none;")
        self._detalle = QLabel("")
        self._detalle.setStyleSheet(
            f"color: {COLOR_TEXTO_SEC}; font-size: 9px; border: none;")
        self._detalle.setWordWrap(True)

        lay.addWidget(self._titulo)
        lay.addWidget(self._valor)
        lay.addWidget(self._detalle)

    def set_value(self, valor, color=None, detalle=None):
        self._valor.setText(valor)
        if color:
            self._valor.setStyleSheet(
                f"color: {color}; font-size: 16px; font-weight: bold;"
                f" border: none;")
        if detalle is not None:
            self._detalle.setText(detalle)
