"""
Ventana principal de NEUROHUB (PySide6).

Reproduce el flujo de trabajo de Raidionics con el pipeline ya existente:

    panel de estudio  ->  panel de capas  ->  visor 2D/3D  ->  consola

La ventana NO ejecuta nada del pipeline en el hilo de la interfaz: se apoya en
`PipelineWorker` y `FbxExportWorker`, que viven en su propio `QThread` y
comunican solo por senales. Asi la UI sigue respondiendo durante la
segmentacion y el export.
"""

import os

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFileDialog, QMessageBox, QStatusBar,
)

from .software_config import (
    COLOR_ACENTO, COLOR_BG, COLOR_BORDE, COLOR_HOVER, COLOR_OK, COLOR_PANEL,
    COLOR_PANEL_ALT, COLOR_TEXTO, COLOR_TEXTO_SEC, COLOR_WARN,
)
from .widgets import QCircularProgressBar, LogConsole, Card
from .panels import LayersPanel, StudyPanel
from .viewer_2d import Viewer2D
from .viewer_3d import Viewer3D
from .study_model import Serie, StudyModel
from .pipeline_bridge import (
    PipelineWorker, FbxExportWorker, MeshFromMaskWorker,
)
from . import mesh_store
from . import pbr


class MainWindow(QMainWindow):
    """Ventana principal: coordina paneles, visores, workers y consola."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NEUROHUB  ·  Neuroimagen clinica")
        self.resize(1440, 900)

        # Estado de la sesion (sin Qt: se podria probar aislado).
        self.modelo = StudyModel()
        self._thread = None          # QThread del proceso en curso
        self._worker = None          # PipelineWorker, FbxExportWorker o MeshFromMask
        self._worker_cancelado = False
        self._malla_pendiente = None  # ruta de la máscara manual en curso

        self._construir_ui()
        self._conectar()
        self._cargar_salidas_existentes()

    # ==================================================================
    # CONSTRUCCION DE LA INTERFAZ
    # ==================================================================
    def _construir_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {COLOR_BG};")
        self.setCentralWidget(central)

        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._construir_cabecera())

        # ---- Cuerpo: panel de estudio | capas | visores ----
        cuerpo = QHBoxLayout()
        cuerpo.setContentsMargins(8, 8, 8, 0)
        cuerpo.setSpacing(8)

        self.panel_estudio = StudyPanel()
        self.panel_estudio.setFixedWidth(300)
        cuerpo.addWidget(self.panel_estudio)

        self.panel_capas = LayersPanel()
        self.panel_capas.setFixedWidth(250)
        cuerpo.addWidget(self.panel_capas)

        # Visores en pestanas: 3D y 2D conviven como en las ventanas separadas
        # de `main.py`, pero sin abrir procesos nuevos.
        self.pestanas = QTabWidget()
        self.visor_3d = Viewer3D()
        self.visor_2d = Viewer2D()
        self.pestanas.addTab(self.visor_3d, "Vista 3D")
        self.pestanas.addTab(self.visor_2d, "Cortes 2D")
        self.pestanas.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {COLOR_BORDE};"
            f" background-color: {COLOR_BG}; }}"
            f"QTabBar::tab {{ background: {COLOR_PANEL}; color: {COLOR_TEXTO_SEC};"
            f" padding: 6px 18px; border: 1px solid {COLOR_BORDE};"
            f" border-bottom: none; border-top-left-radius: 4px;"
            f" border-top-right-radius: 4px; }}"
            f"QTabBar::tab:selected {{ background: {COLOR_PANEL_ALT};"
            f" color: {COLOR_TEXTO}; }}"
            f"QTabBar::tab:hover {{ background: {COLOR_HOVER}; }}")
        cuerpo.addWidget(self.pestanas, 1)
        raiz.addLayout(cuerpo, 1)
        raiz.addWidget(self._construir_pie())

    # ------------------------------------------------------------------
    def _construir_cabecera(self):
        """Barra superior: marca, datos del caso y progreso."""
        self._header = QWidget()
        self._header.setFixedHeight(88)
        self._header.setStyleSheet(
            f"background-color: {COLOR_PANEL};"
            f" border-bottom: 1px solid {COLOR_BORDE};")
        lay = QHBoxLayout(self._header)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(14)

        # Marca + datos del caso.
        caja = QVBoxLayout()
        caja.setSpacing(1)
        tit = QLabel("NEUROHUB")
        tit.setStyleSheet(
            f"color: {COLOR_ACENTO}; font-size: 20px; font-weight: bold;"
            f" letter-spacing: 2px; border: none;")
        self._subtitulo = QLabel("Sin estudio cargado")
        self._subtitulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SEC}; font-size: 11px; border: none;")
        caja.addWidget(tit)
        caja.addWidget(self._subtitulo)
        lay.addLayout(caja)
        lay.addSpacing(10)

        # Tarjetas de estado (equivalen a las StatusCard de `main.py`).
        self.card_estructuras = Card("ESTRUCTURAS", "0")
        self.card_visibles = Card("VISIBLES", "0")
        self.card_estado = Card("ESTADO", "Inactivo")
        for c in (self.card_estructuras, self.card_visibles, self.card_estado):
            c.setFixedWidth(148)
            lay.addWidget(c)
        lay.addStretch(1)

        # Progreso circular + acciones de vista.
        self.barra_progreso = QCircularProgressBar(diameter=68)
        lay.addWidget(self.barra_progreso)

        self._btn_reset = QPushButton("Restablecer vista")
        self._btn_reset.setToolTip("Reencuadrar la camara 3D")
        lay.addWidget(self._btn_reset)

        self._btn_snapshot = QPushButton("Guardar imagen")
        self._btn_snapshot.setToolTip("Exportar la vista 3D actual a PNG")
        lay.addWidget(self._btn_snapshot)

        self._btn_guardar_2d = QPushButton("Guardar corte")
        self._btn_guardar_2d.setToolTip("Exportar el corte 2D visible a PNG")
        lay.addWidget(self._btn_guardar_2d)

        return self._header

    def _construir_pie(self):
        """Consola de log en la parte inferior."""
        pie = QWidget()
        pie.setFixedHeight(190)
        pie.setStyleSheet(
            f"background-color: {COLOR_PANEL};"
            f" border-top: 1px solid {COLOR_BORDE};")
        lay = QHBoxLayout(pie)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        self.consola = LogConsole()
        lay.addWidget(self.consola, 1)

        b_limpiar = QPushButton("Limpiar consola")
        b_limpiar.setFixedWidth(130)
        b_limpiar.clicked.connect(self.consola.limpiar)
        lay.addWidget(b_limpiar, 0, Qt.AlignTop)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Listo")
        return pie

    # ==================================================================
    # CONEXIONES
    # ==================================================================
    def _conectar(self):
        """Cablea paneles, visores y botones. Un unico punto de entrada."""
        # --- Panel de estudio ---
        self.panel_estudio.pedir_carga.connect(self.cargar_estudio)
        self.panel_estudio.serie_elegida.connect(self._cambiar_serie)
        self.panel_estudio.ejecutar.connect(self._accion)

        # --- Panel de capas ---
        self.panel_capas.visibilidad_cambiada.connect(self._aplicar_visibilidad)

        # --- Visor 3D ---
        self.visor_3d.modelo_seleccionado.connect(self._estructura_pulsada)

        # --- Visor 2D (delineado manual del tumor) ---
        # `informacion` alimenta la barra de estado; `estado` enruta las
        # peticiones del visor 2D que necesitan la ventana (por ahora, generar
        # la malla 3D desde la máscara delineada).
        self.visor_2d.informacion.connect(self.statusBar().showMessage)
        self.visor_2d.estado.connect(self._accion_2d)

        # --- Botones de la cabecera ---
        self._btn_reset.clicked.connect(self.visor_3d.reset_camera)
        self._btn_snapshot.clicked.connect(self.guardar_imagen_3d)
        self._btn_guardar_2d.clicked.connect(self.guardar_corte_2d)

    # ==================================================================
    # CARGA DE ESTUDIOS Y SERIES
    # ==================================================================
    def _cargar_salidas_existentes(self):
        """Al arrancar, muestra lo que ya haya generado el pipeline.

        Asi se abre la aplicacion con el ultimo caso visible en lugar de un
        lienzo vacio, que es como trabajaban las sesiones de Raidionics.
        """
        modelos = mesh_store.escanear_mallas()
        cortes = mesh_store.listar_cortes()
        if not modelos and not cortes:
            self.consola.log("Cargue un estudio para comenzar", "INFO")
            self.panel_estudio.set_procesando(False, hay_mallas=False)
            return

        nombre = "Salidas del pipeline"
        self._subtitulo.setText(f"{nombre}  ·  {len(modelos)} estructuras")
        self.consola.log(f"Mallas en {mesh_store.MALLAS_DIR}", "INFO")
        if cortes:
            self.consola.log(f"{len(cortes)} cortes 2D en {mesh_store.SLICES_DIR}",
                             "INFO")

        # Una unica serie "Salidas" apuntando a las rutas globales.
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
        """Carga el volumen NIfTI en el visor 2D, si el caso lo tiene.

        Sin volumen, el visor 2D solo puede mostrar los tres PNG fijos: no hay
        cortes por los que navegar ni máscara que delinear. Se avisa por
        consola en vez de fallar en silencio, porque es la diferencia entre
        "la segmentación no salió" y "no he cargado el volumen".
        """
        from .. import volumen_2d as v2d

        try:
            volumen_path = mesh_store.buscar_volumen(ruta_base, mesh_store.SALIDAS_DIR)
            if not volumen_path:
                self.visor_2d.set_volumen(None)
                self.consola.log(
                    "Sin volumen NIfTI: el visor 2D muestra solo los cortes PNG",
                    "WARNING")
                return False

            # La máscara se elige entre TODAS las candidatas y solo se usa la
            # que comparte rejilla con el volumen. Antes se cogía la primera
            # existente; si venía de otro caso, `cargar_mascara` levantaba
            # ValueError, la excepción caía en el `except` de abajo y el visor
            # se quedaba vacío, es decir, sin pincel y sin borrador.
            candidatas = mesh_store.listar_mascaras_tumor(
                ruta_base, mesh_store.SALIDAS_DIR)
            mascara = mesh_store.buscar_mascara_compatible(candidatas,
                                                          volumen_path)
            if candidatas and not mascara:
                self.consola.log(
                    "Ninguna máscara encaja con la rejilla del volumen: se "
                    "carga la imagen SIN máscara para poder delinearla a mano",
                    "WARNING")
            self.visor_2d.set_volumen(v2d.Volumen2D(volumen_path, mascara))
            self.consola.log(
                f"Visor 2D: {os.path.basename(volumen_path)}"
                + (f" + {os.path.basename(mascara)}" if mascara else " (sin máscara)"),
                "SUCCESS")
            return True
        except Exception as e:
            self.visor_2d.set_volumen(None)
            self.consola.log(f"No se pudo cargar el volumen en el visor 2D: {e}",
                             "ERROR")
            return False

    def cargar_estudio(self, ruta):
        """Registra la ruta elegida como serie activa y recarga visores."""
        # Se refleja siempre en el panel: este metodo tambien se llama desde
        # codigo (no solo desde el boton), y el campo debe reflejar siempre lo
        # que hay cargado.
        self.panel_estudio.set_ruta(ruta or "")
        if not ruta:
            # "Quitar": se deja la ventana en blanco.
            self.modelo.limpiar()
            self.panel_estudio.set_series([], None)
            self._subtitulo.setText("Sin estudio cargado")
            self.panel_capas.set_modelos({}, set())
            self.visor_3d.set_models({})
            self.visor_2d.set_cortes({})
            self._actualizar_tarjetas()
            return

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

        self._subtitulo.setText(f"{nombre}  ·  {serie.modality}")
        self.consola.log(f"Estudio cargado: {ruta}", "SUCCESS")
        self.panel_estudio.set_series(self.modelo.series, uid)
        self.panel_estudio.set_procesando(False, hay_mallas=bool(modelos))
        self._poblar_capas()

    def _cambiar_serie(self, uid):
        """Cambia la serie activa y recarga visores y cortes."""
        serie = self.modelo.set_serie_activa(uid)
        if serie is None:
            return
        rutas = mesh_store.rutas_serie(
            serie.ruta if os.path.isdir(serie.ruta) else None)
        self.visor_2d.set_cortes(mesh_store.listar_cortes(rutas["slices"]))
        self._cargar_volumen_2d(serie.ruta)
        self._subtitulo.setText(f"{serie.nombre}  ·  {serie.modality}")
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

        # `color_rgba` es imprescindible: el visor 3D lo usa para pintar el
        # actor. Sin el, `Viewer3D._build_actor` cae al gris por defecto y toda
        # la escena sale descolorida. Se resuelve aqui con `resolve_pbr` (que
        # aplica los alias arterias/venas/vasos -> venas_arterias) en vez de
        # confiar en la capa, que solo guarda el color hexadecimal del panel.
        modelos = {k: {"label": c["label"], "display": c["color"],
                       "stl": c["ruta"],
                       "color_rgba": pbr.resolve_pbr(k).get(
                           "color_rgba", (0.6, 0.6, 0.6, 1.0))}
                   for k, c in serie.capas.items()}
        visibles = set(serie.claves_visibles())
        self.panel_capas.set_modelos(modelos, visibles)

        self.visor_3d.set_models_dir(
            os.path.dirname(next(iter(serie.capas.values()))["ruta"])
            if serie.capas else None)
        self.visor_3d.set_models(modelos)
        if visibles:
            self.visor_3d.set_visible(visibles)
        self._actualizar_tarjetas()

    def _aplicar_visibilidad(self, claves):
        """Refleja la visibilidad elegida en el visor, el panel y el modelo.

        Se sincroniza tambien el panel porque este metodo es la UNICA via por la
        que pasa cualquier cambio de visibilidad: tanto las casillas del usuario
        como las actualizaciones automaticas (tras el pipeline) convergen aqui,
        de modo que las tres vistas no pueden quedar desincronizadas.
        """
        self.panel_capas.set_visibles(claves)
        self.visor_3d.set_visible(claves)
        serie = self.modelo.serie_activa
        if serie is not None:
            for key in serie.capas:
                serie.set_visible(key, key in claves)
        self._actualizar_tarjetas()

    def _estructura_pulsada(self, key):
        """Seleccion en la vista 3D: se asegura de que la capa quede activa."""
        self.statusBar().showMessage(
            f"Seleccion: {self.visor_3d.etiqueta_estructura(key)}", 4000)

    def _actualizar_tarjetas(self):
        total = len(self.panel_capas.claves())
        visibles = self.modelo.total_capas_visibles()
        self.card_estructuras.set_value(str(total))
        self.card_visibles.set_value(str(visibles))

    # ==================================================================
    # PROCESOS EN SEGUNDO PLANO (QThread)
    # ==================================================================
    def _accion_2d(self, accion):
        """Peticiones que el visor 2D hace a la ventana."""
        if accion == "generar_3d":
            self.generar_malla_desde_mascara()

    def generar_malla_desde_mascara(self):
        """Guarda la máscara delineada y genera la malla STL del tumor.

        El flujo completo es deliberado y automatico: delinear en 2D ->
        guardar la máscara en la rejilla del volumen -> reconstruir la
        superficie -> refrescar el visor 3D. Preguntar al usuario entre pasos
        solo introduciría la posibilidad de guardar la máscara y generar la
        malla de otra, que es justo el desajuste que hay que evitar.
        """
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return False
        volumen = self.visor_2d.volumen()
        if volumen is None or volumen.vacio:
            self.consola.log("No hay volumen en el visor 2D", "WARNING")
            return False
        if volumen.vóxeles_tumor() == 0:
            self.consola.log("La máscara está vacía: delimite el tumor antes",
                             "WARNING")
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
            f"({volumen.vóxeles_tumor():,} vóxeles, "
            f"{volumen.volumen_cm3_tumor():.2f} cm³)", "SUCCESS")

        self._worker_cancelado = False
        self.barra_progreso.reset("Reconstruyendo 3D")
        self.card_estado.set_value("Reconstruyendo", COLOR_ACENTO)
        self.statusBar().showMessage("Generando la malla 3D del tumor...")

        # La STL se escribe junto al resto de mallas de la serie, no al lado
        # del volumen: asi el visor 3D la encuentra con el mismo barrido que
        # usa para el resto de estructuras y sobrevive a un guardado manual.
        serie = self.modelo.serie_activa
        base = serie.ruta if serie is not None and os.path.isdir(serie.ruta) \
            else os.path.dirname(volumen.volumen_path or "")
        worker = MeshFromMaskWorker(destino,
                                    salida_dir=mesh_store.rutas_serie(base)["mallas"],
                                    estructura="tumor")
        self._malla_pendiente = destino
        return self._lanzar_worker(worker)

    def _accion(self, accion):
        """Enruta las acciones del panel de estudio."""
        if accion == "pipeline":
            self.ejecutar_pipeline()
        elif accion == "exportar":
            self.exportar_fbx()
        elif accion == "cancelar":
            self.cancelar()

    def _lanzar_worker(self, worker):
        """Mueve `worker` a un QThread nuevo y conecta sus senales.

        Se crea un hilo POR PROCESO y se destruye al terminar: es la unica forma
        segura de garantizar que ningun QObject quede vivo en un hilo que ya no
        existe (de lo contrario, Qt aborta con "QThread: Destroyed while thread
        is still running").

        Detalle importante: `started` solo llama a `worker.run()`, pero el hilo
        sigue con su event loop, asi que `QThread.finished` NO se emitiria
        nunca y la ventana creeria que hay un proceso eterno. Por eso `run`
        termina llamando a `quit()`: el hilo se cierra solo al acabar el trabajo.
        """
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return False

        self._worker = worker
        self._thread = QThread(self)
        worker.moveToThread(self._thread)

        worker.log.connect(self.consola.log)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._al_terminar_worker)
        # `malla_lista` solo existe en MeshFromMaskWorker; se conecta con
        # hasattr para no obligar a los demas workers a definir una senal que
        # no les aplica.
        if hasattr(worker, "malla_lista"):
            worker.malla_lista.connect(self._on_malla_lista)
        self._thread.started.connect(worker.run)
        self._thread.finished.connect(self._liberar_thread)
        self._thread.start()
        return True

    def _on_malla_lista(self, ruta_stl):
        """Ha aparecido una STL nueva: se registra como capa del tumor.

        Se registra antes de que llegue `finished`, para que el refresco del
        visor 3D vea el archivo ya escrito en disco.
        """
        self.consola.log(f"Modelo 3D del tumor listo: {os.path.basename(ruta_stl)}",
                         "SUCCESS")
        serie = self.modelo.serie_activa
        if serie is not None:
            clave = "tumor"
            meta = {"stl": ruta_stl, "label": "Tumor",
                    "display": pbr.color_de(clave)}
            if clave not in serie.capas:
                serie.add_capa(clave, meta["label"], meta["display"], ruta_stl)
                serie.set_visible(clave, True)

    def _al_terminar_worker(self, ok, mensaje):
        """Ultima senal del worker: apaga el hilo y despues actualiza la UI.

        El orden importa: `quit()` se encola en el hilo del worker, y
        `_liberar_thread` solo actua cuando el hilo ha finished de verdad, de
        modo que nunca se borra la referencia a un worker aun vivo.
        """
        hilo = self._thread
        if hilo is not None:
            hilo.quit()
        self._on_worker_finished(ok, mensaje)

    def _liberar_thread(self):
        """Limpia la referencia al hilo cuando este termina."""
        self._thread = None
        self._worker = None

    def _on_progress(self, ratio):
        self.barra_progreso.set_ratio(ratio)
        self.statusBar().showMessage(f"Procesando... {int(ratio * 100)}%")

    def _on_worker_finished(self, ok, mensaje):
        """Actualiza la UI cuando el worker termina (con exito o no)."""
        cancelado = self._worker_cancelado
        nivel = "SUCCESS" if ok else ("WARNING" if cancelado else "ERROR")
        if ok:
            self.barra_progreso.set_ratio(1.0, "Completado")
        else:
            self.barra_progreso.set_status("Cancelado" if cancelado else "Error")
        self.card_estado.set_value("Listo" if ok else "Detenido",
                                   COLOR_OK if ok else COLOR_WARN)
        self.panel_estudio.set_procesando(
            False, hay_mallas=bool(self.panel_capas.claves()))

        if ok:
            self.consola.log(mensaje, "SUCCESS")
            self.refrescar_resultados()
        else:
            self.consola.log(mensaje, nivel)

    # ------------------------------------------------------------------
    def ejecutar_pipeline(self):
        """Lanza la segmentacion completa en segundo plano."""
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return
        ruta = self.panel_estudio.ruta()
        if not ruta:
            self.consola.log("Seleccione primero un estudio", "WARNING")
            return

        self._worker_cancelado = False
        self.barra_progreso.reset("Segmentando")
        self.card_estado.set_value("Procesando", COLOR_ACENTO)
        self.panel_estudio.set_procesando(True, hay_mallas=True)
        self.statusBar().showMessage("Ejecutando pipeline...")

        self._lanzar_worker(PipelineWorker(
            ruta, generar_slices=self.panel_estudio.generar_slices(),
            modo=self.panel_estudio.modo()))

    def exportar_fbx(self):
        """Convierte las mallas visibles en archivos FBX, en segundo plano."""
        if self._thread is not None:
            self.consola.log("Ya hay un proceso en curso", "WARNING")
            return
        if not self.panel_capas.claves():
            self.consola.log("No hay modelos 3D para exportar", "WARNING")
            return

        self._worker_cancelado = False
        self.barra_progreso.reset("Exportando")
        self.card_estado.set_value("Exportando", COLOR_ACENTO)
        self.panel_estudio.set_procesando(True, hay_mallas=True)
        self.statusBar().showMessage("Exportando a FBX...")

        # Se exportan las estructuras VISIBLES, que es lo que el usuario tiene
        # en pantalla. Si no hay ninguna marcada, se exportan todas.
        visibles = self.panel_capas.claves_visibles()
        self._lanzar_worker(FbxExportWorker(estructuras=sorted(visibles) or None))

    def cancelar(self):
        """Pide al worker en curso que se detenga en el siguiente punto."""
        if self._worker is None:
            return
        self._worker_cancelado = True
        self._worker.cancelar()
        self.consola.log("Cancelando...", "WARNING")
        self.barra_progreso.set_status("Cancelando")

    def refrescar_resultados(self):
        """Reescanea mallas y cortes tras terminar el pipeline."""
        modelos = mesh_store.escanear_mallas()
        cortes = mesh_store.listar_cortes()
        self.consola.log(
            f"Resultados: {len(modelos)} mallas, {len(cortes)} cortes", "SUCCESS")

        serie = self.modelo.serie_activa
        if serie is None:
            return
        # Se conservan las visibilidades que el usuario ya habia elegido.
        visibles = set(serie.claves_visibles())
        for key, meta in modelos.items():
            if key not in serie.capas:
                serie.add_capa(key, meta["label"], meta["display"], meta["stl"])
        self.modelo.slices_2d = cortes

        self.visor_2d.set_cortes(cortes)
        self._cargar_volumen_2d(serie.ruta)
        self._poblar_capas()
        if visibles:
            self.panel_capas.set_visibles(visibles)
            self._aplicar_visibilidad(visibles)
        self.visor_3d.reset_camera()

    # ==================================================================
    # EXPORTACION DE IMAGENES
    # ==================================================================
    def guardar_imagen_3d(self):
        """Guarda la vista 3D actual en un PNG."""
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar vista 3D",
            os.path.join(os.path.expanduser("~"), "neurohub_3d.png"),
            "PNG (*.png)")
        if not ruta:
            return
        ok = self.visor_3d.guardar_imagen(ruta)
        self.consola.log(
            f"Imagen 3D guardada en {ruta}" if ok
            else "No se pudo guardar la imagen",
            "SUCCESS" if ok else "ERROR")

    def guardar_corte_2d(self):
        """Guarda el corte 2D visible en un PNG."""
        self.pestanas.setCurrentIndex(1)
        ruta = self.visor_2d.guardar_corte(self)
        if ruta:
            self.consola.log(f"Corte guardado en {ruta}", "SUCCESS")
        elif self.visor_2d.tiene_cortes():
            self.consola.log("No se pudo guardar el corte", "ERROR")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """Cierra los hilos antes de destruir la ventana."""
        self.cancelar()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)
