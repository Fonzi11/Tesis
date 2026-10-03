"""
NEUROHUB - Procesado completo de un caso desde un NIfTI
======================================================
Ejecuta de principio a fin la reconstruccion 3D de un volumen clinico y genera
los renders PNG, sin depender de la interfaz grafica.

    python NEUROHUB/procesar_caso.py data/nifti/MRBrainTumor1.nii.gz
    python NEUROHUB/procesar_caso.py caso.nii.gz --salida salidas/mi_caso
    python NEUROHUB/procesar_caso.py caso.nii.gz --rapido    # inferencia ~3mm

Etapas
------
 1. Deteccion de modalidad (CT o RM) por el techo de densidad.
 2. Segmentacion con TotalSegmentator: cerebro y craneo. Es la unica etapa que
    da resultado fiable tanto en CT como en RM.
 3. Tumor: metodo segun modalidad. En RM T1ce se usa la version por forma
    (`generate_tumor_mask_t1`), porque la heuristica por intensidad elige el
    seno occipital en vez de la lesion.
 4. Mallas con calidad uniforme (`calidad_mallas.malla_alta_calidad`) y renders.

Notas de modalidad, verificadas sobre MRBrainTumor1.nii.gz (T1ce, 256x256x112):
  - El craneo en RM es un vacio de senal, no un pico de densidad, asi que un
    umbral tipo CT (300 HU) no lo detecta: `generate_skull_mask` lo rechaza
    explicitamente y aqui se usa siempre la mascara de TotalSegmentator.
  - El tumor queda FUERA de la mascara `brain` de TotalSegmentator, porque el
    modelo lo descarta por anomalo. Por eso se busca en la convexidad cerebral.
"""

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
SRC_DIR = os.path.join(BASE_DIR, "src")
for ruta in (SRC_DIR, RAIZ, BASE_DIR):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import importlib  # noqa: E402

import numpy as np  # noqa: E402
import SimpleITK as sitk  # noqa: E402

p01 = importlib.import_module("01_procesamiento_dicom")
from calidad_mallas import (malla_alta_calidad, malla_a_stl,  # noqa: E402
                            rugosidad_alta_frecuencia)


def detectar_modalidad(nifti_path):
    """Distingue CT de RM por el techo de densidad.

    En un TC con hueso el percentil 99.9 supera 1000 HU; en una RM con o sin
    contraste se queda muy por debajo (en MRBrainTumor1 es 397). No clasifica
    contraste ni secuencia: solo decide si el umbral de densidad del craneo
    tiene sentido.
    """
    arr = sitk.GetArrayFromImage(sitk.ReadImage(nifti_path)).astype(np.float32)
    techo = float(np.percentile(arr, 99.9))
    return ("CT" if techo >= 1200 else "RM"), techo


def segmentar(nifti_path, seg_dir, rapido=False):
    """Cerebro y craneo con TotalSegmentator, y tumor segun la modalidad."""
    os.makedirs(seg_dir, exist_ok=True)
    modalidad, techo = detectar_modalidad(nifti_path)
    print(f"\n[1/4] Modalidad detectada: {modalidad} "
          f"(percentil 99.9 = {techo:.0f})")

    print("[2/4] Segmentacion anatomica con TotalSegmentator...")
    p01.run_ai_segmentation(nifti_path, seg_dir, fast_mode=rapido)

    cerebro = os.path.join(seg_dir, "brain.nii.gz")
    craneo = os.path.join(seg_dir, "skull.nii.gz")
    if not os.path.isfile(cerebro):
        print(f"   [X] TotalSegmentator no produjo {cerebro}")
        return None
    if not os.path.isfile(craneo):
        print("   [!] Sin mascara 'skull'; se intenta el umbral de densidad")
        p01.generate_skull_mask(nifti_path, craneo)

    tumor = os.path.join(seg_dir, "tumor.nii.gz")
    print("[3/4] Tumor...")
    if modalidad == "RM":
        # En RM la version por intensidad no discrimina; vease el docstring de
        # generate_tumor_mask_t1 para los tres motivos verificados.
        resultado = p01.generate_tumor_mask_t1(nifti_path, cerebro, tumor)
        if resultado:
            tumor = resultado[0]
    else:
        p01.generate_tumor_mask(nifti_path, cerebro, tumor)

    return {"cerebro": cerebro, "craneo": craneo, "tumor": tumor,
            "modalidad": modalidad}


