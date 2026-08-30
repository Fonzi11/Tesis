"""Small Windows-friendly GUI for exporting an STL into FBX files by layers."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


ROOT = Path(__file__).resolve().parent
BLENDER_SCRIPT = ROOT / "convert_stl_to_fbx_layers.py"


def find_blender() -> str | None:
    found = shutil.which("blender") or shutil.which("blender.exe")
    if found:
        return found
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Blender Foundation",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation",
    ]
    for folder in candidates:
        if folder.exists():
            matches = sorted(folder.glob("Blender */blender.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STL a FBX por capas")
        self.geometry("650x350")
        self.minsize(580, 320)
        self.stl_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.layer_height = tk.StringVar(value="1.0")
        self.status = tk.StringVar(value="Selecciona un STL para comenzar.")
        self.progress = tk.DoubleVar(value=0)
        self._build()

    def _build(self):
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="STL a FBX por capas", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Cada capa se exporta como un FBX independiente para Unity.").pack(anchor="w", pady=(4, 22))
        self._path_row(frame, "Archivo STL", self.stl_path, self.choose_stl)
        self._path_row(frame, "Carpeta de salida", self.output_dir, self.choose_output)
        options = ttk.Frame(frame)
        options.pack(fill="x", pady=(14, 18))
        ttk.Label(options, text="Altura de capa (unidades del STL):").pack(side="left")
        ttk.Entry(options, textvariable=self.layer_height, width=10).pack(side="left", padx=10)
        self.convert_button = ttk.Button(frame, text="Convertir a FBX", command=self.start_conversion)
        self.convert_button.pack(anchor="w")
        ttk.Progressbar(frame, variable=self.progress, maximum=100).pack(fill="x", pady=(22, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=590).pack(anchor="w")

    def _path_row(self, parent, label, variable, command):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=label, width=20).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Examinar...", command=command).pack(side="left", padx=(8, 0))

    def choose_stl(self):
        path = filedialog.askopenfilename(filetypes=[("Archivos STL", "*.stl"), ("Todos", "*.*")])
        if path:
            self.stl_path.set(path)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(path).parent / "fbx_capas"))

    def choose_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir.set(path)

    def start_conversion(self):
        blender = find_blender()
        if not blender:
            messagebox.showerror("Blender no encontrado", "Instala Blender y añádelo al PATH. Luego vuelve a abrir esta aplicación.")
            return
        if not self.stl_path.get() or not Path(self.stl_path.get()).is_file():
            messagebox.showwarning("Falta el STL", "Selecciona un archivo STL válido.")
            return
        try:
            height = float(self.layer_height.get().replace(",", "."))
            if height <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Altura inválida", "La altura de capa debe ser un número mayor que cero.")
            return
        output = self.output_dir.get() or str(Path(self.stl_path.get()).parent / "fbx_capas")
        self.output_dir.set(output)
        self.convert_button.configure(state="disabled")
        self.progress.set(0)
        self.status.set("Convirtiendo... Blender está procesando el modelo.")
        threading.Thread(target=self._run, args=(blender, height, output), daemon=True).start()

    def _run(self, blender, height, output):
        command = [blender, "--background", "--python", str(BLENDER_SCRIPT), "--", self.stl_path.get(), output, "--layer-height", str(height)]
        process = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT))
        exported = [line for line in process.stdout.splitlines() if line.startswith("EXPORTED ")]
        if process.returncode == 0 and exported:
            count = exported[-1].split()[-1]
            self.after(0, lambda: self._done(f"Listo: {count} FBX creados en {output}."))
        else:
            details = (process.stderr or process.stdout).strip().splitlines()
            error = details[-1] if details else "Blender terminó con un error desconocido."
            self.after(0, lambda: self._done(f"Error: {error}"))

    def _done(self, message):
        self.convert_button.configure(state="normal")
        self.progress.set(100 if message.startswith("Listo") else 0)
        self.status.set(message)
        if message.startswith("Listo"):
            messagebox.showinfo("Conversión terminada", message)
        else:
            messagebox.showerror("Conversión fallida", message)


if __name__ == "__main__":
    App().mainloop()