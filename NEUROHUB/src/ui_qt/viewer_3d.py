"""
Visor 3D de NEUROHUB sobre VTK-Qt.

Porta la escena multi-modelo de `FBXPreviewPanel` (main.py) al widget nativo
`QVTKRenderWindowInteractor`. Se conserva TODO lo que hace que el render se
vea bien:

  * presupuesto de caras por estructura y por nivel de calidad
    (QUALITY_FACES: "high" en reposo, "medium" al arrastrar),
  * simplificacion con fast_simplification + cache por (ruta, nivel),
  * conversion vectorizada de la malla a vtkPolyData,
  * materiales PBR con Phong y normales suaves,
  * orden de dibujado (envolventes primero) y opacidad automatica del craneo
    y el cerebro cuando hay estructuras internas visibles.

La diferencia es que ya no hace falta renderizar offscreen y volcar a un
label: VTK dibuja directamente en el widget, asi que la imagen es nitida a
cualquier tamano y la interaccion va fluida con la camara propia de VTK.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy

from .software_config import COLOR_TEXTO_SEC, VIEW_BG_RGB
from .pbr import PBR_ALIASES, resolve_pbr, label_de


class Viewer3D(QWidget):
    """Visor interactivo de las mallas de la serie activa.

    Senales:
        modelo_seleccionado(str): el usuario ha pulsado sobre una estructura.
    """

    modelo_seleccionado = Signal(str)

    # Orden de dibujado: primero las superficies envolventes, despues las
    # estructuras internas. Es lo que hace posible la vista clinica de
    # craneo + cerebro + tumor superpuestos.
    ORDEN_ESCENA = ["craneo", "skull", "cerebro", "brain",
                    "tumor", "aneurisma"]

    # Opacidad de las envolventes: se vuelven semitransparentes solo cuando
    # hay algo visible dentro, para no tapar el tumor o los vasos.
    OPACIDAD_ESTRUCTURA = {"craneo": 0.28, "cerebro": 0.45}

    # Ver comentario de QUALITY_FACES en main.py: el techo de caras depende
    # del MODELO y no del tamano de la malla.
    QUALITY_FACES = {
        "high":   {"craneo": 900000, "cerebro": 700000, "default": 400000},
        "medium": {"craneo": 150000, "cerebro": 120000, "default": 80000},
    }
    MAX_FACES_ABSOLUTO = 1200000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._models = {}          # {clave: {stl, label, color_rgba, display}}
        self._visible_keys = set()
        self._current_key = None
        self._actors = {}          # {clave: {nivel: {"actor","mapper"}}}
        self._mesh_cache = {}      # {(ruta, nivel): trimesh.Trimesh}
        self._quality = "high"
        self._scene_key = None
        self._pickable = {}        # {vtkActor: clave}
        self._models_dir = None    # directorio de STL (ver mesh_store)

        self._vtk = None
        self._ren = None
        self._ren_win = None
        self._interactor = None

        self._construir_ui()
        self._inicializar_vtk()

    # ------------------------------------------------------------------
    def _construir_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._vtk_host = QWidget()
        self._vtk_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout.addWidget(self._vtk_host, 1)

        # Mensaje central cuando no hay nada que mostrar. Se hace visible/oculto
        # en lugar de recrear widgets para no perder el widget VTK.
        self._mensaje = QLabel("Cargue un estudio para comenzar")
        self._mensaje.setAlignment(Qt.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._mensaje.setStyleSheet(f"color: {COLOR_TEXTO_SEC}; font-size: 13px;")
        self._layout.addWidget(self._mensaje, 1)

    # ------------------------------------------------------------------
    def _inicializar_vtk(self):
        """Crea renderer, ventana e interactor (una sola vez)."""
        try:
            import vtk
            from vtkmodules.qt.QVTKRenderWindowInteractor import (
                QVTKRenderWindowInteractor)
        except Exception:
            self._mostrar_mensaje(
                "VTK no esta disponible.\nInstale vtk para ver el visor 3D.")
            return

        self._vtk = vtk
        self._ren = vtk.vtkRenderer()
        r, g, b = VIEW_BG_RGB
        self._ren.SetBackground(r, g, b)

        # Iluminacion de tres puntos (key + fill + rim), igual que en main.py:
        # sin la luz de borde las mallas pierden lectura de volumen.
        key = vtk.vtkLight()
        key.SetPosition(1.0, 0.5, 1.0)
        key.SetIntensity(1.0)
        key.SetColor(1.0, 1.0, 1.0)
        self._ren.AddLight(key)

        fill = vtk.vtkLight()
        fill.SetPosition(-0.8, 0.3, 0.5)
        fill.SetIntensity(0.5)
        fill.SetColor(0.9, 0.9, 0.95)
        self._ren.AddLight(fill)

        rim = vtk.vtkLight()
        rim.SetPosition(0.0, -1.0, 0.2)
        rim.SetIntensity(0.4)
        rim.SetColor(0.8, 0.85, 0.95)
        self._ren.AddLight(rim)

        self._ren.SetAmbient(0.2, 0.2, 0.22)

        self._interactor = QVTKRenderWindowInteractor(self._vtk_host)
        self._ren_win = self._interactor.GetRenderWindow()
        self._ren_win.AddRenderer(self._ren)
        self._interactor.Initialize()

        # Antialiasing por multisampling. FXAA queda DESACTIVADO a proposito:
        # combinado con MSAA produce un framebuffer vacio (medido en el visor
        # anterior con _diag_render.py), porque uno anula al otro.
        try:
            self._ren_win.SetMultiSamples(8)
        except Exception:
            pass

        # Depth peeling: DESACTIVADO a proposito.
        #
        # Con las envolventes translucidas (craneo 0.28, cerebro 0.45) el peeling
        # es lo correcto en teoria, pero medido en esta maquina (tests/
        # diag_actor.py, capturas f_con_peeling vs g_sin_peeling) hace que el
        # craneo y el cerebro NO SE DIBUJEN: el actor se queda sin celdas tras
        # el primer peel, porque con ~900k caras por estructura y 8 pases sobre
        # el mismo framebuffer el render se corta antes de completarlos. El
        # mismo actor, sin peeling, se ve perfecto.
        #
        # La mezcla por alfa (que es la que de verdad se ve) la hace VTK
        # igualmente y ordena los translucidos por profundidad, asi que el
        # resultado clinico es correcto. Si en otra GPU el peeling fuese
        # necesario, basta con poner esto a True.
        self._ren.SetUseDepthPeeling(0)

        cam = self._ren.GetActiveCamera()
        cam.SetPosition(0, 0, 1)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 1, 0)

        # Trackball estandar de VTK: rotar con boton izq., pan con boton der.
        # y zoom con la rueda.
        style = vtk.vtkInteractorStyleTrackballCamera()
        self._interactor.SetInteractorStyle(style)
        self._interactor.AddObserver("LeftButtonPressEvent", self._on_pick)

        self._vtk_host.show()
        self._mensaje.hide()

    # ------------------------------------------------------------------
    def _ajustar_tamano(self):
        """Propaga el tamano del widget a la ventana de render de VTK."""
        if self._ren_win is None:
            return
        w = max(self._vtk_host.width(), 50)
        h = max(self._vtk_host.height(), 50)
        self._ren_win.SetSize(w, h)
        self._ren_win.Render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar_tamano()

    def _mostrar_mensaje(self, texto):
        """Muestra el texto central y oculta el lienzo VTK."""
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
        """Reemplaza el catalogo de estructuras disponibles.

        `modelos` es el dict que devuelve `escanear_mallas`: clave -> {stl,
        label, color_rgba, display}. Se liberan los actores de los modelos que
        ya no existen para no acumular memoria en el renderer.
        """
        self._models = dict(modelos or {})

        # Descarta actores de estructuras que ya no estan.
        for key in list(self._actors):
            if key not in self._models:
                for data in self._actors.pop(key).values():
                    self._ren.RemoveActor(data["actor"])
                self._pickable.pop(data["actor"], None)

        if not self._models:
            self._limpiar_escena()
            self._mostrar_mensaje(
                "No hay modelos 3D.\nEjecute el pipeline para generarlos.")
            return

        # Si la estructura activa desaparecio, se toma la primera disponible.
        if self._current_key not in self._models:
            self._current_key = next(iter(self._models))
            self._visible_keys = {self._current_key}
        self._scene_key = None
        self._ocultar_mensaje()
        self.render()

    def _limpiar_escena(self):
        if self._ren is None:
            return
        coll = self._ren.GetActors()
        for i in range(coll.GetNumberOfItems()):
            self._ren.RemoveActor(coll.GetItemAsObject(i))
        self._actors.clear()
        self._mesh_cache.clear()
        self._pickable.clear()
        self._visible_keys.clear()
        self._current_key = None
        self._scene_key = None

    # ------------------------------------------------------------------
    def set_visible(self, keys):
        """Define el conjunto de estructuras visibles y re-renderiza."""
        validas = {k for k in (keys or []) if k in self._models}
        if not validas:
            self._limpiar_escena()
            self._mostrar_mensaje("Seleccione al menos una estructura visible.")
            return
        self._visible_keys = validas
        self._current_key = next(iter(validas))
        self.render()

    def _resolve_mallas_dir(self):
        return self._models_dir

    def set_models_dir(self, directorio):
        """Fija el directorio del que se toman los STL."""
        self._models_dir = directorio

    def refresh_from_disk(self):
        """Reescanea el directorio de mallas (tras ejecutar el pipeline)."""
        if not self._models_dir:
            return
        from .mesh_store import escanear_mallas
        self.set_models(escanear_mallas(self._models_dir))

    # ==================================================================
    # RENDER
    # ==================================================================
    def render(self, reset_camera=False):
        """Aplica la escena al renderer y dibuja."""
        if self._ren is None or self._vtk is None:
            return
        try:
            ordered = self._sync_scene(self._quality)
            if not ordered:
                self._mostrar_mensaje("No hay geometria disponible para mostrar.")
                return
            self._ocultar_mensaje()

            # El encuadre solo se recalcula cuando cambia la ESCENA, no en
            # cada rotacion, para que la vista no salte.
            escena_key = tuple(sorted(self._visible_keys))
            if reset_camera or escena_key != self._scene_key:
                self._ren.ResetCamera()
                self._ren.ResetCameraClippingRange()
                self._scene_key = escena_key

            self._ren_win.Render()
        except Exception as e:
            self._mostrar_mensaje(f"No se pudo renderizar el modelo:\n{e}")

    def reset_camera(self):
        """Reencuadra la vista (boton 'Restablecer vista')."""
        if self._ren is None:
            return
        self._ren.ResetCamera()
        self._ren.ResetCameraClippingRange()
        if self._ren_win is not None:
            self._ren_win.Render()

    def guardar_imagen(self, ruta):
        """Escribe la vista actual en un PNG. Devuelve True si se genero.

        Se usa `vtkWindowToImageFilter` en lugar de `WriteToPNG`, que VTK 9.7
        elimino de `vtkRenderWindow`. El filtro tambien fija el buffer como RGBA y
        descarta el canal alfa al escribir, de modo que el fondo oscuro del
        renderer sale opaco y no transparente.
        """
        if self._ren_win is None or not ruta:
            return False
        vtk = self._vtk
        if vtk is None:  # VTK no disponible: sin captura posible
            return False
        try:
            self._ren_win.Render()
            cap = vtk.vtkWindowToImageFilter()
            cap.SetInput(self._ren_win)
            cap.SetScale(1)
            cap.SetInputBufferTypeToRGBA()
            cap.ReadFrontBufferOff()
            cap.Update()

            esc = vtk.vtkPNGWriter()
            esc.SetFileName(ruta)
            esc.SetInputConnection(cap.GetOutputPort())
            esc.Write()
            return True
        except Exception:
            return False

    def _scene_order(self, key):
        """Indice de dibujado de `key` (menor = mas atras)."""
        for i, name in enumerate(self.ORDEN_ESCENA):
            if name in key:
                return i
        return len(self.ORDEN_ESCENA)

    def _canon_key(self, key):
        """Clave canonica de una estructura ("skull" -> "craneo", etc.)."""
        return PBR_ALIASES.get((key or "").lower(), (key or "").lower())

    # ==================================================================
    # CONSTRUCCION DE LA ESCENA
    # ==================================================================
    def _quality_faces(self, key, level):
        """Devuelve el techo de caras para `key` en el nivel `level` dado."""
        tabla = self.QUALITY_FACES.get(level, self.QUALITY_FACES["medium"])
        # Se normaliza la clave por si el archivo tiene un sufijo
        # ("cerebro_completo.stl") y asi hereda el presupuesto de su
        # estructura.
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
        """Carga y simplifica la malla al nivel pedido, con cache.

        Se cachea una version por (ruta, nivel): la de "high" para el estado de
        reposo y la de "medium" para el arrastre, de modo que cambiar de nivel
        en caliente no obliga a releer ni re-simplificar el STL.
        """
        import trimesh

        cache_key = (stl_path, level)
        if cache_key in self._mesh_cache:
            return self._mesh_cache[cache_key]

        mesh = trimesh.load(stl_path, force="mesh")
        n_faces = len(mesh.faces)
        objetivo = self._quality_faces(key, level)

        if n_faces > objetivo:
            try:
                import fast_simplification
                reduction = 1.0 - (objetivo / n_faces)
                verts, faces = fast_simplification.simplify(
                    mesh.vertices, mesh.faces, target_reduction=reduction)
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            except Exception:
                # Sin fast_simplification se dibuja la malla completa: mas
                # lenta, pero correcta.
                pass

        self._mesh_cache[cache_key] = mesh
        return mesh

    def _mesh_to_polydata(self, vs, faces):
        """Construye vtkPolyData de forma VECTORIZADA.

        Insertar punto por punto y triangulo por triangulo con bucles Python
        congela la interfaz con mallas de cientos de miles de caras, asi que
        los numpy arrays se convierten a VTK en un solo paso.
        """
        import numpy as np
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

        vs = np.ascontiguousarray(vs, dtype=np.float32)
        faces = np.ascontiguousarray(faces, dtype=np.int64)

        pd = self._vtk.vtkPolyData()

        pts = self._vtk.vtkPoints()
        pts.SetDataTypeToFloat()
        pts.SetData(numpy_to_vtk(vs, deep=True))
        pd.SetPoints(pts)

        n_faces = faces.shape[0]
        if n_faces > 0:
            conn = np.ascontiguousarray(faces.reshape(-1), dtype=np.int64)
            cells = self._vtk.vtkCellArray()
            cells.SetData(3, numpy_to_vtkIdTypeArray(conn, deep=True))
            pd.SetPolys(cells)

        return pd

    def _build_actor(self, key, level):
        """Crea (o recupera de cache) el actor de `key` en el nivel dado."""
        meta = self._models.get(key)
        stl = meta.get("stl") if meta else None
        if not stl or not os.path.isfile(stl):
            return None

        store = self._actors.setdefault(key, {})
        if level in store:
            return store[level]

        import numpy as np
        vtk = self._vtk
        mesh = self._load_preview_mesh(stl, key, level)
        pd = self._mesh_to_polydata(
            np.asarray(mesh.vertices, dtype=np.float64),
            np.asarray(mesh.faces, dtype=np.int64))

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(pd)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        # ========== RENDERIZADO DE ULTRADETALLE ==========
        # Propiedades PBR mejoradas para maxima fidelidad clinica.
        prop = actor.GetProperty()
        rgba = meta.get("color_rgba") or (0.55, 0.55, 0.55, 1.0)
        prop.SetColor(rgba[0], rgba[1], rgba[2])
        prop.SetAmbient(0.28)
        prop.SetDiffuse(0.72)
        prop.SetSpecular(0.35)          # Mayor especularidad
        prop.SetSpecularPower(64.0)     # Brillo puntuado (ultradetalle)
        prop.SetInterpolationToPhong()  # Suavizado por normales
        prop.EdgeVisibilityOff()
        try:
            # Roughness/metallic del PBR de la estructura, con valores por
            # defecto sensatos si el modelo no los trae.
            pbr = resolve_pbr(key)
            prop.SetMetallic(pbr.get("metallic", 0.0))
            prop.SetRoughness(pbr.get("roughness", 0.75))
        except Exception:
            pass

        # Normales suaves: sin esto Phong calcula la normal por cara y la
        # superficie se ve facetada aunque la malla sea lisa.
        try:
            nrm = vtk.vtkPolyDataNormals()
            nrm.SetInputData(pd)
            nrm.ComputePointNormalsOn()
            nrm.ComputeCellNormalsOff()
            nrm.SplittingOff()
            nrm.ConsistencyOn()
            nrm.AutoOrientNormalsOn()
            nrm.Update()
            mapper.SetInputData(nrm.GetOutput())
        except Exception:
            pass

        store[level] = {"pd": pd, "mapper": mapper, "actor": actor}
        self._pickable[actor] = key
        return store[level]

    def _sync_scene(self, level="high"):
        """Aplica al renderer la escena actual: un actor por modelo visible.

        Los actores se crean una vez y despues solo se les cambia la
        visibilidad, de modo que pasar de "medium" a "high" no rehace la escena
        entera. Devuelve la lista ordenada de claves visibles.
        """
        vis = [k for k in (self._visible_keys or {self._current_key}) if k]
        # Orden de dibujado: envolventes primero, estructuras internas luego.
        ordered = sorted(vis, key=self._scene_order)

        # Construir (o recuperar de cache) el actor de cada modelo visible.
        built = {}
        for key in ordered:
            actor_data = self._build_actor(key, level)
            if actor_data is not None:
                built[key] = actor_data

        # Quitar del renderer los actores que ya no se necesitan. La lista se
        # recorre primero y se borra despues: RemoveActor() compacta la
        # coleccion, asi que borrar durante el bucle se salta elementos y
        # dejaba estructuras ocultas visibles en pantalla.
        coll = self._ren.GetActors()
        wanted = {b["actor"] for b in built.values()}
        obsoletos = []
        for i in range(coll.GetNumberOfItems()):
            a = coll.GetItemAsObject(i)
            if a not in wanted:
                obsoletos.append(a)
        for a in obsoletos:
            self._ren.RemoveActor(a)
            # NO se quita de `_pickable`: el actor solo se apaga, no se
            # destruye. Si se borrara aqui, al volver a marcar la casilla la
            # estructura se dibujaria pero dejaria de ser seleccionable con el
            # raton. `_pickable` se limpia en `set_models`/`_limpiar_escena`,
            # que es donde los actores si se descartan de verdad.

        # Anadir / actualizar opacidad segun si hay estructuras dentro.
        for key in ordered:
            actor = built[key]["actor"]
            if actor not in self._ren.GetActors():
                self._ren.AddActor(actor)

            canon = self._canon_key(key)
            base_alpha = self.OPACIDAD_ESTRUCTURA.get(canon)
            if base_alpha is None:
                actor.GetProperty().SetOpacity(1.0)
            else:
                mi_orden = self._scene_order(key)
                # Hay algo visible mas "interior" (tumor, vasos) en la escena.
                hay_dentro = any(self._scene_order(k) > mi_orden
                                 for k in ordered if k != key)
                actor.GetProperty().SetOpacity(base_alpha if hay_dentro else 1.0)

        return list(built.keys())

    # ==================================================================
    # INTERACCION
    # ==================================================================
    def _on_pick(self, obj, event):
        """Selecciona la estructura pulsada en la vista 3D."""
        if not self._pickable:
            return
        try:
            x, y = obj.GetEventPosition()
            picker = self._vtk.vtkPropPicker()
            picker.Pick(x, y, 0, self._ren)
            actor = picker.GetActor()
            if actor is None:
                return
            key = self._pickable.get(actor)
            if key:
                self._current_key = key
                self.modelo_seleccionado.emit(key)
        except Exception:
            pass

    def set_calidad_render(self, level):
        """Fija el nivel de calidad del render: "high" o "medium"."""
        if level in self.QUALITY_FACES:
            self._quality = level

    @property
    def calidad(self):
        return self._quality

    def keys_visibles(self):
        return set(self._visible_keys)

    def etiqueta_estructura(self, key):
        """Nombre legible de la estructura (usado por el panel de capas)."""
        return label_de(key)

    def estructura_activa(self):
        return self._current_key
