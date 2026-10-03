"""
=====================================================================
 NEUROHUB - Interfaz Profesional Dark
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
APP_NAME = "NEUROHUB"
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
MODELOS_DIR = os.path.join(os.path.dirname(BASE_DIR), "archivo", "modelos_3d")
SALIDAS_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")
# Carpeta con las mallas STL de máxima resolución que produce el pipeline
# (cerebro, cráneo, tumor, vasos...). El visor la consulta como fuente
# principal: contiene la geometría real, mientras que MODELOS_DIR/fbx solo
# guarda los FBX de exportación.
MALLAS_DIR = os.path.join(SALIDAS_DIR, "mallas")
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
    "aneurisma": dict(
        color_rgba=(1.00, 0.55, 0.00, 1.0),
        roughness=0.35, metallic=0.0,
        emission=(1.00, 0.35, 0.00, 1.0), subsurface=0.05,
        subsurface_color=(1.0, 0.6, 0.2, 1.0),
        display="#FF8C00", label="Aneurisma",
    ),
}

# Alias de claves: nombres alternativos de archivo que el visor puede
# encontrar (skull.stl, brain.stl...) se mapean a su estructura canónica.
PBR_ALIASES = {
    "skull": "craneo",
    "brain": "cerebro",
    "cranium": "craneo",
    "aneurisma_candidatos": "aneurisma",
}


def resolve_pbr(key):
    """Devuelve la entrada de PBR_COLORS que corresponde a `key`.

    Aplica PBR_ALIASES para que los nombres reales de archivo (skull.stl,
    arterias.stl, ...) hereden el material de su estructura canónica.
    """
    if not key:
        return {}
    k = key.lower()
    if k in PBR_COLORS:
        return PBR_COLORS[k]
    canon = PBR_ALIASES.get(k)
    if canon:
        return PBR_COLORS.get(canon, {})
    # Último recurso: coincidencia por subcadena ("Cerebro_Completo", ...).
    for name, meta in PBR_COLORS.items():
        if name in k:
            return meta
    return {}

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
# CLASE: Panel de Vistas 2D
# =====================================================================
class Slice2DPanel(ctk.CTkFrame):
    """Panel para visualizar cortes 2D con tumor encerrado en círculo."""

    def __init__(self, master, slice_dir, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=COLORS["bg_secondary"], corner_radius=12,
                       border_width=1, border_color=COLORS["border"])
        self.slice_dir = slice_dir
        self._slices = {}
        self._img_tk = {}
        
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 12))
        ctk.CTkLabel(header, text="VISTAS 2D CON TUMOR",
                     font=(FONT_TITLE, 16, "bold"), text_color=COLORS["text"]).pack(side="left")
        
        # Grid de las 3 vistas - DISTRIBUIDO EN VERTICAL para máximo espacio
        grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True, padx=14, pady=14)
        
        self.labels = {}
        self.canvas_widgets = {}
        
        # DISEÑO: cada corte apilado verticalmente. Cada canvas se expande con la
        # ventana y las imágenes se escalan (LANCZOS) al tamaño real disponible
        # para conseguir el MÁXIMO renderizado 2D posible.
        self._orig_images = {}  # copia en alta resolución de cada corte
        
        for i, (name, label_txt) in enumerate([("axial", "AXIAL"), ("coronal", "CORONAL"), ("sagital", "SAGITAL")]):
            row = i
            
            frame = ctk.CTkFrame(grid_frame, fg_color=COLORS["bg_card"], corner_radius=10,
                                 border_width=1, border_color=COLORS["border"])
            frame.grid(row=row, column=0, padx=0, pady=8, sticky="nsew")
            frame.grid_rowconfigure(1, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            
            # Contenedor interno con título + imagen
            inner = ctk.CTkFrame(frame, fg_color="transparent")
            inner.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
            inner.grid_rowconfigure(1, weight=1)
            inner.grid_columnconfigure(0, weight=1)
            
            title = ctk.CTkLabel(inner, text=label_txt,
                                 font=(FONT_FAMILY, 13, "bold"), text_color=COLORS["accent"])
            title.grid(row=0, column=0, sticky="nw", pady=(0, 8))
            
            # Usar Canvas que se expande (sin tamaño fijo) para máximo tamaño
            canvas = ctk.CTkCanvas(inner,
                                  bg=COLORS["bg_input"],
                                  highlightthickness=0,
                                  bd=0)
            canvas.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
            
            # Label de texto para errores/placeholders
            text_label = ctk.CTkLabel(inner, text="Cargando...",
                                     fg_color=COLORS["bg_input"],
                                     corner_radius=8,
                                     text_color=COLORS["text_secondary"])
            text_label.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
            
            self.canvas_widgets[name] = {"canvas": canvas, "label": text_label, "photo": None}
            self.labels[name] = text_label
        
        grid_frame.grid_columnconfigure(0, weight=1)
        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_rowconfigure(1, weight=1)
        grid_frame.grid_rowconfigure(2, weight=1)
        
        # Redibujo los cortes al redimensionar la ventana para máximo detalle.
        self.bind("<Configure>", self._on_panel_resize)
        self._resize_job = None
    
    def _on_panel_resize(self, event=None):
        """Redibuja los cortes con retardo corto al redimensionar la ventana."""
        if getattr(self, "_resize_job", None) is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(80, self._rerender_all)

    def _rerender_all(self):
        """Vuelve a dibujar todas las imágenes al tamaño actual del canvas."""
        for name in ["axial", "coronal", "sagital"]:
            if self.canvas_widgets.get(name, {}).get("photo"):
                self._draw_on_canvas(name)

    def _canvas_size(self, name):
        try:
            canvas = self.canvas_widgets[name]["canvas"]
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            return max(int(w), 60), max(int(h), 60)
        except Exception:
            return 520, 460

    def _draw_on_canvas(self, name):
        """Escala (LANCZOS) la imagen original al tamaño del canvas y la dibuja."""
        try:
            from PIL import Image, ImageTk
            orig = self._orig_images.get(name)
            if orig is None:
                return
            widget_info = self.canvas_widgets[name]
            canvas = widget_info["canvas"]
            text_label = widget_info["label"]

            cw, ch = self._canvas_size(name)
            copy = orig.copy()
            copy.thumbnail((cw, ch), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(copy)
            widget_info["photo"] = photo  # guardar referencia (evita GC)

            canvas.delete("all")
            canvas.create_image(cw // 2, ch // 2, image=photo)
            text_label.grid_remove()
        except Exception as e:
            print(f"[SLICE2D] Error dibujando {name}: {e}")

    def load_slices(self):
        """Carga las imágenes 2D desde archivos PNG (ALTA RESOLUCIÓN)."""
        try:
            from PIL import Image
            import traceback

            for name in ["axial", "coronal", "sagital"]:
                path = os.path.join(self.slice_dir, f"corte_{name}.png")
                widget_info = self.canvas_widgets[name]
                text_label = widget_info["label"]

                print(f"[SLICE2D] Intentando cargar: {path}")

                if os.path.exists(path):
                    try:
                        # Abrir imagen a máxima resolución
                        img = Image.open(path)
                        print(f"[SLICE2D] ✓ {name}: {img.size} (alta resolución)")
                        # Guardar la versión original completa para escalar al
                        # tamaño del canvas en cada frame.
                        self._orig_images[name] = img.convert("RGB").copy()
                        self._draw_on_canvas(name)
                        print(f"[SLICE2D] ✓ {name} cargada exitosamente")

                    except Exception as e:
                        error_msg = str(e)[:50]
                        text_label.configure(text=f"❌ Error\n{error_msg}")
                        print(f"[SLICE2D] ✗ Error cargando {name}: {error_msg}")
                        traceback.print_exc()
                else:
                    text_label.configure(text=f"⚠️ {name.upper()}\nNo encontrado")
                    print(f"[SLICE2D] ⚠️ {path} NO EXISTE")

        except Exception as e:
            print(f"[SLICE2D] Error general: {e}")
            import traceback
            traceback.print_exc()
    
    def clear(self):
        """Limpia las imágenes."""
        for name in self.canvas_widgets:
            widget_info = self.canvas_widgets[name]
            widget_info["canvas"].delete("all")
            widget_info["label"].configure(text="Sin imagen")
            widget_info["label"].grid()
            widget_info["photo"] = None
            self._img_tk.pop(name, None)
            self._orig_images.pop(name, None)


# =====================================================================
# CLASE: Ventana 3D separada
# =====================================================================
class Viewer3DWindow(ctk.CTkToplevel):
    """Ventana independiente que aloja el visor 3D a pantalla casi completa."""

    def __init__(self, master, fbx_dir, stl_dir, status_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title("NEUROHUB - VISOR 3D")
        self.configure(fg_color=COLORS["bg"])

        self.preview_3d = FBXPreviewPanel(self, fbx_dir, stl_dir,
                                          status_callback=status_callback)
        self.preview_3d.pack(fill="both", expand=True, padx=12, pady=12)

        self.geometry("1280x900")
        self.minsize(800, 600)
        # Una vez dibujada la ventana, forzar el render con el tamaño real.
        self.after(250, self._render_after_layout)
        self.lift()
        self.focus_force()

    def _render_after_layout(self):
        """Fuerza el render del visor 3D tras el primer layout de la ventana."""
        try:
            if self.preview_3d is not None and self.preview_3d._models:
                self.preview_3d._render_to_label()
        except Exception:
            pass


# =====================================================================
# CLASE: Ventana 2D separada
# =====================================================================
class Viewer2DWindow(ctk.CTkToplevel):
    """Ventana independiente que aloja las vistas 2D (axial/coronal/sagital)."""

    def __init__(self, master, slice_dir, status_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title("NEUROHUB - VISTAS 2D")
        self.configure(fg_color=COLORS["bg"])

        self.slices_2d = Slice2DPanel(self, slice_dir)
        self.slices_2d.pack(fill="both", expand=True, padx=12, pady=12)

        self.geometry("1100x1200")
        self.minsize(600, 700)
        self.lift()
        self.focus_force()


# =====================================================================
# CLASE: Visor Unificado 2D+3D → ahora en VENTANAS SEPARADAS
# =====================================================================
class UnifiedViewerPanel(ctk.CTkFrame):
    """Controlador que abre EL VISOR 3D y LAS VISTAS 2D en VENTANAS SEPARADAS.

    Mantiene la misma API (refresh_models / load_2d_slices / preview_3d /
    slices_2d) para no romper el resto de la app, pero cada parte vive en su
    propia ventana top-level en lugar de compartir un mismo espacio.
    """

    def __init__(self, master, fbx_dir, stl_dir, slice_dir, status_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color=COLORS["bg"], corner_radius=0)
        self._status_cb = status_callback
        self.fbx_dir = fbx_dir
        self.stl_dir = stl_dir
        self.slice_dir = slice_dir

        # Referencias a las ventanas separadas (se crean bajo demanda)
        self._win3d = None
        self._win2d = None
        self.preview_3d = None  # se completa al abrir la ventana 3D
        self.slices_2d = None   # se completa al abrir la ventana 2D

        # Panel informativo + controles dentro del espacio de la app principal
        info = ctk.CTkFrame(self, fg_color=COLORS["bg_secondary"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        info.pack(fill="both", expand=True, padx=4, pady=4)

        ctk.CTkLabel(info, text="🔲  VISUALIZACIÓN EN VENTANAS SEPARADAS",
                     font=(FONT_TITLE, 16, "bold"), text_color=COLORS["text"]).pack(pady=(24, 4))
        ctk.CTkLabel(info, text="El visor 3D y las vistas 2D se abren en ventanas independientes "
                                "para aprovechar al máximo el espacio de pantalla.",
                     font=(FONT_FAMILY, 12), text_color=COLORS["text_secondary"],
                     wraplength=500, justify="center").pack(pady=(0, 20))

        btn_row = ctk.CTkFrame(info, fg_color="transparent")
        btn_row.pack(pady=4)

        self.btn_open_3d = ctk.CTkButton(
            btn_row, text="🖥  Abrir Visor 3D", command=self.open_3d_window,
            width=210, height=46, corner_radius=8, fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"], text_color=COLORS["on_accent"],
            font=(FONT_TITLE, 14, "bold"))
        self.btn_open_3d.pack(side="left", padx=8)

        self.btn_open_2d = ctk.CTkButton(
            btn_row, text="🗂  Abrir Vistas 2D", command=self.open_2d_window,
            width=210, height=46, corner_radius=8, fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_input"], border_color=COLORS["border"],
            border_width=1, font=(FONT_TITLE, 14, "bold"))
        self.btn_open_2d.pack(side="left", padx=8)

        ctk.CTkLabel(info, text="Consejo: maximiza cada ventana para la máxima resolución de render.",
                     font=(FONT_FAMILY, 11), text_color=COLORS["text_secondary"]).pack(pady=(18, 8))

    def _log(self, message, level="INFO"):
        if self._status_cb:
            self._status_cb(message, level)

    def open_3d_window(self):
        """Abre (o trae al frente) la ventana 3D independiente."""
        if self._win3d is None or not self._win3d.winfo_exists():
            self._win3d = Viewer3DWindow(self, self.fbx_dir, self.stl_dir,
                                         status_callback=self._status_cb)
            self.preview_3d = self._win3d.preview_3d
            self._win3d.protocol("WM_DELETE_WINDOW", self._close_win3d)
        else:
            self._win3d.deiconify()
            self._win3d.lift()
            self._win3d.focus_force()
        return self._win3d

    def open_2d_window(self):
        """Abre (o trae al frente) la ventana 2D independiente."""
        if self._win2d is None or not self._win2d.winfo_exists():
            self._win2d = Viewer2DWindow(self, self.slice_dir)
            self.slices_2d = self._win2d.slices_2d
            self._win2d.protocol("WM_DELETE_WINDOW", self._close_win2d)
        else:
            self._win2d.deiconify()
            self._win2d.lift()
            self._win2d.focus_force()
        return self._win2d

    def _close_win3d(self):
        if self._win3d is not None:
            try:
                self._win3d.destroy()
            except Exception:
                pass
        self._win3d = None
        self.preview_3d = None

    def _close_win2d(self):
        if self._win2d is not None:
            try:
                self._win2d.destroy()
            except Exception:
                pass
        self._win2d = None
        self.slices_2d = None

    def ensure_open(self):
        """Abre ambas ventanas (conveniente al arrancar)."""
        self.open_3d_window()
        self.open_2d_window()

    def refresh_models(self):
        """Actualiza el visor 3D (en su ventana separada), abriéndola si hace falta."""
        if self._win3d is None or not self._win3d.winfo_exists():
            self.open_3d_window()
        if self.preview_3d is not None:
            self.preview_3d.refresh_models()

    def load_2d_slices(self):
        """Carga las vistas 2D (en su ventana separada), abriéndola si hace falta."""
        if self._win2d is None or not self._win2d.winfo_exists():
            self.open_2d_window()
        if self.slices_2d is not None:
            self.slices_2d.load_slices()


# =====================================================================
# CLASE: Visor 3D de Modelos FBX (Original, mantenido por compatibilidad)
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

        # ---- Selector de estructuras visibles (superponer cráneo + cerebro) ----
        # El visor antes solo podía mostrar UN modelo a la vez. Con estas
        # casillas se activan varias estructuras a la vez, que es la vista de
        # uso clínico (cráneo transparente + cerebro + tumor/vasos dentro).
        self.layers_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.layers_frame.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkLabel(self.layers_frame, text="Estructuras:",
                     font=(FONT_FAMILY, 11),
                     text_color=COLORS["text_secondary"]).pack(side="left")

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

        # Estado del visor VTK (offscreen) + lienzo Tk donde se muestra la imagen.
        # La geometría vive en self._actors (un actor por modelo y nivel de
        # calidad); aquí solo queda el renderer y la imagen mostrada.
        self._ren = None
        self._ren_win = None
        self._img_tk = None
        self._img_label = None
        self._vtk_initialized = False
        self._placeholder_placed = False
        self._dragging = False
        self._last_x = 0
        self._last_y = 0
        # Caché de mallas por (ruta STL, nivel de calidad) para no
        # re-simplificar ni re-cargar en cada render / cada drag y zoom. El
        # cuello de botella del render era volver a construir la polydata VTK
        # con bucles Python puros para mallas de cientos de miles de
        # triángulos, congelando la UI.
        self._mesh_cache = {}

        # Escena multi-modelo: un actor por modelo, por nivel de calidad.
        self._actors = {}          # {clave: {"high": {...}, "medium": {...}}}
        self._visible_keys = set()  # claves visibles (puede ser más de una)
        self._scene_key = None      # tupla ordenada detectando cambios de escena
        self._quality = "high"      # nivel de calidad del ÚLTIMO render mostrado
        self._checkboxes = {}       # {clave: CTkCheckBox} para mostrar/ocultar

        self.refresh_models()

    # --------------------------------------------------------------
    def _log(self, message, level="INFO"):
        if self._status_cb:
            self._status_cb(message, level)

    def _scan_models(self):
        """Descubre los modelos disponibles para el visor.

        Se consultan varias carpetas porque cada etapa del proyecto escribe en
        un sitio distinto: los FBX de exportación (MODELOS_DIR/fbx) y las
        mallas STL de máxima resolución (salidas/mallas). Antes solo se
        listaban los .fbx, de modo que con las mallas ya generadas el visor se
        quedaba vacío ("Aún no hay modelos FBX").

        La clave es el nombre de archivo en minúsculas y el material se resuelve
        con resolve_pbr, que aplica los alias de PBR_COLORS.
        """
        models = {}

        def _add(stl_path, name):
            key = os.path.splitext(name)[0].lower()
            meta = resolve_pbr(key)
            models[key] = {
                "fbx": None,
                "stl": stl_path,
                "name": name,
                "label": meta.get("label", key.replace("_", " ").title()),
                "display": meta.get("display", "#8B8B8B"),
                "color_rgba": meta.get("color_rgba", (0.6, 0.6, 0.6, 1.0)),
            }

        # 1) Mallas STL: fuente principal (geometría de máxima resolución).
        for d in (self.stl_dir, MALLAS_DIR):
            if not d or not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".stl"):
                    _add(os.path.join(d, f), f)

        # 2) FBX de exportación: se listan SOLO si no hay STL equivalente, para
        #    no duplicar la misma estructura en el menú.
        if os.path.isdir(self.fbx_dir):
            for f in sorted(os.listdir(self.fbx_dir)):
                if not f.lower().endswith(".fbx"):
                    continue
                key = os.path.splitext(f)[0].lower()
                if key in models:
                    continue
                base = os.path.splitext(f)[0]
                stl = os.path.join(self.stl_dir or "", base + ".stl")
                if not os.path.isfile(stl):
                    stl = os.path.join(MALLAS_DIR, base + ".stl")
                if not os.path.isfile(stl):
                    continue
                _add(stl, f)

        return models

    def _build_layer_toggles(self, keys):
        """(Re)crea las casillas de visibilidad de cada estructura.

        Se llama desde refresh_models. Las casillas permiten ver varias
        estructuras a la vez, que es lo que hace posible la vista clínica de
        cráneo + cerebro + tumor superpuestos.
        """
        for child in self.layers_frame.winfo_children():
            if child is not None and child.winfo_class() == "TCheckbutton":
                child.destroy()
        self._checkboxes = {}

        for key in keys:
            meta = self._models[key]
            var = ctk.StringVar(value="on" if key in self._visible_keys else "off")
            try:
                cb = ctk.CTkCheckBox(
                    self.layers_frame, text=meta["label"], variable=var,
                    command=lambda k=key: self._toggle_layer(k),
                    fg_color=meta["display"], hover_color=meta["display"],
                    text_color=COLORS["text"], font=(FONT_FAMILY, 11))
            except Exception:
                # CTkCheckBox sin soporte de colores: se usa el neutro.
                cb = ctk.CTkCheckBox(
                    self.layers_frame, text=meta["label"], variable=var,
                    command=lambda k=key: self._toggle_layer(k),
                    font=(FONT_FAMILY, 11))
            cb.pack(side="left", padx=(0, 12), pady=2)
            self._checkboxes[key] = (cb, var)

    def _toggle_layer(self, key):
        """Activa o desactiva una estructura y vuelve a renderizar."""
        entry = self._checkboxes.get(key)
        if entry is None:
            return
        var = entry[1]
        activo = var.get() == "on"
        if activo:
            self._visible_keys.add(key)
        else:
            self._visible_keys.discard(key)

        # Si se ocultó todo, se deja visible el modelo del menú para no
        # quedarse con un lienzo completamente vacío.
        if not self._visible_keys and self._current_key in self._models:
            self._visible_keys = {self._current_key}
            self._set_checkbox_states()

        self._log(f"Estructura {'visible' if activo else 'oculta'}: "
                  f"{self._models[key]['label']}", "INFO")
        self._render_vtk()

    def _set_checkbox_states(self):
        """Sincroniza las casillas con el conjunto de estructuras visibles."""
        for key, (cb, var) in self._checkboxes.items():
            var.set("on" if key in self._visible_keys else "off")

    def refresh_models(self):
        self._models = self._scan_models()
        keys = sorted(self._models.keys())
        names = [self._models[k]["name"] for k in keys]
        if not names:
            self.model_menu.configure(values=["—"])
            self.model_var.set("—")
            self._show_message("Aún no hay mallas 3D.\n\nEjecute el Pipeline para "
                               "generar las mallas STL en salidas/mallas.")
            return
        self.model_menu.configure(values=names)
        if self._current_key not in keys:
            self._current_key = keys[0]

        # Si es la primera carga (o el modelo actual ya no existe), se activa
        # por defecto el modelo del menú para que el visor no arranque vacío.
        if not self._visible_keys or not (self._visible_keys & set(keys)):
            self._visible_keys = {self._current_key}

        self._build_layer_toggles(keys)
        self.model_var.set(self._models[self._current_key]["name"])
        self._render_current()

    def _on_select(self, name):
        for key, meta in self._models.items():
            if meta["name"] == name:
                self._current_key = key
                break
        # Elegir del menú fija el modelo activo, pero NO borra el resto de la
        # escena: si el usuario ya tenía varias estructuras visibles, esta se
        # añade a la vista.
        self._visible_keys.add(self._current_key)
        self._set_checkbox_states()
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
        # La calidad del render en reposo es siempre "high": la imagen final
        # que ve el usuario usa la malla de máxima resolución.
        self._quality = "high"
        self._render_vtk(meta, level="high")

    # --------------------------------------------------------------
    def _ensure_canvas(self):
        """Inicializa el renderizador VTK offscreen (una sola vez)."""
        if self._vtk_initialized:
            return
        import vtk
        self._ren = vtk.vtkRenderer()
        self._ren.SetBackground(0.047, 0.047, 0.055)  # equivalente a VIEW_BG (#0c0c0e)
        
        # ========== ILUMINACIÓN DE ULTRADETALLE ==========
        # Luz principal (key light) - directa y fuerte
        light1 = vtk.vtkLight()
        light1.SetPosition(1.0, 0.5, 1.0)
        light1.SetIntensity(1.0)
        light1.SetColor(1.0, 1.0, 1.0)
        self._ren.AddLight(light1)
        
        # Luz de relleno (fill light) - suave desde otro ángulo
        light2 = vtk.vtkLight()
        light2.SetPosition(-0.8, 0.3, 0.5)
        light2.SetIntensity(0.5)
        light2.SetColor(0.9, 0.9, 0.95)
        self._ren.AddLight(light2)
        
        # Luz de borde (rim light) - para resaltar contornos
        light3 = vtk.vtkLight()
        light3.SetPosition(0.0, -1.0, 0.2)
        light3.SetIntensity(0.4)
        light3.SetColor(0.8, 0.85, 0.95)
        self._ren.AddLight(light3)
        
        # Luz ambiental global suave
        self._ren.SetAmbient(0.2, 0.2, 0.22)
        
        self._ren_win = vtk.vtkRenderWindow()
        self._ren_win.AddRenderer(self._ren)
        self._ren_win.SetOffScreenRendering(1)
        # ========== RENDERIZADO DE MÁXIMA CALIDAD ==========
        # Tamaño inicial; el tamaño real de cada frame lo calcula
        # _render_to_label (que aplica supersampling). Se pone un valor alto
        # para que el primer render ya salga con margen antes de que el widget
        # Tk haya informado de su geometría definitiva.
        self._ren_win.SetSize(1600, 1000)
        # Anti-aliasing por MULTISAMPLING: renderiza N muestras por pixel y las
        # promedia, que es lo que suaviza de verdad los bordes de la malla.
        # Valores altos = mejor calidad.
        #
        # FXAA queda DESACTIVADO a proposito. Convierte la escena a un mapa de
        # pendientes en un framebuffer de<float> y renderiza encima; combinado
        # con el multisampling anterior producia un framebuffer VACIO (un solo
        # color) en el 100 % de los casos, medido en _diag_render.py. No es que
        # uno de los dos sirva y el otro no: es que juntos se anulan. Como el
        # MSAA ya promedia muestras de verdad, se queda solo con el.
        try:
            self._ren_win.SetMultiSamples(8)
        except Exception:
            pass
        # Ordenación por profundidad: imprescindible para que la mezcla de
        # opacidades (cráneo/cerebro transparentes) sea correcta y no
        # aparezcan artefactos de interpenetración.
        try:
            self._ren.SetUseDepthPeeling(1)
            self._ren.SetMaximumNumberOfPeels(8)
            self._ren.SetOcclusionRatio(0.1)
        except Exception:
            pass
        self._vtk_initialized = True

    def _mesh_to_polydata(self, vs, faces):
        """Construye vtkPolyData de forma VECTORIZADA.

        La versión anterior insertaba cada punto y cada triángulo con bucles
        Python puros (pts.SetPoint / tris.InsertNextCell), lo que para mallas
        de cientos de miles de triángulos congelaba la interfaz durante
        segundos/minutos. Aquí se convierten los numpy arrays en un solo paso.
        """
        import numpy as np
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

        vs = np.ascontiguousarray(vs, dtype=np.float32)
        faces = np.ascontiguousarray(faces, dtype=np.int64)

        pd = vtk.vtkPolyData()

        # --- Puntos: crear vtkPoints en un solo paso desde los vértices ---
        pts = vtk.vtkPoints()
        pts.SetDataTypeToFloat()
        pts.SetData(numpy_to_vtk(vs, deep=True))
        pd.SetPoints(pts)

        # --- Celdas (triángulos) ---
        # API moderna de vtkCellArray (9.6+): SetData(cellSize, connectivity)
        # con connectivity = array plano de índices (i0,i1,i2, i0,i1,i2, ...).
        n_faces = faces.shape[0]
        if n_faces > 0:
            conn = np.ascontiguousarray(faces.reshape(-1), dtype=np.int64)
            cells = vtk.vtkCellArray()
            cells.SetData(3, numpy_to_vtkIdTypeArray(conn, deep=True))
            pd.SetPolys(cells)

        return pd

    # Presupuesto de caras del visor, en tres niveles.
    #
    # Antes el techo era único y fijo (30k) para cualquier malla, con lo que
    # el cráneo (1.6M caras) y el cerebro (640k) se veían con ~2% de su
    # detalle real: de ahí la apariencia "baja resolución" del visor. Ahora
    # el techo depende del MODELO (no del tamaño de la malla): las estructuras
    # grandes y de superficie lisa (cráneo, cerebro) son las que más ganancia
    # dan con más triángulos.
    #
    #   HIGH   -> en reposo: la imagen final que ve el usuario.
    #   MEDIUM -> durante el arrastre y el zoom (se prioriza la fluidez).
    #
    # La lógica de "cuál nivel usar" vive en _quality_faces(), que además
    # contempla el tamaño real del lienzo.
    QUALITY_FACES = {
        "high":   {"craneo": 900000, "cerebro": 700000, "default": 400000},
        "medium": {"craneo": 150000, "cerebro": 120000, "default": 80000},
    }
    # Techo absoluto como red de seguridad (evita que una malla patológica
    # con millones de caras sin clasificar tumbe la interfaz).
    MAX_FACES_ABSOLUTO = 1200000

    def _quality_faces(self, key, level):
        """Devuelve el techo de caras para `key` en el nivel `level` dado."""
        tabla = self.QUALITY_FACES.get(level, self.QUALITY_FACES["medium"])
        # Se normaliza la clave por si el archivo tiene un sufijo
        # ("cerebro_completo.stl") y así hereda el presupuesto de su estructura.
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
        """Carga y simplifica la malla al nivel de calidad pedido, con CACHÉ.

        Antes se guardaba una única versión simplificada a 30k caras por ruta.
        Ahora se cachea una versión por (ruta, nivel): la de "high" para el
        render en reposo y la de "medium" para el arrastre, de modo que cambiar
        de nivel en caliente no obliga a releer ni re-simplificar el STL.

        El índice `key` es la clave canónica del modelo ("craneo", "cerebro",
        ...) y se usa para elegir el techo de caras de cada nivel.
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
                pass

        self._mesh_cache[cache_key] = mesh
        return mesh

    # ------------------------------------------------------------------
    # ESCENA MULTI-MODELO
    #
    # El visor antes tenía UN SOLO actor: solo se podía ver un modelo cada
    # vez, así que no había forma de superponer cráneo y cerebro (que es
    # justamente la vista de uso clínico). Ahora la escena mantiene un actor
    # por modelo y un conjunto de claves visibles.
    #
    # Los modelos se dibujan ORDENADOS: primero el cráneo y el cerebro
    # (superficies envolventes, semitransparentes) y después las estructuras
    # internas (tumor, vasos), para que el orden de transparencia sea correcto.
    ORDEN_ESCENA = ["craneo", "skull", "cerebro", "brain",
                    "tumor", "aneurisma"]

    # Opacidad por estructura. El cráneo y el cerebro son envolventes: se
    # hacen semitransparentes cuando hay algo visible dentro, o el interior
    # (tumor, vasos) quedaría completamente oculto.
    OPACIDAD_ESTRUCTURA = {
        "craneo": 0.28,
        "cerebro": 0.45,
    }

    def _scene_order(self, key):
        """Índice de dibujado de `key` (menor = más atrás)."""
        for i, name in enumerate(self.ORDEN_ESCENA):
            if name in key:
                return i
        return len(self.ORDEN_ESCENA)

    def _canon_key(self, key):
        """Clave canónica de una estructura ("skull" -> "craneo", etc.)."""
        k = (key or "").lower()
        return PBR_ALIASES.get(k, k)

    def _build_actor(self, key, level="high"):
        """Crea (o reutiliza) el actor VTK de un modelo en el nivel dado.

        El actor se cachea por (clave, nivel) para que cambiar de calidad en
        caliente no reconstruya la geometría innecesariamente. Devuelve el
        dict {"pd", "mapper", "actor"} o None si no se pudo construir.
        """
        import numpy as np
        import vtk

        store = self._actors.setdefault(key, {})
        if level in store:
            return store[level]

        meta = self._models.get(key)
        stl = meta["stl"] if meta else None
        if not stl or not os.path.isfile(stl):
            return None

        mesh = self._load_preview_mesh(stl, key, level)
        vs = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)

        pd = self._mesh_to_polydata(vs, faces)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(pd)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        rgba = meta["color_rgba"]
        prop = actor.GetProperty()
        prop.SetColor(rgba[0], rgba[1], rgba[2])
        # ========== RENDERIZADO DE ULTRADETALLE ==========
        # Propiedades PBR mejoradas para máxima fidelidad clínica
        prop.SetAmbient(0.28)
        prop.SetDiffuse(0.72)
        prop.SetSpecular(0.35)          # Mayor especularidad
        prop.SetSpecularPower(64.0)     # Brillo puntuado (ultradetalle)
        prop.SetInterpolationToPhong()  # Suavizado por normales (Gouraud)
        prop.EdgeVisibilityOff()
        # Metallic y roughness (si el modelo lo soporta)
        try:
            prop.SetMetallic(0.0)
            prop.SetRoughness(0.75)
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
            nrm.Update()
            mapper.SetInputData(nrm.GetOutput())
        except Exception:
            pass

        store[level] = {"pd": pd, "mapper": mapper, "actor": actor}
        return store[level]

    def _sync_scene(self, level="high"):
        """Aplica al renderer la escena actual: un actor por modelo visible.

        Los actores se crean una vez y después solo se les cambia la
        visibilidad, de modo que pasar de "medium" a "high" no rehace la escena
        entera. Devuelve la lista ordenada de claves visibles.
        """
        vis = [k for k in (self._visible_keys or {self._current_key}) if k]
        # Orden de dibujado: envolventes primero, estructuras internas después.
        ordered = sorted(vis, key=self._scene_order)

        # Construir (o recuperar de caché) el actor de cada modelo visible.
        built = {}
        for key in ordered:
            actor_data = self._build_actor(key, level)
            if actor_data is not None:
                built[key] = actor_data

        # Quitar del renderer los actores que ya no se necesitan.
        coll = self._ren.GetActors()
        wanted = {b["actor"] for b in built.values()}
        for i in range(coll.GetNumberOfItems()):
            a = coll.GetItemAsObject(i)
            if a not in wanted:
                self._ren.RemoveActor(a)

        # Añadir / actualizar opacidad según si hay estructuras dentro.
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
                # Hay algo visible más "interior" (tumor, vasos) en la escena.
                hay_dentro = any(self._scene_order(k) > mi_orden
                                 for k in ordered if k != key)
                actor.GetProperty().SetOpacity(base_alpha if hay_dentro else 1.0)

        return ordered

    def _render_vtk(self, meta=None, level="high"):
        """Renderiza la escena (uno o varios modelos) con VTK offscreen."""
        try:
            self._ensure_canvas()

            if meta is not None and not self._visible_keys:
                # Primer modelo tras abrir el visor: se muestra solo.
                self._visible_keys = {self._current_key}

            ordered = self._sync_scene(level)
            if not ordered:
                self._show_message("No hay geometría disponible para mostrar.")
                return

            # El encuadre solo se recalcula cuando cambia la ESCENA (no en
            # cada arrastre), para que la vista no salte al rotar o hacer zoom.
            escena_key = tuple(sorted(self._visible_keys))
            if escena_key != self._scene_key:
                self._ren.ResetCamera()
                self._scene_key = escena_key

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

    # Factor de SUPERSAMPLING: se renderiza a esta resolución y luego se
    # reduce al tamaño del lienzo con LANCZOS. Antes el render era 1:1 con el
    # lienzo (SetSize(w, h)), así que el detalle fino de las mallas se perdía
    # al escalar la imagen al widget. 2.0 en reposo y 1.0 al arrastrar.
    SUPERSAMPLE_REPOSO = 2.0
    SUPERSAMPLE_MOVIMIENTO = 1.0
    # Tope de píxeles del render: evita que una ventana muy grande (p. ej.
    # 4K maximizada) genere un framebuffer desmedido y ralentice el render.
    MAX_PIXELS_RENDER = 6_000_000

    def _render_to_label(self, throttle=False):
        """Renderiza el frame actual de VTK y lo muestra en un widget Tk Label.

        - throttle=True limita la frecuencia de render durante el arrastre/zoom
          para que la interfaz no se congele con cada movimiento de ratón.
        - En reposo usa supersampling: renderiza a 2x el tamaño del lienzo y
          reduce con LANCZOS, lo que elimina el aliasing de los bordes.
        """
        import time as _time
        try:
            if throttle:
                now = _time.monotonic()
                last = getattr(self, "_last_render_ts", 0.0)
                # ~33 fps máx durante la interacción; el render final forzado
                # ocurre en el release del ratón (o al siguiente evento >34ms).
                if (now - last) < 0.03:
                    return
                self._last_render_ts = now

            from PIL import Image, ImageTk
            import numpy as np
            import vtk
            from vtk.util.numpy_support import vtk_to_numpy

            w, h = self._canvas_size()
            if w <= 1 or h <= 1:
                return

            # ---- resolución interna del render (supersampling) ----
            if throttle:
                factor = self.SUPERSAMPLE_MOVIMIENTO
            else:
                factor = self.SUPERSAMPLE_REPOSO
            rw, rh = int(w * factor), int(h * factor)
            # Tope de píxeles: si se pasa, se reduce el factor proporcionalmente.
            if rw * rh > self.MAX_PIXELS_RENDER:
                escala = (self.MAX_PIXELS_RENDER / float(rw * rh)) ** 0.5
                rw, rh = max(int(rw * escala), 1), max(int(rh * escala), 1)

            self._ren_win.SetSize(rw, rh)
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

            # ---- Reducción al tamaño del lienzo (supersampling) ----
            # Si el render se hizo a más resolución que el lienzo, se reduce
            # con LANCZOS. Esto es lo que elimina el "escalado" visible de la
            # imagen y da el aspecto de alta resolución.
            if (width, height) != (w, h):
                img = img.resize((w, h), Image.LANCZOS)

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
    def _set_quality(self, level):
        """Cambia el nivel de calidad de la escena y re-renderiza.

        Durante el arrastre se usa "medium" (malla ligera) para que la rotación
        vaya fluida; al soltar el ratón se vuelve a "high", que es la calidad
        final que ve el usuario. Los actores de cada nivel están cacheados, así
        que alternar entre ellos no vuelve a leer ni simplificar el STL.
        """
        if self._ren is None or level == self._quality:
            return
        try:
            if not self._sync_scene(level):
                return
            self._quality = level
            self._render_to_label()
        except Exception:
            pass

    def _on_press(self, event):
        self._dragging = True
        self._last_x = event.x
        self._last_y = event.y
        # Malla ligera mientras se arrastra: el coste va por triángulo, no por
        # píxel, así que bajar la malla es lo que da fluidez.
        self._set_quality("medium")

    def _on_release(self, event):
        self._dragging = False
        # Volver a la calidad máxima y forzar el render final sin throttle para
        # dejar la vista nítida.
        if self._ren is not None:
            try:
                self._set_quality("high")
                self._ren_win.Render()
                self._render_to_label()
            except Exception:
                pass

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
        self._render_to_label(throttle=True)

    def _on_wheel(self, event):
        if self._ren is None:
            return
        cam = self._ren.GetActiveCamera()
        if getattr(event, "delta", 0) > 0:
            cam.Dolly(1.12)
        else:
            cam.Dolly(0.88)
        cam.OrthogonalizeViewUp()
        # El zoom también redibuja con la malla ligera mientras dura el gesto.
        if not self._dragging:
            self._set_quality("medium")
        self._render_to_label(throttle=True)

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
        """Guarda la vista actual como PNG.

        Con la escena multi-modelo ya no hay un único `self._actor`, así que
        basta con comprobar que el renderer tiene algún actor. El render se
        hace a la máxima resolución de reposo (SUPERSAMPLE_REPOSO) en vez de al
        tamaño del lienzo, para que la imagen guardada tenga más detalle que
        la vista en pantalla.
        """
        if self._ren_win is None or self._ren is None:
            return
        coll = self._ren.GetActors()
        if coll.GetNumberOfItems() == 0:
            return

        from tkinter import filedialog
        etiquetas = "_".join(sorted(self._visible_keys)) or (self._current_key or "modelo")
        path = filedialog.asksaveasfilename(
            title="Guardar vista del modelo", defaultextension=".png",
            initialfile=f"{etiquetas}_preview.png",
            filetypes=[("Imagen PNG", "*.png")])
        if not path:
            return

        import vtk
        w, h = self._canvas_size()
        rw, rh = int(w * self.SUPERSAMPLE_REPOSO), int(h * self.SUPERSAMPLE_REPOSO)
        if rw * rh > self.MAX_PIXELS_RENDER:
            escala = (self.MAX_PIXELS_RENDER / float(rw * rh)) ** 0.5
            rw, rh = max(int(rw * escala), 1), max(int(rh * escala), 1)

        # Tamaño original del render, para restaurarlo después (el mismo
        # render_window se usa para el visor interactivo).
        self._ren_win.SetSize(rw, rh)
        try:
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
        finally:
            self._ren_win.SetSize(int(w), int(h))

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
    """Aplicación principal de NEUROHUB."""

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
        self.ui_queue = queue.Queue()
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

        # Iniciar procesamiento de colas (logs + UI) en el hilo principal
        self.after(100, self._process_queues)

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

        # Columna izquierda: visor 3D + 2D (superior) + consola de logs (inferior)
        left_col = ctk.CTkFrame(view_row, fg_color=COLORS["bg"], corner_radius=0)
        left_col.pack(side="left", fill="both", expand=True)

        # Visor unificado 3D + 2D: ocupa la parte superior, se expande hacia abajo
        viewer_host = ctk.CTkFrame(left_col, fg_color=COLORS["bg"], corner_radius=0)
        viewer_host.pack(side="top", fill="both", expand=True)
        fbx_dir = os.path.join(MODELOS_DIR, "fbx")
        stl_dir = os.path.join(MODELOS_DIR, "stl")
        slice_dir = os.path.join(SALIDAS_DIR, "segmentaciones_ai", "vistas_2d")
        self.unified_viewer = UnifiedViewerPanel(
            viewer_host, fbx_dir, stl_dir, slice_dir,
            status_callback=self._log)
        self.unified_viewer.pack(fill="both", expand=True)
        
        # Guardar referencias para acceso posterior
        self.preview_panel = self.unified_viewer.preview_3d

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

        self.console = LogConsole(console_frame, height=120)
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
        """Drena la cola de logs (SIEMPRE desde el hilo principal)."""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.console.log(message, level)
        except queue.Empty:
            pass

    def _enqueue_ui(self, command, *args):
        """Encoda una operación de UI para el hilo principal.

        Tkinter/customtkinter NO son thread-safe: toda mutación de widgets debe
        ocurrir en el hilo principal. Los hilos de trabajo (pipeline) solo
        encolan la operación; _process_ui_queue la aplica en el hilo principal.
        Esto elimina los cierres/congelamientos del hilo de Tk que se producían
        al llamar directamente a widgets (progress_bar, labels, botones, tarjetas)
        desde el hilo del pipeline después de terminar la malla de vasos.
        """
        self.ui_queue.put((command, args))

    def _process_ui_queue(self):
        """Drena la cola de operaciones de UI (solo hilo principal)."""
        try:
            while True:
                command, args = self.ui_queue.get_nowait()
                if command == "progress":
                    self.progress_bar.set(args[0])
                elif command == "status":
                    self.status_label.configure(text=args[0])
                elif command == "running":
                    self._apply_running_state(args[0])
                elif command == "card":
                    card_attr, value, color = args
                    card = getattr(self, card_attr, None)
                    if card is not None:
                        card.set_value(value, color)
                elif command == "messagebox_error":
                    messagebox.showerror("Error", args[0])
                elif command == "refresh_preview":
                    self._refresh_preview()
        except queue.Empty:
            pass

    def _process_queues(self):
        """Procesa todas las colas hacia la UI desde el hilo principal."""
        self._process_log_queue()
        self._process_ui_queue()
        self.after(100, self._process_queues)

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
        """Actualiza el visor 3D y 2D con los modelos disponibles."""
        if hasattr(self, "unified_viewer") and self.unified_viewer is not None:
            self.unified_viewer.refresh_models()
            self.unified_viewer.load_2d_slices()

    def _refresh_preview_async(self):
        """Actualiza el visor 3D desde el hilo de trabajo (encolado al hilo principal)."""
        try:
            self._enqueue_ui("refresh_preview")
        except Exception:
            pass

    # =================================================================
    # MÉTODOS DE EJECUCIÓN
    # =================================================================
    def _set_running(self, running):
        """Activa/desactiva el estado de ejecución (thread-safe: encola)."""
        # `is_running` es una asignación de atributo simple (segura en CPython);
        # la actualización de widgets se aplica en el hilo principal.
        self.is_running = running
        self._enqueue_ui("running", running)

    def _apply_running_state(self, running):
        """Aplica el estado de ejecución en la UI (solo hilo principal)."""
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
        """Actualiza la barra de estado (thread-safe: encola)."""
        self._enqueue_ui("status", message)

    def _update_progress(self, value):
        """Actualiza la barra de progreso (thread-safe: encola)."""
        self._enqueue_ui("progress", value)

    def _set_card(self, card_attr, value, color=None):
        """Actualiza una tarjeta de estado desde cualquier hilo (encola)."""
        self._enqueue_ui("card", card_attr, value, color)

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
                print("[+] Proceso completado exitosamente", flush=True)
                return result
            except Exception as e:
                self._log(f"Error: {e}", "ERROR")
                self._log(traceback.format_exc(), "ERROR")
                self._update_status("Error en el proceso")
                self._enqueue_ui("messagebox_error", f"Ocurrió un error:\n\n{e}")
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
            self._log("[2/5] Ejecutando segmentación AI (TotalSegmentator)...", "PROGRESS")
            self._update_progress(0.3)
            self.pipeline_01.run_ai_segmentation(nifti_path, output_dir, fast_mode=True)
            self._log("Segmentación AI completada", "SUCCESS")

            # Paso 3: Segmentación de tumor (BRATS con respaldo morfológico)
            self._log("[3/5] Ejecutando segmentación de tumor...", "PROGRESS")
            self._update_progress(0.5)
            self.pipeline_03.integrate_brats_into_pipeline(nifti_path, output_dir)
            brain_path = os.path.join(output_dir, "brain.nii.gz")
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

            # Paso 4: Detección de aneurisma
            self._log("[4/5] Detectando aneurismas...", "PROGRESS")
            self._update_progress(0.7)
            vasos_path = os.path.join(output_dir, "vasos.nii.gz")
            if os.path.exists(vasos_path):
                self.pipeline_03.improve_aneurysm_detection(
                    nifti_path, vasos_path,
                    os.path.join(output_dir, "aneurisma_v2.nii.gz")
                )
                self._log("Detección de aneurisma completada", "SUCCESS")
            else:
                self._log("No se encontró máscara de vasos (vasos.nii.gz), omitiendo detección de aneurisma", "WARNING")

            # Paso 5: Generar modelos 3D
            self._log("[5/5] Generando modelos 3D...", "PROGRESS")
            self._update_progress(0.9)

            stl_dir = os.path.join(MODELOS_DIR, "stl")
            fbx_dir = os.path.join(MODELOS_DIR, "fbx")

            # Cerebro
            brain_path = os.path.join(output_dir, "brain.nii.gz")
            if os.path.exists(brain_path):
                _t0 = time.perf_counter()
                self.pipeline_01.build_mesh(brain_path, os.path.join(stl_dir, "Cerebro.stl"))
                self._log(f"Modelo 3D del cerebro generado ({time.perf_counter() - _t0:.1f}s)", "SUCCESS")

            # Cráneo
            skull_path = os.path.join(output_dir, "skull.nii.gz")
            if os.path.exists(skull_path):
                _t0 = time.perf_counter()
                self.pipeline_01.build_mesh(skull_path, os.path.join(stl_dir, "Craneo.stl"))
                self._log(f"Modelo 3D del cráneo generado ({time.perf_counter() - _t0:.1f}s)", "SUCCESS")

            # Tumor
            tumor_path = os.path.join(output_dir, "tumor_brats.nii.gz")
            if os.path.exists(tumor_path):
                _t0 = time.perf_counter()
                self.pipeline_03.build_mesh_improved(tumor_path, os.path.join(stl_dir, "Tumor.stl"))
                self._log(f"Modelo 3D del tumor generado ({time.perf_counter() - _t0:.1f}s)", "SUCCESS")

            # Aneurisma
            aneu_path = os.path.join(output_dir, "aneurisma_v2.nii.gz")
            if os.path.exists(aneu_path):
                _t0 = time.perf_counter()
                self.pipeline_03.build_mesh_improved(aneu_path, os.path.join(stl_dir, "Aneurisma.stl"))
                self._log(f"Modelo 3D del aneurisma generado ({time.perf_counter() - _t0:.1f}s)", "SUCCESS")

            print("[+] PIPELINE COMPLETADO: modelos STL generados correctamente", flush=True)
            self._update_progress(1.0)
            self._log("=" * 60, "HEADER")
            self._log("PIPELINE COMPLETADO", "HEADER")
            self._log("=" * 60, "HEADER")

            # Actualizar tarjetas (encolado: se aplica en el hilo principal)
            self._set_card("card_resultados", "Pipeline completado", COLORS["success"])
            self._set_card("card_modelos", "4 modelos generados", COLORS["success"])

            # Refrescar el visor 3D para mostrar los modelos recién generados
            # (encolado al hilo principal; el render usa la caché + polydata
            # vectorizada, venas ~0.2s).
            self._refresh_preview_async()

            print("[+] Visor 3D actualizado con los modelos nuevos", flush=True)

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

            self._update_progress(0.8)
            self._log("Actualizando vistas 2D...", "PROGRESS")
            # Refrescar el visualizador de vistas 2D
            self._refresh_preview_async()
            
            self._update_progress(1.0)
            self._log(f"Segmentación BRATS completada: {result}", "SUCCESS")
            self._set_card("card_resultados", "BRATS completado", COLORS["success"])

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
                self._log("No se encontró máscara de vasos (vasos.nii.gz). Se requiere una máscara previa para la detección de aneurismas.", "WARNING")
                self._update_progress(1.0)
                self._set_card("card_resultados", "Falta vasos.nii.gz", COLORS["warning"])
                return

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
            self._set_card("card_resultados", f"{len(reporte)} candidatos", COLORS["success"])

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
                # FIDELIDAD CLÍNICA: se exporta la malla con su resolución NATIVA
                # (sin decimar), para preservar el máximo realismo anatómico.
                # NO se optimiza para Unity/HoloLens/Quest: la decimación sigue
                # disponible opcionalmente vía el parámetro max_faces de la función.
                self.pipeline_01.export_stl_to_single_fbx(
                    stl_path, fbx_path, **params)
                self._log(f"FBX generado: {fbx_name}", "SUCCESS")

            self._update_progress(1.0)
            self._set_card("card_modelos", f"{total} FBX exportados", COLORS["success"])
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