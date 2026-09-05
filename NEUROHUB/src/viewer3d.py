"""
NEUROHUB - Visor 3D Interactivo con Pygame
==========================================
Renderiza mallas 3D reales (cerebro, cráneo, venas, arterias, tumor)
y volúmenes NIfTI/MR en 3D con pygame.

Controles:
  Arrastrar  = rotar        Rueda      = zoom
  C          = cerebro      K          = cráneo
  T          = tumor        V          = vasos
  A          = arterias     N          = venas
  M          = MRI slices   1          = modo malla
  2          = modo puntos
  4          = calidad (auto → 0.75x → 1x → 1.5x)
  R          = reset        3          = auto-rotar
  ESC        = salir
"""

import os
import sys
import time
import math
import numpy as np

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Colores (Dark Theme)
BLACK = (0, 0, 0)
DARK_GRAY = (20, 20, 24)
BORDER = (50, 50, 60)
TEXT = (244, 244, 246)
TEXT_DIM = (180, 180, 190)
ACCENT = (138, 180, 248)
TUMOR_MAGENTA = (200, 40, 220)
ANEURYSM_ORANGE = (255, 140, 0)
CEREBRO_COLOR = (148, 152, 168)
CRANEO_COLOR = (232, 224, 208)
VASO_COLOR = (200, 60, 60)
ARTERIA_COLOR = (220, 40, 40)
VENA_COLOR = (40, 80, 200)

# Directorio de mallas generadas
SALIDAS_DIR = os.path.join(os.path.dirname(SRC_DIR), "..", "salidas")
MALLAS_DIR = os.path.join(SALIDAS_DIR, "mallas")

# Presupuesto de caras por estructura en el visor. Las mallas gigantes
# (cráneo ~552k / cerebro ~225k / vasos ~167k caras) se deciman al cargar
# para que el render muestre TODAS las caras de cada estructura, de forma
# SÓLIDA y completa (no como los "puntitos" del submuestreo temporal de
# 15k caras por frame que dibujaba un 3% del cráneo en cada fotograma).
# Cuanto mayor sea la ventana, más detalle se puede permitir: la decimación
# deja las superficies suaves a 1280-1600 px.
MAX_FACES_POR_MALLA = {
    "craneo": 50000,
    "cerebro": 32000,
    "vasos": 32000,
}


