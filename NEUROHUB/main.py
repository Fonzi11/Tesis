"""
NEUROHUB - Plataforma Unificada Multiplataforma
=================================================
tkinter (GUI) + pygame (Visor 3D) + turtle (Anatomía)
Dark theme completo | Detección de tumores y aneurismas
"""
import os
import sys
import threading
import queue
import webbrowser
from datetime import datetime
from pathlib import Path

NEUROHUB_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(NEUROHUB_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import data_manager as dm
import customtkinter as ctk
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_NAME = "NEUROHUB"
APP_VERSION = "1.0.0"
BG = "#000000"
BG2 = "#16161a"
BG3 = "#1e1e24"
BG4 = "#26262c"
ACCENT = "#8ab4f8"
ACCENT2 = "#b6cdfc"
TEXT = "#f4f4f6"
TXT2 = "#b4b4be"
BORDER = "#33333c"
GREEN = "#82d692"
ORANGE = "#ff8c00"
PURPLE = "#c828dc"
RED = "#c83232"
FONT = "Segoe UI"
FONT_T = "Bahnschrift"

class App:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.configure(fg_color=BG)
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 680)
        self.input_path = None
        self.mask_path = None
        self.console = None
        self.content = None
        self._build()
        self.show_files()

    def _build(self):
        # Sidebar
        sb = ctk.CTkFrame(self.root, fg_color=BG2, width=210, corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)
        ctk.CTkLabel(sb, text="🧠 NEUROHUB", font=(FONT_T, 22, "bold"),
                     text_color=ACCENT).pack(pady=(28, 2))
        ctk.CTkLabel(sb, text="v" + APP_VERSION, font=(FONT, 10),
                     text_color=TXT2).pack()
        ctk.CTkLabel(sb, text="Neuroimágenes Multiplataforma",
                     font=(FONT, 9), text_color=TXT2).pack(pady=(0, 12))

        btns = [
            ("📁 Archivos", self.show_files),
            ("🖼️ Visor 3D", self.launch_viewer),
            ("🧩 Anatomía", self.launch_anatomia),
            ("📚 Datasets", self.show_datasets),
            ("🔍 Analizar", self.run_segmentation),
            ("📤 Exportar FBX", self.export_unity),
            ("📤 Neuronav", self.export_neuronav),
            ("❓ Ayuda", self.show_help),
        ]
        for txt, cmd in btns:
            ctk.CTkButton(sb, text=txt, command=cmd, font=(FONT, 13),
                          fg_color=BG3, hover_color=BG4,
                          corner_radius=8, height=40,
                          text_color=TEXT).pack(fill="x", padx=12, pady=5)

        # Main content
        self.content = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

        # Console
        cf = ctk.CTkFrame(self.root, fg_color=BG2, height=150)
        cf.pack(side="bottom", fill="x")
        self.console = ctk.CTkTextbox(cf, height=140, font=(FONT, 11),
                                       fg_color=BG4, text_color=TEXT)
        self.console.pack(fill="both", expand=True, padx=8, pady=6)
        self.console.configure(state="disabled")
        self.log(f"{APP_NAME} v{APP_VERSION} iniciado.")
        self.log("Cargue un archivo DICOM o NIfTI para comenzar.")

    def log(self, msg):
        self.console.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.console.insert("end", f"[{ts}] {msg}\n")

    # ---------------------------------------------------------------
    def show_files(self):
        """Panel de exploración de archivos."""
        self._clear_content()
        ctk.CTkLabel(self.content, text="EXPLORAR ARCHIVOS",
                     font=(FONT_T, 20, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 4))

        # Tabs fila
        tab = ctk.CTkFrame(self.content, fg_color="transparent")
        tab.pack(fill="x", padx=16)
        ctk.CTkButton(tab, text="NIfTI", command=self._show_nifti_list,
                      font=(FONT, 12), width=100).pack(side="left", padx=4)
        ctk.CTkButton(tab, text="DICOM", command=self._show_dicom_list,
                      font=(FONT, 12), width=100).pack(side="left", padx=4)
        ctk.CTkButton(tab, text="Cargar archivo...",
                      command=self._browse_file, font=(FONT, 12),
                      fg_color=GREEN, width=150).pack(side="right")

        # Lista
        self.file_scroll = ctk.CTkScrollableFrame(self.content,
                                                  fg_color=BG2, corner_radius=8)
        self.file_scroll.pack(fill="both", expand=True, padx=16, pady=8)
        self._show_nifti_list()

    def _show_nifti_list(self):
        self._clear_file_list()
        files = dm.listar_archivos_nifti()
        if not files:
            ctk.CTkLabel(self.file_scroll, text="No hay archivos NIfTI en data/nifti",
                         text_color=TXT2).pack(pady=8)
            return
        for f in files[:50]:
            btn = ctk.CTkButton(
                self.file_scroll,
                text=f"  {f['archivo']}\n  📁 {f['directorio']}",
                font=(FONT, 11), fg_color=BG3, hover_color=BG4,
                corner_radius=6, text_color=TEXT, anchor="w",
                height=46,
                command=lambda p=f['ruta']: self._select_nifti(p))
            btn.pack(fill="x", padx=6, pady=3)

    def _show_dicom_list(self):
        self._clear_file_list()
        files = dm.listar_archivos_dicom()
        if not files:
            ctk.CTkLabel(self.file_scroll, text="No hay series DICOM en data/dicom",
                         text_color=TXT2).pack(pady=8)
            return
        for d in files[:30]:
            btn = ctk.CTkButton(
                self.file_scroll,
                text=f"  📁 {d['nombre']} ({d['series']} archivos)",
                font=(FONT, 11), fg_color=BG3, hover_color=BG4,
                corner_radius=6, text_color=TEXT, anchor="w",
                command=lambda p=d['directorio']: self._select_dicom(p))
            btn.pack(fill="x", padx=6, pady=3)

    def _clear_file_list(self):
        for w in self.file_scroll.winfo_children():
            w.destroy()

    def _browse_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Seleccionar archivo médico",
            filetypes=[("Archivos médicos", "*.nii *.nii.gz *.dcm"),
                       ("NIfTI", "*.nii *.nii.gz"),
                       ("DICOM", "*.dcm *.dicom"),
                       ("Todos", "*.*")])
        if path:
            self.input_path = path
            self.log(f"Archivo cargado: {path}")
            self._show_selected(path)

    def _select_nifti(self, path):
        self.input_path = path
        self.log(f"NIfTI seleccionado: {path}")
        self._show_selected(path)

    def _select_dicom(self, dir_path):
        self.input_path = dir_path
        self.log(f"DICOM seleccionado: {dir_path}")
        self._show_selected(dir_path)

    def _show_selected(self, path):
        """Muestra panel con acciones para el archivo seleccionado."""
        self._clear_content()
        ctk.CTkLabel(self.content, text="📋 ARCHIVO SELECCIONADO",
                     font=(FONT_T, 18, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(self.content, text=str(path), font=(FONT, 11),
                     text_color=GREEN).pack(anchor="w", padx=16, pady=2)

        actions = [
            ("🖼️ Abrir en Visor 3D (pygame)",
             lambda: self.launch_viewer(path=path)),
            ("🧩 Ver Anatomía Interactiva (turtle)",
             lambda: self.launch_anatomia()),
            ("🔍 Segmentar Tumor (BRATS/Heurística)",
             lambda: self._segment_volume(path)),
            ("📤 Exportar Para Neuronavegación (STL)",
             lambda: self._export_stl(path)),
            ("🕵️ Detectar Aneurisma",
             lambda: self._detect_aneurysm(path)),
            ("📚 Ver Datasets Disponibles",
             self.show_datasets),
        ]
        for txt, cmd in actions:
            ctk.CTkButton(self.content, text=txt, command=cmd,
                          font=(FONT, 13), fg_color=BG3, hover_color=BG4,
                          corner_radius=8, height=44, text_color=TEXT
                          ).pack(fill="x", padx=32, pady=6)

        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    # ---------------------------------------------------------------
    def show_datasets(self):
        """Muestra los datasets públicos disponibles."""
        self._clear_content()
        ctk.CTkLabel(self.content, text="📚 DATASETS PÚBLICOS",
                     font=(FONT_T, 20, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 8))

        for ds in dm.listar_datasets():
            color = ORANGE if ds["tipo"] == "ANEURISMA" else ACCENT
            ctk.CTkLabel(self.content, text=f"[{ds['tipo']}] {ds['nombre']}",
                         font=(FONT, 13, "bold"), text_color=color).pack(
                anchor="w", padx=16)
            ctk.CTkLabel(self.content, text=ds["descripcion"],
                         font=(FONT, 11), text_color=TXT2,
                         wraplength=900, justify="left").pack(
                anchor="w", padx=32, pady=2)
            ctk.CTkLabel(self.content,
                         text=f"   Formato: {ds['formato']} | "
                              f"Anotaciones: {ds['anotaciones']}",
                         font=(FONT, 10), text_color=GREEN).pack(
                anchor="w", padx=32, pady=2)
            row = ctk.CTkFrame(self.content, fg_color="transparent")
            row.pack(anchor="w", padx=32)
            ctk.CTkButton(row, text="Abrir fuente",
                          font=(FONT, 10), width=120, height=30,
                          command=lambda u=ds['fuente']: webbrowser.open(u)
                          ).pack(side="left", padx=4)
            if ds["id"] == "brats":
                ctk.CTkButton(row, text="Descargar muestra",
                              font=(FONT, 10), width=130, height=30,
                              fg_color=GREEN,
                              command=self._download_brats
                              ).pack(side="left", padx=4)

    def _download_brats(self):
        def _run():
            self.log("Descargando muestra BraTS2021...")
            try:
                res = dm.descargar_braTS_muestra(num_pacientes=2)
                if res:
                    self.log(f"Descargados {len(res)} pacientes.")
                else:
                    self.log("Error de descarga (¿sin internet?)")
            except Exception as e:
                self.log(f"Error: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def launch_viewer(self, path=None):
        """Lanza el visor 3D pygame."""
        p = path or self.input_path
        if not p:
            p = self._find_first_nifti()
        if p:
            self.log(f"Lanzando visor 3D con: {p}")
            threading.Thread(target=self._run_viewer, args=(p,),
                             daemon=True).start()
        else:
            self.log("⚠ No hay volumen cargado. Seleccione un NIfTI primero.")
            self.show_files()

    def _run_viewer(self, path):
        try:
            import viewer3d
            viewer3d.launch_viewer(nifti_path=path, cargar_mallas=True)
        except Exception as e:
            self.log(f"Error visor: {e}")

    def launch_anatomia(self):
        """Lanza el panel anatómico con turtle."""
        self.log("Lanzando anatomía interactiva (turtle)...")
        threading.Thread(target=self._run_anatomia, daemon=True).start()

    def _run_anatomia(self):
        try:
            import anatomia
            anatomia.launch_anatomia()
        except Exception as e:
            self.log(f"Error anatomía: {e}")

    def _find_first_nifti(self):
        files = dm.listar_archivos_nifti()
        if files:
            self.input_path = files[0]["ruta"]
            return self.input_path
        return None

    # ---------------------------------------------------------------
    def run_segmentation(self):
        path = self.input_path or self._find_first_nifti()
        if not path:
            self.log("⚠ Seleccione un NIfTI para segmentar.")
            self.show_files()
            return
        self._segment_volume(path)

    def _segment_volume(self, path):
        self._clear_content()
        ctk.CTkLabel(self.content, text="🔍 SEGMENTANDO",
                     font=(FONT_T, 18, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(self.content, text=str(path),
                     font=(FONT, 11), text_color=GREEN).pack(anchor="w", padx=16)
        self.progress = ctk.CTkProgressBar(self.content, width=500)
        self.progress.pack(pady=16)
        self.progress.set(0)
        self.log(f"Iniciando segmentación de: {path}")

        # Si es un directorio (carpeta de paciente BraTS o serie DICOM),
        # resolver a un NIfTI interno. El pipeline ATLAS detectará luego
        # los hermanos *_t1/_t1ce/_t2/_flair para usar BRATS completo.
        if os.path.isdir(path):
            cand = sorted(
                f for f in os.listdir(path)
                if f.lower().endswith((".nii", ".nii.gz"))
                and not f.lower().endswith("_seg.nii.gz")
            )
            if cand:
                path = os.path.join(path, cand[0])
                self.input_path = path
                self.log(f"Directorio → volumen NIfTI: {os.path.basename(path)}")

        def _run():
            try:
                atlas_src = r"d:\Tesis\ATLAS\src"
                if atlas_src not in sys.path:
                    sys.path.insert(0, atlas_src)
                import importlib
                try:
                    integrar = importlib.import_module("03_integrar_brats")
                except ImportError:
                    integrar = None

                if integrar:
                    self.log("Llamando pipeline ATLAS (BRATS)...")
                    results = integrar.integrate_brats_into_pipeline(
                        path, output_dir=os.path.join(dm.OUTPUT_DIR, "segmentacion"))
                    self.progress.set(1.0)
                    if results and "tumor_brats" in results:
                        m = results.get("metodo", "BRATS")
                        self.log(f"Segmentación completada (método: {m})")
                        self.mask_path = results["tumor_brats"]
                        self.log(f"Máscara: {self.mask_path}")
                    else:
                        m = (results or {}).get("metodo", "?")
                        self.log(f"Segmentación completada (método: {m})")
                        if self.mask_path is None or not os.path.exists(self.mask_path):
                            self.log("BRATS no produjo máscara. Aplicando método "
                                     "heurístico morfológico...")
                            self._heuristic_segment(path)
                else:
                    self._basic_segment(path)
            except Exception as e:
                self.log(f"Error pipeline: {e}")
                self._basic_segment(path)

        threading.Thread(target=_run, daemon=True).start()

    def _heuristic_segment(self, path):
        """Aplica el método morfológico heurístico real (núcleo + histeresis).

        Usa generate_tumor_mask del pipeline ATLAS (01_procesamiento_dicom),
        el mismo respaldo morfológico que usa el pipeline completo. Si no hay
        máscara de cerebro, se deriva una con Otsu + morfología.
        """
        import SimpleITK as sitk
        import numpy as np
        try:
            img = dm.cargar_volumen(path)
            if img is None:
                self.log("No se pudo cargar el volumen.")
                self._basic_segment(path)
                return

            out_dir = os.path.join(dm.OUTPUT_DIR, "segmentacion")
            os.makedirs(out_dir, exist_ok=True)

            # 1) Máscara de cerebro: derivarla SIEMPRE fresca del volumen
            #    actual (evita reutilizar un brain.nii.gz de otro estudio).
            brain_path = os.path.join(out_dir, "brain.nii.gz")
            arr = sitk.GetArrayFromImage(img)
            from skimage import filters
            vals = arr[arr > 0]
            if len(vals) == 0:
                self.log("Volumen sin datos (>0). No se puede segmentar.")
                return
            thresh = filters.threshold_otsu(vals)
            brain = (arr > thresh * 0.5).astype(np.uint8)
            from scipy import ndimage
            brain = ndimage.binary_closing(brain, iterations=3)
            brain = ndimage.binary_opening(brain, iterations=2)
            lab, n = ndimage.label(brain)
            if n > 0:
                sizes = ndimage.sum(brain, lab, range(1, n + 1))
                big = int(np.argmax(sizes)) + 1
                brain = (lab == big).astype(np.uint8)
            out = sitk.GetImageFromArray(brain)
            out.CopyInformation(img)
            sitk.WriteImage(out, brain_path)
            self.log(f"Máscara de cerebro derivada: {brain_path}")

            # 2) Heurística morfológica real del pipeline ATLAS
            atlas_src = r"d:\Tesis\ATLAS\src"
            if atlas_src not in sys.path:
                sys.path.insert(0, atlas_src)
            import importlib
            p01 = importlib.import_module("01_procesamiento_dicom")
            tumor_path = os.path.join(out_dir, "tumor_heur.nii.gz")
            res = p01.generate_tumor_mask(path, brain_path, tumor_path)
            if res is not None and os.path.exists(tumor_path):
                self.mask_path = tumor_path
                self.log(f"Tumor heurístico morfológico: {tumor_path}")
            else:
                self.log("Heurística morfológica no produjo tumor; "
                         "usando segmentación básica...")
                self._basic_segment(path)
            self.progress.set(1.0)
        except Exception as e:
            self.log(f"Error en heurística morfológica: {e}")
            import traceback
            self.log(traceback.format_exc().splitlines()[-1] if traceback else str(e))
            self._basic_segment(path)

    def _basic_segment(self, path):
        import SimpleITK as sitk
        import numpy as np
        try:
            self.log("Usando segmentación heurística de respaldo...")
            img = dm.cargar_volumen(path)
            if img is None:
                self.log("No se pudo cargar el volumen.")
                return
            arr = sitk.GetArrayFromImage(img)
            vals = arr[arr > 0]
            thresh = np.percentile(vals, 98) if len(vals) else 0
            tumor = (arr > thresh * 0.95).astype(np.uint8)
            from scipy import ndimage
            tumor = ndimage.binary_erosion(tumor, iterations=2)
            tumor = ndimage.binary_dilation(tumor, iterations=3)
            out = sitk.GetImageFromArray(tumor.astype(np.uint8))
            out.CopyInformation(img)
            os.makedirs(os.path.join(dm.OUTPUT_DIR, "segmentacion"), exist_ok=True)
            out_path = os.path.join(dm.OUTPUT_DIR, "segmentacion",
                                    "tumor_heur.nii.gz")
            sitk.WriteImage(out, out_path)
            self.mask_path = out_path
            self.log(f"Máscara heurística guardada: {out_path}")
            self.progress.set(1.0)
        except Exception as e:
            self.log(f"Error en segmentación básica: {e}")

    def _detect_aneurysm(self, path):
        self.log("⚠ La detección de aneurismas requiere CTA/MRA con contraste.")
        self.log("Se recomienda segmentar primero los vasos con TotalSegmentator.")
        self.log("Luego analizar dilataciones locales del esqueleto vascular.")
        self.run_segmentation()

    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    def export_unity(self):
        """Exporta mallas 3D y FBX para Unity."""
        self.log("Generando mallas 3D y exportando FBX para Unity...")
        self.log("Estructuras: cerebro, cráneo, tumor, arterias, venas")
        threading.Thread(target=self._run_unity_export, daemon=True).start()

    def _run_unity_export(self):
        try:
            import segmentacion_completa as sc
            mri = os.path.join(dm.DATA_DIR, "nifti", "MRBrainTumor1.nii.gz")
            if not os.path.exists(mri):
                # Buscar cualquier MRI disponible
                files = dm.listar_archivos_nifti()
                mri = files[0]["ruta"] if files else None
            res = sc.exportar_para_unity(mri)
            if res:
                for f in res.get("fbx_individuales", []):
                    self.log(f"FBX listo: {f}")
                self.log("¡Exportación a Unity completada!")
                self.log("Importar FBX en Unity: Assets > Import New Asset")
            else:
                self.log("No se pudieron generar las mallas.")
        except Exception as e:
            self.log(f"Error exportando FBX: {e}")

    def export_neuronav(self):
        """Exporta para neuronavegación."""
        path = self.input_path or self._find_first_nifti()
        if not path:
            self.log("⚠ Seleccione un NIfTI para exportar.")
            self.show_files()
            return

        self._clear_content()
        ctk.CTkLabel(self.content, text="📤 EXPORTAR PARA NEURONAVEGACIÓN",
                     font=(FONT_T, 18, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(self.content,
                     text="Los formatos STL y NIfTI son compatibles con "
                          "Medtronic StealthStation y BrainLab. "
                          "También se puede importar en 3D Slicer.",
                     font=(FONT, 11), text_color=TXT2,
                     wraplength=900, justify="left").pack(
            anchor="w", padx=16, pady=4)

        ctk.CTkLabel(self.content, text=f"Volumen: {path}",
                     font=(FONT, 10), text_color=GREEN).pack(anchor="w", padx=16)

        btns = [
            ("💾 Exportar cerebro completo (STL)",
             lambda: self._do_export(path, None)),
            ("🎯 Exportar tumor segmentado (STL)",
             lambda: self._do_export(path, self.mask_path or "tumor")),
            ("⚙️ Exportar NIfTI original",
             lambda: self._do_export(path, "nifti_only")),
        ]
        for txt, cmd in btns:
            ctk.CTkButton(self.content, text=txt, command=cmd,
                          font=(FONT, 13), fg_color=BG3, hover_color=BG4,
                          corner_radius=8, height=42, text_color=TEXT
                          ).pack(fill="x", padx=32, pady=6)

        ctk.CTkLabel(self.content,
                     text="⚠ Los archivos STL se pueden importar en "
                          "3D Slicer → exportar a formato de neuronavegación "
                          "o directamente en sistemas compatibles con STL.",
                     font=(FONT, 10), text_color=ORANGE,
                     wraplength=800, justify="left").pack(
            anchor="w", padx=32, pady=12)

    def _do_export(self, path, mode):
        def _run():
            self.log("Exportando...")
            try:
                if mode == "nifti_only":
                    import shutil
                    out_dir = os.path.join(dm.OUTPUT_DIR, "neuronavegacion")
                    os.makedirs(out_dir, exist_ok=True)
                    dst = os.path.join(out_dir, Path(path).name)
                    shutil.copy2(path, dst)
                    self.log(f"NIfTI exportado: {dst}")
                elif mode is None:
                    res = dm.exportar_whole_brain_stl(path)
                    if res:
                        self.log(f"STL cerebro: {res['stl']}")
                        self.log(f"Voxels: {res['voxels']}")
                else:
                    # Buscar máscara
                    import glob
                    masks = glob.glob(os.path.join(dm.OUTPUT_DIR,
                                                   "**", "*.nii.gz"),
                                      recursive=True)
                    mask_file = None
                    if self.mask_path and os.path.exists(self.mask_path):
                        mask_file = self.mask_path
                    elif masks:
                        mask_file = masks[0]
                    if mask_file:
                        res = dm.exportar_para_neuronavegacion(path, mask_file)
                        if res and "stl" in res:
                            self.log(f"STL tumor: {res['stl']}")
                            self.log(f"Vol: {res.get('volumen_cm3', 0):.2f} cm³")
                    else:
                        self.log("⚠ No se encontró máscara de tumor. "
                                 "Ejecute la segmentación primero.")
            except Exception as e:
                self.log(f"Error exportando: {e}")
        threading.Thread(target=_run, daemon=True).start()

    # ---------------------------------------------------------------
    def show_help(self):
        """Muestra la ayuda."""
        self._clear_content()
        ctk.CTkLabel(self.content, text="❓ AYUDA DE NEUROHUB",
                     font=(FONT_T, 20, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=16, pady=(16, 8))
        help_text = (
            "🧠 NEUROHUB - Plataforma de Neuroimágenes Multiplataforma\n\n"
            "CONTROLES:\n"
            "• [Archivos]: Explora y carga archivos NIfTI/DICOM\n"
            "• [Visor 3D]: Lanza el visor 3D interactivo con mallas reales\n"
            "  - Arrastrar = rotar, rueda = zoom\n"
            "  - C = cerebro, K = cráneo, T = tumor\n"
            "  - A = arterias, V = venas, N = vasos\n"
            "  - M = MRI slices, 1 = malla, 2 = puntos\n"
            "  - R = reset, 3 = auto-rotar, ESC = salir\n"
            "• [Anatomía]: Panel educativo con turtle\n"
            "  - ← → o A/D para navegar estructuras\n"
            "• [Datasets]: Información de datasets públicos\n"
            "• [Analizar]: Segmenta tumores con BRATS (ATLAS)\n"
            "• [Exportar FBX]: Genera mallas 3D de cerebro, cráneo,\n"
            "  arterias, venas y tumor; exporta FBX para Unity\n"
            "• [Neuronav]: Exporta STL/NIfTI para neuronavegación\n\n"
            "DATASETS COMPATIBLES:\n"
            "• BraTS (tumores MRI, formato NIfTI)\n"
            "• TCIA (DICOM oncológico)\n"
            "• ADAM (aneurismas, NIfTI)\n\n"
            "FORMATOS DE EXPORTACIÓN:\n"
            "• FBX (Unity, con materiales y colores por estructura)\n"
            "• STL (superficies 3D para neuronavegación e impresión 3D)\n"
            "• NIfTI (volúmenes con coordenadas espaciales)\n"
            "• Compatible con Medtronic, BrainLab, Unity y 3D Slicer\n"
        )
        ctk.CTkLabel(self.content, text=help_text, font=(FONT, 11),
                     text_color=TEXT, justify="left", wraplength=950).pack(
            anchor="w", padx=32, pady=8)

    # ---------------------------------------------------------------
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = App()
    app.run()

