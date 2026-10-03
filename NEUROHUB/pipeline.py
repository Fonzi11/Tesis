"""
NEUROHUB - Pipeline completo en Python
=====================================
Ejecuta de principio a fin la reconstrucción 3D del caso clínico:

  1. Carga las máscaras segmentadas desde NIfTI.
  2. Reconstruye cada estructura con calidad uniforme (calidad_mallas.py).
  3. Exporta STL y un diccionario listo para el visor.
  4. Abre el visor 3D en viewer3d.py y/o genera una captura.

Es el sustituto del flujo basado en 3D Slicer: todo el pipeline corre en Python
puro, sin depender de que Slicer esté instalado.

Uso:
    python NEUROHUB/pipeline.py                 # mallas + visor
    python NEUROHUB/pipeline.py --sin-visor     # solo genera las mallas
    python NEUROHUB/pipeline.py --captura      # mallas + captura PNG headless
"""

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
SRC_DIR = os.path.join(BASE_DIR, "src")
HERRAMIENTAS_DIR = os.path.join(RAIZ, "herramientas")
for ruta in (SRC_DIR, HERRAMIENTAS_DIR, RAIZ):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import numpy as np
import SimpleITK as sitk

from calidad_mallas import (malla_alta_calidad, malla_a_stl, malla_a_dict,
                            rugosidad_alta_frecuencia)

SEG_AI_DIR = os.path.join(RAIZ, "salidas", "segmentaciones_ai")
MALLAS_DIR = os.path.join(RAIZ, "salidas", "mallas")


# Estructuras del pipeline: SOLO cerebro, cráneo y tumor.
# La vasculatura (vasos, arterias, venas, aneurisma) se eliminó del producto:
# una MRI anatómica no permite separar arterias de venas con fiabilidad, y en MR
# las venas no se distinguishen del resto del árbol vascular, así que esa capa
# no aportaba información verificable.
ESTRUCTURAS = [
    {"clave": "cerebro",  "mascaras": ["brain.nii.gz"],              "min_voxels": 500},
    {"clave": "craneo",   "mascaras": ["skull.nii.gz"],              "min_voxels": 500},
    {"clave": "tumor",    "mascaras": ["tumor_brats.nii.gz",
                                        "tumor_heuristica.nii.gz",
                                        "tumor.nii.gz"],               "min_voxels": 20},
]

COLORES = {
    "cerebro":   (0.83, 0.67, 0.62),
    "craneo":    (0.91, 0.88, 0.83),
    "tumor":     (0.75, 0.15, 0.43),
}


def _cargar_mascara(nombres, verbose=True):
    """Carga la primera máscara disponible de una lista de candidatas.

    Devuelve (array, spacing_simpleitk, ruta) o (None, None, None).
    """
    for nombre in nombres:
        ruta = os.path.join(SEG_AI_DIR, nombre)
        if not os.path.isfile(ruta):
            continue
        try:
            img = sitk.ReadImage(ruta)
            arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
            if arr.sum() == 0:
                if verbose:
                    print(f"[PIPE] [i] {nombre}: vacía, se prueba la siguiente")
                continue
            if verbose:
                print(f"[PIPE] [OK] Máscara cargada: {nombre} "
                      f"({arr.sum():,} vóxeles, spacing {tuple(round(s, 3) for s in img.GetSpacing())})")
            return arr, img.GetSpacing(), ruta
        except Exception as error:
            if verbose:
                print(f"[PIPE] [!] No se pudo leer {nombre}: {error}")
    return None, None, None


def reconstruir_todas(estructuras=None, salida_dir=None, verbose=True):
    """Reconstruye todas las estructuras y exporta las mallas STL.

    Returns:
        dict con los mismos campos que usa el visor 3D, indexado por estructura.
    """
    estructuras = estructuras or ESTRUCTURAS
    salida_dir = salida_dir or MALLAS_DIR
    os.makedirs(salida_dir, exist_ok=True)

    mallas = {}
    for cfg in estructuras:
        clave = cfg["clave"]
        arr, spacing, ruta = _cargar_mascara(cfg["mascaras"], verbose)
        if arr is None:
            if verbose:
                print(f"[PIPE] [!] {clave}: sin máscara disponible, se omite")
            continue

        t0 = time.time()
        verts, faces = malla_alta_calidad(
            arr, spacing, estructura=clave,
            min_voxels=cfg.get("min_voxels", 0), verbose=verbose)
        if len(verts) == 0:
            if verbose:
                print(f"[PIPE] [!] {clave}: malla vacía, se omite")
            continue

        stl = os.path.join(salida_dir, f"{clave}.stl")
        if not malla_a_stl(verts, faces, stl):
            stl = None

        rugosidad = rugosidad_alta_frecuencia(verts, faces)

        mallas[clave] = malla_a_dict(verts, faces)
        mallas[clave].update({
            "stl": stl,
            "origen": os.path.basename(ruta),
            "color": COLORES.get(clave, (0.75, 0.75, 0.75)),
            "voxels": int(arr.sum()),
            "volumen_cm3": float(arr.sum()) * float(np.prod(spacing[:3])) / 1000.0,
            "rugosidad": rugosidad,
            "segundos": time.time() - t0,
        })
        if verbose:
            kb = os.path.getsize(stl) / 1024 if stl and os.path.isfile(stl) else 0
            print(f"[PIPE] [OK] {clave:10s} {len(faces):>9,} caras  "
                  f"{kb:>8.1f} KB  rugosidad={rugosidad:.3f}  "
                  f"{time.time() - t0:5.1f}s")

    if verbose:
        print(f"\n[PIPE] [DONE] {len(mallas)} estructuras en {salida_dir}")
    return mallas


