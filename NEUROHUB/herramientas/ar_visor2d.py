"""
Prepara los volúmenes 2D de cada caso ATLAS en UNA sola rejilla.

El visor 2D de ATLAS necesita, por caso, tres NIfTI alineados vóxel a vóxel:

    visor2d/imagen.nii.gz     imagen de lectura (T1-Gd, angio-TC...)
    visor2d/anatomia.nii.gz   etiquetas de FreeSurfer SynthSeg (contornos)
    visor2d/lesion.nii.gz     lesión editable (tumor o aneurisma)
    visor2d/info.json         modalidad y descripción de cada capa

Las fuentes originales viven en rejillas distintas (la RM del paciente a
0,45 mm en orientación sagital, SynthSeg a 1 mm, la angio-TC a 0,38 mm), y
superponer etiquetas de otra rejilla desplaza los contornos. Aquí todo se
remuestrea en espacio físico (SimpleITK) sobre una rejilla de referencia:
lineal para la imagen y vecino más cercano para las etiquetas.

    python NEUROHUB/herramientas/ar_visor2d.py            # los cinco casos
    python NEUROHUB/herramientas/ar_visor2d.py tumor_02   # uno
"""

import json
import os
import sys

import numpy as np
import SimpleITK as sitk

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AR = os.path.join(RAIZ, "salidas", "modelos_ar_freesurfer")
ENT = os.path.join(AR, "_entrada")
SYN = os.path.join(AR, "_synthseg")
BRATS = os.path.join(RAIZ, "data", "nifti", "braTS_sample")

# Etiqueta reservada (fuera del rango de SynthSeg) para las arterias de la
# angio-TC: el visor la dibuja como contorno rojo junto a la anatomía.
ETIQUETA_ARTERIAS = 900


def _brats(caso_id):
    n = caso_id.split("_")[1]
    d = os.path.join(BRATS, f"BraTS2021_{n}")
    return {
        "imagen": os.path.join(d, f"BraTS2021_{n}_t1ce.nii.gz"),
        "imagen_desc": "RM T1 con gadolinio (BraTS 2021)",
        "modalidad": "MRI",
        "referencia": "imagen",
        "anatomia": os.path.join(SYN, f"{caso_id}_synthseg.nii.gz"),
        "lesion": os.path.join(d, f"BraTS2021_{n}_seg.nii.gz"),
        "lesion_desc": "Tumor: segmentación de expertos BraTS (necrosis, edema, realce)",
    }


CASOS = {
    "tumor_02": {
        "imagen": os.path.join(ENT, "tumor_02", "tumor_02_t1ce.nii.gz"),
        "imagen_desc": "RM T1 con gadolinio del paciente (HUSI)",
        "modalidad": "MRI",
        # Rejilla 1 mm de SynthSeg: la RM original (0,45 mm, 111 M vóxeles)
        # no cabe con holgura en memoria del visor.
        "referencia": os.path.join(ENT, "synthseg_in", "tumor_02.nii.gz"),
        "anatomia": os.path.join(SYN, "tumor_02_synthseg.nii.gz"),
        "lesion": os.path.join(ENT, "tumor_02", "tumor_02_tumor_brats.nii.gz"),
        "lesion_desc": "Tumor: SegResNet BraTS sobre la RM del paciente (revisión pendiente)",
    },
    "aneurisma_05": {
        "imagen": os.path.join(ENT, "aneurisma_05", "aneurisma_05_cta12.nii.gz"),
        "imagen_desc": "Angio-TC del paciente (HUSI)",
        "modalidad": "CTA",
        # 0,6 mm isotrópico sobre el recuadro intracraneal: conserva el saco
        # (~7 mm) y reduce la angio-TC de 150 M a ~25 M vóxeles.
        "referencia": ("recorte", os.path.join(ENT, "aneurisma_05", "sustraccion",
                                               "intracraneal.nii.gz"), 0.6),
        "anatomia": os.path.join(SYN, "aneurisma_05_synthseg.nii.gz"),
        "arterias": os.path.join(ENT, "aneurisma_05", "aneurisma", "arterias.nii.gz"),
        "lesion": os.path.join(ENT, "aneurisma_05", "aneurisma", "aneurisma.nii.gz"),
        "lesion_desc": "Aneurisma sacular del sifón carotídeo derecho",
    },
    "brats_00000": _brats("brats_00000"),
    "brats_00003": _brats("brats_00003"),
    "brats_00006": _brats("brats_00006"),
}


