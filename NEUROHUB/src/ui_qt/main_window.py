"""
Ventana principal de ATLAS (PySide6).

    casos y estudio  ->  capas 3D  ->  visor 3D / cortes 2D  ->  registro

La ventana no ejecuta nada del pipeline en el hilo de la interfaz: los
procesos largos viven en `PipelineWorker`, `FbxExportWorker`, etc., cada uno en
su `QThread`, y solo se comunican por señales.

Al arrancar se abre el primer caso ATLAS (`salidas/modelos_ar_freesurfer`),
cuyas mallas y volúmenes comparten sistema de coordenadas. La carpeta global
`salidas/mallas` mezclaba mallas de pacientes distintos y ya no se muestra
por defecto.
"""

import os

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFileDialog, QMessageBox, QStatusBar, QSplitter, QFrame,
)

from .software_config import (
    APP_INSTITUCION, APP_TITULO_VENTANA, COLOR_ACENTO, COLOR_BG, COLOR_BORDE_SUAVE,
    COLOR_ERROR, COLOR_OK, COLOR_PANEL, COLOR_TEXTO, COLOR_TEXTO_SEC,
    COLOR_TEXTO_TENUE, COLOR_WARN,
)
from .widgets import (BarraEstadoProceso, Card, Chip, LogConsole, LogoAtlas,
                      Separador, icono_aplicacion)
from .panels import COLOR_LESION, LayersPanel, StudyPanel
from .viewer_2d import Viewer2D
from .viewer_3d import Viewer3D
from .study_model import Serie, StudyModel
from .pipeline_bridge import (
    PipelineWorker, ClinicalCTAWorker, FreeSurferWorker, FbxExportWorker,
    MeshFromMaskWorker,
)
from . import casos_atlas
from . import mesh_store
from . import pbr
from ..hardware_backend import describe_backends


class _EstadoProceso:
    """Adaptador: el código de procesos llama `card_estado.set_value(...)`;
    el estado se muestra en el indicador compacto de la cabecera."""

    def __init__(self, barra):
        self._barra = barra

    def set_value(self, valor, color=None, detalle=None):
        estado = {COLOR_OK: "ok", COLOR_WARN: "aviso", COLOR_ERROR: "error"}.get(
            color, "activo")
        self._barra.set_status(valor, estado)

    def setToolTip(self, texto):
        self._barra.setToolTip(texto)