# Umbral de rugosidad admitido. Las tres estructuras comparten umbral porque
# comparten método: cerebro, cráneo y tumor son masas reconstruidas con la
# misma rejilla y el mismo suavizado, así que su acabado debe ser comparable.
UMBRAL_RUGOSIDAD = {
    "cerebro": 0.24,
    "craneo": 0.24,
    "tumor": 0.24,
}
UMBRAL_POR_DEFECTO = 0.30


def informe_calidad(mallas):
    """Comprueba que ninguna estructura supere su umbral de rugosidad.

    El objetivo es que el cerebro y el cráneo se vean tan lisos como el tumor,
    y como las tres se reconstruyen igual, el criterio es directo: el valor debe
    quedar por debajo del umbral para todas.

    Devuelve True si todas las estructuras pasan el control.
    """
    if not mallas:
        return False

    print("\n" + "=" * 68)
    print("CALIDAD DE SUPERFICIE POR ESTRUCTURA")
    print("=" * 68)
    print(f"{'estructura':12s} {'caras':>10s} {'vol (cm3)':>10s} "
          f"{'rugosidad':>11s} {'umbral':>8s}  estado")

    cumple = True
    for clave, datos in mallas.items():
        rug = datos.get("rugosidad")
        if rug is None:
            continue
        umbral = UMBRAL_RUGOSIDAD.get(clave, UMBRAL_POR_DEFECTO)
        estado = "OK" if rug <= umbral else "GRANULADA"
        if rug > umbral:
            cumple = False
        print(f"{clave:12s} {len(datos['faces']):>10,} "
              f"{datos.get('volumen_cm3', 0.0):>10.1f} {rug:>11.3f} "
              f"{umbral:>8.2f}  {estado}")

    tumor = mallas.get("tumor", {}).get("rugosidad")
    cerebro = mallas.get("cerebro", {}).get("rugosidad")
    craneo = mallas.get("craneo", {}).get("rugosidad")
    if None not in (tumor, cerebro, craneo):
        print(f"\n  Comparación con el tumor (referencia de nitidez):")
        print(f"    cerebro {cerebro:.3f} | cráneo {craneo:.3f} | tumor {tumor:.3f}")
        if cerebro <= tumor and craneo <= tumor:
            print("    [OK] cerebro y cráneo son tan lisos o más que el tumor")
        else:
            print("    [X] alguna masa sigue más rugosa que el tumor")

    print(f"\n  {'[OK] Todas las superficies superan el control' if cumple else '[X] Hay superficies por debajo de su umbral'}")
    return cumple


def abrir_visor(mallas=None):
    """Abre el visor 3D (viewer3d.py) con las mallas generadas."""
    from viewer3d import launch_gpu_viewer
    return launch_gpu_viewer()


def generar_preview(mallas=None, salida=None):
    """Genera la captura PNG de la escena con las mallas ya construidas."""
    from generar_preview import main as preview_main
    salida = salida or os.path.join(RAIZ, "salidas", "preview_3d.png")
    sys.argv = ["generar_preview.py", "--out", salida]
    return preview_main()


def main():
    ap = argparse.ArgumentParser(description="Pipeline 3D completo de NEUROHUB")
    ap.add_argument("--sin-visor", action="store_true",
                    help="genera las mallas y no abre el visor")
    ap.add_argument("--captura", action="store_true",
                    help="genera además una captura PNG headless")
    args = ap.parse_args()

    print("=" * 66)
    print("NEUROHUB - Pipeline de reconstrucción 3D (Python puro)")
    print("=" * 66)
    inicio = time.time()
    mallas = reconstruir_todas()
    if mallas:
        informe_calidad(mallas)
    if not mallas:
        print("[PIPE] [X] No se generó ninguna malla. Revisa salidas/segmentaciones_ai/")
        return 1

    if args.captura:
        print("\n[PIPE] Generando captura PNG...")
        try:
            generar_preview()
        except Exception as error:
            print(f"[PIPE] [!] No se pudo generar la captura: {error}")

    if not args.sin_visor:
        print("\n[PIPE] Abriendo el visor 3D...")
        try:
            abrir_visor()
        except Exception as error:
            print(f"[PIPE] [!] No se pudo abrir el visor: {error}")

    print(f"\n[PIPE] Tiempo total: {time.time() - inicio:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