def _rejilla_recorte(mascara_path, espaciado, margen_mm=12.0):
    """Rejilla isotrópica que cubre el recuadro de `mascara` con un margen."""
    m = sitk.ReadImage(mascara_path)
    a = sitk.GetArrayViewFromImage(m) > 0
    zz, yy, xx = np.nonzero(a)
    esquinas = []
    for z in (zz.min(), zz.max()):
        for y in (yy.min(), yy.max()):
            for x in (xx.min(), xx.max()):
                esquinas.append(m.TransformIndexToPhysicalPoint((int(x), int(y), int(z))))
    esquinas = np.array(esquinas)
    lo = esquinas.min(0) - margen_mm
    hi = esquinas.max(0) + margen_mm
    tam = np.ceil((hi - lo) / espaciado).astype(int) + 1
    ref = sitk.Image([int(t) for t in tam], sitk.sitkUInt8)
    ref.SetSpacing([espaciado] * 3)
    ref.SetOrigin([float(v) for v in lo])
    ref.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, 1))
    return ref


def _remuestrear(img, ref, etiquetas, defecto=0):
    interp = sitk.sitkNearestNeighbor if etiquetas else sitk.sitkLinear
    return sitk.Resample(img, ref, sitk.Transform(), interp, defecto, img.GetPixelID())


def preparar(caso_id):
    cfg = CASOS[caso_id]
    salida = os.path.join(AR, caso_id, "visor2d")
    os.makedirs(salida, exist_ok=True)

    imagen = sitk.ReadImage(cfg["imagen"])
    ref_cfg = cfg["referencia"]
    if ref_cfg == "imagen":
        ref = imagen
    elif isinstance(ref_cfg, tuple):
        ref = _rejilla_recorte(ref_cfg[1], ref_cfg[2])
    else:
        ref = sitk.ReadImage(ref_cfg)

    aire = -1024 if cfg["modalidad"] in ("CT", "CTA") else 0
    img_r = _remuestrear(sitk.Cast(imagen, sitk.sitkFloat32), ref, False, aire)
    if cfg["modalidad"] in ("CT", "CTA"):
        img_r = sitk.Clamp(img_r, sitk.sitkFloat32, -1024.0, 3071.0)
    sitk.WriteImage(sitk.Cast(img_r, sitk.sitkInt16 if aire else sitk.sitkFloat32),
                    os.path.join(salida, "imagen.nii.gz"))

    anat = _remuestrear(sitk.Cast(sitk.ReadImage(cfg["anatomia"]), sitk.sitkUInt16), ref, True)
    if cfg.get("arterias"):
        art = _remuestrear(sitk.Cast(sitk.ReadImage(cfg["arterias"]), sitk.sitkUInt16), ref, True)
        a = sitk.GetArrayFromImage(anat)
        a[sitk.GetArrayViewFromImage(art) > 0] = ETIQUETA_ARTERIAS
        nueva = sitk.GetImageFromArray(a)
        nueva.CopyInformation(anat)
        anat = nueva
    sitk.WriteImage(anat, os.path.join(salida, "anatomia.nii.gz"))

    les = _remuestrear(sitk.Cast(sitk.ReadImage(cfg["lesion"]), sitk.sitkUInt8), ref, True)
    sitk.WriteImage(les, os.path.join(salida, "lesion.nii.gz"))

    n_les = int((sitk.GetArrayViewFromImage(les) > 0).sum())
    vox_mm3 = float(np.prod(ref.GetSpacing()))
    info = {
        "caso": caso_id,
        "modalidad": cfg["modalidad"],
        "imagen": cfg["imagen_desc"],
        "lesion": cfg["lesion_desc"],
        "anatomia": "FreeSurfer 7.4.1 mri_synthseg --robust --parc",
        "etiqueta_arterias": ETIQUETA_ARTERIAS if cfg.get("arterias") else None,
        "tamano": list(ref.GetSize()),
        "espaciado_mm": [round(v, 3) for v in ref.GetSpacing()],
        "lesion_cm3": round(n_les * vox_mm3 / 1000.0, 2),
    }
    with open(os.path.join(salida, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"{caso_id}: {info['tamano']} @ {info['espaciado_mm']} mm, "
          f"lesión {info['lesion_cm3']} cm³ -> {salida}")
    return salida


if __name__ == "__main__":
    for caso in (sys.argv[1:] or list(CASOS)):
        preparar(caso)
