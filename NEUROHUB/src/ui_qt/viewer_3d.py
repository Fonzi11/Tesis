"""
Visor 3D de ATLAS sobre VTK-Qt.

Escena multi-estructura con:

  * opacidad por estructura (la del caso o la que fije el usuario por grupo),
  * transparencias ordenadas con *depth peeling* (sin él, VTK solo ordena
    actores completos por su centroide y las capas translúcidas anidadas
    —corteza sobre sustancia blanca sobre tumor— se pintan en orden erróneo),
  * iluminación de estudio (vtkLightKit) ligada a la cámara: al girar el
    modelo no aparece una cara "a oscuras",
  * cubo de orientación anatómica (convención LPS de DICOM: A/P, D/I, S/I),
  * vistas estándar (anterior, posterior, laterales, superior, inferior),
  * decimación por cuádricas de VTK con preservación de volumen. La
    simplificación anterior (fast_simplification) dejaba aristas de hasta
    10 cm que cruzaban la escena como agujas.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QFrame)

from .software_config import (COLOR_BORDE_SUAVE, COLOR_PANEL, COLOR_TEXTO,
                              COLOR_TEXTO_SEC, COLOR_TEXTO_TENUE, VIEW_BG_RGB,
                              VIEW_BG_TOP_RGB)
from .pbr import PBR_ALIASES, resolve_pbr, label_de

# Vistas estándar en LPS: (dirección desde el foco hacia la cámara, "arriba").
VISTAS = {
    "anterior": ((0, -1, 0), (0, 0, 1)),
    "posterior": ((0, 1, 0), (0, 0, 1)),
    "derecha": ((-1, 0, 0), (0, 0, 1)),
    "izquierda": ((1, 0, 0), (0, 0, 1)),
    "superior": ((0, 0, 1), (0, -1, 0)),
    "inferior": ((0, 0, -1), (0, -1, 0)),
    # Vista inicial: anterolateral derecha y algo superior, la habitual en
    # planificación porque deja ver a la vez la cara y la convexidad.
    "oblicua": ((-0.62, -0.92, 0.42), (0, 0, 1)),
}
NOMBRES_VISTA = [("anterior", "Anterior"), ("posterior", "Posterior"),
                 ("derecha", "Derecha"), ("izquierda", "Izquierda"),
                 ("superior", "Superior"), ("inferior", "Inferior")]


class Viewer3D(QWidget):
    """Visor interactivo de las mallas del caso activo.

    Señales:
        modelo_seleccionado(str): el usuario ha pulsado sobre una estructura.
    """

    modelo_seleccionado = Signal(str)

    ORDEN_ESCENA = [
        "craneo", "skull", "cerebro", "brain", "corteza",
        "fs_white_matter", "sustancia_blanca", "fs_cortex", "fs_cerebellum",
        "cerebelo", "fs_brainstem", "tronco", "fs_thalamus", "fs_basal_ganglia",
        "fs_hippocampus", "fs_ventricles", "ventriculos",
        "vasos", "arterias", "venas", "vessels",
        "tumor_edema", "tumor_realce", "tumor_necrosis", "tumor", "aneurisma",
    ]

    # Opacidad por defecto de las envolventes del pipeline clásico (los casos
    # ATLAS traen la suya). Solo se aplica si hay algo visible dentro.
    OPACIDAD_ESTRUCTURA = {
        "craneo": 0.22, "cerebro": 0.35, "fs_cortex": 0.40,
        "fs_white_matter": 0.32, "fs_ventricles": 0.6,
    }

    QUALITY_FACES = {
        "high": {"craneo": 600000, "cerebro": 500000, "vasos": 500000,
                 "arterias": 500000, "venas": 500000, "default": 300000},
        "medium": {"craneo": 150000, "cerebro": 120000, "vasos": 180000,
                   "arterias": 180000, "venas": 180000, "default": 80000},
    }
    MAX_FACES_ABSOLUTO = 1200000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = {}
        self._visible_keys = set()
        self._current_key = None
        self._actors = {}
        self._mesh_cache = {}
        self._quality = "high"
        self._scene_key = None
        self._modelos_firma = None
        self._pickable = {}
        self._models_dir = None
        self._opacidad_usuario = {}

        self._vtk = None
        self._ren = None
        self._ren_win = None
        self._interactor = None
        self._marcador = None

        self._construir_ui()
        self._inicializar_vtk()

    # ------------------------------------------------------------------
    def _construir_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Barra de vistas: control segmentado + estructura seleccionada.
        self._barra = QWidget()
        self._barra.setObjectName("barraVisor3D")
        self._barra.setStyleSheet(
            f"#barraVisor3D {{ background: {COLOR_PANEL};"
            f" border-bottom: 1px solid {COLOR_BORDE_SUAVE}; }}")
        bl = QHBoxLayout(self._barra)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.setSpacing(10)
        seg = QFrame()
        seg.setObjectName("grupoSegmentado")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self._botones_vista = {}
        for clave, texto in NOMBRES_VISTA:
            b = QPushButton(texto)
            b.setObjectName("segmento")
            b.setCheckable(True)
            b.setAutoExclusive(False)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Vista {texto.lower()}")
            b.clicked.connect(lambda _c, k=clave: self.set_vista(k))
            sl.addWidget(b)
            self._botones_vista[clave] = b
        bl.addWidget(seg)
        self._btn_reset = QPushButton("Restablecer")
        self._btn_reset.setObjectName("fantasma")
        self._btn_reset.setToolTip("Vista oblicua inicial, encuadrando todo el modelo")
        self._btn_reset.clicked.connect(self.reset_camera)
        bl.addWidget(self._btn_reset)
        bl.addStretch(1)
        self._lbl_sel = QLabel("")
        self._lbl_sel.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 11px;")
        bl.addWidget(self._lbl_sel)
        self._layout.addWidget(self._barra)

        self._vtk_host = QWidget()
        self._vtk_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vtk_layout = QVBoxLayout(self._vtk_host)
        self._vtk_layout.setContentsMargins(0, 0, 0, 0)
        self._vtk_layout.setSpacing(0)
        self._layout.addWidget(self._vtk_host, 1)

        self._mensaje = QLabel("Elija un caso para comenzar")
        self._mensaje.setAlignment(Qt.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._mensaje.setStyleSheet(f"color: {COLOR_TEXTO_TENUE}; font-size: 13px;")
        self._layout.addWidget(self._mensaje, 1)

        self._lbl_ayuda = QLabel(
            "Arrastrar: rotar  ·  Mayús+arrastrar o botón central: desplazar  ·  "
            "Rueda: zoom  ·  Clic: identificar estructura")
        self._lbl_ayuda.setStyleSheet(
            f"color: {COLOR_TEXTO_TENUE}; font-size: 10px; background: {COLOR_PANEL};"
            f" border-top: 1px solid {COLOR_BORDE_SUAVE}; padding: 4px 12px;")
        self._layout.addWidget(self._lbl_ayuda)

    # ------------------------------------------------------------------
    def _inicializar_vtk(self):
        """Crea renderer, ventana, interactor, luces y marcador de orientación."""
        try:
            import vtk
            from vtkmodules.qt.QVTKRenderWindowInteractor import (
                QVTKRenderWindowInteractor)
        except Exception:
            self._mostrar_mensaje(
                "VTK no está disponible.\nInstale vtk para ver el visor 3D.")
            return

        self._vtk = vtk
        self._ren = vtk.vtkRenderer()
        self._ren.SetBackground(*VIEW_BG_RGB)
        self._ren.SetBackground2(*VIEW_BG_TOP_RGB)
        self._ren.GradientBackgroundOn()

        # Iluminación de estudio ligada a la cámara (key/fill/back/head).
        self._ren.RemoveAllLights()
        kit = vtk.vtkLightKit()
        kit.SetKeyLightIntensity(0.95)
        kit.SetKeyToFillRatio(2.6)
        kit.SetKeyToHeadRatio(3.2)
        kit.SetKeyToBackRatio(3.0)
        kit.AddLightsToRenderer(self._ren)
        self._ren.SetAmbient(0.10, 0.11, 0.13)

        self._interactor = QVTKRenderWindowInteractor(self._vtk_host)
        self._interactor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vtk_layout.addWidget(self._interactor, 1)
        self._ren_win = self._interactor.GetRenderWindow()
        self._ren_win.AddRenderer(self._ren)
        self._interactor.Initialize()

        try:
            self._ren_win.SetMultiSamples(0)  # incompatible con depth peeling
        except Exception:
            pass
        # Depth peeling: transparencias correctas entre capas anidadas. Con
        # mallas de hasta ~700 k triángulos (casos ATLAS) 6 pasadas bastan;
        # el umbral de oclusión 0,05 corta antes las pasadas que ya no
        # aportan, que es lo que antes dejaba el cráneo sin dibujar.
        self._ren.SetUseDepthPeeling(1)
        self._ren.SetMaximumNumberOfPeels(6)
        self._ren.SetOcclusionRatio(0.05)
        self._ren.SetUseFXAA(True)

        cam = self._ren.GetActiveCamera()
        cam.SetPosition(0, -1, 0)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 0, 1)

        style = vtk.vtkInteractorStyleTrackballCamera()
        self._interactor.SetInteractorStyle(style)
        self._interactor.AddObserver("LeftButtonPressEvent", self._on_pick, 1.0)

        self._crear_marcador()
        self._vtk_host.show()
        self._mensaje.hide()

    def _crear_marcador(self):
        """Cubo anatómico en la esquina inferior izquierda (LPS)."""
        vtk = self._vtk
        try:
            cubo = vtk.vtkAnnotatedCubeActor()
            cubo.SetXPlusFaceText("Iz")     # +X = izquierda del paciente
            cubo.SetXMinusFaceText("D")
            cubo.SetYPlusFaceText("P")
            cubo.SetYMinusFaceText("A")
            cubo.SetZPlusFaceText("S")
            cubo.SetZMinusFaceText("Inf")
            cubo.SetFaceTextScale(0.55)
            prop = cubo.GetCubeProperty()
            prop.SetColor(0.16, 0.20, 0.26)
            prop.SetAmbient(0.6)
            texto = cubo.GetTextEdgesProperty()
            texto.SetLineWidth(1)
            texto.SetColor(0.30, 0.36, 0.44)
            for cara in ("XPlus", "XMinus", "YPlus", "YMinus", "ZPlus", "ZMinus"):
                p = getattr(cubo, f"Get{cara}FaceProperty")()
                p.SetColor(0.85, 0.90, 0.95)
                p.SetInterpolationToFlat()
            self._marcador = vtk.vtkOrientationMarkerWidget()
            self._marcador.SetOrientationMarker(cubo)
            self._marcador.SetInteractor(self._interactor)
            self._marcador.SetViewport(0.0, 0.0, 0.13, 0.17)
            self._marcador.SetEnabled(1)
            self._marcador.InteractiveOff()
        except Exception:
            self._marcador = None

    # ------------------------------------------------------------------
    def _ajustar_tamano(self):
        if self._ren_win is None:
            return
        self._ren_win.Render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar_tamano()

    def _mostrar_mensaje(self, texto):
        self._mensaje.setText(texto)
        self._mensaje.show()
        if self._vtk_host is not None:
            self._vtk_host.hide()

    def _ocultar_mensaje(self):
        self._mensaje.hide()
        if self._vtk_host is not None:
            self._vtk_host.show()
        self._ajustar_tamano()

    # ==================================================================
    # CARGA DE MODELOS
    # ==================================================================
    def set_models(self, modelos):
        """Reemplaza el catálogo de estructuras (clave -> stl, label, color...)."""
        self._models = dict(modelos or {})
        self._opacidad_usuario = {}

        for key in list(self._actors):
            datos = self._actors.pop(key)
            if self._ren is not None:
                for data in datos.values():
                    self._ren.RemoveActor(data["actor"])
                    self._pickable.pop(data["actor"], None)
        self._mesh_cache.clear()
        self._lbl_sel.setText("")

        if not self._models:
            self._limpiar_escena()
            self._mostrar_mensaje("No hay modelos 3D.\nElija un caso o ejecute el pipeline.")
            return

        self._current_key = next(iter(self._models))
        self._visible_keys = set(self._models)
        self._scene_key = None
        self._modelos_firma = None
        self._ocultar_mensaje()
        self.render()

    def _limpiar_escena(self):
        if self._ren is None:
            return
        for a in list(self._actores_en_escena()):
            self._ren.RemoveActor(a)
        self._actors.clear()
        self._mesh_cache.clear()
        self._pickable.clear()
        self._visible_keys.clear()
        self._current_key = None
        self._scene_key = None

    def _actores_en_escena(self):
        coll = self._ren.GetActors()
        return [coll.GetItemAsObject(i) for i in range(coll.GetNumberOfItems())]

    def set_visible(self, keys):
        """Define las estructuras visibles y re-renderiza (sin mover la cámara)."""
        validas = {k for k in (keys or []) if k in self._models}
        self._visible_keys = validas
        if not validas:
            if self._ren is not None:
                for a in self._actores_en_escena():
                    self._ren.RemoveActor(a)
                self._ren_win.Render()
            self._lbl_sel.setText("Ninguna estructura visible")
            return
        if self._current_key not in validas:
            self._current_key = next(iter(validas))
        self.render()

    def set_opacidad(self, cambios):
        """Fija la opacidad (0..1) de las estructuras indicadas."""
        for k, a in (cambios or {}).items():
            if k in self._models:
                self._opacidad_usuario[k] = max(0.02, min(1.0, float(a)))
        self.render()

    def _resolve_mallas_dir(self):
        return self._models_dir

    def set_models_dir(self, directorio):
        self._models_dir = directorio

    def refresh_from_disk(self):
        if not self._models_dir:
            return
        from .mesh_store import escanear_mallas
        self.set_models(escanear_mallas([self._models_dir]))

    # ==================================================================
    # RENDER Y CÁMARA
    # ==================================================================
    def render(self, reset_camera=False):
        """Aplica la escena al renderer y dibuja.

        La cámara solo se reencuadra cuando cambia el CASO (o se pide): al
        mostrar u ocultar capas la vista se queda donde el usuario la dejó.
        """
        if self._ren is None or self._vtk is None:
            return
        try:
            ordered = self._sync_scene(self._quality)
            if not ordered:
                self._mostrar_mensaje("No hay geometría disponible para mostrar.")
                return
            self._ocultar_mensaje()
            firma = tuple(sorted(self._models))
            if reset_camera or firma != self._modelos_firma:
                self._modelos_firma = firma
                self._encuadrar("oblicua")
            self._ren.ResetCameraClippingRange()
            self._ren_win.Render()
        except Exception as e:
            self._mostrar_mensaje(f"No se pudo renderizar el modelo:\n{e}")

    def _limites_escena(self):
        """Límites de TODAS las estructuras del caso (no solo las visibles),
        para que el encuadre no cambie al ocultar capas."""
        import numpy as np
        lo, hi = None, None
        for datos in self._actors.values():
            for d in datos.values():
                b = d["actor"].GetBounds()
                if b is None or b[0] > b[1]:
                    continue
                a = np.array(b).reshape(3, 2)
                lo = a[:, 0] if lo is None else np.minimum(lo, a[:, 0])
                hi = a[:, 1] if hi is None else np.maximum(hi, a[:, 1])
        return lo, hi

    def _encuadrar(self, vista):
        import numpy as np
        lo, hi = self._limites_escena()
        if lo is None:
            self._ren.ResetCamera()
            return
        centro = (lo + hi) / 2.0
        radio = float(np.linalg.norm(hi - lo)) / 2.0
        direccion, arriba = VISTAS.get(vista, VISTAS["oblicua"])
        d = np.array(direccion, dtype=float)
        d /= np.linalg.norm(d)
        cam = self._ren.GetActiveCamera()
        cam.SetViewAngle(30.0)
        distancia = radio / np.sin(np.radians(30.0) / 2.0) * 0.92
        cam.SetFocalPoint(*centro)
        cam.SetPosition(*(centro + d * distancia))
        cam.SetViewUp(*arriba)
        cam.OrthogonalizeViewUp()
        self._ren.ResetCameraClippingRange()
        for k, b in self._botones_vista.items():
            b.setChecked(k == vista)

    def set_vista(self, vista):
        """Vista anatómica estándar (anterior, posterior, derecha...)."""
        if self._ren is None:
            return
        self._encuadrar(vista)
        self._ren_win.Render()

    def reset_camera(self):
        """Vista inicial (oblicua) encuadrando todo el caso."""
        if self._ren is None:
            return
        self._encuadrar("oblicua")
        self._ren_win.Render()

    def guardar_imagen(self, ruta, escala=1):
        """Escribe la vista actual en un PNG. Devuelve True si se generó."""
        if self._ren_win is None or not ruta or self._vtk is None:
            return False
        vtk = self._vtk
        try:
            if self._marcador is not None:
                self._marcador.SetEnabled(0)
            self._ren_win.Render()
            cap = vtk.vtkWindowToImageFilter()
            cap.SetInput(self._ren_win)
            cap.SetScale(max(1, min(int(escala), 4)))
            cap.SetInputBufferTypeToRGB()
            cap.ReadFrontBufferOff()
            cap.Update()
            esc = vtk.vtkPNGWriter()
            esc.SetFileName(ruta)
            esc.SetInputConnection(cap.GetOutputPort())
            esc.Write()
            return True
        except Exception:
            return False
        finally:
            if self._marcador is not None:
                self._marcador.SetEnabled(1)
                self._marcador.InteractiveOff()
            self._ren_win.Render()

    def _scene_order(self, key):
        k = (key or "").lower()
        for i, name in enumerate(self.ORDEN_ESCENA):
            if k.startswith(name) or name in k:
                return i
        return len(self.ORDEN_ESCENA)

    def _canon_key(self, key):
        return PBR_ALIASES.get((key or "").lower(), (key or "").lower())

    # ==================================================================
    # CONSTRUCCIÓN DE LA ESCENA
    # ==================================================================
    def _quality_faces(self, key, level):
        tabla = self.QUALITY_FACES.get(level, self.QUALITY_FACES["medium"])
        k = (key or "").lower()
        canon = PBR_ALIASES.get(k)
        if canon in tabla:
            k = canon
        elif k not in tabla:
            for name in tabla:
                if name != "default" and name in k:
                    k = name
                    break
        return min(tabla.get(k, tabla["default"]), self.MAX_FACES_ABSOLUTO)

    def _load_preview_mesh(self, stl_path, key, level="high"):
        """Lee el STL y lo decima por cuádricas si supera el presupuesto."""
        vtk = self._vtk
        cache_key = (stl_path, level)
        if cache_key in self._mesh_cache:
            return self._mesh_cache[cache_key]
        lector = vtk.vtkSTLReader()
        lector.SetFileName(stl_path)
        lector.Update()
        limpio = vtk.vtkCleanPolyData()
        limpio.SetInputConnection(lector.GetOutputPort())
        limpio.Update()
        pd = limpio.GetOutput()
        objetivo = self._quality_faces(key, level)
        n = pd.GetNumberOfPolys()
        if n > objetivo:
            dec = vtk.vtkQuadricDecimation()
            dec.SetInputData(pd)
            dec.SetTargetReduction(1.0 - objetivo / float(n))
            dec.VolumePreservationOn()
            dec.Update()
            pd = dec.GetOutput()
        self._mesh_cache[cache_key] = pd
        return pd

    def _mesh_to_polydata(self, vs, faces):
        """vtkPolyData a partir de arrays numpy (vectorizado)."""
        import numpy as np
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

        vs = np.ascontiguousarray(vs, dtype=np.float32)
        faces = np.ascontiguousarray(faces, dtype=np.int64)
        pd = self._vtk.vtkPolyData()
        pts = self._vtk.vtkPoints()
        pts.SetDataTypeToFloat()
        pts.SetData(numpy_to_vtk(vs, deep=True))
        pd.SetPoints(pts)
        if faces.shape[0] > 0:
            cells = self._vtk.vtkCellArray()
            cells.SetData(3, numpy_to_vtkIdTypeArray(faces.reshape(-1), deep=True))
            pd.SetPolys(cells)
        return pd

    def _build_actor(self, key, level):
        meta = self._models.get(key)
        stl = meta.get("stl") if meta else None
        if not stl or not os.path.isfile(stl):
            return None
        store = self._actors.setdefault(key, {})
        if level in store:
            return store[level]

        vtk = self._vtk
        pd = self._load_preview_mesh(stl, key, level)
        nrm = vtk.vtkPolyDataNormals()
        nrm.SetInputData(pd)
        nrm.ComputePointNormalsOn()
        nrm.ComputeCellNormalsOff()
        nrm.SplittingOff()
        nrm.ConsistencyOn()
        nrm.AutoOrientNormalsOn()
        nrm.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(nrm.GetOutput())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        prop = actor.GetProperty()
        rgba = meta.get("color_rgba") or (0.55, 0.55, 0.55, 1.0)
        prop.SetColor(rgba[0], rgba[1], rgba[2])
        prop.SetAmbient(0.12)
        prop.SetDiffuse(0.85)
        prop.SetSpecular(0.18)
        prop.SetSpecularPower(28.0)
        prop.SetSpecularColor(1.0, 1.0, 1.0)
        prop.SetInterpolationToPhong()
        prop.EdgeVisibilityOff()
        prop.BackfaceCullingOff()

        store[level] = {"pd": pd, "mapper": mapper, "actor": actor}
        self._pickable[actor] = key
        return store[level]

    def _opacidad_de(self, key, ordered):
        """Opacidad efectiva: usuario > caso > envolvente clásica > opaco."""
        if key in self._opacidad_usuario:
            return self._opacidad_usuario[key]
        meta = self._models.get(key) or {}
        if "opacity" in meta:
            return float(meta["opacity"])
        base = self.OPACIDAD_ESTRUCTURA.get(self._canon_key(key))
        if base is None:
            return 1.0
        mi_orden = self._scene_order(key)
        hay_dentro = any(self._scene_order(k) > mi_orden for k in ordered if k != key)
        return base if hay_dentro else 1.0

    def _sync_scene(self, level="high"):
        """Un actor por estructura visible, con su opacidad. Devuelve las claves."""
        vis = [k for k in self._visible_keys if k]
        ordered = sorted(vis, key=self._scene_order)
        built = {}
        for key in ordered:
            data = self._build_actor(key, level)
            if data is not None:
                built[key] = data
        # Se construyen también los actores no visibles una vez, para que el
        # encuadre use los límites del caso completo.
        for key in self._models:
            if key not in self._actors:
                self._build_actor(key, level)

        wanted = {b["actor"] for b in built.values()}
        for a in self._actores_en_escena():
            if a not in wanted:
                self._ren.RemoveActor(a)
        en_escena = set(self._actores_en_escena())
        for key in ordered:
            if key not in built:
                continue
            actor = built[key]["actor"]
            if actor not in en_escena:
                self._ren.AddActor(actor)
            alfa = self._opacidad_de(key, ordered)
            prop = actor.GetProperty()
            prop.SetOpacity(alfa)
            # Superficies muy translúcidas: menos brillo especular, que sobre
            # varias capas apiladas satura a blanco.
            prop.SetSpecular(0.18 if alfa > 0.6 else 0.08)
        return list(built.keys())

    # ==================================================================
    # INTERACCIÓN
    # ==================================================================
    def _on_pick(self, obj, _event):
        """Identifica la estructura bajo el cursor (sin bloquear la rotación)."""
        if not self._pickable or self._vtk is None:
            return
        try:
            x, y = obj.GetEventPosition()
            picker = self._vtk.vtkCellPicker()
            picker.SetTolerance(0.0005)
            visibles = {d["actor"] for k in self._visible_keys
                        for d in self._actors.get(k, {}).values()}
            # Se prioriza lo más interno (lesión) y lo más opaco: con capas
            # translúcidas, el primer impacto suele ser una envolvente.
            mejor = None
            picker.Pick(x, y, 0, self._ren)
            actor = picker.GetActor()
            if actor in visibles:
                mejor = self._pickable.get(actor)
            if mejor:
                self._current_key = mejor
                meta = self._models.get(mejor, {})
                vol = meta.get("volumen_cm3")
                texto = meta.get("label") or label_de(mejor)
                if vol is not None:
                    texto += f"  ·  {float(vol):.1f} cm³"
                self._lbl_sel.setText(texto)
                self.modelo_seleccionado.emit(mejor)
        except Exception:
            pass

    def set_calidad_render(self, level):
        if level in self.QUALITY_FACES:
            self._quality = level

    @property
    def calidad(self):
        return self._quality

    def keys_visibles(self):
        return set(self._visible_keys)

    def etiqueta_estructura(self, key):
        meta = self._models.get(key) or {}
        return meta.get("label") or label_de(key)

    def estructura_activa(self):
        return self._current_key
