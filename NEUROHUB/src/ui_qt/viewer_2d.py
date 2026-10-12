"""
Visor 2D interactivo de los cortes ortogonales, con delineado manual.

Que cambia respecto a la version anterior
-----------------------------------------
La version previa solo mostraba tres PNG ya generados: no habia forma de
corregir ni de completar una segmentacion automatica. Este visor carga el
volumen NIfTI, permite pintar y borrar tumor corte a corte, deshacer, y
guardar la mascara en la MISMA rejilla del volumen para que el pipeline la
convierta en malla 3D.

Decisiones de interfaz
----------------------
* Navegacion con rueda + Ctrl/Shift: la rueda sola hace zoom, como en cualquier
  visor de imagenes, y con Ctrl (o Shift) avanza de corte. Separar las dos
  acciones por modificador evita tener que adivinar cual de las dos se acaba
  de activar.
* El radio del pincel se expresa en VOXELES, no en pixeles de pantalla: el
  usuario elige un tamano anatomico y no uno que dependa del zoom.
* El arrastre izquierdo pinta. Para desplazar la imagen se usa la rueda o el
  espacio central; el raton izquierdo queda dedicado al delineado, que es la
  tarea principal de esta pantalla.
* Cuando no hay volumen cargado se siguen aceptando PNG (`set_cortes`), de
  modo que el visor sigue sirviendo como visor de PNG del pipeline.

Todo el calculo de imagen vive en `volumen_2d.Volumen2D`; este modulo solo
traduce eventos de raton y teclado a llamadas sobre ese objeto.
"""

import os

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QCursor,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
    QScrollArea, QFrame, QFileDialog, QSlider, QComboBox,
)

from .software_config import (
    COLOR_BG, COLOR_TEXTO, COLOR_TEXTO_SEC, COLOR_PANEL, COLOR_PANEL_ALT,
    COLOR_BORDE,
)

# Color del pincel: el MISMO verde del overlay. Si el cursor y la mascara
# tuvieran colores distintos, no se podria ver si lo que se esta pintando es
# exactamente lo que quedara guardado.
COLOR_PINCEL = "#00E66E"
COLOR_PINCEL_BORRADO = "#FF5C5C"

# Desplazamiento minimo (en pixeles de touchpad) que cuenta como UNA tiqueta de
# rueda. Por debajo se ignora, para que el temblor del dedo al hacer scroll no
# haga avanzar el corte de uno en uno.
UMBRAL_TIQUETA = 40

# Tope de cortes por evento de rueda. Un giro de rueda rapido trae `angleDelta`
# de +-240 o mas; sin tope se saltarian quince cortes de golpe y el usuario
# perderia el corte con el tumor. En Slicer pasa igual: el scroll es fino.
SALTOS_MAXIMOS_POR_RUEDA = 3


