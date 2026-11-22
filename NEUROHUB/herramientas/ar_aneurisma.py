"""Separa el saco aneurismático del árbol arterial de una angio-TC.

    python ar_aneurisma.py --vasos vasos.nii.gz --salida carpeta
           [--radio-mm 2.4] [--semilla-lps x y z]

Método (morfología matemática, reproducible y sin parámetros ocultos):
  1. Se conserva el árbol arterial principal (mayor componente conexa).
  2. Apertura con una esfera de radio mayor que la arteria madre: las
     arterias normales (radio < ``radio_mm``) desaparecen y solo sobreviven
     las dilataciones saculares.
  3. Reconstrucción geodésica limitada a 1 vóxel dentro del árbol para
     recuperar el contorno del saco sin volver a crecer por la arteria.
  4. Si se da ``semilla_lps`` (p. ej. el punto localizado en la DSA) se
     conserva la componente más cercana a ese punto; si no, la mayor.

La localización debe confirmarse con la angiografía/DSA del caso y por un
especialista antes del uso clínico.
"""
import argparse
import json
import os

import numpy as np
import SimpleITK as sitk
from scipy import ndimage


def _bola(radio_mm, sp):
    r = [int(np.ceil(radio_mm / s)) for s in sp]
    z, y, x = np.ogrid[-r[0]:r[0] + 1, -r[1]:r[1] + 1, -r[2]:r[2] + 1]
    return (z * sp[0]) ** 2 + (y * sp[1]) ** 2 + (x * sp[2]) ** 2 <= radio_mm ** 2


def separar(vasos_path, salida, radio_mm=2.4, semilla=None):
    os.makedirs(salida, exist_ok=True)
    img = sitk.ReadImage(vasos_path)
    v = sitk.GetArrayFromImage(img) > 0
    sp = np.array(img.GetSpacing())[::-1]
    vox = float(np.prod(sp))

    lab, n = ndimage.label(v)
    if n > 1:
        v = lab == 1 + int(np.argmax(ndimage.sum(v, lab, range(1, n + 1))))

    nucleo = ndimage.binary_opening(v, structure=_bola(radio_mm, sp))
    lab, n = ndimage.label(nucleo)
    if n == 0:
        raise SystemExit("Ninguna dilatación supera %.1f mm de radio." % radio_mm)
    tam = ndimage.sum(nucleo, lab, range(1, n + 1))
    centros = ndimage.center_of_mass(nucleo, lab, range(1, n + 1))
    candidatos = []
    for i, (t, c) in enumerate(zip(tam, centros)):
        p = img.TransformContinuousIndexToPhysicalPoint(tuple(float(x) for x in c[::-1]))
        candidatos.append({"etiqueta": i + 1, "volumen_mm3": round(t * vox, 1),
                           "centro_lps": [round(x, 1) for x in p]})
    if semilla is not None:
        elegido = min(candidatos, key=lambda c: np.linalg.norm(
            np.array(c["centro_lps"]) - np.array(semilla)))
    else:
        elegido = max(candidatos, key=lambda c: c["volumen_mm3"])
    saco = lab == elegido["etiqueta"]
    # Recupera el contorno del saco (la apertura lo erosiona en las esquinas).
    saco = ndimage.binary_dilation(saco, iterations=1) & v
    arterias = v & ~saco

    dt = ndimage.distance_transform_edt(saco, sampling=sp)
    ext = np.argwhere(saco)
    dims = (ext.max(0) - ext.min(0) + 1) * sp
    info = {"radio_apertura_mm": radio_mm, "candidatos": candidatos,
            "aneurisma": dict(elegido, volumen_mm3=round(saco.sum() * vox, 1),
                              diametro_inscrito_mm=round(2 * dt.max(), 1),
                              extension_zyx_mm=[round(float(d), 1) for d in dims])}
    for nombre, arr in (("aneurisma", saco), ("arterias", arterias)):
        out = sitk.GetImageFromArray(arr.astype(np.uint8))
        out.CopyInformation(img)
        sitk.WriteImage(out, os.path.join(salida, nombre + ".nii.gz"))
    with open(os.path.join(salida, "aneurisma.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return info


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vasos", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument("--radio-mm", type=float, default=2.4)
    p.add_argument("--semilla-lps", type=float, nargs=3)
    a = p.parse_args()
    separar(a.vasos, a.salida, a.radio_mm, a.semilla_lps)
