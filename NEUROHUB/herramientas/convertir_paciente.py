"""
NEUROHUB - DICOM de paciente -> NIfTI, eligiendo la serie correcta
===============================================================
Un estudio de "Imagenes pacientes" no es una sola serie: son varias (cabeza
angulada 0.5 mm, reconstrucciones 5 mm, AiCE, y las localizadores de 2-6
cortes). `dicom_to_nifti` de 01_procesamiento_dicom se queda con la PRIMERA
de la carpeta, que en estos estudios es un localizador de 2 cortes y falla al
leer, o peor, produce un volumen degenerado.

Este modulo elige la serie por criterios explicitos y reproducibles:
  1. mas de 50 cortes (descarta localizadores y escanagramas),
  2. el menor `PixelSpacing` x `SliceThickness` (la reconstruccion fina gana),
  3. desempate por numero de cortes.

Uso
---
    python herramientas/convertir_paciente.py 890923
    python herramientas/convertir_paciente.py --todos
"""

import argparse
import os
import sys

import numpy as np
import SimpleITK as sitk

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "NEUROHUB", "src"))

ORIGEN = os.path.join(BASE_DIR, "data", "dicom", "pacientes")
DESTINO = os.path.join(BASE_DIR, "data", "nifti", "pacientes")
MIN_CORTES = 50


def _serie_info(carpeta, reader, sid):
    import pydicom
    files = reader.GetGDCMSeriesFileNames(carpeta, sid)
    if not files:
        return None
    ds = pydicom.dcmread(files[0], stop_before_pixels=True)
    return {
        "sid": sid,
        "files": files,
        "descripcion": str(getattr(ds, "SeriesDescription", "?")),
        "n_cortes": len(files),
        "pixel_spacing": [float(v) for v in getattr(ds, "PixelSpacing", [1, 1])],
        "grosor": float(getattr(ds, "SliceThickness", 1.0)),
    }


def elegir_serie(carpeta):
    """Devuelve la serie con mas detalle anatómico de la carpeta."""
    reader = sitk.ImageSeriesReader()
    sids = reader.GetGDCMSeriesIDs(carpeta)
    candidatas = []
    for sid in sids or []:
        info = _serie_info(carpeta, reader, sid)
        if info and info["n_cortes"] >= MIN_CORTES:
            info["resolucion"] = (info["pixel_spacing"][0]
                                 * info["grosor"])
            candidatas.append(info)
    if not candidatas:
        raise RuntimeError(f"{carpeta}: ninguna serie tiene >= {MIN_CORTES} cortes")
    candidatas.sort(key=lambda i: (i["resolucion"], -i["n_cortes"]))
    return candidatas[0], candidatas


def convertir(caso, forzar=False):
    carpeta = os.path.join(ORIGEN, caso)
    salida = os.path.join(DESTINO, f"{caso}.nii.gz")
    if os.path.isfile(salida) and not forzar:
        print(f"  [OK] {caso}: ya existe {os.path.basename(salida)}")
        return salida

    elegida, candidatas = elegir_serie(carpeta)
    print(f"\n{caso}: {len(candidatas)} series con >= {MIN_CORTES} cortes")
    for i in candidatas:
        marca = " <== elegida" if i is elegida else ""
        print(f"     {i['n_cortes']:>5} cortes  "
              f"{i['pixel_spacing'][0]:.2f}x{i['pixel_spacing'][1]:.2f} "
              f"x{i['grosor']:.1f} mm  {i['descripcion'][:34]:34s}{marca}")

    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(elegida["files"])
    # Algunas series de estos estudios cruzan Rows/Columns (552x474) entre
    # cortes, y SimpleITK falla con "ImageIO returns IO region that does not
    # fully contain". Leer sin pedir un tipo concreto deja que GDCM lo resuelva.
    reader.MetaDataDictionaryArrayUpdateOn()
    reader.SetOutputPixelType(sitk.sitkFloat32)
    imagen = reader.Execute()

    os.makedirs(DESTINO, exist_ok=True)
    # SimpleITK entrega LPS; NIfTI espera RAS. Sin la conversion el volumen sale
    # espejado y el cerebro se situa del reves en los renders.
    imagen.SetDirection((1, 0, 0, 0, -1, 0, 0, 0, 1))
    sitk.WriteImage(imagen, salida, True)

    arr = sitk.GetArrayFromImage(imagen).astype(np.float32)
    print(f"  [OK] {os.path.basename(salida)}  size={imagen.GetSize()}  "
          f"spacing={tuple(round(s, 3) for s in imagen.GetSpacing())}  "
          f"p99.9={np.percentile(arr, 99.9):.0f}")
    return salida


def main():
    ap = argparse.ArgumentParser(description="Convierte casos DICOM a NIfTI")
    ap.add_argument("caso", nargs="?", help="nombre de la carpeta del caso")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    args = ap.parse_args()

    if args.todos:
        casos = sorted(c for c in os.listdir(ORIGEN)
                       if os.path.isdir(os.path.join(ORIGEN, c)))
    elif args.caso:
        casos = [args.caso]
    else:
        ap.error("indica un caso o --todos")

    fallos = 0
    for caso in casos:
        try:
            convertir(caso, forzar=args.forzar)
        except Exception as error:
            print(f"  [X] {caso}: {error}")
            fallos += 1
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())