class Viewer2D(QWidget):
    """Cortes axial/coronal/sagital con overlay y pincel de delineado.

    Senales:
        corte_cambiado(str): el plano mostrado ha cambiado.
        mascara_modificada(): el usuario ha pintado, borrado o cargado algo.
        estado(str): accion pedida a la ventana ("generar_3d", ...).
        informacion(str): texto de estado para la barra inferior.
    """

    corte_cambiado = Signal(str)
    mascara_modificada = Signal()
    estado = Signal(str)
    informacion = Signal(str)

    EJES = [("axial", "Axial"), ("coronal", "Coronal"), ("sagital", "Sagital")]

    # Radios de pincel ofrecidos, en VOXELES (la unidad del dato).
    RADIOS_VOXEL = [1, 2, 3, 5, 8, 12]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volumen = None            # volumen_2d.Volumen2D o None
        self._eje_actual = "axial"
        self._indice = 0
        self._pixmap = QPixmap()
        self._png = {}                  # {eje: ruta} en modo visor-de-PNG
        self._paginators = {eje: _Lienzo(self, eje) for eje, _ in self.EJES}

        # Herramientas de delineado.
        self._herramienta = "navegar"   # navegar | pintar | borrar
        self._radio_voxel = 3
        self._pintando = False
        # Estado del trazo en curso. Se recuerda el ultimo voxel, el corte y
        # el eje para poder pintar SEGMENTOS entre dos `mouseMove` en vez de
        # puntos sueltos, y para no mezclar cortes si el eje cambia a mitad.
        self._ultimo_voxel = None
        self._indice_pintando = None
        self._eje_pintando = None
        self._delineado_con_lapiz = False
        self._overlay_visible = True
        self._bloqueando_slider = False

        self._construir_ui()

    # ------------------------------------------------------------------
    def _barra_herramientas(self):
        """Herramientas de delineado. Se ocultan si no hay volumen cargado."""
        self._barra_brush = QHBoxLayout()
        self._barra_brush.setSpacing(6)

        self._grp_brush = QButtonGroup(self)
        self._grp_brush.setExclusive(True)
        self._botones_brush = {}
        for clave, texto, tip, color in (
                ("navegar", "  Mano  ", "Zoom (Ctrl+rueda) y arrastre (botón derecho)", COLOR_TEXTO),
                ("pintar", "  Pincel  ", "Pintar tumor con el botón izquierdo  ·  B",
                 COLOR_PINCEL),
                ("borrar", "  Borrar  ", "Borrar tumor con el botón izquierdo  ·  E",
                 COLOR_PINCEL_BORRADO)):
            b = QPushButton(texto)
            b.setCheckable(True)
            b.setChecked(clave == "navegar")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._qss_boton(color, clave == "navegar"))
            b.clicked.connect(lambda _c, k=clave: self.set_herramienta(k))
            self._grp_brush.addButton(b)
            self._botones_brush[clave] = b
            self._barra_brush.addWidget(b)

        self._barra_brush.addSpacing(10)
        self._barra_brush.addWidget(QLabel("Pincel:"))
        self._cmb_radio = QComboBox()
        for r in self.RADIOS_VOXEL:
            self._cmb_radio.addItem(f"{r} vox", r)
        self._cmb_radio.setCurrentText("3 vox")
        self._cmb_radio.currentIndexChanged.connect(self._cambio_radio)
        self._cmb_radio.setToolTip(
            "Radio del pincel en voxels del volumen (no en pixeles de pantalla)")
        self._barra_brush.addWidget(self._cmb_radio)

        self._btn_undo = QPushButton("Deshacer")
        self._btn_undo.clicked.connect(self.deshacer)
        self._btn_undo.setToolTip("Revierte la ultima pintada (Ctrl+Z)")
        self._barra_brush.addWidget(self._btn_undo)

        self._btn_limpiar = QPushButton("Limpiar tumor")
        self._btn_limpiar.clicked.connect(self.limpiar)
        self._btn_limpiar.setToolTip(
            "Borra toda la mascara actual (se puede deshacer)")
        self._barra_brush.addWidget(self._btn_limpiar)

        self._barra_brush.addStretch(1)

        # Siempre activo: es la salida del modo visor-de-PNG, donde no hay
        # cortes por los que hacer scroll ni mascara que "Limpiar tumor" pueda
        # vaciar. Sin este boton esos dos controles quedan deshabilitados sin
        # explicacion visible.
        self._btn_cargar_volumen = QPushButton("Cargar volumen…")
        self._btn_cargar_volumen.setToolTip(
            "Abre una imagen NIfTI para navegar sus cortes y delinear el tumor")
        self._btn_cargar_volumen.clicked.connect(self.cargar_volumen)
        self._barra_brush.addWidget(self._btn_cargar_volumen)

        self._btn_cargar_mascara = QPushButton("Cargar máscara")
        self._btn_cargar_mascara.setToolTip(
            "Carga una mascara NIfTI delineada (debe compartir la rejilla)")
        self._btn_cargar_mascara.clicked.connect(self.cargar_mascara)
        self._barra_brush.addWidget(self._btn_cargar_mascara)

        self._btn_guardar_mascara = QPushButton("Guardar máscara")
        self._btn_guardar_mascara.setToolTip(
            "Guarda la mascara delineada como NIfTI en la rejilla del volumen")
        self._btn_guardar_mascara.clicked.connect(self.guardar_mascara)
        self._barra_brush.addWidget(self._btn_guardar_mascara)

        self._btn_3d = QPushButton("Segmentar y crear 3D")
        self._btn_3d.setToolTip(
            "Usa el contorno pintado como máscara, la guarda en la rejilla "
            "del estudio y crea el modelo 3D de alta calidad")
        self._btn_3d.clicked.connect(lambda: self.estado.emit("generar_3d"))
        self._barra_brush.addWidget(self._btn_3d)

        self._barra_brush_widget = QWidget()
        self._barra_brush_widget.setLayout(self._barra_brush)
        self._barra_brush_widget.setObjectName("barraDelineado")
        self._barra_brush_widget.setStyleSheet(
            f"#barraDelineado {{ background: {COLOR_PANEL}; border: 1px solid {COLOR_BORDE};"
            " border-radius: 10px; }")
        return self._barra_brush_widget

    @staticmethod
    def _qss_boton(color, activo):
        """QSS del boton de herramienta: el activo se marca con su color."""
        if activo:
            return (f"QPushButton {{ color: {color}; background: {COLOR_PANEL_ALT};"
                    f" border: 1px solid {color}; border-radius: 4px;"
                    " padding: 4px 12px; font-weight: bold; }"
                    f"QPushButton:hover {{ background: {COLOR_PANEL_ALT}; }}")
        return (f"QPushButton {{ color: {COLOR_TEXTO}; background: {COLOR_PANEL_ALT};"
                f" border: 1px solid {COLOR_BORDE}; border-radius: 4px;"
                " padding: 4px 12px; }"
                f"QPushButton:hover {{ border-color: {color}; }}")

    # ------------------------------------------------------------------
    def _barra_navegacion(self):
        """Deslizador de corte + etiqueta de estado."""
        barra = QHBoxLayout()
        barra.setSpacing(8)

        self._btn_prev = QPushButton("◀")
        self._btn_prev.setFixedWidth(34)
        self._btn_prev.setToolTip("Corte anterior")
        self._btn_prev.clicked.connect(lambda: self.avanzar(-1))
        barra.addWidget(self._btn_prev)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setToolTip(
            "Corte actual. Rueda: cambiar de corte  ·  Ctrl+rueda: zoom")
        self._slider.valueChanged.connect(self._desde_slider)
        barra.addWidget(self._slider, 1)

        self._btn_next = QPushButton("▶")
        self._btn_next.setFixedWidth(34)
        self._btn_next.setToolTip("Corte siguiente")
        self._btn_next.clicked.connect(lambda: self.avanzar(1))
        barra.addWidget(self._btn_next)

        self._lbl_corte = QLabel("-")
        self._lbl_corte.setMinimumWidth(190)
        self._lbl_corte.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 11px;")
        barra.addWidget(self._lbl_corte)
        return barra

    def _construir_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        lay.addLayout(self._barra_ejes())
        lay.addWidget(self._barra_herramientas())
        lay.addLayout(self._barra_navegacion())

        self._stack_host = QWidget()
        stack_lay = QVBoxLayout(self._stack_host)
        stack_lay.setContentsMargins(0, 0, 0, 0)
        stack_lay.setSpacing(0)
        for eje, _titulo in self.EJES:
            w = self._paginators[eje]
            w.hide()
            w.setStyleSheet(f"background: {COLOR_BG};")
            stack_lay.addWidget(w)
        lay.addWidget(self._stack_host, 1)

        self._vacio = QLabel(
            "Sin volumen para mostrar.\n\nCargue un estudio y ejecute el "
            "pipeline, o abra un caso con volumen NIfTI para delinear el "
            "tumor manualmente.")
        self._vacio.setAlignment(Qt.AlignCenter)
        self._vacio.setWordWrap(True)
        self._vacio.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 13px;")
        lay.addWidget(self._vacio, 1)

        self.set_eje("axial")

    # ------------------------------------------------------------------
    def _barra_ejes(self):
        """Selector de plano + informacion de la ventana activa."""
        barra = QHBoxLayout()
        barra.setSpacing(6)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        for i, (eje, titulo) in enumerate(self.EJES):
            b = QPushButton(titulo)
            b.setCheckable(True)
            b.setChecked(eje == "axial")
            b.clicked.connect(lambda _c, e=eje: self.set_eje(e))
            self._grupo.addButton(b, i)
            barra.addWidget(b)

        barra.addSpacing(12)
        self._btn_fit = QPushButton("Ajustar")
        self._btn_fit.setToolTip("Escala el corte para que quepa en la ventana")
        self._btn_fit.clicked.connect(self.ajustar)
        barra.addWidget(self._btn_fit)

        self._btn_overlay = QPushButton("Máscara")
        self._btn_overlay.setCheckable(True)
        self._btn_overlay.setChecked(True)
        self._btn_overlay.setToolTip("Mostrar u ocultar el relleno del tumor")
        # La conexion va AQUI, una sola vez. Estaba dentro de `set_volumen`,
        # que se llama en cada carga de estudio: cada vez se añadia una copia
        # mas y, tras cinco cambios de caso, un solo clic en "Máscara"
        # repintaba el corte cinco veces y el visor se notaba lento.
        self._btn_overlay.toggled.connect(self._cambio_overlay)
        barra.addWidget(self._btn_overlay)
        self._overlay_visible = True

        barra.addStretch(1)
        self._lbl_info = QLabel("")
        self._lbl_info.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        barra.addWidget(self._lbl_info)
        return barra

    # ==================================================================
    # CARGA DE DATOS
    # ==================================================================
    def set_volumen(self, volumen):
        """Adopta un `volumen_2d.Volumen2D` (o None para vaciar).

        Se llama cuando el pipeline termina, para que el visor 2D y el 3D
        miren EXACTAMENTE el mismo volumen y la misma mascara. Si el 2D se
        cargara por su cuenta con otro NIfTI, los dos visores podrian mostrar
        cosas distintas sin avisar.
        """
        self._volumen = volumen
        self._delineado_con_lapiz = False
        if volumen is None or volumen.vacio:
            self._indice = 0
            self._pixmap = QPixmap()
            self._actualizar_visibilidad()
            self._actualizar_navegacion()
            return False

        for eje, _t in self.EJES:
            self._paginators[eje].set_volumen(volumen, eje)
        self._indice = volumen.indice_mas_tumor(self._eje_actual)
        self.set_eje(self._eje_actual)
        return True

    def _cambio_overlay(self, visible):
        self._overlay_visible = bool(visible)
        self._refrescar()

    def set_cortes(self, cortes):
        """Modo visor-de-PNG: {eje: ruta}. Las rutas inexistentes se descartan.

        Es el camino que usa el pipeline cuando solo quiere mostrar los tres
        PNG ya generados. Si hay un volumen cargado, manda el volumen.
        """
        self._png = {}
        for eje, path in (cortes or {}).items():
            if eje in self._paginators and path and os.path.isfile(path):
                self._png[eje] = path
        self._refrescar()

    def cargar_volumen(self, parent=None):
        """Abre un selector y carga un NIfTI como volumen navegable.

        Sin esto, un caso en el que el pipeline no dejo copia de la imagen
        (o que solo trae los tres PNG de cortes) se queda en modo
        visor-de-PNG: se ve una imagen fija, la rueda no cambia de corte y
        "Limpiar tumor" esta DESACTIVADO, porque sin volumen no hay ni rejilla
        ni mascara que vaciar. El usuario lo ve como dos fallos distintos
        ("el scroll no responde" y "no me limpia el tumor") cuando en realidad
        falta la imagen.
        """
        inicio = os.path.dirname(self._volumen.volumen_path) \
            if (self._volumen is not None and self._volumen.volumen_path) else ""
        ruta, _ = QFileDialog.getOpenFileName(
            parent or self, "Cargar volumen del paciente", inicio,
            "Volúmenes (*.nii.gz *.nii);;Todos los archivos (*)")
        if not ruta:
            return None
        return self.cargar_volumen_desde(ruta)

    def cargar_volumen_desde(self, ruta, parent=None):
        """Carga `ruta` como volumen. Devuelve la ruta, o None si falla."""
        if not ruta or not os.path.isfile(ruta):
            self.informacion.emit("Ese fichero no existe.")
            return None
        from .. import volumen_2d as v2d
        try:
            volumen = v2d.Volumen2D(ruta)
        except Exception as e:
            self.informacion.emit(f"No se pudo cargar el volumen: {e}")
            return None
        if volumen.vacio:
            self.informacion.emit("El fichero no contiene una imagen legible.")
            return None
        self._png = {}
        self.set_volumen(volumen)
        self.informacion.emit(
            f"Volumen cargado: {os.path.basename(ruta)}  ·  "
            f"{volumen.n_cortes(self._eje_actual)} cortes  ·  "
            "Pinte el tumor y pulse «Segmentar y crear 3D»")
        return ruta

    def cargar_mascara(self, parent=None):
        """Abre un selector y carga la mascara elegida sobre el volumen actual."""
        if self._volumen is None or self._volumen.vacio:
            self.informacion.emit("Cargue primero un volumen.")
            return None
        inicio = os.path.dirname(self._volumen.volumen_path or "")
        ruta, _ = QFileDialog.getOpenFileName(
            parent or self, "Cargar máscara del tumor", inicio,
            "Máscaras (*.nii.gz *.nii);;Todos los archivos (*)")
        if not ruta:
            return None
        try:
            self._volumen.cargar_mascara(ruta)
        except Exception as e:
            self.informacion.emit(f"No se pudo cargar la máscara: {e}")
            return None
        self._refrescar()
        self.mascara_modificada.emit()
        self.informacion.emit(f"Máscara cargada: {os.path.basename(ruta)}")
        return ruta

    def guardar_mascara(self, parent=None):
        """Guarda la mascara en NIfTI. Devuelve la ruta, o None si se cancela.

        Es el paso que cierra el circuito: lo delineado en pantalla se escribe
        en la rejilla del volumen y a partir de ahi el pipeline puede generar
        la malla 3D.
        """
        if self._volumen is None or self._volumen.vacio:
            self.informacion.emit("No hay volumen cargado.")
            return None
        sugerido = os.path.join(
            os.path.dirname(self._volumen.volumen_path or ""),
            "tumor_manual.nii.gz")
        ruta, _ = QFileDialog.getSaveFileName(
            parent or self, "Guardar máscara del tumor", sugerido,
            "NIfTI (*.nii.gz)")
        if not ruta:
            return None
        try:
            self._volumen.guardar_mascara(ruta, formato="NIfTI")
        except Exception as e:
            self.informacion.emit(f"No se pudo guardar la máscara: {e}")
            return None
        self.mascara_modificada.emit()
        self.informacion.emit(
            f"Máscara guardada ({self._volumen.vóxeles_tumor():,} vóxeles)")
        return ruta

    # ==================================================================
    # HERRAMIENTAS
    # ==================================================================
    def set_herramienta(self, clave):
        """Fija la herramienta activa: navegar | pintar | borrar."""
        if clave not in ("navegar", "pintar", "borrar"):
            return
        self._herramienta = clave
        colores = {"navegar": COLOR_TEXTO, "pintar": COLOR_PINCEL,
                   "borrar": COLOR_PINCEL_BORRADO}
        for k, b in self._botones_brush.items():
            b.setStyleSheet(self._qss_boton(colores[k], k == clave))
        # El cursor refleja la herramienta: es la pista mas rapida de en que
        # modo se esta, sin tener que mirar los botones.
        for w in self._paginators.values():
            w.set_cursor_herramienta(clave)
        self.informacion.emit({
            "navegar": "Navegar: rueda = zoom, Ctrl+rueda = corte.",
            "pintar": "Pincel: arrastre para marcar tumor.",
            "borrar": "Borrar: arrastre para quitar tumor.",
        }[clave])

    def _cambio_radio(self, _index):
        self._radio_voxel = int(self._cmb_radio.currentData() or 3)
        for w in self._paginators.values():
            w.update()

    def _cambiar_radio(self, delta):
        """Cambia el radio al vecino de la lista (atajos [ ] o + -)."""
        radios = list(self.RADIOS_VOXEL)
        try:
            i = radios.index(self._radio_voxel)
        except ValueError:
            i = 2
        i = max(0, min(len(radios) - 1, i + int(delta)))
        self._cmb_radio.setCurrentIndex(i)

    def herramienta(self):
        return self._herramienta

    def deshacer(self):
        """Revierte la ultima pintada y redibuja."""
        if self._volumen is None or self._volumen.vacio:
            return False
        ok = self._volumen.deshacer()
        self._refrescar()
        self.mascara_modificada.emit()
        self.informacion.emit("Deshecho." if ok else "No hay nada que deshacer.")
        return ok

    def limpiar(self):
        """Vacia la mascara actual (se puede deshacer)."""
        if self._volumen is None or self._volumen.vacio:
            return False
        ok = self._volumen.limpiar_mascara()
        self._refrescar()
        if ok:
            self.mascara_modificada.emit()
        self.informacion.emit(
            "Máscara vaciada (se puede deshacer)." if ok
            else "La máscara ya estaba vacía.")
        return ok

    # ==================================================================
    # NAVEGACION Y RENDER
    # ==================================================================
    # Alto en pixeles del corte renderizado antes de aplicar el zoom de
    # pantalla. 1024 coincide con la resolucion del PNG exportado, asi que
    # delinear sobre lo que se ve y lo que se guarda usan el mismo detalle.
    _ALTO_RENDER = 1024

    def set_eje(self, eje):
        """Muestra el plano indicado y ajusta el deslizador a sus cortes."""
        if eje not in self._paginators:
            return
        self._eje_actual = eje
        for i, (e, _t) in enumerate(self.EJES):
            if e == eje and self._grupo.button(i) is not None:
                self._grupo.button(i).setChecked(True)
        if self._volumen is not None and not self._volumen.vacio:
            self._indice = self._acotar(self._indice,
                                        self._volumen.n_cortes(eje))
        self._refrescar()
        self.corte_cambiado.emit(eje)

    def _acotar(self, indice, total):
        return max(0, min(int(indice), max(0, total - 1)))

    def n_cortes(self):
        """Numero de cortes del eje actual (0 si no hay volumen)."""
        if self._volumen is None or self._volumen.vacio:
            return 0
        return self._volumen.n_cortes(self._eje_actual)

    def indice(self):
        return int(self._indice)

    def avanzar(self, delta):
        """Avanza `delta` cortes dentro del rango (no pasa de los extremos)."""
        total = self.n_cortes()
        if total <= 0:
            return
        self.set_indice(self._indice + delta)

    def set_indice(self, indice):
        """Fija el corte actual y redibuja."""
        total = self.n_cortes()
        if total <= 0:
            return
        nuevo = self._acotar(indice, total)
        if nuevo == self._indice:
            return
        self._indice = nuevo
        self._refrescar()
        self.corte_cambiado.emit(self._eje_actual)

    def corte_actual(self):
        """Corte con mas tumor del eje actual. Se usa el boton 'ir al tumor'."""
        if self._volumen is None or self._volumen.vacio:
            return 0
        return self._volumen.indice_mas_tumor(self._eje_actual)

    def ir_al_tumor(self):
        self.set_indice(self.corte_actual())

    def _desde_slider(self, valor):
        if self._bloqueando_slider:
            return
        self.set_indice(valor)

    def ajustar(self):
        """Reajusta el corte al tamano disponible (boton 'Ajustar')."""
        self._paginators[self._eje_actual].ajustar()
        self.corte_cambiado.emit(self._eje_actual)

    def _refrescar(self, ajustar=True, solo_imagen=False):
        """Redibuja el corte actual. `ajustar=False` conserva zoom y pan.

        Al pintar, recentrar el corte en cada muestra del raton hacia que el
        pincel "saltara" y el usuario perdiera el encuadre. El overlay se
        actualiza; la vista no.
        """
        if not solo_imagen:
            self._actualizar_visibilidad()
            self._actualizar_navegacion()
        w = self._paginators[self._eje_actual]
        if self._volumen is not None and not self._volumen.vacio:
            w.set_imagen(self._render_actual())
        elif self._eje_actual in self._png:
            w.set_pixmap(QPixmap(self._png[self._eje_actual]))
        else:
            w.set_pixmap(None)
        if ajustar:
            w.ajustar()

    def _render_actual(self):
        """Renderiza el corte actual con overlay y devuelve un QPixmap."""
        rgb, _info = self._volumen.render_corte(
            self._eje_actual, self._indice, alto=self._ALTO_RENDER,
            overlay=self._overlay_visible)
        h, w = rgb.shape[:2]
        # QImage no copia: hay que envolver el buffer para que siga vivo.
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        return QPixmap.fromImage(img.copy())

    def escala_voxel_por_eje(self, eje):
        """(kX, kY) pixeles de render por voxel, uno por direccion del corte.

        Delega en `Volumen2D.escala_voxeles`. Son dos numeros y no uno porque
        en coronal y sagital un voxel vertical ocupa 9.14 px y uno horizontal
        2.68 px; usar un unico factor descentraba el pincel en vertical.
        """
        if self._volumen is None or self._volumen.vacio:
            return 1.0, 1.0
        return self._volumen.escala_voxeles(eje, alto=self._ALTO_RENDER)

    def escala_px_por_voxel(self, eje):
        """Pixeles de render por voxel en ese eje (el menor de los dos).

        Se mantiene para el circulo del cursor, que es un radio unico. Para
        traducir coordenadas hay que usar `escala_voxel_por_eje`.
        """
        kx, ky = self.escala_voxel_por_eje(eje)
        return min(kx, ky)

    def _actualizar_visibilidad(self):
        """Muestra el panel vacio o el lienzo, segun haya datos."""
        hay_volumen = self._volumen is not None and not self._volumen.vacio
        hay_png = bool(self._png)
        self._stack_host.setVisible(hay_volumen or hay_png)
        self._vacio.setVisible(not (hay_volumen or hay_png))
        # Las herramientas de delineado solo tienen sentido con un volumen.
        # La barra se mantiene visible (para que el usuario sepa que existen)
        # pero sus controles se desactivan.
        self._cmb_radio.setEnabled(hay_volumen)
        for clave in ("pintar", "borrar"):
            self._botones_brush[clave].setEnabled(hay_volumen)
        self._btn_undo.setEnabled(hay_volumen)
        self._btn_limpiar.setEnabled(hay_volumen)
        self._btn_guardar_mascara.setEnabled(hay_volumen)
        self._btn_cargar_mascara.setEnabled(hay_volumen)
        self._btn_3d.setEnabled(
            hay_volumen
            and self._delineado_con_lapiz
            and self._volumen.vóxeles_tumor() > 0
        )
        for e, w in self._paginators.items():
            activo = hay_volumen or e in self._png
            w.setVisible(activo and e == self._eje_actual)

    def _actualizar_navegacion(self):
        """Sincroniza el deslizador, los botones y la etiqueta de estado."""
        total = self.n_cortes()
        hay = total > 0

        self._bloqueando_slider = True
        self._slider.setRange(0, max(0, total - 1))
        self._slider.setValue(self._acotar(self._indice, total))
        self._slider.setEnabled(hay)
        self._btn_prev.setEnabled(hay)
        self._btn_next.setEnabled(hay)
        self._btn_overlay.setEnabled(hay)
        self._bloqueando_slider = False

        if not hay:
            self._lbl_corte.setText("—")
            self._lbl_info.setText("")
            return

        v = self._volumen
        vox = v.vóxeles_tumor()
        self._lbl_corte.setText(
            f"Corte {self._indice + 1}/{total}   ·   "
            f"{vox:,} vox   ·   {v.volumen_cm3_tumor():.1f} cm³")
        self._lbl_info.setText(
            f"ventana {v.ventana()[0]:.0f}–{v.ventana()[1]:.0f}   ·   "
            f"{'máscara sin guardar' if v.mascara_modificada else 'máscara guardada'}")
        self.informacion.emit(self._lbl_corte.text())

    # ==================================================================
    # EVENTOS DE RATON Y TECLADO
    # ==================================================================
    def mouse_press(self, evento, widget):
        """Delegado por el lienzo. Empieza a pintar si la herramienta lo pide."""
        if self._herramienta == "navegar":
            return False
        p0 = widget.voxel_continuo(_pos_evento(evento), acoplar=True)
        if p0 is None:
            return False
        self._pintando = True
        self._ultimo_voxel = p0
        self._indice_pintando = self._indice
        self._eje_pintando = self._eje_actual
        if self._volumen is not None and not self._volumen.vacio:
            self._volumen.iniciar_trazo(self._eje_pintando, self._indice_pintando)
        self._pintar_punto(p0, widget)
        return True

    def mouse_move(self, evento, widget):
        """Delegado por el lienzo. Continua el trazo y el desplazamiento."""
        if self._pintando and self._herramienta != "navegar":
            p1 = widget.voxel_continuo(_pos_evento(evento), acoplar=True)
            if p1 is not None:
                # Si el corte o el eje han cambiado a mitad de trazo (no deberia
                # pasar, pero con Ctrl+rueda durante el arrastre sí), se cierra
                # el trazo anterior antes de seguir: mezclar dos cortes en la
                # misma mascara daria un tumor con forma de escalera.
                if (self._indice_pintando != self._indice
                        or self._eje_pintando != self._eje_actual):
                    if self._volumen is not None and not self._volumen.vacio:
                        self._volumen.cerrar_trazo()
                    self._pintando = False
                    self._ultimo_voxel = None
                    return True
                self._pintar_segmento(self._ultimo_voxel, p1, widget)
                self._ultimo_voxel = p1
            return True
        return False

    def mouse_release(self, _evento, _widget):
        """Delegado por el lienzo. Cierra el trazo."""
        if self._pintando:
            self._pintando = False
            self._ultimo_voxel = None
            self._indice_pintando = None
            self._eje_pintando = None
            if self._volumen is not None and not self._volumen.vacio:
                self._volumen.cerrar_trazo()
            self._actualizar_navegacion()
            return True
        return False

    def rueda(self, evento, widget):
        """Rueda = cambio de corte; con Ctrl o Shift = zoom.

        Es el reparto de 3D Slicer, y es el que espera el usuario: en un visor
        medico la rueda principal recorre los cortes, porque es la accion que
        se repite docenas de veces. El zoom, que se ajusta una vez y luego se
        deja, pasa a Ctrl (ademas de Shift, para quien venga de otros visores).

        Antes la rueda sola hacia zoom y el cambio de corte exigia Ctrl: en un
        visor de cortes eso es al reves, y el usuario reportaba que el scroll de
        profundidad "no respondia" (en realidad hacia zoom).
        """
        if evento.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return widget.zoom(evento)
        pasos = _pasos_de_rueda(evento)
        if pasos:
            self.avanzar(pasos)
            return True
        # Una rueda tactil puede llegar sin desplazamiento util: se ignora en
        # vez de dejar el corte donde estaba.
        return False

    def _pintar_punto(self, uv, widget):
        """Pinta un punto (un solo pincel) en la posicion de voxel dada."""
        self._pintar_segmento(uv, uv, widget)

    def _pintar_segmento(self, uv0, uv1, widget):
        """Pinta el segmento entre dos vóxeles, interpolando el hueco.

        El widget aporta el factor de pantalla por voxel en cada eje: hace
        falta para que el pincel siga siendo elipse con cualquier zoom, y no
        solo a la vista por defecto.
        """
        if self._volumen is None or self._volumen.vacio:
            return
        if uv0 is None or uv1 is None:
            return
        kx, ky = widget.escala_voxel_por_eje()
        valor = 0 if self._herramienta == "borrar" else 1
        n = self._volumen.pintar_tramo_2d(
            self._eje_pintando or self._eje_actual,
            self._indice_pintando if self._indice_pintando is not None
            else self._indice,
            uv0, uv1, kx, ky, radio=self._radio_voxel, valor=valor,
            registrar_historial=False)
        if n:
            self._delineado_con_lapiz = True
            self.mascara_modificada.emit()
        self._refrescar(ajustar=False, solo_imagen=True)

    def keyPressEvent(self, event):
        """Atajos de teclado del visor."""
        tecla = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)

        if tecla in (Qt.Key_Left, Qt.Key_Down):
            self.avanzar(-1)
        elif tecla in (Qt.Key_Right, Qt.Key_Up):
            self.avanzar(1)
        elif tecla == Qt.Key_Home:
            self.set_indice(0)
        elif tecla == Qt.Key_End:
            self.set_indice(self.n_cortes() - 1)
        elif tecla == Qt.Key_PageUp:
            self.avanzar(10)
        elif tecla == Qt.Key_PageDown:
            self.avanzar(-10)
        elif tecla == Qt.Key_T:
            self.ir_al_tumor()
        elif ctrl and tecla == Qt.Key_Z:
            self.deshacer()
        elif ctrl and tecla == Qt.Key_S:
            self.guardar_mascara(self)
        elif tecla == Qt.Key_B:
            self.set_herramienta("pintar")
        elif tecla == Qt.Key_E:
            self.set_herramienta("borrar")
        elif tecla in (Qt.Key_BracketLeft, Qt.Key_Minus):
            self._cambiar_radio(-1)
        elif tecla in (Qt.Key_BracketRight, Qt.Key_Plus, Qt.Key_Equal):
            self._cambiar_radio(1)
        elif tecla == Qt.Key_Escape:
            self.set_herramienta("navegar")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def wheelEvent(self, event):
        """Rueda sobre las barras: mismo reparto que sobre el lienzo."""
        if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return self._zoom_actual(event)
        pasos = _pasos_de_rueda(event)
        if pasos:
            self.avanzar(pasos)
            event.accept()
            return
        event.ignore()

    def _zoom_actual(self, event):
        """Zoom del lienzo visible, para la rueda sobre las barras."""
        w = self._paginators.get(self._eje_actual)
        if w is not None and w.zoom(event):
            event.accept()
            return
        event.ignore()

    # ==================================================================
    # API PUBLICA QUE USA LA VENTANA PRINCIPAL
    # ==================================================================
    def volumen(self):
        return self._volumen

    def eje_actual(self):
        return self._eje_actual

    def tiene_cortes(self):
        return (self._volumen is not None and not self._volumen.vacio) \
            or bool(self._png)

    def pixmap(self):
        """Pixmap del corte visible (para 'Guardar corte')."""
        return self._paginators[self._eje_actual].pixmap()

    def guardar_corte(self, parent=None):
        """Exporta el corte visible a PNG. Devuelve la ruta, o None si se cancela."""
        w = self._paginators.get(self._eje_actual)
        if w is None or w.pixmap().isNull():
            return None
        destino = os.path.join(os.path.expanduser("~"),
                               f"neurohub_{self._eje_actual}_"
                               f"{self._indice + 1:04d}.png")
        if parent is not None:
            destino, _ = QFileDialog.getSaveFileName(
                parent, "Guardar corte", destino, "PNG (*.png)")
            if not destino:
                return None
        return destino if w.pixmap().save(destino) else None