class MainWindow(QMainWindow):
    """Ventana principal: coordina paneles, visores, workers y registro."""

    def __init__(self, parent=None, cargar_inicial=True):
        super().__init__(parent)
        self.setWindowTitle(APP_TITULO_VENTANA)
        self.setWindowIcon(icono_aplicacion())
        self.resize(1680, 1000)
        self.setMinimumSize(1280, 780)

        self.modelo = StudyModel()
        self.casos = []
        self.caso_activo = None
        self._thread = None
        self._worker = None
        self._worker_cancelado = False
        self._malla_pendiente = None

        self._construir_ui()
        self._conectar()
        if cargar_inicial:
            self._cargar_inicio()

    # ==================================================================
    # CONSTRUCCIÓN
    # ==================================================================
    def _construir_ui(self):
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"#central {{ background-color: {COLOR_BG}; }}")
        self.setCentralWidget(central)
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._construir_cabecera())

        self.panel_estudio = StudyPanel()
        self.panel_capas = LayersPanel()
        for panel in (self.panel_estudio, self.panel_capas):
            panel.setObjectName("panelLateral")
            panel.setStyleSheet(
                f"#panelLateral {{ background: {COLOR_PANEL};"
                f" border-right: 1px solid {COLOR_BORDE_SUAVE}; }}")
        self.panel_estudio.setMinimumWidth(270)
        self.panel_capas.setMinimumWidth(260)

        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)
        self.visor_3d = Viewer3D()
        self.visor_2d = Viewer2D()
        self.pestanas.addTab(self.visor_3d, "Modelo 3D")
        self.pestanas.addTab(self.visor_2d, "Cortes 2D")
        contenedor_tabs = QWidget()
        contenedor_tabs.setObjectName("contenedorVisores")
        contenedor_tabs.setStyleSheet(f"#contenedorVisores {{ background: {COLOR_PANEL}; }}")
        ct = QVBoxLayout(contenedor_tabs)
        ct.setContentsMargins(0, 0, 0, 0)
        ct.addWidget(self.pestanas)

        self._split_h = QSplitter(Qt.Horizontal)
        self._split_h.setChildrenCollapsible(False)
        self._split_h.addWidget(self.panel_estudio)
        self._split_h.addWidget(self.panel_capas)
        self._split_h.addWidget(contenedor_tabs)
        self._split_h.setStretchFactor(2, 1)
        self._split_h.setSizes([300, 290, 1090])

        self._split_v = QSplitter(Qt.Vertical)
        self._split_v.setChildrenCollapsible(True)
        self._split_v.addWidget(self._split_h)
        self._split_v.addWidget(self._construir_registro())
        self._split_v.setStretchFactor(0, 1)
        self._split_v.setSizes([860, 120])
        raiz.addWidget(self._split_v, 1)

        barra = QStatusBar()
        self.setStatusBar(barra)
        self._lbl_institucion = QLabel(APP_INSTITUCION)
        self._lbl_institucion.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; padding-right: 8px;")
        barra.addPermanentWidget(self._lbl_institucion)
        barra.showMessage("Listo")

    def _construir_cabecera(self):
        """Marca, caso activo, métricas, estado del proceso y acciones."""
        self._header = QWidget()
        self._header.setObjectName("cabecera")
        self._header.setFixedHeight(64)
        self._header.setStyleSheet(
            f"#cabecera {{ background-color: {COLOR_PANEL};"
            f" border-bottom: 1px solid {COLOR_BORDE_SUAVE}; }}")
        lay = QHBoxLayout(self._header)
        lay.setContentsMargins(18, 10, 14, 10)
        lay.setSpacing(16)

        lay.addWidget(LogoAtlas())
        lay.addWidget(Separador(vertical=True))

        caja = QVBoxLayout()
        caja.setSpacing(2)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self._titulo_caso = QLabel("Sin caso")
        self._titulo_caso.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 14px; font-weight: 600;")
        self._chip_lesion = Chip("")
        self._chip_lesion.hide()
        fila.addWidget(self._titulo_caso)
        fila.addWidget(self._chip_lesion)
        fila.addStretch(1)
        self._subtitulo = QLabel("Elija un caso para comenzar")
        self._subtitulo.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        caja.addLayout(fila)
        caja.addWidget(self._subtitulo)
        lay.addLayout(caja, 1)

        self.card_estructuras = Card("Estructuras", "0")
        self.card_visibles = Card("Visibles", "0")
        self.card_triangulos = Card("Triángulos", "—")
        self.card_backend = Card("Inferencia", "—")
        for c in (self.card_estructuras, self.card_visibles, self.card_triangulos,
                  self.card_backend):
            c.setFixedWidth(104)
            lay.addWidget(c)
        self._actualizar_backend()

        lay.addWidget(Separador(vertical=True))
        self.barra_progreso = BarraEstadoProceso()
        self.barra_progreso.setToolTip("Estado del proceso en curso")
        lay.addWidget(self.barra_progreso)
        self.card_estado = _EstadoProceso(self.barra_progreso)

        self._btn_snapshot = QPushButton("Captura 3D")
        self._btn_snapshot.setObjectName("headerAction")
        self._btn_snapshot.setToolTip("Exportar la vista 3D actual a PNG (doble resolución)")
        lay.addWidget(self._btn_snapshot)
        self._btn_guardar_2d = QPushButton("Exportar corte")
        self._btn_guardar_2d.setObjectName("headerAction")
        self._btn_guardar_2d.setToolTip("Exportar el corte 2D visible a PNG")
        lay.addWidget(self._btn_guardar_2d)
        return self._header

    def _construir_registro(self):
        """Registro de actividad, plegable desde el separador."""
        cont = QFrame()
        cont.setObjectName("registro")
        cont.setStyleSheet(f"#registro {{ background: {COLOR_BG};"
                           f" border-top: 1px solid {COLOR_BORDE_SUAVE}; }}")
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        cab = QWidget()
        cab.setObjectName("registroCabecera")
        cab.setStyleSheet(f"#registroCabecera {{ background: {COLOR_PANEL}; }}")
        cl = QHBoxLayout(cab)
        cl.setContentsMargins(14, 3, 8, 3)
        t = QLabel("REGISTRO")
        t.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 10px; font-weight: 700;"
                        " letter-spacing: 1.2px;")
        cl.addWidget(t)
        self._lbl_ultimo = QLabel("")
        self._lbl_ultimo.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        cl.addWidget(self._lbl_ultimo, 1)
        b_limpiar = QPushButton("Limpiar")
        b_limpiar.setObjectName("fantasma")
        cl.addWidget(b_limpiar)
        self._btn_plegar = QPushButton("Ocultar")
        self._btn_plegar.setObjectName("fantasma")
        self._btn_plegar.clicked.connect(self._alternar_registro)
        cl.addWidget(self._btn_plegar)
        lay.addWidget(cab)
        self.consola = LogConsole()
        lay.addWidget(self.consola, 1)
        b_limpiar.clicked.connect(self.consola.limpiar)
        self.consola.nuevo_mensaje.connect(
            lambda m, n: self._lbl_ultimo.setText(m if n != "INFO" else ""))
        return cont

    def _alternar_registro(self):
        alto = self._split_v.sizes()
        visible = self.consola.isVisible()
        self.consola.setVisible(not visible)
        self._btn_plegar.setText("Mostrar" if visible else "Ocultar")
        if visible:
            self._split_v.setSizes([sum(alto) - 30, 30])
        else:
            self._split_v.setSizes([sum(alto) - 130, 130])

    def _actualizar_backend(self):
        try:
            texto = describe_backends()
        except Exception as exc:
            self.card_backend.set_value("Error", COLOR_WARN, f"No se pudo detectar: {exc}")
            return
        amd = "amd-directml=sí" in texto
        self.card_backend.set_value("GPU AMD" if amd else "CPU",
                                    COLOR_OK if amd else COLOR_WARN, texto)

    # ==================================================================
    # CONEXIONES
    # ==================================================================
    def _conectar(self):
        self.panel_estudio.caso_elegido.connect(self.cargar_caso)
        self.panel_estudio.pedir_carga.connect(self.cargar_estudio)
        self.panel_estudio.serie_elegida.connect(self._cambiar_serie)
        self.panel_estudio.ejecutar.connect(self._accion)
        self.panel_capas.visibilidad_cambiada.connect(self._aplicar_visibilidad)
        self.panel_capas.opacidad_cambiada.connect(self.visor_3d.set_opacidad)
        self.visor_3d.modelo_seleccionado.connect(self._estructura_pulsada)
        self.visor_2d.informacion.connect(self.statusBar().showMessage)
        self.visor_2d.estado.connect(self._accion_2d)
        self._btn_snapshot.clicked.connect(self.guardar_imagen_3d)
        self._btn_guardar_2d.clicked.connect(self.guardar_corte_2d)

    # ==================================================================
    # CASOS ATLAS
    # ==================================================================
    def _cargar_inicio(self):
        """Abre el primer caso ATLAS; sin casos, las salidas del pipeline."""
        self.casos = casos_atlas.listar_casos()
        self.panel_estudio.set_casos(self.casos)
        if self.casos:
            self.consola.log(f"{len(self.casos)} casos ATLAS en {casos_atlas.CASOS_DIR}",
                             "INFO")
            self.cargar_caso(self.casos[0]["id"])
        else:
            self._cargar_salidas_existentes()

    def cargar_caso(self, caso_id):
        """Muestra un caso ATLAS: mallas 3D, cortes 2D y datos de cabecera."""
        caso = next((c for c in self.casos if c["id"] == caso_id), None)
        if caso is None:
            return False
        self.caso_activo = caso
        self.modelo.serie_activa = None
        self.panel_estudio.set_caso_activo(caso_id)
        self.panel_estudio.set_procesando(False, hay_mallas=True)

        modelos = caso["modelos"]
        self.panel_capas.set_modelos(modelos, set(modelos))
        self.visor_3d.set_models_dir(os.path.join(caso["carpeta"], "stl"))
        self.visor_3d.set_models(modelos)

        self._titulo_caso.setText(caso["titulo"])
        lesion = caso.get("lesion")
        if lesion:
            self._chip_lesion.setText(lesion.capitalize())
            self._chip_lesion.set_color(COLOR_LESION.get(lesion, COLOR_ACENTO))
            self._chip_lesion.show()
        else:
            self._chip_lesion.hide()
        partes = [caso.get("subtitulo", "")]
        if caso.get("segmentacion"):
            partes.append(caso["segmentacion"].split(" --")[0])
        self._subtitulo.setText("  ·  ".join(p for p in partes if p))
        self._subtitulo.setToolTip(caso.get("segmentacion_lesion") or "")

        self._cargar_volumen_caso(caso)
        self._actualizar_tarjetas()
        self.consola.log(f"Caso {caso['titulo']}: {len(modelos)} estructuras", "SUCCESS")
        return True

    def _cargar_volumen_caso(self, caso):
        """Imagen, anatomía y lesión del caso en el visor 2D."""
        from .. import volumen_2d as v2d

        datos = caso.get("visor2d")
        if not datos:
            self.visor_2d.set_volumen(None)
            self.visor_2d.set_titulo("")
            self.consola.log("Este caso no tiene volúmenes 2D preparados "
                             "(herramientas/ar_visor2d.py)", "WARNING")
            return False
        try:
            vol = v2d.Volumen2D(datos["imagen"], datos.get("lesion"))
            info = datos.get("info") or {}
            if info.get("modalidad"):
                vol.modalidad = info["modalidad"]
                vol.calcular_window()
            if datos.get("anatomia"):
                vol.cargar_etiquetas(datos["anatomia"])
            if caso.get("lesion") == "aneurisma":
                vol.color_lesion = (255, 217, 26)
            self.visor_2d.set_volumen(vol)
            self.visor_2d.set_titulo(
                f"{caso['titulo']}  ·  {info.get('imagen', os.path.basename(datos['imagen']))}")
            return True
        except Exception as e:
            self.visor_2d.set_volumen(None)
            self.consola.log(f"No se pudo cargar el volumen 2D: {e}", "ERROR")
            return False

    # ==================================================================
    # ESTUDIOS PROPIOS Y SERIES
    # ==================================================================
    def _cargar_salidas_existentes(self):
        """Sin casos ATLAS: muestra lo que haya dejado el pipeline clásico."""
        modelos = mesh_store.escanear_mallas()
        cortes = mesh_store.listar_cortes()
        volumen_existente = mesh_store.buscar_volumen(
            mesh_store.SALIDAS_DIR, mesh_store.SALIDAS_DIR)
        if not modelos and not cortes and not volumen_existente:
            self.consola.log("Cargue un estudio para comenzar", "INFO")
            self.panel_estudio.set_procesando(False, hay_mallas=False)
            self._actualizar_tarjetas()
            return
        nombre = "Salidas del pipeline"
        serie = Serie(uid="salidas", nombre=nombre,
                      ruta=os.path.join(mesh_store.RAIZ_DIR, "salidas"))
        for key, meta in modelos.items():
            serie.add_capa(key, meta["label"], meta["display"], meta["stl"])
        self.modelo.limpiar()
        self.modelo.add_serie(serie)
        self.panel_estudio.set_series(self.modelo.series, serie.uid)
        self.panel_estudio.set_procesando(False, hay_mallas=bool(modelos))
        self.modelo.slices_2d = cortes
        self._cargar_volumen_2d(serie.ruta)
        self._poblar_capas()

    def _cargar_volumen_2d(self, ruta_base):
        """Carga el volumen NIfTI del estudio propio en el visor 2D."""
        from .. import volumen_2d as v2d

        try:
            volumen_path = mesh_store.buscar_volumen(ruta_base, mesh_store.SALIDAS_DIR)
            if not volumen_path:
                self.visor_2d.set_volumen(None)
                self.consola.log(
                    "Sin volumen NIfTI: el visor 2D muestra solo los cortes PNG",
                    "WARNING")
                return False
            rutas = mesh_store.rutas_serie(ruta_base if ruta_base else None)
            candidatas = mesh_store.listar_mascaras_tumor(rutas["segmentaciones"])
            mascara = mesh_store.buscar_mascara_compatible(candidatas, volumen_path)
            if candidatas and not mascara:
                self.consola.log(
                    "Ninguna máscara encaja con la rejilla del volumen: se carga "
                    "la imagen sin máscara para delinearla a mano", "WARNING")
            volumen_2d = v2d.Volumen2D(volumen_path, mascara)
            self.visor_2d.set_volumen(volumen_2d)
            self.visor_2d.set_titulo(os.path.basename(volumen_path))
            self.consola.log(
                f"Visor 2D: {os.path.basename(volumen_path)}"
                + (f" + {os.path.basename(mascara)}" if mascara else " (sin máscara)")
                + f" · ventana {volumen_2d.modalidad or 'AUTO'}", "SUCCESS")
            return True
        except Exception as e:
            self.visor_2d.set_volumen(None)
            self.consola.log(f"No se pudo cargar el volumen en el visor 2D: {e}", "ERROR")
            return False

    def cargar_estudio(self, ruta):
        """Registra la ruta elegida como serie activa y recarga visores."""
        self.panel_estudio.set_ruta(ruta or "")
        if not ruta:
            self.modelo.limpiar()
            self.panel_estudio.set_series([], None)
            if self.casos:
                self.cargar_caso(self.casos[0]["id"])
            else:
                self.panel_capas.set_modelos({}, set())
                self.visor_3d.set_models({})
                self.visor_2d.set_cortes({})
                self._actualizar_tarjetas()
            return

        self.caso_activo = None
        rutas = mesh_store.rutas_serie(ruta if os.path.isdir(ruta) else None)
        nombre = os.path.basename(os.path.normpath(ruta)) or ruta
        uid = f"serie-{len(self.modelo.series) + 1}"
        serie = Serie(uid=uid, nombre=nombre, ruta=ruta)
        modelos = mesh_store.escanear_mallas(dirs=[rutas["mallas"]])
        for key, meta in modelos.items():
            serie.add_capa(key, meta["label"], meta["display"], meta["stl"])
        self.modelo.add_serie(serie)
        self.modelo.slices_2d = mesh_store.listar_cortes(rutas["slices"])
        self.visor_2d.set_cortes(self.modelo.slices_2d)
        self._cargar_volumen_2d(ruta)
        self._titulo_caso.setText(nombre)
        self._chip_lesion.hide()
        self._subtitulo.setText(ruta)
        self.consola.log(f"Estudio cargado: {ruta}", "SUCCESS")
        self.panel_estudio.set_series(self.modelo.series, uid)
        self.panel_estudio.set_caso_activo(None)
        self.panel_estudio.set_procesando(False, hay_mallas=bool(modelos))
        self._poblar_capas()

    def _cambiar_serie(self, uid):
        serie = self.modelo.set_serie_activa(uid)
        if serie is None:
            return
        self.caso_activo = None
        rutas = mesh_store.rutas_serie(serie.ruta if os.path.isdir(serie.ruta) else None)
        self.visor_2d.set_cortes(mesh_store.listar_cortes(rutas["slices"]))
        self._cargar_volumen_2d(serie.ruta)
        self._titulo_caso.setText(serie.nombre)
        self._chip_lesion.hide()
        self._subtitulo.setText(serie.ruta)
        self.consola.log(f"Serie activa: {serie.nombre}", "INFO")
        self._poblar_capas()

    def _poblar_capas(self):
        """Vuelca las capas de la serie activa en el panel y en el visor."""
        serie = self.modelo.serie_activa
        if serie is None:
            self.panel_capas.set_modelos({}, set())
            self.visor_3d.set_models({})
            self._actualizar_tarjetas()
            return
        modelos = {k: {"label": c["label"], "display": c["color"], "stl": c["ruta"],
                       "color_rgba": pbr.resolve_pbr(k).get("color_rgba", (0.6, 0.6, 0.6, 1.0))}
                   for k, c in serie.capas.items()}
        visibles = set(serie.claves_visibles())
        self.panel_capas.set_modelos(modelos, visibles)
        self.visor_3d.set_models_dir(
            os.path.dirname(next(iter(serie.capas.values()))["ruta"]) if serie.capas else None)
        self.visor_3d.set_models(modelos)
        self.visor_3d.set_visible(visibles)
        self._actualizar_tarjetas()

    def _aplicar_visibilidad(self, claves):
        """Única vía de los cambios de visibilidad: panel, visor y modelo."""
        self.panel_capas.set_visibles(claves)
        self.visor_3d.set_visible(claves)
        serie = self.modelo.serie_activa
        if serie is not None:
            for key in serie.capas:
                serie.set_visible(key, key in claves)
        self._actualizar_tarjetas()

    def _estructura_pulsada(self, key):
        self.statusBar().showMessage(
            f"Selección: {self.visor_3d.etiqueta_estructura(key)}", 5000)

    def _actualizar_tarjetas(self):
        total = len(self.panel_capas.claves())
        visibles = len(self.panel_capas.claves_visibles())
        self.card_estructuras.set_value(str(total))
        self.card_visibles.set_value(str(visibles))
        tri = (self.caso_activo or {}).get("triangulos")
        self.card_triangulos.set_value(f"{tri / 1000:.0f} k" if tri else "—")
        self._btn_snapshot.setEnabled(bool(total and visibles))
        self._btn_guardar_2d.setEnabled(self.visor_2d.tiene_cortes())

    # ==================================================================
    # PROCESOS EN SEGUNDO PLANO (QThread)
    # ==================================================================
    def _accion_2d(self, accion):
        if accion == "generar_3d":
            self.generar_malla_desde_mascara()

    def generar_malla_desde_mascara(self):
        """Guarda la máscara delineada y genera la malla STL de la lesión."""
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return False
        volumen = self.visor_2d.volumen()
        if volumen is None or volumen.vacio:
            self.consola.log("No hay volumen en el visor 2D", "WARNING")
            return False
        if volumen.vóxeles_tumor() == 0:
            self.consola.log("La máscara está vacía: delimite la lesión antes", "WARNING")
            return False
        destino = os.path.join(os.path.dirname(volumen.volumen_path or ""),
                               "tumor_manual.nii.gz")
        try:
            volumen.guardar_mascara(destino, formato="NIfTI")
        except Exception as e:
            self.consola.log(f"No se pudo guardar la máscara: {e}", "ERROR")
            return False
        self.consola.log(
            f"Máscara guardada: {os.path.basename(destino)} "
            f"({volumen.vóxeles_tumor():,} vóxeles, {volumen.volumen_cm3_tumor():.2f} cm³)",
            "SUCCESS")
        self._worker_cancelado = False
        self.barra_progreso.reset("Reconstruyendo 3D")
        self.statusBar().showMessage("Generando la malla 3D de la lesión...")
        serie = self.modelo.serie_activa
        base = serie.ruta if serie is not None and os.path.isdir(serie.ruta) \
            else os.path.dirname(volumen.volumen_path or "")
        worker = MeshFromMaskWorker(destino, salida_dir=mesh_store.rutas_serie(base)["mallas"],
                                    estructura="tumor")
        self._malla_pendiente = destino
        return self._lanzar_worker(worker)

    def _accion(self, accion):
        {"pipeline": self.ejecutar_pipeline, "exportar": self.exportar_fbx,
         "cta": self.ejecutar_cta, "freesurfer": self.ejecutar_freesurfer,
         "cta_aprobar": self.aprobar_cta, "cancelar": self.cancelar}.get(
            accion, lambda: None)()

    def _lanzar_worker(self, worker):
        """Mueve `worker` a un QThread nuevo; el hilo se cierra al terminar."""
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return False
        self._worker = worker
        self._thread = QThread(self)
        worker.moveToThread(self._thread)
        worker.log.connect(self.consola.log)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._al_terminar_worker)
        if hasattr(worker, "malla_lista"):
            worker.malla_lista.connect(self._on_malla_lista)
        self._thread.started.connect(worker.run)
        self._thread.finished.connect(self._liberar_thread)
        self._thread.start()
        return True

    def _on_malla_lista(self, ruta_stl):
        self.consola.log(f"Modelo 3D de la lesión listo: {os.path.basename(ruta_stl)}",
                         "SUCCESS")
        serie = self.modelo.serie_activa
        if serie is not None and "tumor" not in serie.capas:
            serie.add_capa("tumor", "Tumor", pbr.color_de("tumor"), ruta_stl)
            serie.set_visible("tumor", True)

    def _al_terminar_worker(self, ok, mensaje):
        hilo = self._thread
        if hilo is not None:
            hilo.quit()
        self._on_worker_finished(ok, mensaje)

    def _liberar_thread(self):
        self._thread = None
        self._worker = None

    def _on_progress(self, ratio):
        self.barra_progreso.set_ratio(ratio)
        self.statusBar().showMessage(f"Procesando... {int(ratio * 100)}%")

    def _on_worker_finished(self, ok, mensaje):
        cancelado = self._worker_cancelado
        nivel = "SUCCESS" if ok else ("WARNING" if cancelado else "ERROR")
        if ok:
            self.barra_progreso.set_ratio(1.0, "Completado")
        else:
            self.barra_progreso.set_status("Cancelado" if cancelado else "Error en el proceso",
                                           "aviso" if cancelado else "error")
        self.panel_estudio.set_procesando(False, hay_mallas=bool(self.panel_capas.claves()))
        self.consola.log(mensaje, nivel)
        if ok:
            self.refrescar_resultados()

    def _preparar_proceso(self, texto):
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return False
        self._worker_cancelado = False
        self.barra_progreso.reset(texto)
        self.panel_estudio.set_procesando(True, hay_mallas=True)
        self.statusBar().showMessage(f"{texto}...")
        return True

    def ejecutar_pipeline(self):
        ruta = self.panel_estudio.ruta()
        if not ruta:
            self.consola.log("Seleccione primero un estudio", "WARNING")
            return
        if not self._preparar_proceso("Segmentando"):
            return
        rutas = mesh_store.rutas_serie(ruta if os.path.isdir(ruta) else None)
        self._lanzar_worker(PipelineWorker(
            ruta, output_dir=rutas["segmentaciones"],
            generar_slices=self.panel_estudio.generar_slices(),
            modo=self.panel_estudio.modo()))

    def ejecutar_freesurfer(self):
        ruta = self.panel_estudio.ruta()
        if not ruta:
            self.consola.log("Seleccione primero un estudio", "WARNING")
            return
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return
        licencia, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar licencia de FreeSurfer", os.path.expanduser("~"),
            "Licencia FreeSurfer (license.txt);;Todos los archivos (*)")
        if not licencia:
            self.consola.log("FreeSurfer necesita una licencia license.txt válida.", "WARNING")
            return
        serie = self.modelo.serie_activa
        base = serie.ruta if serie is not None and os.path.isdir(serie.ruta) \
            else os.path.dirname(ruta) if os.path.isfile(ruta) else ruta
        rutas = mesh_store.rutas_serie(base)
        sujeto = self._nombre_sujeto(serie.nombre if serie else base)
        subjects_dir = os.path.join(mesh_store.RAIZ_DIR, "salidas", "freesurfer", "subjects")
        if not self._preparar_proceso("FreeSurfer"):
            return
        self.consola.log(f"FreeSurfer: sujeto {sujeto}; salida {rutas['segmentaciones']}",
                         "INFO")
        self._lanzar_worker(FreeSurferWorker(
            ruta, subjects_dir, rutas["segmentaciones"], sujeto, licencia))

    @staticmethod
    def _nombre_sujeto(nombre):
        import re
        limpio = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(nombre or "sujeto"))
        return limpio.strip("._-") or "sujeto"

    def ejecutar_cta(self):
        ruta = self.panel_estudio.ruta()
        if not ruta or not os.path.isdir(ruta):
            self.consola.log("Seleccione la carpeta DICOM de una serie CTA.", "WARNING")
            return
        if not self._preparar_proceso("Flujo CTA"):
            return
        salida = mesh_store.rutas_serie(ruta)["segmentaciones"]
        self._lanzar_worker(ClinicalCTAWorker(ruta, salida))

    def aprobar_cta(self):
        ruta = self.panel_estudio.ruta()
        if not ruta or not os.path.isdir(ruta):
            self.consola.log("Seleccione primero una carpeta DICOM CTA", "WARNING")
            return
        salida = mesh_store.rutas_serie(ruta)["segmentaciones"]
        if not os.path.exists(os.path.join(salida, "vasos_cta.nrrd")):
            self.consola.log("Ejecute primero el flujo CTA y revise el candidato.", "WARNING")
            return
        respuesta = QMessageBox.question(
            self, "Aprobación humana requerida",
            "Confirma que revisó los cortes, la máscara vascular y la geometría "
            "DICOM. ¿Desea generar el DICOM SEG?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if respuesta != QMessageBox.Yes:
            self.consola.log("Exportación SEG cancelada por el usuario", "INFO")
            return
        if not self._preparar_proceso("Exportando SEG"):
            return
        self._lanzar_worker(ClinicalCTAWorker(ruta, salida, approved_by="usuario-local"))

    def exportar_fbx(self):
        """Convierte las mallas visibles en FBX, en segundo plano."""
        if not self.panel_capas.claves():
            self.consola.log("No hay modelos 3D para exportar", "WARNING")
            return
        if self.caso_activo is not None:
            stl_dir = os.path.join(self.caso_activo["carpeta"], "stl")
            fbx_dir = os.path.join(self.caso_activo["carpeta"], "fbx_escritorio")
        else:
            serie = self.modelo.serie_activa
            rutas = mesh_store.rutas_serie(
                serie.ruta if serie is not None and os.path.isdir(serie.ruta) else None)
            stl_dir, fbx_dir = rutas["mallas"], rutas["fbx"]
        if not self._preparar_proceso("Exportando FBX"):
            return
        visibles = self.panel_capas.claves_visibles()
        self._lanzar_worker(FbxExportWorker(stl_dir=stl_dir, fbx_dir=fbx_dir,
                                            estructuras=sorted(visibles) or None))

    def cancelar(self):
        if self._worker is None:
            return
        self._worker_cancelado = True
        self._worker.cancelar()
        self.consola.log("Cancelando...", "WARNING")
        self.barra_progreso.set_status("Cancelando", "aviso")

    def refrescar_resultados(self):
        """Reescanea mallas y cortes del estudio propio tras un proceso."""
        serie = self.modelo.serie_activa
        if serie is None:
            return
        rutas = mesh_store.rutas_serie(serie.ruta if os.path.isdir(serie.ruta) else None)
        modelos = mesh_store.escanear_mallas(dirs=[rutas["mallas"]], fbx_dir=rutas["fbx"])
        cortes = mesh_store.listar_cortes(rutas["slices"])
        self.consola.log(f"Resultados: {len(modelos)} mallas, {len(cortes)} cortes", "SUCCESS")
        visibles = set(serie.claves_visibles())
        serie.capas.clear()
        for key, meta in modelos.items():
            serie.add_capa(key, meta["label"], meta["display"], meta["stl"])
        self.modelo.slices_2d = cortes
        self.visor_2d.set_cortes(cortes)
        self._cargar_volumen_2d(serie.ruta)
        self._poblar_capas()
        if visibles:
            self._aplicar_visibilidad(visibles & set(modelos))
        self.visor_3d.reset_camera()

    # ==================================================================
    # EXPORTACIÓN DE IMÁGENES
    # ==================================================================
    def _nombre_base(self):
        if self.caso_activo:
            return f"atlas_{self.caso_activo['id']}"
        return "atlas"

    def guardar_imagen_3d(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar vista 3D",
            os.path.join(os.path.expanduser("~"), f"{self._nombre_base()}_3d.png"),
            "PNG (*.png)")
        if not ruta:
            return
        ok = self.visor_3d.guardar_imagen(ruta, escala=2)
        self.consola.log(f"Imagen 3D guardada en {ruta}" if ok
                         else "No se pudo guardar la imagen", "SUCCESS" if ok else "ERROR")

    def guardar_corte_2d(self):
        self.pestanas.setCurrentIndex(1)
        ruta = self.visor_2d.guardar_corte(self)
        if ruta:
            self.consola.log(f"Corte guardado en {ruta}", "SUCCESS")
        elif self.visor_2d.tiene_cortes():
            self.consola.log("No se pudo guardar el corte", "ERROR")

    def closeEvent(self, event):
        self.cancelar()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)