class Pygame3DViewer:
    """Visor 3D de volumen médico con pygame."""

    QUALITY_MODES = ["auto", "0.75x", "1.0x", "1.5x"]

    @staticmethod
    def _pick_window_size(width, height):
        """Resolución de la ventana: la más alta que soporte el monitor.

        Prioridad: argumentos explícitos > variable de entorno
        NEUROHUB_RES=ANCHOxALTO > 85 % del escritorio
        (mínimo 1280x800, tope 2560x1600).
        """
        if width and height:
            return int(width), int(height)
        env = os.environ.get("NEUROHUB_RES", "")
        if "x" in env:
            try:
                w, h = env.lower().split("x")
                return max(800, int(w)), max(600, int(h))
            except Exception:
                pass
        try:
            import pygame
            if not pygame.get_init():
                pygame.init()
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = 1920, 1080
        w = max(1280, min(int(dw * 0.85), 2560))
        h = max(800, min(int(dh * 0.85), 1600))
        return w, h

    def __init__(self, width=None, height=None,
                 title="NEUROHUB - Visor 3D"):
        try:
            import pygame
        except ImportError:
            raise RuntimeError("pygame no está instalado. pip install pygame")
        self.pygame = pygame
        self.width, self.height = self._pick_window_size(width, height)
        self.title = title
        self.volume = None
        self.mask = None
        self.mask_aneurysm = None
        self.vessels = None
        self.spacing = (1, 1, 1)
        self.center = (0.5, 0.5, 0.5)
        self.rot_x = 20.0
        self.rot_y = -30.0
        self.zoom = 1.0
        self.slice_idx = 0
        self.show_volume = True
        self.show_mask = True
        self.show_aneurysm = True
        self.auto_rotate = False
        self._cube_verts = None
        self._cube_edges = None
        self._slice_data = None

        # Meshes 3D cargados desde STL
        self.meshes = {}
        self.mesh_visible = {
            "cerebro": True, "craneo": True, "tumor": True,
            "arterias": True, "venas": True, "vasos": True,
        }
        self.mesh_colors = {
            "cerebro": CEREBRO_COLOR, "craneo": CRANEO_COLOR,
            "tumor": TUMOR_MAGENTA, "arterias": ARTERIA_COLOR,
            "venas": VENA_COLOR, "vasos": VASO_COLOR,
        }
        self.render_mode = "malla"  # "malla" o "puntos"
        # Calidad de render (supersampling) en reposo: 0=auto (medido), o fixed
        self.quality_mode_idx = 0
        self.quality = 1.0

    # ---------------------------------------------------------------
    def load_meshes_from_stl(self, mallas_dir=None):
        """
        Carga las mallas 3D generadas (STL) para visualización.
        Cada estructura se muestra como superficie poligonal 3D real.

        Escala GLOBAL (una sola para todo el escenario): preserva el tamaño
        relativo real entre estructuras. Antes cada malla se normalizaba POR
        SEPARADO a 1.2 unidades, así que el tumor (hoy ~61 mm reales, antes
        175 mm) se dibujaba del mismo tamaño que el cráneo (218 mm) — de ahí
        que pareciera un tumor del tamaño del cerebro.
        """
        import trimesh

        mallas_dir = mallas_dir or MALLAS_DIR
        if not os.path.isdir(mallas_dir):
            print(f"[3D] Mallas no encontradas en: {mallas_dir}")
            return False

        cargadas = {}
        global_span = 0.0  # mayor extensión física de TODAS las mallas (mm)
        for fname in sorted(os.listdir(mallas_dir)):
            if not fname.lower().endswith(".stl"):
                continue
            nombre = os.path.splitext(fname)[0]
            path = os.path.join(mallas_dir, fname)
            try:
                mesh = trimesh.load(path)
                verts = np.asarray(mesh.vertices, dtype=np.float64)
                faces = np.asarray(mesh.faces, dtype=np.int64)

                # Modelo completo en el visor: decimar las mallas que superan
                # el presupuesto (preserva la forma y permite dibujarlo entero).
                objetivo = MAX_FACES_POR_MALLA.get(nombre, 24000)
                if len(faces) > objetivo:
                    md = trimesh.Trimesh(vertices=verts, faces=faces,
                                         process=False)
                    md = md.simplify_quadric_decimation(face_count=objetivo)
                    verts = np.asarray(md.vertices, dtype=np.float64)
                    faces = np.asarray(md.faces, dtype=np.int64)

                # Versión "lite" (~1/4 caras): se usa SOLO durante el arrastre
                # y la auto-rotación para que la rotación siga fluida aunque el
                # detalle completo se reserve para cuando la cámara se detiene.
                objetivo_lite = max(4000, objetivo // 4)
                if len(faces) > objetivo_lite:
                    md_lite = trimesh.Trimesh(vertices=verts, faces=faces,
                                              process=False)
                    md_lite = md_lite.simplify_quadric_decimation(
                        face_count=objetivo_lite)
                    faces_lite = np.asarray(md_lite.faces, dtype=np.int64)
                else:
                    faces_lite = faces

                verts_c = verts - verts.mean(axis=0)
                max_span = float(np.abs(verts_c).max())
                global_span = max(global_span, max_span)
                cargadas[nombre] = {"verts": verts_c, "faces": faces,
                                    "faces_lite": faces_lite,
                                    "span": max_span}
                print(f"[3D] Malla cargada: {nombre} "
                      f"({len(verts)} verts, {len(faces)} faces, "
                      f"span={max_span:.1f} mm)")
            except Exception as e:
                print(f"[3D] Error cargando {fname}: {e}")

        if not cargadas or global_span <= 0:
            self.meshes = {}
            return False

        # Factor ÚNICO de escala: el cráneo ocupa 1.2 unidades y el resto
        # queda en proporción real (cerebro ≈ 0.8, tumor ≈ 0.28, vasos ≈ 0.8).
        escala = 1.2 / global_span
        self.meshes = {
            nombre: {"verts": info["verts"] * escala,
                     "faces": info["faces"],
                     "faces_lite": info["faces_lite"]}
            for nombre, info in cargadas.items()
        }
        return len(self.meshes) > 0

    # ---------------------------------------------------------------
    def load_nifti(self, nifti_path, mask_path=None, aneurysm_path=None,
                   vessels_path=None):
        """Carga volumen NIfTI o serie DICOM y sus máscaras."""
        import SimpleITK as sitk
        try:
            # Soporte DICOM: directorio o .dcm también pasan por cargar_volumen
            import data_manager as dm
            img = dm.cargar_volumen(nifti_path)
            if img is None:
                print(f"[3D] No se pudo cargar: {nifti_path}")
                return False
            self.volume = sitk.GetArrayFromImage(img).astype(np.float32)
            self.spacing = img.GetSpacing()
            m, M = self.volume.min(), self.volume.max()
            if M > m:
                self.volume = (self.volume - m) / (M - m)
            self.center = (self.volume.shape[2] / 2,
                           self.volume.shape[1] / 2,
                           self.volume.shape[0] / 2)
            self._build_cube()
            self._compute_slices()
        except Exception as e:
            print(f"[3D] Error cargando volumen: {e}")
            return False

        if mask_path and os.path.exists(mask_path):
            try:
                mi = sitk.ReadImage(mask_path)
                self.mask = (sitk.GetArrayFromImage(mi) > 0).astype(np.uint8)
            except Exception:
                self.mask = None
        if aneurysm_path and os.path.exists(aneurysm_path):
            try:
                ai = sitk.ReadImage(aneurysm_path)
                self.mask_aneurysm = (sitk.GetArrayFromImage(ai) > 0).astype(np.uint8)
            except Exception:
                self.mask_aneurysm = None
        if vessels_path and os.path.exists(vessels_path):
            try:
                vi = sitk.ReadImage(vessels_path)
                self.vessels = (sitk.GetArrayFromImage(vi) > 0).astype(np.uint8)
            except Exception:
                self.vessels = None
        return True

    # ---------------------------------------------------------------
    def _build_cube(self):
        if self.volume is None:
            return
        d, h, w = self.volume.shape
        self._cube_verts = np.array([
            [0, 0, 0], [w, 0, 0], [w, h, 0], [0, h, 0],
            [0, 0, d], [w, 0, d], [w, h, d], [0, h, d]], dtype=float)
        self._cube_edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)]

    def _compute_slices(self):
        """Precomputa slices 2D para las 3 vistas."""
        self._slice_data = {"axial": None, "coronal": None, "sagital": None}
        if self.volume is None:
            return
        d, h, w = self.volume.shape
        z = min(d - 1, max(0, self.slice_idx))
        y = h // 2
        x = w // 2
        self._slice_data["axial"] = self.volume[z, :, :]
        self._slice_data["coronal"] = self.volume[:, y, :]
        self._slice_data["sagital"] = self.volume[:, :, x]

    def _project(self, x, y, z):
        """Proyecta punto 3D a 2D con rotación."""
        cos_x = math.cos(math.radians(self.rot_x))
        sin_x = math.sin(math.radians(self.rot_x))
        y2 = y * cos_x - z * sin_x
        z2 = y * sin_x + z * cos_x
        cos_y = math.cos(math.radians(self.rot_y))
        sin_y = math.sin(math.radians(self.rot_y))
        x3 = x * cos_y + z2 * sin_y
        scale = min(self.width, self.height) * 0.35 * self.zoom
        sx = self.width / 2 + x3 * scale
        sy = self.height / 2 - y2 * scale
        return sx, sy

    # ---------------------------------------------------------------
    def render(self):
        """Bucle principal de renderizado."""
        pygame = self.pygame
        pygame.init()
        screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(self.title)
        clock = pygame.time.Clock()
        font = pygame.font.SysFont("consolas", 13, bold=True)

        running = True
        dragging = False
        last_mouse = (0, 0)
        mesh_dirty = True   # el primer frame dibuja las mallas COMPLETAS
        # Los "puntitos" salían del barrido temporal: 15k caras/frame. Ahora
        # se dibujan TODAS las caras cuando cambia la cámara y se reutiliza
        # ese frame (cache) mientras no hay interacción.
        cache_surface = pygame.Surface((self.width, self.height))

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        dragging = True
                        last_mouse = pygame.mouse.get_pos()
                    elif event.button == 4:
                        self.zoom *= 1.1
                    elif event.button == 5:
                        self.zoom /= 1.1
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        dragging = False
                elif event.type == pygame.MOUSEMOTION and dragging:
                    dx = event.pos[0] - last_mouse[0]
                    dy = event.pos[1] - last_mouse[1]
                    self.rot_y += dx * 0.5
                    self.rot_x += dy * 0.5
                    self.rot_x = max(-90, min(90, self.rot_x))
                    last_mouse = event.pos
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.rot_x, self.rot_y, self.zoom = 20, -30, 1.0
                    elif event.key == pygame.K_UP:
                        self.slice_idx += 1
                        self._compute_slices()
                    elif event.key == pygame.K_DOWN:
                        self.slice_idx -= 1
                        self._compute_slices()
                    elif event.key == pygame.K_3:
                        self.auto_rotate = not self.auto_rotate
                    elif event.key == pygame.K_m:
                        self.show_volume = not self.show_volume
                    elif event.key == pygame.K_b:
                        self.show_mask = not self.show_mask
                    # Toggle estructuras 3D
                    elif event.key == pygame.K_c:
                        self.mesh_visible["cerebro"] = not self.mesh_visible["cerebro"]
                    elif event.key == pygame.K_k:
                        self.mesh_visible["craneo"] = not self.mesh_visible["craneo"]
                    elif event.key == pygame.K_t:
                        self.mesh_visible["tumor"] = not self.mesh_visible["tumor"]
                    elif event.key == pygame.K_a:
                        self.mesh_visible["arterias"] = not self.mesh_visible["arterias"]
                    elif event.key == pygame.K_n:
                        self.mesh_visible["vasos"] = not self.mesh_visible["vasos"]
                    elif event.key == pygame.K_v:
                        self.mesh_visible["venas"] = not self.mesh_visible["venas"]
                    # Modos de renderizado
                    elif event.key == pygame.K_1:
                        self.render_mode = "malla"
                    elif event.key == pygame.K_2:
                        self.render_mode = "puntos"
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        dragging = True
                        last_mouse = pygame.mouse.get_pos()
                    elif event.button == 4:
                        self.zoom *= 1.1
                        mesh_dirty = True
                    elif event.button == 5:
                        self.zoom /= 1.1
                        mesh_dirty = True
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        dragging = False
                        mesh_dirty = True   # render final sin recorte (nítido)
                elif event.type == pygame.MOUSEMOTION and dragging:
                    dx = event.pos[0] - last_mouse[0]
                    dy = event.pos[1] - last_mouse[1]
                    self.rot_y += dx * 0.5
                    self.rot_x += dy * 0.5
                    self.rot_x = max(-90, min(90, self.rot_x))
                    last_mouse = event.pos
                    mesh_dirty = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_r:
                        self.rot_x, self.rot_y, self.zoom = 20, -30, 1.0
                        mesh_dirty = True
                    elif event.key == pygame.K_UP:
                        self.slice_idx += 1
                        self._compute_slices()
                    elif event.key == pygame.K_DOWN:
                        self.slice_idx -= 1
                        self._compute_slices()
                    elif event.key == pygame.K_3:
                        self.auto_rotate = not self.auto_rotate
                        mesh_dirty = True
                    elif event.key == pygame.K_m:
                        self.show_volume = not self.show_volume
                    elif event.key == pygame.K_b:
                        self.show_mask = not self.show_mask
                    # Toggle estructuras 3D
                    elif event.key == pygame.K_c:
                        self.mesh_visible["cerebro"] = not self.mesh_visible["cerebro"]
                        mesh_dirty = True
                    elif event.key == pygame.K_k:
                        self.mesh_visible["craneo"] = not self.mesh_visible["craneo"]
                        mesh_dirty = True
                    elif event.key == pygame.K_t:
                        self.mesh_visible["tumor"] = not self.mesh_visible["tumor"]
                        mesh_dirty = True
                    elif event.key == pygame.K_a:
                        self.mesh_visible["arterias"] = not self.mesh_visible["arterias"]
                        mesh_dirty = True
                    elif event.key == pygame.K_n:
                        self.mesh_visible["vasos"] = not self.mesh_visible["vasos"]
                        mesh_dirty = True
                    elif event.key == pygame.K_v:
                        self.mesh_visible["venas"] = not self.mesh_visible["venas"]
                        mesh_dirty = True
                    # Modos de renderizado
                    elif event.key == pygame.K_1:
                        self.render_mode = "malla"
                        mesh_dirty = True
                    elif event.key == pygame.K_2:
                        self.render_mode = "puntos"
                        mesh_dirty = True
                    elif event.key == pygame.K_4:
                        # Cicla calidad: auto -> 0.75x -> 1.0x -> 1.5x
                        self.quality_mode_idx = (self.quality_mode_idx + 1) % 4
                        if self.quality_mode_idx == 0:
                            self.quality = 1.0  # vuelve a auto-calibrarse
                        else:
                            self.quality = (
                                0.75, 1.0, 1.5)[self.quality_mode_idx - 1]
                        print(f"[3D] Calidad: {self.QUALITY_MODES[self.quality_mode_idx]}")
                        mesh_dirty = True
                    elif event.key == pygame.K_ESCAPE:
                        running = False

            if self.auto_rotate:
                self.rot_y += 0.5
                mesh_dirty = True

            screen.fill(DARK_GRAY)

            # Mallas 3D: se redibujan POR COMPLETO solo cuando cambió la cámara
            # o las estructuras visibles; si no, se reutiliza el frame cacheado.
            # Durante el arrastre / auto-rotación se renderiza a menor
            # resolución (más ágil) y al soltar se redibuja al 100% (nítido).
            # Resolución dinámica:
            #  - al arrastrar / auto-rotar: 0.5x con las mallas "lite" (ágil;
            #    el smoothscale permite ver el último frame completo).
            #  - en reposo: self.quality (auto se calibra entre 0.75x y 1.5x
            #    según lo que el equipo logre redibujar sin ir lento).
            if dragging or self.auto_rotate:
                mesh_scale = 0.5
            else:
                mesh_scale = self.quality
            cw = max(16, int(self.width * mesh_scale))
            ch = max(16, int(self.height * mesh_scale))
            if cache_surface.get_size() != (cw, ch):
                cache_surface = pygame.Surface((cw, ch))
                mesh_dirty = True

            if mesh_dirty:
                cache_surface.fill(DARK_GRAY)
                t0 = time.perf_counter()
                self._render_meshes(
                    cache_surface, lite=(dragging or self.auto_rotate))
                dt = time.perf_counter() - t0
                mesh_dirty = False
                # Auto-calibración en reposo: si redibujar todo tarda mucho,
                # baja la resolución; si sobra tiempo, la sube.
                if mesh_scale >= 1.0 and self.quality_mode_idx == 0:
                    if dt > 0.8:
                        self.quality = max(0.75, self.quality * 0.75)
                    elif dt < 0.30:
                        self.quality = min(1.5, self.quality * 1.2)

            if cache_surface.get_size() != (self.width, self.height):
                screen.blit(pygame.transform.smoothscale(
                    cache_surface, (self.width, self.height)), (0, 0))
            else:
                screen.blit(cache_surface, (0, 0))

            # Luego el volumen de referencia
            self._render_volume(screen, font)

            # Info bar
            qlabel = "auto" if self.quality_mode_idx == 0 \
                else f"{self.quality:.2f}x"
            info = [
                ("NEUROHUB - VISOR 3D", ACCENT),
                ("", None),
                ("Arrastrar: rotar | Rueda: zoom | Up/Down: slices", TEXT_DIM),
                ("C:cerebro K:craneo T:tumor A:arterias V:venas N:vasos", TEXT_DIM),
                ("1:malla 2:puntos 3:auto 4:calidad R:reset ESC:salir", TEXT_DIM),
                (f"res={self.width}x{self.height}  calidad={qlabel}", TEXT_DIM),
            ]
            y = 10
            for text, color in info:
                surf = font.render(text, True, color or TEXT)
                screen.blit(surf, (10, y))
                y += 18

            # === CORRECCIÓN: sin display.flip() la ventana quedaba en negro ===
            # Todo lo dibujado vive en el buffer; hace falta presentarlo.
            pygame.display.flip()
            # Limitar a 30 FPS (evita 100% CPU y da CPU al render submuestreado)
            clock.tick(30)

    # ---------------------------------------------------------------
    def _render_meshes(self, screen, lite=False):
        """
        Renderiza las mallas 3D POR COMPLETO (todas sus caras, sin submuestreo).

        Antes se dibujaban solo 15.000 caras por frame con un barrido temporal:
        en un instante concreto el cráneo (552k caras) o el cerebro (225k)
        solo mostraban ~3% de sus triángulos, con pinta de nube de puntos
        ("puntitos"). Ahora las mallas grandes se deciman al cargar
        (cráneo ~50k, cerebro ~32k, vasos ~32k) y aquí se proyectan TODAS las
        caras de cada estructura en cada redibujado, ordenadas de lejos a
        cerca, para que la superficie se vea sólida y completa.

        Argumento lite: durante el arrastre / auto-rotación se usan las mallas
        "lite" (~1/4 caras) para mantener la fluidez; la versión completa se
        reserva para los fotogramas en reposo (alta resolución).
        """
        pygame = self.pygame
        if not self.meshes:
            return

        W, H = screen.get_size()

        # Pre-calcular matriz de rotación
        cos_x = math.cos(math.radians(self.rot_x))
        sin_x = math.sin(math.radians(self.rot_x))
        cos_y = math.cos(math.radians(self.rot_y))
        sin_y = math.sin(math.radians(self.rot_y))
        scale = min(W, H) * 0.35 * self.zoom
        cx = W / 2
        cy = H / 2

        for nombre, mesh_data in self.meshes.items():
            if not self.mesh_visible.get(nombre, True):
                continue
            verts = mesh_data["verts"]
            faces = mesh_data["faces_lite" if lite else "faces"]
            if len(verts) == 0 or len(faces) == 0:
                continue
            color = self.mesh_colors.get(nombre, (200, 200, 200))

            # Modo puntos: nube de vértices (solo si el usuario lo pide con '2')
            if self.render_mode == "puntos":
                step = max(1, len(verts) // 3000)
                pts = verts[::step]
                px = np.empty(len(pts))
                py = np.empty(len(pts))
                for i in range(len(pts)):
                    x, y, z = pts[i]
                    y2 = y * cos_x - z * sin_x
                    z2 = y * sin_x + z * cos_x
                    x3 = x * cos_y + z2 * sin_y
                    px[i] = cx + x3 * scale
                    py[i] = cy - y2 * scale
                valid = ((px > -10) & (px < W + 10) &
                         (py > -10) & (py < H + 10))
                for i in np.where(valid)[0]:
                    pygame.draw.circle(screen, color,
                                       (int(px[i]), int(py[i])), 1)
                continue

            # Modo malla: TODAS las caras, proyección vectorizada.
            # Back-face culling (el mismo criterio que antes) descarta ~50% de
            # las caras y evita pintar la cara interna de las cáscaras.
            fv0 = verts[faces[:, 0]]
            A = fv0; B = verts[faces[:, 1]]; C = verts[faces[:, 2]]
            N = np.cross(B - A, C - A)
            nz_v = (N[:, 0] * sin_y +
                    (N[:, 1] * sin_x + N[:, 2] * cos_x) * cos_y)
            caras = np.where(nz_v < 0)[0]
            if len(caras) == 0:
                continue
            # --- profundidad real en espacio de cámara: ordenar lejos -> cerca
            fv = verts[faces[caras]]
            y2 = fv[:, :, 1] * cos_x - fv[:, :, 2] * sin_x
            z2 = fv[:, :, 1] * sin_x + fv[:, :, 2] * cos_x
            z3 = -fv[:, :, 0] * sin_y + z2 * cos_y
            depth = z3.mean(axis=1)
            order = np.argsort(depth)[::-1]          # lejos primero
            sel = caras[order]

            # --- proyección vectorizada de TODAS las caras visibles ---
            fv = verts[faces[sel]]
            X, Y, Z = fv[:, :, 0], fv[:, :, 1], fv[:, :, 2]
            y2 = Y * cos_x - Z * sin_x
            z2 = Y * sin_x + Z * cos_x
            x3 = X * cos_y + z2 * sin_y
            PX = cx + x3 * scale
            PY = cy - y2 * scale

            # Descartar caras totalmente fuera de pantalla (raster holgado)
            in_x = (PX > -200) & (PX < W + 200)
            in_y = (PY > -200) & (PY < H + 200)
            keep = (in_x & in_y).all(axis=1)
            sel = sel[keep]
            if len(sel) == 0:
                continue
            fv = fv[keep]
            X, Y, Z = fv[:, :, 0], fv[:, :, 1], fv[:, :, 2]
            y2 = Y * cos_x - Z * sin_x
            z2 = Y * sin_x + Z * cos_x
            x3 = X * cos_y + z2 * sin_y
            PX = cx + x3 * scale
            PY = cy - y2 * scale

            # Sombreado simple según profundidad normalizada (cerca = brillante)
            depth = depth[keep]
            dmin, dmax = depth.min(), depth.max()
            if dmax > dmin:
                nrm = (depth - dmin) / (dmax - dmin)
                shade = 1.0 - 0.40 * nrm
            else:
                shade = np.ones_like(depth)
            col_r = int(color[0]); col_g = int(color[1]); col_b = int(color[2])

            for i in range(len(sel)):
                pts2d = [(int(PX[i, 0]), int(PY[i, 0])),
                         (int(PX[i, 1]), int(PY[i, 1])),
                         (int(PX[i, 2]), int(PY[i, 2]))]
                s = float(shade[i])
                col = (int(col_r * s), int(col_g * s), int(col_b * s))
                try:
                    pygame.draw.polygon(screen, col, pts2d)
                except Exception:
                    pass
    # ---------------------------------------------------------------
    def _render_volume(self, screen, font):
        """Renderiza el volumen de referencia."""
        pygame = self.pygame

        if self._cube_verts is not None:
            proj = []
            for v in self._cube_verts:
                p = self._project(v[0], v[1], v[2])
                proj.append((int(p[0]), int(p[1])))
            for e in self._cube_edges:
                pygame.draw.line(screen, BORDER, proj[e[0]], proj[e[1]], 1)

        if self._slice_data is not None and self.show_volume:
            self._draw_slice_panels(screen, font)

        if self.mask is not None and self.show_mask:
            self._draw_mask_points(screen, self.mask, TUMOR_MAGENTA)
        if self.mask_aneurysm is not None and self.show_aneurysm:
            self._draw_mask_points(screen, self.mask_aneurysm, ANEURYSM_ORANGE)

        ly = self.height - 70
        for name, color in [("Tumor", TUMOR_MAGENTA),
                            ("Aneurisma", ANEURYSM_ORANGE)]:
            pygame.draw.rect(screen, color, (10, ly, 12, 12))
            sx = font.render(name, True, TEXT)
            screen.blit(sx, (28, ly - 2))
            ly += 18

    def _draw_slice_panels(self, screen, font):
        """Dibuja cortes axial/coronal/sagital en las esquinas."""
        pygame = self.pygame
        pw, ph = 140, 90
        m = 10
        y0 = self.height - ph - m
        labels = ["AXIAL", "CORONAL", "SAGITAL"]
        spots = [(m, y0), (m + pw + 6, y0), (m + 2 * (pw + 6), y0)]

        for (key, label), (x0, yy) in zip(
                zip(["axial", "coronal", "sagital"], labels), spots):
            data = self._slice_data.get(key)
            if data is None:
                continue
            norm = (data - data.min()) / (np.ptp(data) + 1e-8)
            arr8 = (norm * 255).astype(np.uint8)
            try:
                surf = pygame.surfarray.make_surface(
                    np.stack([arr8, arr8, arr8], axis=-1))
                surf = pygame.transform.scale(surf, (pw, ph))
                screen.blit(surf, (x0, yy))
                pygame.draw.rect(screen, ACCENT, (x0, yy, pw, ph), 1)
                lb = font.render(label, True, ACCENT)
                screen.blit(lb, (x0 + 3, yy - 1))
            except Exception:
                pass

    def _draw_mask_points(self, screen, mask, color):
        """Dibuja la máscara como un cubo contorno."""
        pygame = self.pygame
        if mask is None or mask.sum() == 0:
            return
        coords = np.argwhere(mask)
        if len(coords) < 5:
            return
        mins = coords.min(axis=0)
        maxs = coords.max(axis=0)
        corners = np.array([
            [mins[2], mins[1], mins[0]], [maxs[2], mins[1], mins[0]],
            [maxs[2], maxs[1], mins[0]], [mins[2], maxs[1], mins[0]],
            [mins[2], mins[1], maxs[0]], [maxs[2], mins[1], maxs[0]],
            [maxs[2], maxs[1], maxs[0]], [mins[2], maxs[1], maxs[0]]])
        proj = []
        for c in corners:
            p = self._project(c[0], c[1], c[2])
            proj.append((int(p[0]), int(p[1])))
        edges = [(0, 1), (1, 2), (2, 3), (3, 0),
                 (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        for e in edges:
            pygame.draw.line(screen, color, proj[e[0]], proj[e[1]], 2)


def launch_viewer(nifti_path=None, mask_path=None, aneurysm_path=None,
                  vessels_path=None, title="NEUROHUB - Visor 3D",
                  cargar_mallas=True):
    """Lanza el visor 3D."""
    v = Pygame3DViewer(title=title)
    if nifti_path:
        v.load_nifti(nifti_path, mask_path, aneurysm_path, vessels_path)
    if cargar_mallas:
        v.load_meshes_from_stl()
    v.render()
    return v


if __name__ == "__main__":
    launch_viewer()

