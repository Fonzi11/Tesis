"""
Paneles laterales de ATLAS: casos y estudio (izquierda) y capas 3D.

Ambos paneles solo hablan con la ventana por señales, de modo que se pueden
probar sin levantar el visor VTK.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QCheckBox, QFileDialog, QLineEdit, QComboBox, QScrollArea, QSlider, QFrame,
)

from .software_config import (
    COLOR_ACENTO, COLOR_BORDE, COLOR_BORDE_SUAVE, COLOR_PANEL_ALT, COLOR_SELECCION,
    COLOR_SUPERFICIE, COLOR_TEXTO, COLOR_TEXTO_SEC, COLOR_TEXTO_TENUE, COLOR_WARN,
    rgba,
)
from .widgets import QCollapsibleGroupBox, Chip
from .pbr import color_de, label_de
from .pipeline_bridge import MODO_ANEURISMA, MODO_TUMOR
from .casos_atlas import GRUPOS, NOMBRE_GRUPO, grupo_de

COLOR_LESION = {"tumor": "#E0559B", "aneurisma": "#F0A640"}

# Opacidad inicial por grupo para mallas del pipeline clásico, que no traen la
# suya (los casos ATLAS usan la de su `resumen.json`).
OPACIDAD_GRUPO = {"craneo": 0.22, "corteza": 0.35, "sustancia_blanca": 0.30,
                  "ventriculos": 0.6}


# =============================================================================
# Utilidades
# =============================================================================
class _Muestra(QWidget):
    """Círculo con el color de la estructura."""

    def __init__(self, color="#8B8B8B", parent=None, lado=10):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(lado, lado)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(0, 0, 0, 90))
        p.setBrush(self._color)
        p.drawEllipse(self.rect().adjusted(0, 0, -1, -1))


def _scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


def _boton_fantasma(texto, tip=""):
    b = QPushButton(texto)
    b.setObjectName("fantasma")
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


# =============================================================================
# Panel de capas
# =============================================================================
class _FilaCapa(QWidget):
    """Una estructura: casilla de visibilidad, color, nombre y volumen."""

    def __init__(self, key, meta, visible, al_cambiar, parent=None):
        super().__init__(parent)
        self.key = key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 0, 4, 0)
        lay.setSpacing(8)
        self.chk = QCheckBox()
        self.chk.setChecked(bool(visible))
        self.chk.toggled.connect(lambda _v: al_cambiar())
        lay.addWidget(self.chk)
        lay.addWidget(_Muestra(meta.get("display") or color_de(key)))
        nombre = QLabel(meta.get("label") or label_de(key))
        nombre.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 11px;")
        nombre.setToolTip(meta.get("stl") or "")
        lay.addWidget(nombre, 1)
        vol = meta.get("volumen_cm3")
        if vol is not None:
            v = QLabel(f"{float(vol):.1f} cm³")
            v.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 10px;")
            lay.addWidget(v)
        self.setFixedHeight(24)


class _GrupoCapas(QFrame):
    """Grupo de estructuras con visibilidad conjunta y opacidad."""

    def __init__(self, grupo, filas_meta, visibles, panel, parent=None):
        super().__init__(parent)
        self.grupo = grupo
        self._panel = panel
        self._expandido = False
        self.setObjectName("grupoCapas")
        self.setStyleSheet(
            f"QFrame#grupoCapas {{ background: {COLOR_PANEL_ALT};"
            f" border: 1px solid {COLOR_BORDE_SUAVE}; border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        cab = QHBoxLayout()
        cab.setSpacing(8)
        self.chk = QCheckBox()
        self.chk.setTristate(False)
        self.chk.clicked.connect(self._al_pulsar_grupo)
        cab.addWidget(self.chk)
        # Color del grupo: el de la estructura más representativa (en la
        # lesión, el tumor con realce o el saco aneurismático, no el edema).
        clave0 = next((k for k in filas_meta if "realce" in k or k.startswith("aneurisma")),
                      next(iter(filas_meta)))
        cab.addWidget(_Muestra(filas_meta[clave0].get("display") or color_de(clave0), lado=11))
        tit = QLabel(NOMBRE_GRUPO.get(grupo, grupo))
        tit.setStyleSheet(f"color: {COLOR_TEXTO}; font-weight: 600;")
        cab.addWidget(tit, 1)
        self._contador = QLabel("")
        self._contador.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 10px;")
        cab.addWidget(self._contador)
        self._btn_exp = QPushButton("▸")
        self._btn_exp.setObjectName("fantasma")
        self._btn_exp.setFixedSize(22, 22)
        self._btn_exp.setStyleSheet("padding: 0px;")
        self._btn_exp.setCursor(Qt.PointingHandCursor)
        self._btn_exp.setToolTip("Mostrar las estructuras del grupo")
        self._btn_exp.clicked.connect(self._alternar)
        cab.addWidget(self._btn_exp)
        if len(filas_meta) == 1:
            self._btn_exp.hide()
        lay.addLayout(cab)

        op = QHBoxLayout()
        op.setContentsMargins(22, 0, 0, 0)
        op.setSpacing(8)
        # El deslizador no fija una opacidad única: escala la de cada capa
        # conservando sus proporciones (centro = valores del caso, izquierda
        # = invisible, derecha = opaco). Si igualara todas, en la lesión el
        # edema taparía al tumor con realce y a la necrosis que lleva dentro.
        self._alfa_base = {k: float(m.get("opacity", 1.0)) for k, m in filas_meta.items()}
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.slider.setToolTip("Opacidad del grupo (centro: valores del caso)")
        self.slider.valueChanged.connect(self._al_mover_opacidad)
        self._lbl_op = QLabel(self._texto_opacidad(50))
        self._lbl_op.setFixedWidth(34)
        self._lbl_op.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_op.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 10px;")
        op.addWidget(self.slider, 1)
        op.addWidget(self._lbl_op)
        lay.addLayout(op)

        self._hijos = QWidget()
        self._hijos.setObjectName("hijosGrupo")
        self._hijos.setStyleSheet("#hijosGrupo { background: transparent; }")
        hl = QVBoxLayout(self._hijos)
        hl.setContentsMargins(0, 4, 0, 0)
        hl.setSpacing(0)
        self.filas = {}
        for key, meta in filas_meta.items():
            fila = _FilaCapa(key, meta, key in visibles, self._al_cambiar_hijo)
            hl.addWidget(fila)
            self.filas[key] = fila
        self._hijos.setVisible(False)
        lay.addWidget(self._hijos)
        self._sincronizar_cabecera()

    # ------------------------------------------------------------------
    def _alternar(self):
        self._expandido = not self._expandido
        self._hijos.setVisible(self._expandido)
        self._btn_exp.setText("▾" if self._expandido else "▸")

    def _al_pulsar_grupo(self, marcado):
        for f in self.filas.values():
            f.chk.blockSignals(True)
            f.chk.setChecked(bool(marcado))
            f.chk.blockSignals(False)
        self._sincronizar_cabecera()
        self._panel._emitir_visibilidad()

    def _al_cambiar_hijo(self):
        self._sincronizar_cabecera()
        self._panel._emitir_visibilidad()

    def opacidades_para(self, valor):
        """Opacidad de cada estructura para la posición `valor` (0..100)."""
        t = valor / 100.0
        res = {}
        for k, a in self._alfa_base.items():
            res[k] = a * (t / 0.5) if t <= 0.5 else a + (1.0 - a) * ((t - 0.5) / 0.5)
            res[k] = max(0.02, min(1.0, res[k]))
        return res

    def _texto_opacidad(self, valor):
        ops = self.opacidades_para(valor)
        return f"{100 * max(ops.values()):.0f}%"

    def _al_mover_opacidad(self, valor):
        self._lbl_op.setText(self._texto_opacidad(valor))
        self._panel._emitir_opacidad(self.opacidades_para(valor))

    def _sincronizar_cabecera(self):
        n = sum(f.chk.isChecked() for f in self.filas.values())
        total = len(self.filas)
        self.chk.blockSignals(True)
        self.chk.setTristate(0 < n < total)
        self.chk.setCheckState(Qt.Checked if n == total else
                               Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self.chk.blockSignals(False)
        self._contador.setText(f"{n}/{total}" if total > 1 else "")
        self.slider.setEnabled(n > 0)

    def set_visibles(self, keys):
        for k, f in self.filas.items():
            f.chk.blockSignals(True)
            f.chk.setChecked(k in keys)
            f.chk.blockSignals(False)
        self._sincronizar_cabecera()


class LayersPanel(QWidget):
    """Estructuras 3D agrupadas por capa anatómica.

    Emite:
        visibilidad_cambiada(set): claves visibles tras un cambio.
        opacidad_cambiada(dict): {clave: opacidad 0..1} de las estructuras tocadas.
    """

    visibilidad_cambiada = Signal(set)
    opacidad_cambiada = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._modelos = {}
        self._grupos = {}
        self._construir_ui()

    def _construir_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 10, 10)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(4)
        tit = QLabel("CAPAS 3D")
        tit.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 10px; font-weight: 700;"
                          " letter-spacing: 1.2px;")
        head.addWidget(tit)
        self._lbl_total = QLabel("")
        self._lbl_total.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 10px;")
        head.addWidget(self._lbl_total)
        head.addStretch(1)
        self._btn_todas = _boton_fantasma("Todas", "Mostrar todas las estructuras")
        self._btn_todas.clicked.connect(lambda: self._set_todas(True))
        self._btn_ninguna = _boton_fantasma("Ninguna", "Ocultar todas las estructuras")
        self._btn_ninguna.clicked.connect(lambda: self._set_todas(False))
        head.addWidget(self._btn_todas)
        head.addWidget(self._btn_ninguna)
        lay.addLayout(head)

        self._host = QWidget()
        self._host.setObjectName("listaCapas")
        self._host.setStyleSheet("#listaCapas { background: transparent; }")
        self._lista = QVBoxLayout(self._host)
        self._lista.setContentsMargins(0, 0, 4, 0)
        self._lista.setSpacing(6)
        self._lista.addStretch(1)
        self._area = _scroll(self._host)
        lay.addWidget(self._area, 1)

        self._vacio = QLabel("Sin modelos 3D.\nElija un caso o ejecute el pipeline.")
        self._vacio.setAlignment(Qt.AlignCenter)
        self._vacio.setWordWrap(True)
        self._vacio.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 11px;")
        lay.addWidget(self._vacio, 1)

    # ------------------------------------------------------------------
    def set_modelos(self, modelos, visibles=None):
        """Repuebla el panel. `visibles` fija el estado inicial de las casillas."""
        self._modelos = {}
        for k, m in (modelos or {}).items():
            meta = dict(m)
            meta.setdefault("grupo", grupo_de(k))
            meta.setdefault("opacity", OPACIDAD_GRUPO.get(meta["grupo"], 1.0))
            self._modelos[k] = meta
        while self._lista.count() > 1:
            item = self._lista.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._grupos.clear()
        if visibles is None:
            visibles = set(self._modelos)

        por_grupo = {}
        for k, m in self._modelos.items():
            por_grupo.setdefault(m["grupo"], {})[k] = m
        orden = [g for g, _ in reversed(GRUPOS)]   # la lesión arriba
        for g in sorted(por_grupo, key=lambda x: orden.index(x) if x in orden else 99):
            w = _GrupoCapas(g, por_grupo[g], set(visibles), self)
            self._grupos[g] = w
            self._lista.insertWidget(self._lista.count() - 1, w)

        hay = bool(self._modelos)
        self._area.setVisible(hay)
        self._vacio.setVisible(not hay)
        self._btn_todas.setEnabled(hay)
        self._btn_ninguna.setEnabled(hay)
        self._actualizar_total()

    def _checks(self):
        return {k: f.chk for g in self._grupos.values() for k, f in g.filas.items()}

    def _emitir_visibilidad(self):
        self._actualizar_total()
        self.visibilidad_cambiada.emit(self.claves_visibles())

    def _emitir_opacidad(self, cambios):
        for k, a in cambios.items():
            if k in self._modelos:
                self._modelos[k]["opacity"] = a
        self.opacidad_cambiada.emit(dict(cambios))

    def _actualizar_total(self):
        if self._modelos:
            self._lbl_total.setText(f"· {len(self.claves_visibles())}/{len(self._modelos)}")
        else:
            self._lbl_total.setText("")

    def _set_todas(self, valor):
        for g in self._grupos.values():
            g.set_visibles(set(g.filas) if valor else set())
        self._emitir_visibilidad()

    def claves_visibles(self):
        return {k for k, c in self._checks().items() if c.isChecked()}

    def set_visibles(self, keys):
        """Sincroniza las casillas sin re-emitir la señal (evita bucles)."""
        objetivo = set(keys or ())
        for g in self._grupos.values():
            g.set_visibles(objetivo)
        self._actualizar_total()

    def opacidades(self):
        return {k: float(m.get("opacity", 1.0)) for k, m in self._modelos.items()}

    def claves(self):
        return list(self._modelos)

    def estructura_de(self, key):
        return self._modelos.get(key)


# =============================================================================
# Panel de casos y estudio
# =============================================================================
class _TarjetaCaso(QPushButton):
    """Caso ATLAS: título, origen y tipo de lesión."""

    def __init__(self, caso, parent=None):
        super().__init__(parent)
        self.caso_id = caso["id"]
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setToolTip(f"{caso['titulo']}\n{caso.get('segmentacion', '')}\n"
                        f"{caso.get('segmentacion_lesion', '')}".strip())
        self.setStyleSheet(
            f"QPushButton {{ text-align: left; background: transparent; min-height: 54px;"
            f" border: 1px solid transparent; border-radius: 8px; padding: 0px; }}"
            f"QPushButton:hover {{ background: {COLOR_SUPERFICIE}; border-color: {COLOR_BORDE}; }}"
            f"QPushButton:checked {{ background: {COLOR_SELECCION};"
            f" border-color: {rgba(COLOR_ACENTO, 150)}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(caso["titulo"])
        t.setStyleSheet(f"color: {COLOR_TEXTO}; font-weight: 600; font-size: 12px;")
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        s = QLabel(caso.get("subtitulo") or "")
        s.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 10px;")
        s.setAttribute(Qt.WA_TransparentForMouseEvents)
        col.addWidget(t)
        col.addWidget(s)
        lay.addLayout(col, 1)
        lesion = caso.get("lesion")
        if lesion:
            chip = Chip(lesion.capitalize(), COLOR_LESION.get(lesion, COLOR_ACENTO))
            chip.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(chip, 0, Qt.AlignVCenter)


class _SerieButton(QPushButton):
    """Botón plano de la lista de series."""

    def __init__(self, texto, parent=None):
        super().__init__(texto, parent)
        self.setCheckable(True)
        self.setToolTip(texto)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 6px 10px; background: transparent;"
            f" border: 1px solid transparent; border-radius: 6px; color: {COLOR_TEXTO}; }}"
            f"QPushButton:hover {{ background: {COLOR_SUPERFICIE}; border-color: {COLOR_BORDE}; }}"
            f"QPushButton:checked {{ background: {COLOR_SELECCION};"
            f" border-color: {rgba(COLOR_ACENTO, 150)}; }}")


class StudyPanel(QWidget):
    """Casos ATLAS, estudio propio y control del pipeline.

    Emite:
        caso_elegido(str): id del caso ATLAS elegido.
        pedir_carga(str): el usuario quiere cargar una ruta de estudio.
        serie_elegida(str): uid de la serie seleccionada.
        ejecutar(str): "pipeline" | "freesurfer" | "cta" | "cta_aprobar" |
                       "exportar" | "cancelar".
    """

    caso_elegido = Signal(str)
    pedir_carga = Signal(str)
    serie_elegida = Signal(str)
    ejecutar = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._botones_serie = {}
        self._tarjetas = {}
        self._procesando = False
        self._hay_mallas = False
        self._construir_ui()

    # ------------------------------------------------------------------
    def _construir_ui(self):
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        contenido = QWidget()
        contenido.setObjectName("contenidoEstudio")
        contenido.setStyleSheet("#contenidoEstudio { background: transparent; }")
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(14, 14, 10, 14)
        lay.setSpacing(14)
        exterior.addWidget(_scroll(contenido))

        # ---- Casos ATLAS ----
        self._grp_casos = QCollapsibleGroupBox("Casos ATLAS", expanded=True)
        self._host_casos = QWidget()
        self._lay_casos = QVBoxLayout(self._host_casos)
        self._lay_casos.setContentsMargins(0, 0, 0, 0)
        self._lay_casos.setSpacing(2)
        self._grp_casos.body().addWidget(self._host_casos)
        self._sin_casos = QLabel("No hay casos preparados en\nsalidas/modelos_ar_freesurfer")
        self._sin_casos.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 11px;")
        self._grp_casos.body().addWidget(self._sin_casos)
        lay.addWidget(self._grp_casos)

        # ---- Estudio propio ----
        grp_ent = QCollapsibleGroupBox("Estudio propio", expanded=True)
        cuerpo = grp_ent.body()
        self._ruta = QLineEdit()
        self._ruta.setPlaceholderText("Carpeta DICOM o volumen NIfTI")
        self._ruta.setReadOnly(True)
        self._ruta.setToolTip("La carpeta DICOM puede contener los archivos en subcarpetas")
        cuerpo.addWidget(self._ruta)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        self._btn_cargar = QPushButton("DICOM…")
        self._btn_cargar.setToolTip("Seleccionar la carpeta completa del estudio DICOM "
                                    "(se buscan series también en subcarpetas)")
        self._btn_cargar.clicked.connect(self._elegir_carpeta_dicom)
        self._btn_archivo = QPushButton("NIfTI…")
        self._btn_archivo.setToolTip("Seleccionar un volumen NIfTI o un DICOM individual")
        self._btn_archivo.clicked.connect(self._elegir_archivo)
        self._btn_limpiar = _boton_fantasma("Quitar", "Descargar el estudio propio")
        self._btn_limpiar.clicked.connect(self.limpiar_estudio)
        fila.addWidget(self._btn_cargar, 1)
        fila.addWidget(self._btn_archivo, 1)
        fila.addWidget(self._btn_limpiar)
        cuerpo.addLayout(fila)
        self._host_series = QWidget()
        self._lay_series = QVBoxLayout(self._host_series)
        self._lay_series.setContentsMargins(0, 2, 0, 0)
        self._lay_series.setSpacing(2)
        cuerpo.addWidget(self._host_series)
        self._sin_series = QLabel("")
        self._sin_series.hide()
        lay.addWidget(grp_ent)

        # ---- Procesamiento ----
        grp_proc = QCollapsibleGroupBox("Procesamiento", expanded=False)
        p = grp_proc.body()
        lbl_modo = QLabel("Modo de análisis")
        lbl_modo.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        p.addWidget(lbl_modo)
        self._cmb_modo = QComboBox()
        self._cmb_modo.addItem("Anatomía + vasos", None)
        self._cmb_modo.addItem("Aneurisma", MODO_ANEURISMA)
        self._cmb_modo.addItem("Tumor", MODO_TUMOR)
        self._cmb_modo.setToolTip("El modo es excluyente: aneurisma y tumor no se "
                                  "ejecutan en el mismo caso.")
        p.addWidget(self._cmb_modo)
        self._chk_slices = QCheckBox("Generar vistas 2D")
        self._chk_slices.setChecked(True)
        p.addWidget(self._chk_slices)

        self._btn_run = QPushButton("Ejecutar pipeline")
        self._btn_run.setObjectName("primario")
        self._btn_run.setToolTip("Segmentación + mallas + vistas 2D")
        self._btn_run.clicked.connect(lambda: self.ejecutar.emit("pipeline"))
        p.addWidget(self._btn_run)

        grid = QGridLayout()
        grid.setSpacing(6)
        self._btn_freesurfer = QPushButton("FreeSurfer")
        self._btn_freesurfer.setToolTip("recon-all sobre el estudio activo y exportación "
                                        "de aseg a NIfTI. Requiere T1 y license.txt.")
        self._btn_freesurfer.clicked.connect(lambda: self.ejecutar.emit("freesurfer"))
        self._btn_cta = QPushButton("Flujo CTA")
        self._btn_cta.setToolTip("Validar geometría, candidato vascular y NRRD. "
                                 "El DICOM SEG requiere revisión humana.")
        self._btn_cta.clicked.connect(lambda: self.ejecutar.emit("cta"))
        self._btn_cta_aprobar = QPushButton("Aprobar SEG")
        self._btn_cta_aprobar.setToolTip("Registra la revisión humana y genera el DICOM SEG.")
        self._btn_cta_aprobar.clicked.connect(lambda: self.ejecutar.emit("cta_aprobar"))
        self._btn_fbx = QPushButton("Exportar FBX")
        self._btn_fbx.setToolTip("Convertir las mallas visibles a FBX para Unity")
        self._btn_fbx.clicked.connect(lambda: self.ejecutar.emit("exportar"))
        for i, b in enumerate((self._btn_freesurfer, self._btn_cta,
                               self._btn_cta_aprobar, self._btn_fbx)):
            grid.addWidget(b, i // 2, i % 2)
        p.addLayout(grid)
        self._btn_cancel = _boton_fantasma("Cancelar proceso", "Detener el proceso en curso")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(lambda: self.ejecutar.emit("cancelar"))
        p.addWidget(self._btn_cancel)
        lay.addWidget(grp_proc)
        lay.addStretch(1)
        self._actualizar_botones()

    # ------------------------------------------------------------------ casos
    def set_casos(self, casos, activo=None):
        while self._lay_casos.count():
            item = self._lay_casos.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._tarjetas.clear()
        for c in casos or []:
            t = _TarjetaCaso(c)
            t.clicked.connect(lambda _c, cid=c["id"]: self._elegir_caso(cid))
            self._lay_casos.addWidget(t)
            self._tarjetas[c["id"]] = t
        self._sin_casos.setVisible(not self._tarjetas)
        self.set_caso_activo(activo)

    def _elegir_caso(self, cid):
        self.set_caso_activo(cid)
        self.caso_elegido.emit(cid)

    def set_caso_activo(self, cid):
        for k, t in self._tarjetas.items():
            t.setChecked(k == cid)
        if cid:
            for b in self._botones_serie.values():
                b.setChecked(False)

    # ------------------------------------------------------------------ estudio
    def _elegir_carpeta_dicom(self):
        ruta = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta completa del estudio DICOM",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if not ruta:
            return
        self.set_ruta(ruta)
        self.pedir_carga.emit(ruta)

    def _elegir_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar volumen", os.path.expanduser("~"),
            "Volúmenes (*.nii *.nii.gz *.dcm *.dicom *.ima);;Todos los archivos (*)")
        if not ruta:
            return
        self.set_ruta(ruta)
        self.pedir_carga.emit(ruta)

    def set_ruta(self, ruta):
        self._ruta.setText(ruta or "")
        self._ruta.setToolTip(ruta or "")
        self._actualizar_botones()

    def ruta(self):
        return self._ruta.text().strip()

    def generar_slices(self):
        return self._chk_slices.isChecked()

    def modo(self):
        """Modo de análisis elegido, o None si solo se quiere anatomía/vasos."""
        return self._cmb_modo.currentData()

    def limpiar_estudio(self):
        self.set_ruta("")
        self.set_series([], None)
        self.pedir_carga.emit("")

    def set_series(self, series, uid_activa=None):
        while self._lay_series.count():
            item = self._lay_series.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._botones_serie.clear()
        for s in series or []:
            b = _SerieButton(s.nombre)
            b.setToolTip(f"{s.nombre}\n{s.ruta}")
            b.clicked.connect(lambda _c, u=s.uid: self._elegir_serie(u))
            self._lay_series.addWidget(b)
            self._botones_serie[s.uid] = b
        self._host_series.setVisible(bool(self._botones_serie))
        if uid_activa is not None:
            self.set_serie_activa(uid_activa)

    def _elegir_serie(self, uid):
        self.set_serie_activa(uid)
        self.serie_elegida.emit(uid)

    def set_serie_activa(self, uid):
        for u, b in self._botones_serie.items():
            b.setChecked(u == uid)
        if uid is not None and uid in self._botones_serie:
            for t in self._tarjetas.values():
                t.setChecked(False)

    # ------------------------------------------------------------------ proceso
    def set_procesando(self, activo, hay_mallas=True):
        self._procesando = bool(activo)
        self._hay_mallas = bool(hay_mallas)
        self._actualizar_botones()

    def _actualizar_botones(self):
        proc = self._procesando
        hay_ruta = bool(self.ruta())
        self._btn_run.setEnabled(not proc and hay_ruta)
        self._btn_freesurfer.setEnabled(not proc and hay_ruta)
        self._btn_cta.setEnabled(not proc and hay_ruta)
        self._btn_cta_aprobar.setEnabled(not proc and hay_ruta)
        self._btn_fbx.setEnabled(not proc and self._hay_mallas)
        self._btn_cancel.setEnabled(proc)
        for t in self._tarjetas.values():
            t.setEnabled(not proc)
