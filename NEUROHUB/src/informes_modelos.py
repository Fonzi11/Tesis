"""Informes reproducibles de segmentación y mallas 3D."""

import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import SimpleITK as sitk
import trimesh


def _dice(a, b):
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    inter = int(np.logical_and(a, b).sum())
    total = int(a.sum() + b.sum())
    return (2.0 * inter / total) if total else None


def generar_informes(mallas_dir, informes_dir, mascaras=None, volumen=None,
                     operaciones=None, tiempo_renderizado_s=None,
                     notas=None):
    """Escribe un informe JSON y Markdown por cada modelo, sin sobrescribir."""
    os.makedirs(informes_dir, exist_ok=True)
    mascaras = mascaras or {}
    operaciones = operaciones or []
    notas = notas or []
    inicio = time.perf_counter()
    referencia = sitk.ReadImage(volumen) if volumen and os.path.isfile(volumen) else None
    indice = []

    for nombre in sorted(os.listdir(mallas_dir)):
        if not nombre.lower().endswith(".stl"):
            continue
        ruta = os.path.join(mallas_dir, nombre)
        clave = os.path.splitext(nombre)[0]
        datos = {
            "modelo": clave,
            "archivo_malla": os.path.abspath(ruta),
            "tamano_bytes": os.path.getsize(ruta),
            "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "operaciones": list(operaciones),
            "tiempo_renderizado_s": tiempo_renderizado_s,
            "dice": None,
            "dice_estado": "N/A: no se proporcionó una referencia independiente",
        }
        try:
            mesh = trimesh.load(ruta, force="mesh")
            datos["vertices"] = int(len(mesh.vertices))
            datos["caras"] = int(len(mesh.faces))
            datos["volumen_malla_cm3"] = float(
                abs(mesh.volume) / 1000.0) if mesh.is_volume else None
        except Exception as error:
            datos["vertices"] = None
            datos["caras"] = None
            datos["volumen_malla_cm3"] = None
            datos["malla_error"] = str(error)
        mascara = mascaras.get(clave)
        if mascara and os.path.isfile(mascara):
            imagen = sitk.ReadImage(mascara)
            arr = sitk.GetArrayFromImage(imagen) > 0
            datos["resolucion_voxel_mm"] = list(imagen.GetSpacing())
            datos["dimensiones_voxel"] = list(imagen.GetSize())
            datos["voxeles_segmentados"] = int(arr.sum())
            datos["volumen_segmentado_cm3"] = float(
                arr.sum() * np.prod(imagen.GetSpacing()) / 1000.0)
            referencia_path = mascaras.get(f"{clave}__referencia")
            if referencia_path and os.path.isfile(referencia_path):
                ref = sitk.ReadImage(referencia_path)
                if ref.GetSize() == imagen.GetSize() and \
                        ref.GetSpacing() == imagen.GetSpacing():
                    score = _dice(arr, sitk.GetArrayFromImage(ref) > 0)
                    datos["dice"] = score
                    datos["dice_estado"] = "calculado contra referencia independiente"
        else:
            datos["resolucion_voxel_mm"] = (
                list(referencia.GetSpacing()) if referencia is not None else None)
            datos["dimensiones_voxel"] = (
                list(referencia.GetSize()) if referencia is not None else None)
            datos["voxeles_segmentados"] = None
            datos["volumen_segmentado_cm3"] = None
        if referencia is not None:
            datos["volumen_referencia"] = {
                "dimensiones_voxel": list(referencia.GetSize()),
                "resolucion_voxel_mm": list(referencia.GetSpacing()),
            }
        base = os.path.join(informes_dir, clave)
        json_path = base + ".json"
        md_path = base + ".md"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=2, ensure_ascii=False)
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(f"# Informe de modelo: {clave}\n\n")
            fh.write(f"- Archivo: `{datos['archivo_malla']}`\n")
            fh.write(f"- Tamaño: {datos['tamano_bytes']:,} bytes\n")
            fh.write(f"- Vértices: {datos['vertices'] or 'N/A'}\n")
            fh.write(f"- Caras: {datos['caras'] or 'N/A'}\n")
            fh.write(f"- Volumen de malla: {datos['volumen_malla_cm3'] or 'N/A'} cm³\n")
            fh.write(f"- Resolución: {datos['resolucion_voxel_mm'] or 'N/A'} mm\n")
            fh.write(f"- Dimensiones: {datos['dimensiones_voxel'] or 'N/A'} voxeles\n")
            fh.write(f"- Voxeles segmentados: {datos['voxeles_segmentados'] or 'N/A'}\n")
            fh.write(f"- Volumen: {datos['volumen_segmentado_cm3'] or 'N/A'} cm³\n")
            fh.write(f"- Dice: {datos['dice'] if datos['dice'] is not None else 'N/A'}\n")
            fh.write(f"- Estado Dice: {datos['dice_estado']}\n")
            fh.write(f"- Tiempo de renderizado: {tiempo_renderizado_s or 'N/A'} s\n\n")
            fh.write("## Operaciones realizadas\n\n")
            for operacion in operaciones:
                fh.write(f"- {operacion}\n")
        indice.append(datos)
    resumen = {
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "tiempo_informes_s": time.perf_counter() - inicio,
        "mallas_dir": os.path.abspath(mallas_dir),
        "modelos": indice,
        "notas": notas,
    }
    with open(os.path.join(informes_dir, "indice.json"), "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, indent=2, ensure_ascii=False)
    return resumen
