"""
=====================================================================
 PROYECTO ATLAS - Interfaz Profesional Dark
 Segmentación y Modelado 3D de Neuroimágenes
=====================================================================
"""

import os
import re
import struct
import sys
import threading
import queue
import time
import traceback
import subprocess
from datetime import datetime
from pathlib import Path

# Añadir src al path
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import customtkinter as ctk
from tkinter import filedialog, messagebox

# Configuración de la interfaz
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# =====================================================================
# CONSTANTES
# =====================================================================
APP_NAME = "PROYECTO ATLAS"
APP_VERSION = "1.0.0"
APP_SUBTITLE = "Segmentación y Modelado 3D de Neuroimágenes"

COLORS = {
    # ---- Fondos: negro real + superficies Material 3 Dark (neutras, apagadas) ----
    "bg": "#000000",            # Ventana / fondo principal (alto contraste)
    "bg_secondary": "#16161a",  # Sidebar y encabezados (elevación 1)
    "bg_card": "#1e1e24",       # Tarjetas / botones tonales (elevación 2)
    "bg_input": "#26262c",      # Campos de entrada / chips (elevación 3)
    # ---- Acento azul tonal (muted, WCAG AA sobre superficies oscuras) ----
    "accent": "#8ab4f8",
    "accent_hover": "#a8c7fa",
    "accent_light": "#b6cdfc",  # Texto acento / valores
    "on_accent": "#0f1419",     # Texto sobre botones primarios (contraste AA)
    # ---- Semánticos apagados (alto contraste sobre superficie oscura) ----
    "success": "#82d692",
    "success_hover": "#5fb97d",
    "warning": "#f0bf72",
    "danger": "#f19aa1",
    # ---- Texto y bordes (WCAG AA+) ----
    "text": "#f4f4f6",
    "text_secondary": "#b4b4be",
    "border": "#33333c",
}
# Rutas base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
MODELOS_DIR = os.path.join(os.path.dirname(BASE_DIR), "modelos_3d")
SALIDAS_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")
MODELOS_PT_DIR = os.path.join(os.path.dirname(BASE_DIR), "modelos_preentrenados")

# Fuentes de la interfaz: familia principal (moderna/legible), títulos llamativos y emojis.
FONT_FAMILY = "Segoe UI"
FONT_TITLE = "Bahnschrift"
FONT_EMOJI = "Segoe UI Emoji"


def _register_bundled_fonts():
    """Registra en Windows (privadas al proceso) las fuentes empaquetadas en assets/fonts.

    Permite usar tipografías como Montserrat (OFL) sin instalarlas en el sistema.
    Devuelve la lista de nombres de archivo registrados.
    """
    if os.name != "nt":
        return []
    import ctypes
    fonts_dir = os.path.join(BASE_DIR, "assets", "fonts")
    if not os.path.isdir(fonts_dir):
        return []
    registered = []
    for fname in sorted(os.listdir(fonts_dir)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        path = os.path.join(fonts_dir, fname)
        try:
            # FR_PRIVATE=0x10: fuente visible solo para este proceso (sin permisos de admin).
            if ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0) != 0:
                registered.append(fname)
        except Exception:
            continue
    return registered


# Si Montserrat (o variante) quedó registrada, úsala para los títulos (fallback Bahnschrift).
if any("montserrat" in _f.lower() for _f in _register_bundled_fonts()):
    FONT_TITLE = "Montserrat"

# Blender opcional (reservado): la detección se conserva por compatibilidad aunque la
# interfaz ya no ofrece el botón de render con Blender.
BLENDER_PATH_ENV = "BLENDER_PATH"

# =====================================================================
# COLORES DE MATERIALES PBR (fuente única para exportación FBX y visor 3D)
# =====================================================================
# Cada entrada define color RGBA (0-1), rugosidad, metálico, emisión y subsurface,
# tal como los usa 01_procesamiento_dicom.export_stl_to_single_fbx. Incluye también
# un color sRGB y nombre legible para la UI del visor 3D.
PBR_COLORS = {
    "cerebro": dict(
        color_rgba=(0.76, 0.60, 0.58, 0.85),
        roughness=0.75, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.35,
        subsurface_color=(0.9, 0.45, 0.35, 1.0),
        display="#C99A91", label="Cerebro",
    ),
    "craneo": dict(
        color_rgba=(0.92, 0.88, 0.78, 1.0),
        roughness=0.85, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.08,
        subsurface_color=(1.0, 0.95, 0.80, 1.0),
        display="#EAE0C7", label="Cráneo",
    ),
    "tumor": dict(
        color_rgba=(0.40, 0.00, 0.90, 1.0),
        roughness=0.45, metallic=0.0,
        emission=(0.30, 0.00, 0.60, 1.0), subsurface=0.10,
        subsurface_color=(0.6, 0.0, 0.8, 1.0),
        display="#6600E6", label="Tumor",
    ),
    "venas_arterias": dict(
        color_rgba=(0.85, 0.05, 0.05, 1.0),
        roughness=0.20, metallic=0.05,
        emission=(0, 0, 0, 1), subsurface=0.20,
        subsurface_color=(1.0, 0.2, 0.2, 1.0),
        display="#D90D0D", label="Venas y Arterias",
    ),
    "aneurisma": dict(
        color_rgba=(1.00, 0.55, 0.00, 1.0),
        roughness=0.35, metallic=0.0,
        emission=(1.00, 0.35, 0.00, 1.0), subsurface=0.05,
        subsurface_color=(1.0, 0.6, 0.2, 1.0),
        display="#FF8C00", label="Aneurisma",
    ),
}

def _resolve_lnk_target(lnk_path):
    """Extrae la ruta objetivo (Windows) de un acceso directo .lnk (formato Shell Link)."""
    try:
        with open(lnk_path, 'rb') as fh:
            data = fh.read()
        if len(data) < 120 or not data.startswith(b'\x4c\x00\x00\x00'):
            return None
        header_flags = struct.unpack_from('<I', data, 20)[0]
        off = 76
        if header_flags & 0x1:  # HasLinkTargetIDList
            idl_size = struct.unpack_from('<H', data, off)[0]
            off += 2 + idl_size
        # Intento 1: campo LocalBasePath del bloque LinkInfo (.lnk convencionales)
        if off + 28 <= len(data):
            link_info_size = struct.unpack_from('<I', data, off)[0]
            if 28 <= link_info_size <= len(data) - off:
                link_info = data[off:off + link_info_size]
                li_flags = struct.unpack_from('<I', link_info, 8)[0]
                if li_flags & 0x1:  # VolumeIDAndLocalBasePath
                    local_base_path_offset = struct.unpack_from('<I', link_info, 16)[0]
                    if 0 < local_base_path_offset <= len(link_info) - 2:
                        raw = link_info[local_base_path_offset:]
                        end = raw.find(b'\x00\x00')
                        if end > 0:
                            raw = raw[:end]
                        target = raw.decode('utf-16-le', 'ignore').rstrip('\x00')
                        if ':' in target and '\\' in target:
                            return target
        # Intento 2 (robusto): buscar cualquier ruta 'X:\...\*.exe|cmd|bat' como
        # cadena UTF-16 en todo el archivo, probando ambas alineaciones de bytes.
        for byte_off in (0, 1):
            text = data[byte_off:].decode('utf-16-le', 'ignore')
            for m in re.finditer(r'[A-Za-z]:\\.+?\.(?:exe|cmd|bat)\x00', text):
                t = m.group(0).rstrip('\x00')
                if t and ('\\' in t):
                    return t
        return None
    except Exception:
        return None


