"""
Paneles laterales de NEUROHUB: estudio (series) y capas (estructuras 3D).

Ambos paneles son "cabezas intelijentes": solo conocen el `StudyModel` y el
visor a traves de senales, de modo que se pueden probar sin levantar una
ventana VTK.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QFileDialog, QLineEdit, QComboBox,
)

from .software_config import (COLOR_ACENTO, COLOR_BORDE, COLOR_PANEL_ALT,
                              COLOR_SELECCION, COLOR_TEXTO, COLOR_TEXTO_SEC)
from .widgets import QCollapsibleGroupBox
from .pbr import color_de, label_de
from .pipeline_bridge import MODO_ANEURISMA, MODO_TUMOR


# =============================================================================
# Muestra de color de una estructura
# =============================================================================
class _Muestra(QWidget):
    """Cuadrado del color PBR de la estructura."""

    def __init__(self, color="#8B8B8B", parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(14, 14)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(COLOR_BORDE))
        p.setBrush(self._color)
        p.drawRoundedRect(self.rect(), 3, 3)


# =============================================================================
# Panel de capas
# =============================================================================
class LayersPanel(QWidget):
    """Lista de estructuras 3D con su visibilidad y color.

    Emite:
        visibilidad_cambiada(set): claves visibles tras un cambio.
    """

    visibilidad_cambiada = Signal(set)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._modelos = {}        # {clave: meta}
        self._checks = {}         # {clave: QCheckBox}

        self._construir_ui()

    def _construir_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Cabecera: "Capas" + botones de mostrar/ocultar todo.
        head = QHBoxLayout()
        tit = QLabel("CAPAS 3D")
        tit.setStyleSheet(f"color: {COLOR_TEXTO}; font-weight: bold;")
        head.addWidget(tit)
        head.addStretch(1)
        self._btn_todas = QPushButton("Todas")
        self._btn_todas.setFixedWidth(58)
        self._btn_todas.clicked.connect(lambda: self._set_todas(True))
        self._btn_ninguna = QPushButton("Ninguna")
        self._btn_ninguna.setFixedWidth(66)
        self._btn_ninguna.clicked.connect(lambda: self._set_todas(False))
        head.addWidget(self._btn_todas)
        head.addWidget(self._btn_ninguna)
        lay.addLayout(head)

        self._grupo = QCollapsibleGroupBox("Modelos segmentados", expanded=True)
        self._lista_host = QWidget()
        self._lista_lay = QVBoxLayout(self._lista_host)
        self._lista_lay.setContentsMargins(0, 0, 0, 0)
        self._lista_lay.setSpacing(2)
        self._grupo.body().addWidget(self._lista_host)
        lay.addWidget(self._grupo, 1)

        self._vacio = QLabel("Sin modelos 3D.\nEjecute el pipeline para generarlos.")
        self._vacio.setAlignment(Qt.AlignCenter)
        self._vacio.setWordWrap(True)
        self._vacio.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        lay.addWidget(self._vacio)

    # ------------------------------------------------------------------
    def set_modelos(self, modelos, visibles=None):
        """Repuebla el panel. `visibles` fija el estado inicial de las casillas."""
        self._modelos = dict(modelos or {})

        # Limpia las filas anteriores.
        while self._lista_lay.count():
            item = self._lista_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._checks.clear()

        if visibles is None:
            visibles = set(self._modelos)

        for key, meta in self._modelos.items():
            self._lista_lay.addWidget(
                self._crear_fila(key, meta, key in visibles))

        hay = bool(self._modelos)
        self._grupo.setVisible(hay)
        self._vacio.setVisible(not hay)

    def _crear_fila(self, key, meta, visible):
        """Una fila: casilla de visibilidad, color y nombre de la estructura."""
        fila = QWidget()
        fl = QHBoxLayout(fila)
        fl.setContentsMargins(2, 1, 2, 1)
        fl.setSpacing(6)

        chk = QCheckBox()
        chk.setChecked(bool(visible))
        chk.toggled.connect(lambda _v, k=key: self._al_cambiar(k))
        fl.addWidget(chk)

        fl.addWidget(_Muestra(meta.get("display") or color_de(key)))

        nombre = QLabel(meta.get("label") or label_de(key))
        nombre.setStyleSheet(f"color: {COLOR_TEXTO}; background: transparent;")
        nombre.setToolTip(meta.get("stl") or "")
        fl.addWidget(nombre, 1)

        self._checks[key] = chk
        return fila

    # ------------------------------------------------------------------
    def _al_cambiar(self, _key=None):
        self.visibilidad_cambiada.emit(self.claves_visibles())

    def _set_todas(self, valor):
        for chk in self._checks.values():
            chk.setChecked(valor)
        self._al_cambiar()

    def claves_visibles(self):
        return {k for k, c in self._checks.items() if c.isChecked()}

    def set_visibles(self, keys):
        """Sincroniza las casillas sin re-emitir la senal (evita bucles)."""
        objetivo = set(keys or ())
        for k, c in self._checks.items():
            c.blockSignals(True)
            c.setChecked(k in objetivo)
            c.blockSignals(False)

    def claves(self):
        return list(self._modelos)

    def estructura_de(self, key):
        return self._modelos.get(key)

# =============================================================================
# Panel de estudio
# =============================================================================
class _SerieButton(QPushButton):
    """Boton plano de la lista de series, con el estilo de los timestamps."""

    def __init__(self, texto, parent=None):
        super().__init__(texto, parent)
        self.setCheckable(True)
        self.setToolTip(texto)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 5px 8px;"
            f" border: 1px solid transparent; border-radius: 4px;"
            f" color: {COLOR_TEXTO}; }}"
            f"QPushButton:hover {{ background: {COLOR_PANEL_ALT};"
            f" border-color: {COLOR_BORDE}; }}"
            f"QPushButton:checked {{ background: {COLOR_SELECCION};"
            f" border-color: {COLOR_ACENTO}; }}")


class StudyPanel(QWidget):
    """Series del estudio, datos de entrada y control del pipeline.

    Emite:
        pedir_carga(str): el usuario quiere cargar una ruta de estudio.
        serie_elegida(str): uid de la serie seleccionada.
        ejecutar(str): "pipeline" | "exportar" | "cancelar".
    """

    pedir_carga = Signal(str)
    serie_elegida = Signal(str)
    ejecutar = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._botones_serie = {}     # {uid: _SerieButton}
        self._construir_ui()

    # ------------------------------------------------------------------
    def _construir_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # ---- Entrada del estudio ----
        grp_ent = QCollapsibleGroupBox("Estudio", expanded=True)
        cuerpo = grp_ent.body()

        self._ruta = QLineEdit()
        self._ruta.setPlaceholderText("Ruta del estudio (DICOM o NIfTI)")
        self._ruta.setReadOnly(True)
        self._ruta.setToolTip("Se rellena al elegir una carpeta o archivo")
        cuerpo.addWidget(self._ruta)

        fila = QHBoxLayout()
        self._btn_cargar = QPushButton("Cargar...")
        self._btn_cargar.setToolTip("Seleccionar la carpeta o el volumen del caso")
        self._btn_cargar.clicked.connect(self._elegir_ruta)
        self._btn_limpiar = QPushButton("Quitar")
        self._btn_limpiar.clicked.connect(self.limpiar_estudio)
        fila.addWidget(self._btn_cargar)
        fila.addWidget(self._btn_limpiar)
        cuerpo.addLayout(fila)
        lay.addWidget(grp_ent)

        # ---- Series (una por timestamp/volumen) ----
        self._grp_series = QCollapsibleGroupBox("Series", expanded=True)
        self._host_series = QWidget()
        self._lay_series = QVBoxLayout(self._host_series)
        self._lay_series.setContentsMargins(0, 0, 0, 0)
        self._lay_series.setSpacing(2)
        self._grp_series.body().addWidget(self._host_series)
        lay.addWidget(self._grp_series)

        self._sin_series = QLabel("Sin series cargadas")
        self._sin_series.setAlignment(Qt.AlignCenter)
        self._sin_series.setStyleSheet(
            f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        lay.addWidget(self._sin_series)
        lay.addStretch(1)

        # ---- Procesamiento ----
        grp_proc = QCollapsibleGroupBox("Procesamiento", expanded=True)
        p = grp_proc.body()

        self._chk_slices = QCheckBox("Generar vistas 2D")
        self._chk_slices.setChecked(True)
        p.addWidget(self._chk_slices)
        p.addSpacing(8)

        # ---- Modo de analisis: aneurisma O tumor, nunca los dos ----
        # Se ofrece como combo, no como dos checkboxes, precisamente para que
        # el estado "las dos cosas a la vez" sea irrepresentable en la
        # interfaz. `normalizar_modo` vuelve a validar el valor en el worker,
        # de modo que la garantia no depende solo de este widget.
        lbl_modo = QLabel("Modo de analisis")
        lbl_modo.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        p.addWidget(lbl_modo)

        self._cmb_modo = QComboBox()
        self._cmb_modo.addItem("Anatomia + vasos (sin modo)", None)
        self._cmb_modo.addItem("Aneurisma", MODO_ANEURISMA)
        self._cmb_modo.addItem("Tumor", MODO_TUMOR)
        self._cmb_modo.setToolTip(
            "El modo es excluyente: aneurisma y tumor son diagnosticos\n"
            "incompatibles y no se pueden ejecutar en el mismo caso.")
        p.addWidget(self._cmb_modo)
        p.addSpacing(4)

        self._btn_run = QPushButton("Ejecutar pipeline")
        self._btn_run.setToolTip("Segmentacion + mallas + vistas 2D")
        self._btn_run.clicked.connect(lambda: self.ejecutar.emit("pipeline"))
        p.addWidget(self._btn_run)

        self._btn_fbx = QPushButton("Exportar FBX")
        self._btn_fbx.setToolTip("Convertir las mallas STL a FBX")
        self._btn_fbx.clicked.connect(lambda: self.ejecutar.emit("exportar"))
        p.addWidget(self._btn_fbx)

        self._btn_cancel = QPushButton("Cancelar")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setToolTip("Detener el proceso en curso")
        self._btn_cancel.clicked.connect(lambda: self.ejecutar.emit("cancelar"))
        p.addWidget(self._btn_cancel)

        lay.addWidget(grp_proc)
        lay.addStretch(1)
        self._actualizar_botones()

    # ------------------------------------------------------------------
    def _elegir_ruta(self):
        """Abre el selector de carpeta (o de archivo) y avisa a la ventana."""
        ruta = QFileDialog.getExistingDirectory(
            self, "Seleccionar estudio", os.path.expanduser("~"))
        if not ruta:
            # Si se cancela el selector de carpeta, se ofrece el de archivos
            # para poder elegir un NIfTI suelto.
            archivo, _ = QFileDialog.getOpenFileName(
                self, "Seleccionar volumen", os.path.expanduser("~"),
                "Volumenes (*.nii *.nii.gz *.dcm);;Todos los archivos (*)")
            if not archivo:
                return
            ruta = archivo
        self.set_ruta(ruta)
        self.pedir_carga.emit(ruta)

    def set_ruta(self, ruta):
        self._ruta.setText(ruta or "")
        self._actualizar_botones()

    def ruta(self):
        return self._ruta.text().strip()

    def generar_slices(self):
        return self._chk_slices.isChecked()

    def modo(self):
        """Modo de analisis elegido, o None si solo se quiere anatomia/vasos."""
        return self._cmb_modo.currentData()

    def limpiar_estudio(self):
        self.set_ruta("")
        self.set_series([], None)
        self.pedir_carga.emit("")

    # ------------------------------------------------------------------
    def set_series(self, series, uid_activa=None):
        """Repuebla la lista de series (una por timestamp/volumen)."""
        while self._lay_series.count():
            item = self._lay_series.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._botones_serie.clear()

        for s in series or []:
            b = _SerieButton(s.nombre)
            b.setToolTip(f"{s.nombre}\n{s.ruta}")
            b.clicked.connect(lambda _c, u=s.uid: self._elegir_serie(u))
            self._lay_series.addWidget(b)
            self._botones_serie[s.uid] = b

        self._sin_series.setVisible(not self._botones_serie)
        if uid_activa is not None:
            self.set_serie_activa(uid_activa)

    def _elegir_serie(self, uid):
        self.set_serie_activa(uid)
        self.serie_elegida.emit(uid)

    def set_serie_activa(self, uid):
        for u, b in self._botones_serie.items():
            b.setChecked(u == uid)

    # ------------------------------------------------------------------
    def set_procesando(self, activo, hay_mallas=True):
        """Activa/desactiva los controles mientras dura un proceso."""
        self._procesando = bool(activo)
        self._hay_mallas = bool(hay_mallas)
        self._actualizar_botones()

    def _actualizar_botones(self):
        proc = getattr(self, "_procesando", False)
        mallas = getattr(self, "_hay_mallas", False)
        self._btn_run.setEnabled(not proc and bool(self.ruta()))
        self._btn_fbx.setEnabled(not proc and mallas)
        self._btn_cancel.setEnabled(proc)