def construir_mallas(mascaras, mallas_dir):
    """Reconstruye cada estructura con el MISMO perfil de calidad."""
    os.makedirs(mallas_dir, exist_ok=True)
    min_vox = {"cerebro": 500, "craneo": 500, "tumor": 20}
    resumen = {}
    for clave in ("cerebro", "craneo", "tumor"):
        ruta = mascaras.get(clave)
        if not ruta or not os.path.isfile(ruta):
            print(f"   [X] {clave}: sin mascara, se omite")
            continue
        im = sitk.ReadImage(ruta)
        arr = (sitk.GetArrayFromImage(im) > 0).astype(np.uint8)
        if arr.sum() == 0:
            print(f"   [X] {clave}: mascara vacia, se omite")
            continue
        sp = im.GetSpacing()
        vol = arr.sum() * float(np.prod(sp)) / 1000.0
        verts, faces = malla_alta_calidad(arr, sp, estructura=clave,
                                          min_voxels=min_vox[clave])
        if len(faces) == 0:
            print(f"   [X] {clave}: malla vacia")
            continue
        rug = rugosidad_alta_frecuencia(verts, faces)
        destino = os.path.join(mallas_dir, f"{clave}.stl")
        malla_a_stl(verts, faces, destino)
        resumen[clave] = {"caras": int(len(faces)), "volumen_cm3": vol,
                          "rugosidad": rug, "stl": destino}
        print(f"   [OK] {clave:8s} {len(faces):>9,} caras  {vol:7.1f} cm3  "
              f"rugosidad={rug:.3f}")
    return resumen


def main():
    ap = argparse.ArgumentParser(
        description="Procesado completo de un caso NIfTI en NEUROHUB")
    ap.add_argument("nifti", help="ruta del volumen NIfTI de entrada")
    ap.add_argument("--salida", default=None,
                    help="carpeta de trabajo (por defecto, una bajo salidas/)")
    ap.add_argument("--rapido", action="store_true",
                    help="inferencia TotalSegmentator a ~3mm (mas rapido, menos detalle)")
    args = ap.parse_args()

    if not os.path.isfile(args.nifti):
        print(f"[X] No existe el volumen: {args.nifti}")
        return 1

    # .nii.gz son dos extensiones: sin esto la carpeta sale "caso_x.nii".
    nombre = os.path.basename(args.nifti)
    for sufijo in (".nii.gz", ".nii", ".gz"):
        if nombre.lower().endswith(sufijo):
            nombre = nombre[: -len(sufijo)]
            break
    trabajo = args.salida or os.path.join(RAIZ, "salidas", f"caso_{nombre}")
    seg_dir = os.path.join(trabajo, "segmentaciones")
    mallas_dir = os.path.join(trabajo, "mallas")
    renders_dir = os.path.join(trabajo, "renders")

    print("=" * 70)
    print(f"NEUROHUB - Procesado de {nombre}")
    print("=" * 70)
    inicio = time.time()

    mascaras = segmentar(args.nifti, seg_dir, rapido=args.rapido)
    if not mascaras:
        print("[X] La segmentacion no produjo cerebro: se aborta.")
        return 1

    print("[4/4] Reconstruccion de superficies...")
    resumen = construir_mallas(mascaras, mallas_dir)
    if not resumen:
        print("[X] No se genero ninguna malla.")
        return 1

    print("\nGenerando renders...")
    import render_caso
    render_caso.generar(mallas_dir, renders_dir)

    print("\n" + "=" * 70)
    print(f"Completado en {time.time() - inicio:.1f}s")
    print(f"  mascaras : {seg_dir}")
    print(f"  mallas   : {mallas_dir}")
    print(f"  renders  : {renders_dir}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())