def _iter_blender_lnk():
    """Itera los accesos directos .lnk con 'Blender' en el nombre del menú de inicio."""
    import glob as _glob
    apdata = os.environ.get('APPDATA') or os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Roaming')
    base = os.path.join(apdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs')
    if not os.path.isdir(base):
        return
    seen = set()
    for pattern in (os.path.join(base, 'Blender', '*.lnk'),
                    os.path.join(base, '*.lnk'),
                    os.path.join(base, '**', '*.lnk')):
        for p in _glob.glob(pattern, recursive=True):
            p = os.path.normpath(p)
            if p.lower() in seen:
                continue
            seen.add(p.lower())
            if 'blender' in os.path.basename(p).lower():
                yield p


def _find_blender():
    """Localiza una instalación de Blender (env, PATH, rutas comunes, D: y menú de inicio)."""
    import shutil
    candidates = []
    if os.environ.get(BLENDER_PATH_ENV):
        candidates.append(os.environ[BLENDER_PATH_ENV])
    exe = shutil.which("blender")
    if exe:
        candidates.append(exe)
    for probe in (
        r"C:\Program Files\Blender Foundation\Blender\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        r"C:\Program Files\Blender 3.6\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender3.6\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender3.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender3.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.5\blender.exe",
    ):
        if os.path.exists(probe):
            candidates.append(probe)
    # Búsqueda directa en raíces de disco (D:\Blender\blender.exe, etc.)
    for root in ('D:', 'C:'):
        rroot = root + os.sep  # 'D:\\'
        direct = os.path.join(rroot, 'Blender', 'blender.exe')
        if os.path.isfile(direct):
            candidates.append(direct)
        bdir = os.path.join(rroot, 'Blender')
        if os.path.isdir(bdir):
            try:
                for sub in os.listdir(bdir):
                    p = os.path.join(bdir, sub, 'blender.exe')
                    if os.path.isfile(p):
                        candidates.append(p)
            except OSError:
                pass
    # Menú de inicio: resolver los .lnk (cubre instalaciones portable/launcher)
    for lnk in _iter_blender_lnk():
        tgt = _resolve_lnk_target(lnk)
        if not tgt:
            continue
        if os.path.basename(tgt).lower() == 'blender.exe':
            candidates.append(tgt)
        else:  # launcher u otro ejecutable: buscar blender.exe junto a él
            cand = os.path.join(os.path.dirname(tgt), 'blender.exe')
            if os.path.isfile(cand):
                candidates.append(cand)
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.normpath(c)
    return None



# =====================================================================
# CLASE: Visor 3D de Modelos FBX
# =====================================================================
class FBXPreviewPanel(ctk.CTkFrame):
    """Visor 3D integrado para previsualizar los modelos FBX generados.

    Renderiza la geometría de cada FBX (su malla, idéntica a la del STL
    homólogo) con el color/material PBR correcto mediante un visor 3D
    interactivo basado en VTK (rendering offscreen) mostrado en el lienzo Tk.
    """

    VIEW_BG = "#0c0c0e"

    def __init__(self, master, fbx_dir, stl_dir, status_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=COLORS["bg_secondary"], corner_radius=12,
                       border_width=1, border_color=COLORS["border"])
        self.fbx_dir = fbx_dir
        self.stl_dir = stl_dir
        self._status_cb = status_callback
        self._models = {}
        self._current_key = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(header, text="VISOR 3D DE MODELOS",
                     font=(FONT_TITLE, 15, "bold"), text_color=COLORS["text"]).pack(side="left")
        self.renderer_badge = ctk.CTkLabel(
            header, text="●  Renderer: VTK (3D)",
            font=(FONT_FAMILY, 10), text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_input"], corner_radius=12, padx=10, pady=3)
        self.renderer_badge.pack(side="right")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(toolbar, text="Modelo:",
                     font=(FONT_FAMILY, 11), text_color=COLORS["text"]).pack(side="left")
        self.model_var = ctk.StringVar(value="—")
        self.model_menu = ctk.CTkOptionMenu(
            toolbar, values=["—"], variable=self.model_var,
            command=self._on_select, width=200, height=30,
            fg_color=COLORS["bg_input"], button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            font=(FONT_FAMILY, 11), dropdown_font=(FONT_FAMILY, 11))
        self.model_menu.pack(side="left", padx=(8, 10))

        self.swatch = ctk.CTkLabel(toolbar, text="", width=20, height=20,
                                   corner_radius=5, fg_color=COLORS["border"])
        self.swatch.pack(side="left", padx=(0, 8))
        self.key_label = ctk.CTkLabel(toolbar, text="Sin modelo",
                                      font=(FONT_FAMILY, 11), text_color=COLORS["text_secondary"])
        self.key_label.pack(side="left")

        self.btn_snapshot = ctk.CTkButton(
            toolbar, text="Guardar vista PNG", command=self._save_snapshot,
            width=120, height=28, corner_radius=6, fg_color="transparent",
            hover_color=COLORS["bg_input"], border_color=COLORS["border"],
            border_width=1, font=(FONT_FAMILY, 11))
        self.btn_snapshot.pack(side="right", padx=(6, 0))

        self.btn_reload = ctk.CTkButton(
            toolbar, text="Recargar modelos", command=self.refresh_models,
            width=120, height=28, corner_radius=6, fg_color="transparent",
            hover_color=COLORS["bg_input"], border_color=COLORS["border"],
            border_width=1, font=(FONT_FAMILY, 11))
        self.btn_reload.pack(side="right", padx=(6, 0))

        self.canvas_host = ctk.CTkFrame(self, fg_color=self.VIEW_BG, corner_radius=8)
        self.canvas_host.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.canvas_host.pack_propagate(False)

        # Estado del visor VTK (offscreen) + lienzo Tk donde se muestra la imagen
        self._ren = None
        self._ren_win = None
        self._actor = None
        self._mapper = None
        self._pd = None
        self._vs = None
        self._faces = None
        self._img_tk = None
        self._img_label = None
        self._vtk_initialized = False
        self._placeholder_placed = False
        self._dragging = False
        self._last_x = 0
        self._last_y = 0

        self.refresh_models()

    # --------------------------------------------------------------
    def _log(self, message, level="INFO"):
        if self._status_cb:
            self._status_cb(message, level)

    def _scan_models(self):
        models = {}
        if not os.path.isdir(self.fbx_dir):
            return models
        for f in sorted(os.listdir(self.fbx_dir)):
            if not f.lower().endswith(".fbx"):
                continue
            key = os.path.splitext(f)[0].lower()
            stl = os.path.join(self.stl_dir, os.path.splitext(f)[0] + ".stl")
            meta = PBR_COLORS.get(key, {})
            models[key] = {
                "fbx": os.path.join(self.fbx_dir, f),
                "stl": stl,
                "name": f,
                "label": meta.get("label", key.replace("_", " ").title()),
                "display": meta.get("display", "#8B8B8B"),
                "color_rgba": meta.get("color_rgba", (0.6, 0.6, 0.6, 1.0)),
            }
        return models

    def refresh_models(self):
        self._models = self._scan_models()
        keys = sorted(self._models.keys())
        names = [self._models[k]["name"] for k in keys]
        if not names:
            self.model_menu.configure(values=["—"])
            self.model_var.set("—")
            self._show_message("Aún no hay modelos FBX.\n\nEjecute el Pipeline y luego "
                               "\"Exportar a FBX\" para generar modelos.")
            return
        self.model_menu.configure(values=names)
        if self._current_key not in keys:
            self._current_key = keys[0]
        self.model_var.set(self._models[self._current_key]["name"])
        self._render_current()

    def _on_select(self, name):
        for key, meta in self._models.items():
            if meta["name"] == name:
                self._current_key = key
                break
        self._render_current()

    def _render_current(self):
        if not self._current_key or self._current_key not in self._models:
            self._show_message("Seleccione un modelo para previsualizar.")
            return
        meta = self._models[self._current_key]
        self._log(f"Previsualizando modelo: {meta['name']}", "INFO")
        self.key_label.configure(text=meta["label"])
        try:
            self.swatch.configure(fg_color=meta["display"])
        except Exception:
            pass
        self._render_vtk(meta)

    # --------------------------------------------------------------
    def _ensure_canvas(self):
        """Inicializa el renderizador VTK offscreen (una sola vez)."""
        if self._vtk_initialized:
            return
        import vtk
        self._ren = vtk.vtkRenderer()
        self._ren.SetBackground(0.047, 0.047, 0.055)  # equivalente a VIEW_BG (#0c0c0e)
        self._ren_win = vtk.vtkRenderWindow()
        self._ren_win.AddRenderer(self._ren)
        self._ren_win.SetOffScreenRendering(1)
        self._vtk_initialized = True

    def _mesh_to_polydata(self, vs, faces):
        import vtk
        pd = vtk.vtkPolyData()
        pts = vtk.vtkPoints()
        pts.SetNumberOfPoints(len(vs))
        for i in range(len(vs)):
            v = vs[i]
            pts.SetPoint(i, float(v[0]), float(v[1]), float(v[2]))
        pd.SetPoints(pts)
        tris = vtk.vtkCellArray()
        for t in faces:
            tri = vtk.vtkTriangle()
            tri.GetPointIds().SetId(0, int(t[0]))
            tri.GetPointIds().SetId(1, int(t[1]))
            tri.GetPointIds().SetId(2, int(t[2]))
            tris.InsertNextCell(tri)
        pd.SetPolys(tris)
        return pd

    def _load_preview_mesh(self, stl_path):
        import trimesh
        mesh = trimesh.load(stl_path, force="mesh")
        if len(mesh.faces) > 40000:
            try:
                import fast_simplification
                target = 30000
                verts, faces = fast_simplification.simplify(
                    mesh.vertices, mesh.faces,
                    target_reduction=1 - target / len(mesh.faces))
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
            except Exception:
                pass
        return mesh

    def _render_vtk(self, meta):
        """Renderiza el modelo con VTK (offscreen) y lo muestra en el lienzo Tk."""
        try:
            import vtk
            self._ensure_canvas()
            stl = meta["stl"]
            if not os.path.exists(stl):
                self._show_message("No se encontró la malla correspondiente (STL).")
                return
            mesh = self._load_preview_mesh(stl)
            vs = mesh.vertices.astype(float)
            faces = mesh.faces
            self._vs = vs
            self._faces = faces
            rgba = meta["color_rgba"]

            self._pd = self._mesh_to_polydata(vs, faces)
            self._mapper = vtk.vtkPolyDataMapper()
            self._mapper.SetInputData(self._pd)
            self._actor = vtk.vtkActor()
            self._actor.SetMapper(self._mapper)
            self._actor.GetProperty().SetColor(rgba[0], rgba[1], rgba[2])
            self._actor.GetProperty().SetAmbient(0.35)
            self._actor.GetProperty().SetDiffuse(0.65)
            self._actor.GetProperty().SetSpecular(0.15)
            self._actor.GetProperty().SetSpecularPower(20.0)
            self._actor.GetProperty().SetInterpolationToPhong()
            self._actor.GetProperty().EdgeVisibilityOff()

            self._ren.RemoveAllViewProps()
            self._ren.AddActor(self._actor)
            self._ren.ResetCamera()
            self._render_to_label()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_message(f"No se pudo renderizar el modelo:\n{e}")

    def _canvas_size(self):
        try:
            w = self.canvas_host.winfo_width()
            h = self.canvas_host.winfo_height()
            return max(int(w), 50), max(int(h), 50)
        except Exception:
            return 640, 480

    def _render_to_label(self):
        """Renderiza el frame actual de VTK y lo muestra en un widget Tk Label."""
        try:
            from PIL import Image, ImageTk
            import numpy as np
            import vtk
            from vtk.util.numpy_support import vtk_to_numpy

            w, h = self._canvas_size()
            self._ren_win.SetSize(int(w), int(h))
            self._ren_win.Render()

            w2i = vtk.vtkWindowToImageFilter()
            w2i.SetInput(self._ren_win)
            w2i.SetInputBufferTypeToRGBA()
            w2i.ReadFrontBufferOff()
            w2i.Update()
            data = w2i.GetOutput()
            dims = data.GetDimensions()
            width, height = dims[0], dims[1]
            vtk_array = data.GetPointData().GetScalars()
            buf = vtk_to_numpy(vtk_array)
            buf = buf.reshape(height, width, -1)
            rgb = buf[:, :, :3].astype("uint8")
            rgb = np.ascontiguousarray(rgb[::-1])  # voltear vertical (VTK: origen abajo-izquierda)
            img = Image.fromarray(rgb, "RGB")
            self._img_tk = ImageTk.PhotoImage(img)

            self._clear_viewport_placeholders()
            if self._img_label is None:
                import tkinter as tk
                self._img_label = tk.Label(self.canvas_host, image=self._img_tk,
                                           bg=self.VIEW_BG, bd=0, highlightthickness=0)
                self._img_label.pack(fill="both", expand=True)
            else:
                self._img_label.configure(image=self._img_tk)
            self._img_label.bind("<ButtonPress-1>", self._on_press)
            self._img_label.bind("<B1-Motion>", self._on_drag)
            self._img_label.bind("<ButtonRelease-1>", self._on_release)
            self._img_label.bind("<MouseWheel>", self._on_wheel)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_message(f"Error al mostrar el render:\n{e}")

    # ---------------- Interacción (rotar y zoom) ----------------
    def _on_press(self, event):
        self._dragging = True
        self._last_x = event.x
        self._last_y = event.y

    def _on_release(self, event):
        self._dragging = False

    def _on_drag(self, event):
        if not self._dragging or self._ren is None:
            return
        dx = event.x - self._last_x
        dy = event.y - self._last_y
        self._last_x = event.x
        self._last_y = event.y
        if dx == 0 and dy == 0:
            return
        cam = self._ren.GetActiveCamera()
        cam.Azimuth(-dx * 0.5)
        cam.Elevation(dy * 0.5)
        cam.OrthogonalizeViewUp()
        self._render_to_label()

    def _on_wheel(self, event):
        if self._ren is None:
            return
        cam = self._ren.GetActiveCamera()
        if getattr(event, "delta", 0) > 0:
            cam.Dolly(1.12)
        else:
            cam.Dolly(0.88)
        cam.OrthogonalizeViewUp()
        self._render_to_label()

    def _clear_viewport_placeholders(self):
        for w in self.canvas_host.winfo_children():
            if w is self._img_label:
                continue
            w.destroy()
        self._placeholder_placed = False

    def _show_message(self, text):
        self._clear_viewport_placeholders()
        if not self._placeholder_placed:
            msg = ctk.CTkLabel(self.canvas_host, text=text, justify="center",
                               font=(FONT_FAMILY, 13), text_color=COLORS["text_secondary"])
            msg.pack(expand=True)
            self._placeholder_placed = True

    def _save_snapshot(self):
        if self._ren_win is None or self._actor is None:
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="Guardar vista del modelo", defaultextension=".png",
            initialfile=f"{self._current_key or 'modelo'}_preview.png",
            filetypes=[("Imagen PNG", "*.png")])
        if path:
            import vtk
            self._ren_win.Render()
            w2i = vtk.vtkWindowToImageFilter()
            w2i.SetInput(self._ren_win)
            w2i.SetInputBufferTypeToRGBA()
            w2i.ReadFrontBufferOff()
            w2i.Update()
            writer = vtk.vtkPNGWriter()
            writer.SetFileName(path)
            writer.SetInputConnection(w2i.GetOutputPort())
            writer.Write()
            self._log(f"Vista guardada: {path}", "SUCCESS")

    def _show_image_png(self, png_path):
        """Muestra una imagen externa (PNG/JPEG) en el lienzo del visor."""
        from PIL import Image, ImageTk
        self._img_tk = ImageTk.PhotoImage(Image.open(png_path))
        self._clear_viewport_placeholders()
        if self._img_label is None:
            import tkinter as tk
            self._img_label = tk.Label(self.canvas_host, image=self._img_tk,
                                       bg=self.VIEW_BG, bd=0, highlightthickness=0)
            self._img_label.pack(fill="both", expand=True)
        else:
            self._img_label.configure(image=self._img_tk)


# =====================================================================
# CLASE: Consola de Log
# =====================================================================
class LogConsole(ctk.CTkTextbox):
    """Consola de texto para mostrar logs del pipeline."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            font=("Consolas", 11),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text"],
            border_color=COLORS["border"],
            border_width=1,
            wrap="word",
            state="disabled",
        )
        self._tag_colors = {
            "INFO": COLORS["text"],
            "SUCCESS": COLORS["success"],
            "WARNING": COLORS["warning"],
            "ERROR": COLORS["danger"],
            "HEADER": COLORS["accent_light"],
            "PROGRESS": COLORS["accent"],
        }

    def log(self, message, level="INFO"):
        """Añade un mensaje a la consola con color según nivel."""
        self.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = level.upper()
        if tag not in self._tag_colors:
            tag = "INFO"

        self.insert("end", f"[{timestamp}] ", "INFO")
        self.insert("end", f"{message}\n", tag)
        self.configure(state="disabled")
        self.see("end")

    def clear(self):
        """Limpia la consola."""
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def _setup_tags(self):
        """Configura los tags de color."""
        for tag, color in self._tag_colors.items():
            self.tag_config(tag, foreground=color)


# =====================================================================
# CLASE: Tarjeta de Estado
# =====================================================================
class StatusCard(ctk.CTkFrame):
    """Tarjeta con indicador de estado."""

    def __init__(self, master, title, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])

        self.title_label = ctk.CTkLabel(self, text=title, font=(FONT_FAMILY, 11, "bold"), text_color=COLORS["text_secondary"])
        self.title_label.pack(padx=16, pady=(10, 2), anchor="w")

        self.value_label = ctk.CTkLabel(self, text="—", font=(FONT_TITLE, 19, "bold"), text_color=COLORS["accent_light"])
        self.value_label.pack(padx=16, pady=(0, 2), anchor="w")

        self.detail_label = ctk.CTkLabel(self, text="", font=(FONT_FAMILY, 10), text_color=COLORS["text_secondary"])
        self.detail_label.pack(padx=16, pady=(0, 10), anchor="w")

    def set_value(self, value, color=None):
        self.value_label.configure(text=value, text_color=color or COLORS["accent_light"])

    def set_detail(self, detail):
        self.detail_label.configure(text=detail)


# =====================================================================
# CLASE: Aplicación Principal
# =====================================================================
class AtlasApp(ctk.CTk):
    """Aplicación principal del Proyecto ATLAS."""

    def __init__(self):
        super().__init__()

        # Configuración de la ventana
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1400x860")
        self.minsize(1100, 720)
        self.configure(fg_color=COLORS["bg"])
        # Centrar la ventana en pantalla
        self.update_idletasks()
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w, h = 1400, 860
            x = max((sw - w) // 2, 0)
            y = max((sh - h) // 2, 0)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        # Variables de estado
        self.input_path = None
        self.output_dir = None
        self.is_running = False
        self.log_queue = queue.Queue()
        self.current_step = ""

        # Importar módulos del pipeline
        self.pipeline_01 = None
        self.pipeline_02 = None
        self.pipeline_03 = None
        self._load_pipeline_modules()

        # Crear directorios necesarios
        self._ensure_directories()

        # Construir interfaz
        self._build_sidebar()
        self._build_main_area()
        self._build_status_bar()

        # Iniciar procesamiento de cola de logs
        self.after(100, self._process_log_queue)

        # Log de inicio
        self._log(f"{APP_NAME} v{APP_VERSION} iniciado", "HEADER")
        self._log(f"Directorio base: {BASE_DIR}", "INFO")
        self._log("Sistema listo. Seleccione un archivo DICOM o NIfTI para comenzar.", "SUCCESS")

    # =================================================================
    # MÉTODOS DE INICIALIZACIÓN
    # =================================================================
    def _load_pipeline_modules(self):
        """Carga los módulos del pipeline."""
        try:
            import importlib
            self.pipeline_01 = importlib.import_module("01_procesamiento_dicom")
            self.pipeline_02 = importlib.import_module("02_segmentacion_brats")
            self.pipeline_03 = importlib.import_module("03_integrar_brats")
        except Exception as e:
            self._log(f"Error cargando módulos del pipeline: {e}", "ERROR")

    def _ensure_directories(self):
        """Crea los directorios necesarios si no existen."""
        for d in [DATA_DIR, MODELOS_DIR, SALIDAS_DIR, MODELOS_PT_DIR,
                  os.path.join(SALIDAS_DIR, "segmentaciones_ai"),
                  os.path.join(SALIDAS_DIR, "reportes"),
                  os.path.join(MODELOS_DIR, "stl"),
                  os.path.join(MODELOS_DIR, "fbx")]:
            os.makedirs(d, exist_ok=True)

    # =================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # =================================================================
    def _build_sidebar(self):
        """Construye la barra lateral."""
        self.sidebar = ctk.CTkFrame(self, width=260, fg_color=COLORS["bg_secondary"], corner_radius=0)
        self.sidebar.pack(side="left", fill="y", padx=0, pady=0)
        self.sidebar.pack_propagate(False)

        # Logo / Título
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(padx=20, pady=(28, 20), fill="x")

        badge = ctk.CTkFrame(logo_frame, width=64, height=64, corner_radius=16,
                             fg_color=COLORS["accent"], border_width=0)
        badge.pack_propagate(False)
        badge.pack(anchor="center", pady=(0, 10))
        ctk.CTkLabel(badge, text="🧠", font=(FONT_EMOJI, 32),
                     text_color="#ffffff").pack(expand=True)

        ctk.CTkLabel(logo_frame, text=APP_NAME, font=(FONT_TITLE, 21, "bold"),
                     text_color=COLORS["accent_light"]).pack()
        ctk.CTkLabel(logo_frame, text=APP_SUBTITLE, font=(FONT_FAMILY, 10),
                     text_color=COLORS["text_secondary"]).pack(pady=(2, 0))

        # Separador
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=20, pady=10)

        # Sección: Entrada
        ctk.CTkLabel(self.sidebar, text="ENTRADA", font=(FONT_FAMILY, 11, "bold"), text_color=COLORS["text_secondary"]).pack(padx=20, pady=(10, 5), anchor="w")

        self.btn_select_input = ctk.CTkButton(
            self.sidebar, text="Seleccionar DICOM/NIfTI",
            command=self._select_input, height=40,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            font=(FONT_FAMILY, 13, "bold")
        )
        self.btn_select_input.pack(padx=20, pady=5, fill="x")

        self.input_label = ctk.CTkLabel(
            self.sidebar, text="Sin archivo seleccionado",
            font=(FONT_FAMILY, 10), text_color=COLORS["text_secondary"], wraplength=220
        )
        self.input_label.pack(padx=20, pady=(0, 10), fill="x")

        # Sección: Pipeline
        ctk.CTkLabel(self.sidebar, text="PIPELINE", font=(FONT_FAMILY, 11, "bold"), text_color=COLORS["text_secondary"]).pack(padx=20, pady=(10, 5), anchor="w")

        self.btn_run_pipeline = ctk.CTkButton(
            self.sidebar, text="Ejecutar Pipeline Completo",
            command=self._run_pipeline, height=44, corner_radius=8,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["on_accent"],
            font=(FONT_FAMILY, 13, "bold")
        )
        self.btn_run_pipeline.pack(padx=20, pady=5, fill="x")

        self.btn_run_brats = ctk.CTkButton(
            self.sidebar, text="Segmentar Tumor (BRATS)",
            command=self._run_brats, height=40, corner_radius=8,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1,
            font=(FONT_FAMILY, 12)
        )
        self.btn_run_brats.pack(padx=20, pady=5, fill="x")

        self.btn_run_aneurisma = ctk.CTkButton(
            self.sidebar, text="Detectar Aneurisma",
            command=self._run_aneurisma, height=40, corner_radius=8,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1,
            font=(FONT_FAMILY, 12)
        )
        self.btn_run_aneurisma.pack(padx=20, pady=5, fill="x")

        self.btn_export_fbx = ctk.CTkButton(
            self.sidebar, text="Exportar a FBX",
            command=self._export_fbx, height=40, corner_radius=8,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1,
            font=(FONT_FAMILY, 12)
        )
        self.btn_export_fbx.pack(padx=20, pady=5, fill="x")

        # Selector de enfoque: resalta Tumor o Aneurisma en la exportación FBX
        ctk.CTkLabel(
            self.sidebar, text="ENFOQUE 3D",
            font=(FONT_FAMILY, 11, "bold"), text_color=COLORS["text_secondary"]
        ).pack(padx=20, pady=(10, 5), anchor="w")

        # Selector de enfoque: al seleccionar, el botón pasa a azul tonal con texto negro (AA).
        self.seg_target = ctk.CTkFrame(self.sidebar, fg_color=COLORS["bg_input"], corner_radius=8)
        self._target_btns = {}
        for _value in ["Completo", "Tumor", "Aneurisma"]:
            _btn = ctk.CTkButton(
                self.seg_target, text=_value,
                command=lambda v=_value: self._on_target_change(v),
                height=32, corner_radius=8, border_width=0,
                fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
                text_color=COLORS["text"],
                font=(FONT_FAMILY, 11, "bold"))
            _btn.pack(side="left", fill="x", expand=True, padx=2, pady=2)
            self._target_btns[_value] = _btn
        self.target_mode = "Completo"
        self._apply_target_selection()
        self.seg_target.pack(padx=20, pady=5, fill="x")

        # Separador
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=20, pady=10)

        # Sección: Salida
        ctk.CTkLabel(self.sidebar, text="SALIDA", font=(FONT_FAMILY, 11, "bold"), text_color=COLORS["text_secondary"]).pack(padx=20, pady=(10, 5), anchor="w")

        self.btn_select_output = ctk.CTkButton(
            self.sidebar, text="Seleccionar Carpeta Salida",
            command=self._select_output, height=40, corner_radius=8,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1,
            font=(FONT_FAMILY, 12)
        )
        self.btn_select_output.pack(padx=20, pady=5, fill="x")

        self.output_label = ctk.CTkLabel(
            self.sidebar, text=SALIDAS_DIR,
            font=(FONT_FAMILY, 10), text_color=COLORS["text_secondary"], wraplength=220
        )
        self.output_label.pack(padx=20, pady=(0, 10), fill="x")

        # Separador
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=20, pady=10)

        # Botón limpiar consola
        self.btn_clear = ctk.CTkButton(
            self.sidebar, text="Limpiar Consola",
            command=self._clear_console, height=35,
            fg_color="transparent", hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1,
            font=(FONT_FAMILY, 11)
        )
        self.btn_clear.pack(padx=20, pady=5, fill="x")

        # Versión
        ctk.CTkLabel(
            self.sidebar, text=f"v{APP_VERSION}",
            font=(FONT_FAMILY, 9), text_color=COLORS["text_secondary"]
        ).pack(side="bottom", pady=10)

    def _build_main_area(self):
        """Construye el área principal (visor 3D + panel de estado + consola)."""
        self.main_area = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        self.main_area.pack(side="left", fill="both", expand=True, padx=0, pady=0)

        # ---- Encabezado ----
        header = ctk.CTkFrame(self.main_area, fg_color=COLORS["bg_secondary"], corner_radius=0, height=64)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=20, pady=8)
        ctk.CTkLabel(brand, text=APP_NAME, font=(FONT_TITLE, 18, "bold"),
                     text_color=COLORS["text"]).pack(anchor="w")
        ctk.CTkLabel(brand, text=APP_SUBTITLE, font=(FONT_FAMILY, 10),
                     text_color=COLORS["text_secondary"]).pack(anchor="w")

        self.status_indicator = ctk.CTkLabel(
            header, text="● LISTO", font=(FONT_FAMILY, 13, "bold"),
            text_color=COLORS["success"])
        self.status_indicator.pack(side="right", padx=24, pady=10)

        # ---- Contenido: visor 3D (izquierda) + estado (derecha) ----
        content = ctk.CTkFrame(self.main_area, fg_color=COLORS["bg"], corner_radius=0)
        content.pack(fill="both", expand=True, padx=20, pady=(16, 8))

        view_row = ctk.CTkFrame(content, fg_color=COLORS["bg"])
        view_row.pack(fill="both", expand=True)

        # Panel derecho: tarjetas de estado (ancho fijo)
        stats = ctk.CTkFrame(view_row, width=300, fg_color=COLORS["bg"])
        stats.pack(side="right", fill="y", padx=(16, 0))
        stats.pack_propagate(False)

        self.card_archivo = StatusCard(stats, "Archivo de Entrada")
        self.card_archivo.pack(fill="x", pady=(0, 10))
        self.card_estado = StatusCard(stats, "Estado del Pipeline")
        self.card_estado.pack(fill="x", pady=(0, 10))
        self.card_resultados = StatusCard(stats, "Resultados")
        self.card_resultados.pack(fill="x", pady=(0, 10))
        self.card_modelos = StatusCard(stats, "Modelos 3D Generados")
        self.card_modelos.pack(fill="x", pady=(0, 10))

        # Columna izquierda: visor 3D (superior) + consola de logs (inferior)
        left_col = ctk.CTkFrame(view_row, fg_color=COLORS["bg"], corner_radius=0)
        left_col.pack(side="left", fill="both", expand=True)

        # Visor 3D de modelos FBX: ocupa la parte superior, se expande hacia abajo
        viewer_host = ctk.CTkFrame(left_col, fg_color=COLORS["bg"], corner_radius=0)
        viewer_host.pack(side="top", fill="both", expand=True)
        fbx_dir = os.path.join(MODELOS_DIR, "fbx")
        stl_dir = os.path.join(MODELOS_DIR, "stl")
        self.preview_panel = FBXPreviewPanel(
            viewer_host, fbx_dir, stl_dir,
            status_callback=self._log)
        self.preview_panel.pack(fill="both", expand=True)

        # Consola de logs: debajo del visor, altura fija en la parte inferior
        console_frame = ctk.CTkFrame(left_col, fg_color=COLORS["bg"], corner_radius=0)
        console_frame.pack(side="bottom", fill="x", pady=(8, 0))

        console_label_row = ctk.CTkFrame(console_frame, fg_color="transparent")
        console_label_row.pack(fill="x")
        ctk.CTkLabel(console_label_row, text="CONSOLA DE LOGS",
                     font=(FONT_FAMILY, 11, "bold"),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        self.btn_clear_console = ctk.CTkButton(
            console_label_row, text="Limpiar", command=self._clear_console,
            width=70, height=24, fg_color="transparent", hover_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=1, font=(FONT_FAMILY, 10))
        self.btn_clear_console.pack(side="right")

        self.console = LogConsole(console_frame, height=180)
        self.console.pack(fill="x", expand=False, pady=(6, 0))

        self._refresh_preview()

    def _build_status_bar(self):
        """Construye la barra de estado inferior."""
        self.status_bar = ctk.CTkFrame(self, height=30, fg_color=COLORS["bg_secondary"], corner_radius=0)
        self.status_bar.pack(side="bottom", fill="x")

        self.status_label = ctk.CTkLabel(
            self.status_bar, text="Listo", font=(FONT_FAMILY, 10),
            text_color=COLORS["text_secondary"]
        )
        self.status_label.pack(side="left", padx=15, pady=5)

        self.progress_bar = ctk.CTkProgressBar(
            self.status_bar, width=200, height=6,
            fg_color=COLORS["bg_input"], progress_color=COLORS["accent"]
        )
        self.progress_bar.pack(side="right", padx=15, pady=5)
        self.progress_bar.set(0)

    # =================================================================
    # MÉTODOS DE LOG
    # =================================================================
    def _log(self, message, level="INFO"):
        """Añade un mensaje a la cola de logs."""
        self.log_queue.put((message, level))

    def _process_log_queue(self):
        """Procesa la cola de logs."""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.console.log(message, level)
        except queue.Empty:
            pass
        self.after(100, self._process_log_queue)

    def _clear_console(self):
        """Limpia la consola."""
        self.console.clear()
        self._log("Consola limpiada", "INFO")

    # =================================================================
    # MÉTODOS DE SELECCIÓN
    # =================================================================
    def _select_input(self):
        """Selecciona archivo de entrada."""
        filetypes = [
            ("Archivos médicos", "*.nii.gz *.nii *.dcm *.dicom"),
            ("NIfTI", "*.nii.gz *.nii"),
            ("DICOM", "*.dcm *.dicom"),
            ("Todos los archivos", "*.*")
        ]
        path = filedialog.askopenfilename(title="Seleccionar archivo de entrada", filetypes=filetypes)
        if path:
            self.input_path = path
            self.input_label.configure(text=os.path.basename(path))
            self.card_archivo.set_value(os.path.basename(path), COLORS["success"])
            self.card_archivo.set_detail(path)
            self._log(f"Archivo seleccionado: {path}", "SUCCESS")
            self._update_status("Archivo seleccionado")

    def _select_output(self):
        """Selecciona carpeta de salida."""
        path = filedialog.askdirectory(title="Seleccionar carpeta de salida")
        if path:
            self.output_dir = path
            self.output_label.configure(text=path)
            self._log(f"Carpeta de salida: {path}", "SUCCESS")

    def _on_target_change(self, value):
        """Guarda el enfoque 3D seleccionado (Completo/Tumor/Aneurisma)."""
        self.target_mode = value
        self._apply_target_selection()
        self._log(f"Enfoque 3D seleccionado: {value}", "INFO")

    def _apply_target_selection(self):
        """El botón seleccionado usa azul tonal con texto negro (contraste AA)."""
        for _value, _btn in self._target_btns.items():
            if _value == self.target_mode:
                _btn.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                               text_color=COLORS["on_accent"])
            else:
                _btn.configure(fg_color=COLORS["bg_card"], hover_color=COLORS["bg_input"],
                               text_color=COLORS["text"])

    def _refresh_preview(self):
        """Actualiza el visor 3D con los modelos FBX disponibles."""
        if hasattr(self, "preview_panel") and self.preview_panel is not None:
            self.preview_panel.refresh_models()

    def _refresh_preview_async(self):
        """Actualiza el visor 3D desde el hilo de trabajo (programado al UI)."""
        try:
            self.after(0, self._refresh_preview)
        except Exception:
            pass

    # =================================================================
    # MÉTODOS DE EJECUCIÓN
    # =================================================================
    def _set_running(self, running):
        """Activa/desactiva el estado de ejecución."""
        self.is_running = running
        state = "disabled" if running else "normal"
        self.btn_run_pipeline.configure(state=state)
        self.btn_run_brats.configure(state=state)
        self.btn_run_aneurisma.configure(state=state)
        self.btn_export_fbx.configure(state=state)
        self.btn_select_input.configure(state=state)

        if running:
            self.status_indicator.configure(text="● PROCESANDO", text_color=COLORS["warning"])
            self.card_estado.set_value("Procesando...", COLORS["warning"])
        else:
            self.status_indicator.configure(text="● LISTO", text_color=COLORS["success"])
            self.card_estado.set_value("Completado", COLORS["success"])

    def _update_status(self, message):
        """Actualiza la barra de estado."""
        self.status_label.configure(text=message)

    def _update_progress(self, value):
        """Actualiza la barra de progreso."""
        self.progress_bar.set(value)

    def _mask_has_voxels(self, mask_path):
        """Devuelve True si existe una máscara con al menos un voxel positivo."""
        try:
            if not mask_path or not os.path.exists(mask_path):
                return False
            mask_img = self.pipeline_01.sitk.ReadImage(mask_path)
            arr = self.pipeline_01.sitk.GetArrayFromImage(mask_img)
            return bool((arr > 0).any())
        except Exception:
            return False

    def _run_in_thread(self, target, *args):
        """Ejecuta una función en un hilo separado."""
        def wrapper():
            try:
                self._set_running(True)
                self._update_progress(0.1)
                result = target(*args)
                self._update_progress(1.0)
                self._log("Proceso completado exitosamente", "SUCCESS")
                self._update_status("Proceso completado")
                return result
            except Exception as e:
                self._log(f"Error: {e}", "ERROR")
                self._log(traceback.format_exc(), "ERROR")
                self._update_status("Error en el proceso")
                messagebox.showerror("Error", f"Ocurrió un error:\n\n{e}")
            finally:
                self._set_running(False)

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()

    def _run_pipeline(self):
        """Ejecuta el pipeline completo."""
        if not self.input_path:
            messagebox.showwarning("Advertencia", "Seleccione un archivo de entrada primero.")
            return

        self._log("=" * 60, "HEADER")
        self._log("INICIANDO PIPELINE COMPLETO", "HEADER")
        self._log("=" * 60, "HEADER")

        output_dir = self.output_dir or os.path.join(SALIDAS_DIR, "segmentaciones_ai")

        def pipeline_task():
            # Paso 1: Resolver volumen
            self._log("[1/6] Resolviendo volumen de entrada...", "PROGRESS")
            self._update_progress(0.1)
            nifti_path = self.pipeline_01.resolve_input_volume(
                self.input_path,
                os.path.join(output_dir, "volumen_paciente.nii.gz")
            )
            self._log(f"Volumen: {nifti_path}", "SUCCESS")

            # Paso 2: Segmentación AI
            self._log("[2/6] Ejecutando segmentación AI (TotalSegmentator)...", "PROGRESS")
            self._update_progress(0.3)
            self.pipeline_01.run_ai_segmentation(nifti_path, output_dir, fast_mode=True)
            self._log("Segmentación AI completada", "SUCCESS")

            # Paso 3: Segmentación de vasos (venas + arterias)
            self._log("[3/6] Segmentando vasos cerebrales (venas y arterias)...", "PROGRESS")
            self._update_progress(0.4)
            brain_path = os.path.join(output_dir, "brain.nii.gz")
            vasos_path = os.path.join(output_dir, "vasos.nii.gz")
            if os.path.exists(brain_path):
                self.pipeline_01.generate_vessels_mask(nifti_path, brain_path, vasos_path)
                if os.path.exists(vasos_path):
                    self._log("Segmentación de vasos completada", "SUCCESS")
                else:
                    self._log("No se generó máscara de vasos", "WARNING")
            else:
                self._log("No se encontró máscara de cerebro (brain.nii.gz), omitiendo vasos", "WARNING")

            # Paso 4: Segmentación de tumor (BRATS con respaldo morfológico)
            self._log("[4/6] Ejecutando segmentación de tumor...", "PROGRESS")
            self._update_progress(0.5)
            self.pipeline_03.integrate_brats_into_pipeline(nifti_path, output_dir)
            # Corrección de tumor: si BRATS no produjo una máscara válida
            # (estudio CT, modelo no disponible o máscara vacía), aplicar el
            # método morfológico heurístico como respaldo.
            tumor_path = os.path.join(output_dir, "tumor_brats.nii.gz")
            if not self._mask_has_voxels(tumor_path):
                self._log("BRATS no produjo tumor. Aplicando método morfológico de respaldo...", "WARNING")
                if os.path.exists(brain_path):
                    self.pipeline_01.generate_tumor_mask(nifti_path, brain_path, tumor_path)
                    if self._mask_has_voxels(tumor_path):
                        self._log("Tumor segmentado por método morfológico", "SUCCESS")
                    else:
                        self._log("No se pudo segmentar el tumor", "ERROR")
                else:
                    self._log("No se pudo segmentar el tumor (falta máscara de cerebro)", "ERROR")
            else:
                self._log("Segmentación de tumor completada", "SUCCESS")

            # Paso 5: Detección de aneurisma
            self._log("[5/6] Detectando aneurismas...", "PROGRESS")
            self._update_progress(0.7)
            if os.path.exists(vasos_path):
                self.pipeline_03.improve_aneurysm_detection(
                    nifti_path, vasos_path,
                    os.path.join(output_dir, "aneurisma_v2.nii.gz")
                )
                self._log("Detección de aneurisma completada", "SUCCESS")
            else:
                self._log("No se encontró máscara de vasos, omitiendo detección de aneurisma", "WARNING")

            # Paso 6: Generar modelos 3D
            self._log("[6/6] Generando modelos 3D...", "PROGRESS")
            self._update_progress(0.9)

            stl_dir = os.path.join(MODELOS_DIR, "stl")
            fbx_dir = os.path.join(MODELOS_DIR, "fbx")

            # Cerebro
            brain_path = os.path.join(output_dir, "brain.nii.gz")
            if os.path.exists(brain_path):
                self.pipeline_01.build_mesh(brain_path, os.path.join(stl_dir, "Cerebro.stl"))
                self._log("Modelo 3D del cerebro generado", "SUCCESS")

            # Cráneo
            skull_path = os.path.join(output_dir, "skull.nii.gz")
            if os.path.exists(skull_path):
                self.pipeline_01.build_mesh(skull_path, os.path.join(stl_dir, "Craneo.stl"))
                self._log("Modelo 3D del cráneo generado", "SUCCESS")

            # Tumor
            tumor_path = os.path.join(output_dir, "tumor_brats.nii.gz")
            if os.path.exists(tumor_path):
                self.pipeline_03.build_mesh_improved(tumor_path, os.path.join(stl_dir, "Tumor.stl"))
                self._log("Modelo 3D del tumor generado", "SUCCESS")

            # Aneurisma
            aneu_path = os.path.join(output_dir, "aneurisma_v2.nii.gz")
            if os.path.exists(aneu_path):
                self.pipeline_03.build_mesh_improved(aneu_path, os.path.join(stl_dir, "Aneurisma.stl"))
                self._log("Modelo 3D del aneurisma generado", "SUCCESS")

            # Vasos
            vasos_path = os.path.join(output_dir, "vasos.nii.gz")
            if os.path.exists(vasos_path):
                self.pipeline_01.build_mesh(vasos_path, os.path.join(stl_dir, "Venas_Arterias.stl"))
                self._log("Modelo 3D de vasos generado", "SUCCESS")

            self._update_progress(1.0)
            self._log("=" * 60, "HEADER")
            self._log("PIPELINE COMPLETADO", "HEADER")
            self._log("=" * 60, "HEADER")

            # Actualizar tarjetas
            self.card_resultados.set_value("Pipeline completado", COLORS["success"])
            self.card_modelos.set_value("5 modelos generados", COLORS["success"])

        self._run_in_thread(pipeline_task)

    def _run_brats(self):
        """Ejecuta solo la segmentación BRATS."""
        if not self.input_path:
            messagebox.showwarning("Advertencia", "Seleccione un archivo de entrada primero.")
            return

        self._log("=" * 60, "HEADER")
        self._log("SEGMENTACIÓN BRATS", "HEADER")
        self._log("=" * 60, "HEADER")

        output_dir = self.output_dir or os.path.join(SALIDAS_DIR, "segmentaciones_ai")

        def brats_task():
            self._update_progress(0.2)
            self._log("Verificando modelo BRATS...", "PROGRESS")
            self.pipeline_02.verify_brats_model()

            self._update_progress(0.4)
            self._log("Ejecutando segmentación...", "PROGRESS")
            result = self.pipeline_03.integrate_brats_into_pipeline(self.input_path, output_dir)

            self._update_progress(1.0)
            self._log(f"Segmentación BRATS completada: {result}", "SUCCESS")
            self.card_resultados.set_value("BRATS completado", COLORS["success"])

        self._run_in_thread(brats_task)

    def _run_aneurisma(self):
        """Ejecuta solo la detección de aneurisma."""
        if not self.input_path:
            messagebox.showwarning("Advertencia", "Seleccione un archivo de entrada primero.")
            return

        self._log("=" * 60, "HEADER")
        self._log("DETECCIÓN DE ANEURISMA", "HEADER")
        self._log("=" * 60, "HEADER")

        output_dir = self.output_dir or os.path.join(SALIDAS_DIR, "segmentaciones_ai")

        def aneu_task():
            self._update_progress(0.2)
            vasos_path = os.path.join(output_dir, "vasos.nii.gz")

            if not os.path.exists(vasos_path):
                self._log("No se encontró máscara de vasos. Ejecutando segmentación de vasos...", "WARNING")
                self._update_progress(0.4)
                self.pipeline_01.generate_vessels_mask(
                    self.input_path,
                    os.path.join(output_dir, "brain.nii.gz"),
                    vasos_path
                )

            self._update_progress(0.6)
            self._log("Analizando curvatura y forma vascular...", "PROGRESS")
            result, reporte = self.pipeline_03.improve_aneurysm_detection(
                self.input_path, vasos_path,
                os.path.join(output_dir, "aneurisma_v2.nii.gz")
            )

            self._update_progress(0.8)
            self._log(f"Candidatos detectados: {len(reporte)}", "SUCCESS")
            for i, cand in enumerate(reporte, 1):
                self._log(f"  Candidato #{i}: {cand}", "INFO")

            self._update_progress(1.0)
            self.card_resultados.set_value(f"{len(reporte)} candidatos", COLORS["success"])

        self._run_in_thread(aneu_task)

    def _export_fbx(self):
        """Exporta STL a FBX."""
        stl_dir = os.path.join(MODELOS_DIR, "stl")
        fbx_dir = os.path.join(MODELOS_DIR, "fbx")

        if not os.path.exists(stl_dir) or not os.listdir(stl_dir):
            messagebox.showwarning("Advertencia", "No hay modelos STL para exportar.")
            return

        self._log("=" * 60, "HEADER")
        self._log("EXPORTACIÓN A FBX", "HEADER")
        self._log("=" * 60, "HEADER")

        # Parámetros PBR por modelo (fuente única: PBR_COLORS). Se filtran solo
        # los argumentos aceptados por export_stl_to_single_fbx.
        _FBX_KW = ("color_rgba", "roughness", "metallic", "emission", "subsurface", "subsurface_color")
        _PBR = {k: {kk: vv for kk, vv in v.items() if kk in _FBX_KW}
                for k, v in PBR_COLORS.items()}
        # Modelo de interés seleccionado (Tumor/Aneurisma): se resalta con más emisión.
        _target = getattr(self, "target_mode", "Completo").lower()

        def export_task():
            stl_files = [f for f in os.listdir(stl_dir) if f.endswith('.stl')]
            total = len(stl_files)

            for i, stl_file in enumerate(stl_files):
                self._update_progress((i + 1) / total)
                stl_path = os.path.join(stl_dir, stl_file)
                fbx_name = stl_file.replace('.stl', '.fbx')
                fbx_path = os.path.join(fbx_dir, fbx_name)

                base = os.path.splitext(stl_file)[0].lower()
                params = dict(_PBR.get(base, {}))
                if _target and _target in base:
                    # Resaltar el modelo de interés con mayor intensidad de emisión.
                    e = list(params.get("emission", (0, 0, 0, 1)))
                    e[0], e[1], e[2] = 1.0, 0.6, 0.1
                    params["emission"] = tuple(e)

                self._log(f"Exportando {stl_file}...", "PROGRESS")
                self.pipeline_01.export_stl_to_single_fbx(stl_path, fbx_path, **params)
                self._log(f"FBX generado: {fbx_name}", "SUCCESS")

            self._update_progress(1.0)
            self.card_modelos.set_value(f"{total} FBX exportados", COLORS["success"])
            # Actualizar el visor 3D con los modelos recién exportados.
            self._refresh_preview_async()

        self._run_in_thread(export_task)


# =====================================================================
# PUNTO DE ENTRADA
# =====================================================================
def main():
    app = AtlasApp()
    app.mainloop()

if __name__ == "__main__":
    main()