# =============================================================================
# LIENZO DE UN CORTE
# =============================================================================
class _Lienzo(QWidget):
    """Dibuja el pixmap del corte y traduce pantalla <-> voxel.

    El mapeo es la parte critica: si el puntero no esta exactamente sobre la
    imagen, `pintar` no debe escribir nada, y si el mapeo estuviera
    desplazado, el tumor se dibujaria en un sitio distinto del que el
    usuario ve. Por eso todo pasa por `_base` (la esquina real de la imagen
    dentro del widget) y no por supuestos sobre la escala.
    """

    def __init__(self, visor, eje, parent=None):
        super().__init__(parent)
        self._visor = visor
        self._eje = eje
        self._pixmap = QPixmap()
        self._escala = 1.0
        self._base = (0.0, 0.0)          # esquina del pixmap dentro del widget
        self._arrastrando = False
        self._origen = None
        self.setMouseTracking(True)
        self.setMinimumSize(240, 240)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background: transparent;")
        self.setToolTip(
            "Rueda: zoom  ·  Ctrl+rueda: corte  ·  B: pincel  ·  E: borrar"
            "  ·  T: ir al tumor  ·  Ctrl+Z: deshacer")

    # ------------------------------------------------------------------
    def set_volumen(self, volumen, eje):
        """Fija el volumen y el eje de este lienzo."""
        self._eje = eje

    def set_cursor_herramienta(self, herramienta):
        """Cursor segun la herramienta: pincel, borrador o mano."""
        if herramienta == "pintar":
            self.setCursor(_cursor_pinzel())
        elif herramienta == "borrar":
            self.setCursor(_cursor_borrador())
        else:
            self.setCursor(Qt.OpenHandCursor)

    def set_pixmap(self, pm):
        self._pixmap = pm if pm is not None else QPixmap()
        self.update()

    def set_imagen(self, pm):
        self.set_pixmap(pm)

    def pixmap(self):
        return self._pixmap

    # ------------------------------------------------------------------
    def ajustar(self):
        """Escala la imagen para que quepa en el widget visible."""
        if self._pixmap.isNull():
            return
        esc = min(self.width() / max(1, self._pixmap.width()),
                  self.height() / max(1, self._pixmap.height()), 1.0)
        self._escala = max(esc, 0.02)
        self._recalcular_base()
        self.update()

    def zoom(self, evento):
        """Zoom centrado en el cursor. True si el evento se ha consumido."""
        if self._pixmap.isNull():
            return False
        delta = evento.angleDelta().y()
        if delta == 0:
            # Los portatiles con touchpad mandan `pixelDelta` y pueden dejar
            # `angleDelta` a 0: sin esto, Ctrl+rueda no hacia nada en un equipo
            # con pantalla tactil.
            if evento.hasPixelDelta() and evento.pixelDelta().y() != 0:
                delta = evento.pixelDelta().y()
            else:
                return False
        self._escala = min(max(self._escala * (1.15 if delta > 0 else 1 / 1.15),
                               0.05), 16.0)
        self._recalcular_base()
        self.update()
        return True

    def _recalcular_base(self):
        """Recentra el pixmap y guarda su esquina en coordenadas del widget."""
        w = int(self._pixmap.width() * self._escala) or 1
        h = int(self._pixmap.height() * self._escala) or 1
        self._base = ((self.width() - w) / 2.0, (self.height() - h) / 2.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ajustar()

    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        """Pinta el corte y, si toca, el circulo del pincel."""
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window())

        if self._pixmap.isNull():
            p.end()
            return

        w = int(self._pixmap.width() * self._escala) or 1
        h = int(self._pixmap.height() * self._escala) or 1
        x, y = int(self._base[0]), int(self._base[1])
        p.drawPixmap(x, y, self._pixmap.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        herramienta = self._visor.herramienta()
        if herramienta in ("pintar", "borrar"):
            # La previsualizacion refleja el TAMAÑO REAL del pincel. Como el
            # corte se renderiza con aspecto fisico corregido, un circulo de
            # N vóxeles no se ve circular en coronal/sagital, y el pincel
            # eliptico marca justo una elipse en vóxeles. Se dibuja la misma
            # elipse que se pinta, no un circulo descreen, para no prometer una
            # forma que luego no se cumple.
            pos = self.mapFromGlobal(QCursor.pos())
            rx, ry = self._radios_pixeles()
            color = (COLOR_PINCEL if herramienta == "pintar"
                     else COLOR_PINCEL_BORRADO)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QBrush(_qcolor(color)), 1.5, Qt.SolidLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(pos), rx, ry)
        p.end()

    def _radios_pixeles(self):
        """(rx, ry) del pincel en pixeles de pantalla, ya con el zoom aplicado.

        El radio se elige en VOXELES y aqui se convierte a pixeles. La
        asimetria importa: se multiplica cada eje por SU factor (kx para
        horizontal, ky para vertical) y ademas por el zoom del widget, que es
        lo que hace que "pincel de 3 voxels" marque 3 voxels con cualquier
        nivel de zoom en vez de 3 pixeles.
        """
        kx, ky = self._visor.escala_voxel_por_eje(self._eje)
        radio = self._visor._radio_voxel
        return (max(2.0, radio * kx * self._escala),
                max(2.0, radio * ky * self._escala))

    def _radio_pixeles(self):
        """Radio mayor del pincel, para el cursor del sistema."""
        rx, ry = self._radios_pixeles()
        return max(rx, ry)

    # ------------------------------------------------------------------
    def escala_voxel_por_eje(self):
        """(kX, kY) pixeles de pantalla por voxel, con el zoom ya aplicado.

        Son los factores que el visor necesita para dibujar el pincel con su
        forma real. Se aplican aqui y no en el visor porque el visor solo sabe
        del render, mientras que el tamano en pantalla depende del zoom, que
        es estado del widget.
        """
        kx, ky = self._visor.escala_voxel_por_eje(self._eje)
        return kx * self._escala, ky * self._escala

    def coordenada_voxel(self, pos):
        """(x, y) en voxeles del corte, o None si `pos` cae fuera de la imagen."""
        uv = self.voxel_continuo(pos)
        return None if uv is None else (int(round(uv[0])), int(round(uv[1])))

    def voxel_continuo(self, pos, acoplar=False):
        """(x, y) en voxeles SIN redondear, o None fuera de la imagen.

        Ojo con las unidades, que es donde se escondia el desplazamiento:
        el pixmap tiene `kX`/`kY` pixeles por voxel (no un factor unico: en
        coronal valen 2.68 en horizontal y 9.14 en vertical), de modo que cada
        coordenada se divide por SU factor. Dividirlas todas por el menor
        hacía que la vertical acabara 3.4 veces mas abajo de donde se veia y
        a veces fuera del volumen, donde ya no se pintaba nada.

        Sin redondear a proposito: al pintar un trazo largo, redondear en cada
        pixel dejaria huecos entre dos puntos consecutivos cuando el raton se
        mueve mas rapido que el refresco de la pantalla.

        `acoplar=True` recorta al borde del corte (durante un arrastre) para
        que el pincel no se apague al rozar el margen.
        """
        if self._pixmap.isNull() or self._pixmap.width() == 0:
            return None
        px = self._pixmap.width() * self._escala
        py = self._pixmap.height() * self._escala
        if px <= 0 or py <= 0:
            return None
        u = (pos.x() - self._base[0]) / px
        v = (pos.y() - self._base[1]) / py
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            if not acoplar:
                return None
            u = min(max(u, 0.0), 1.0)
            v = min(max(v, 0.0), 1.0)
        kx, ky = self._visor.escala_voxel_por_eje(self._eje)
        return (u * self._pixmap.width() / max(kx, 1e-6),
                v * self._pixmap.height() / max(ky, 1e-6))

    # ------------------------------------------------------------------
    # EVENTOS
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        """Derecho y central desplazan; izquierdo delega en el visor."""
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._arrastrando = True
            pos = _pos_evento(event)
            self._origen = QPointF(pos.x(), pos.y())
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._visor.mouse_press(event, self):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Desplaza si se arrastra; si no, delega el trazo del pincel."""
        if self._arrastrando and self._origen is not None:
            pos = _pos_evento(event)
            p = QPointF(pos.x(), pos.y())
            d = p - self._origen
            self._origen = p
            self._base = (self._base[0] + d.x(), self._base[1] + d.y())
            self.update()
            event.accept()
            return
        if self._visor.mouse_move(event, self):
            event.accept()
            return
        if self._visor.herramienta() in ("pintar", "borrar"):
            self.update()      # sigue al circulo del pincel
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._arrastrando:
            self._arrastrando = False
            self._origen = None
            self._visor.set_cursor_herramienta(self._visor.herramienta())
            event.accept()
            return
        if self._visor.mouse_release(event, self):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._visor.rueda(event, self):
            event.accept()
            return
        event.ignore()


def _pasos_de_rueda(evento):
    """Cuantos cortes recorre la rueda: +1 hacia abajo, -1 hacia arriba.

    Se normalizan las tres formas en que llega el desplazamiento:

    * `angleDelta`: el raton de rueda, en octavos de grado (normalmente +-120).
    * `pixelDelta`: el touchpad, en pixeles. Puede traer valores pequenos como
      15 o 40; si se usara tal cual, un solo gesto saltaria veinte cortes.
    * `inverted`: el Natural Scrolling de Windows/macOS ya invierte el signo y
      avisa con `evento.inverted()`. Si tambien se invirtiera aqui, la rueda
      bajaria al subir y el usuario lo percibe como que "no responde".

    Devuelve 0 si no hay desplazamiento reconocible.
    """
    ang = evento.angleDelta().y()
    pix = evento.pixelDelta().y() if evento.hasPixelDelta() else 0

    # El touchpad manda pixeles; el raton, grados. Se elige la magnitud mayor
    # y se normaliza a "tiquetas" con `UMBRAL_TIQUETA`.
    if abs(ang) >= 8 and (abs(ang) > abs(pix) or pix == 0):
        magnitud = abs(ang) / 120.0
    elif pix != 0:
        magnitud = abs(pix) / UMBRAL_TIQUETA
    else:
        return 0

    pasos = int(round(magnitud))
    if pasos <= 0:
        return 0
    pasos = min(pasos, SALTOS_MAXIMOS_POR_RUEDA)
    return -pasos if (ang < 0 or pix < 0) else pasos


def _pos_evento(evento):
    """Posicion del puntero en coordenadas del widget (subpixel si existe)."""
    if hasattr(evento, "position"):
        try:
            return evento.position()
        except Exception:
            pass
    return evento.pos()


def _qcolor(hex_color):
    """QColor a partir de un '#RRGGBB' de `software_config`."""
    return QColor(hex_color)


def _cursor_pinzel():
    """Cursor de cruz con circulo: previsualiza el area que se va a pintar."""
    d = 32
    pm = QPixmap(d, d)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QBrush(QColor(COLOR_PINCEL)), 1))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(1, 1, d - 3, d - 3))
    p.drawLine(d // 2, 0, d // 2, d)
    p.drawLine(0, d // 2, d, d // 2)
    p.end()
    return QCursor(pm, d // 2, d // 2)


def _cursor_borrador():
    """Cursor de tachado rojo: distingue borrar de pintar sin leer los botones."""
    d = 32
    pm = QPixmap(d, d)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QPen(QBrush(QColor(COLOR_PINCEL_BORRADO)), 2))
    p.drawLine(6, 26, 26, 6)
    p.drawEllipse(QRectF(2, 2, d - 5, d - 5))
    p.end()
    return QCursor(pm, d // 2, d // 2)