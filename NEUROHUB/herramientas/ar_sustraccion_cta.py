"""Angio-TC por sustracción ósea (TC simple registrada y restada a la CTA).

    python ar_sustraccion_cta.py --cta cta.nii.gz --ct ct.nii.gz --salida carpeta

Salidas en ``carpeta``:
  * ct_en_cta.nii.gz      TC simple remuestreada en la rejilla de la CTA,
  * sustraccion.nii.gz    CTA - TC (HU de contraste, hueso eliminado),
  * vasos.nii.gz          máscara arterial intracraneal,
  * craneo.nii.gz         máscara ósea (TC simple > 300 HU).
"""
import argparse
import os

import numpy as np
import SimpleITK as sitk
from scipy import ndimage


def registrar(fija, movil):
    f = sitk.Cast(fija, sitk.sitkFloat32)
    m = sitk.Cast(movil, sitk.sitkFloat32)
    # Se registra con la ventana ósea: el cráneo es idéntico en ambas
    # adquisiciones y no cambia con el contraste.
    f_b = sitk.Clamp(f, sitk.sitkFloat32, 0, 1500)
    m_b = sitk.Clamp(m, sitk.sitkFloat32, 0, 1500)
    ini = sitk.CenteredTransformInitializer(
        f_b, m_b, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY)
    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMeanSquares()
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.02, seed=3)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(1.0, 1e-4, 300, 0.6)
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetShrinkFactorsPerLevel([4, 2, 1])
    reg.SetSmoothingSigmasPerLevel([2, 1, 0.5])
    reg.SetInitialTransform(ini, inPlace=False)
    tx = reg.Execute(f_b, m_b)
    print("registro TC->CTA: MSE %.1f (%s)" % (
        reg.GetMetricValue(), reg.GetOptimizerStopConditionDescription()[:50]))
    return tx


def procesar(cta_path, ct_path, salida):
    os.makedirs(salida, exist_ok=True)
    cta = sitk.ReadImage(cta_path, sitk.sitkFloat32)
    ct = sitk.ReadImage(ct_path, sitk.sitkFloat32)
    tx = registrar(cta, ct)
    ct_r = sitk.Resample(ct, cta, tx, sitk.sitkLinear, -1024.0)
    sitk.WriteImage(sitk.Cast(ct_r, sitk.sitkInt16), os.path.join(salida, "ct_en_cta.nii.gz"))

    # Vóxeles de la CTA que la TC simple no cubre: sin TC no hay sustracción.
    unos = sitk.Image(ct.GetSize(), sitk.sitkUInt8) + 1
    unos.CopyInformation(ct)
    cubierto = sitk.Resample(unos, cta, tx, sitk.sitkNearestNeighbor, 0)
    a_cub = ndimage.binary_erosion(sitk.GetArrayFromImage(cubierto) > 0, iterations=3)
    a_cta = np.clip(sitk.GetArrayFromImage(cta), -1024, 3071)
    a_ct = np.clip(sitk.GetArrayFromImage(ct_r), -1024, 3071)
    sp = np.array(cta.GetSpacing())[::-1]  # (z, y, x)

    hueso = a_ct > 300
    # Cavidad intracraneal: el interior cerrado de la calota, por cortes axiales
    # (la base del cráneo deja agujeros que impiden un relleno 3D directo).
    cerrado = ndimage.binary_closing(hueso, structure=np.ones((3, 5, 5)), iterations=2)
    intracraneal = np.zeros_like(hueso)
    for k in range(hueso.shape[0]):
        intracraneal[k] = ndimage.binary_fill_holes(cerrado[k]) & ~cerrado[k]
    intracraneal = ndimage.binary_opening(intracraneal, iterations=2)
    etiq, n = ndimage.label(intracraneal)
    if n:
        tam = ndimage.sum(intracraneal, etiq, range(1, n + 1))
        intracraneal = etiq == (1 + int(np.argmax(tam)))
    # Se incluye la base (sifón carotídeo dentro del seno cavernoso): dilatación
    # de 6 mm del espacio intracraneal sin invadir el hueso.
    radio = max(1, int(round(6.0 / sp[1])))
    zona = ndimage.binary_dilation(intracraneal, iterations=radio)

    sus = np.where(a_cub, a_cta - a_ct, 0.0)
    # Borde óseo: la sustracción deja un halo por el desajuste sub-vóxel.
    borde = ndimage.binary_dilation(hueso, iterations=2) & ~ndimage.binary_erosion(hueso, iterations=1)
    sus[borde] = np.minimum(sus[borde], 0)
    sus_img = sitk.GetImageFromArray(sus.astype(np.float32))
    sus_img.CopyInformation(cta)
    sitk.WriteImage(sitk.Cast(sus_img, sitk.sitkInt16), os.path.join(salida, "sustraccion.nii.gz"))

    # Máscara combinada en lugar de umbral sobre la resta: un desajuste
    # sub-milimétrico del hueso produce restas de >2000 HU en el borde óseo.
    # Vaso = realza en la CTA, realza respecto a la TC simple y no está a menos
    # de ~1 mm de hueso en la TC simple.
    hueso_margen = ndimage.binary_dilation(a_ct > 200, iterations=3)
    cta_suave = ndimage.gaussian_filter(a_cta, 0.5)
    vasos = (cta_suave > 180) & (sus > 100) & a_cub & zona & ~hueso_margen
    etiq, n = ndimage.label(vasos)
    if n:
        tam = ndimage.sum(vasos, etiq, range(1, n + 1))
        # Se conservan las ramas conectadas grandes (> 300 mm3).
        vox = float(np.prod(sp))
        vasos = np.isin(etiq, 1 + np.nonzero(tam * vox > 300)[0])
    for nombre, arr in (("vasos", vasos), ("craneo", hueso),
                        ("intracraneal", intracraneal)):
        im = sitk.GetImageFromArray(arr.astype(np.uint8))
        im.CopyInformation(cta)
        sitk.WriteImage(im, os.path.join(salida, nombre + ".nii.gz"))
    print("vasos %.1f cm3, cráneo %.1f cm3" % (
        vasos.sum() * np.prod(sp) / 1000, hueso.sum() * np.prod(sp) / 1000))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cta", required=True)
    p.add_argument("--ct", required=True)
    p.add_argument("--salida", required=True)
    a = p.parse_args()
    procesar(a.cta, a.ct, a.salida)
