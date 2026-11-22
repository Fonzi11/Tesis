"""Máscara de cráneo desde TC, opcionalmente llevada al espacio de una RM.

    python ar_craneo_ct.py --ct ct.nii.gz --salida craneo.nii.gz
           [--referencia t1.nii.gz] [--espaciado 0.5]

Con ``--referencia`` la TC se registra rígidamente (información mutua) sobre
la RM del mismo paciente y el hueso se umbraliza ya en el espacio de la RM,
de modo que cráneo, cerebro y tumor comparten coordenadas físicas.
"""
import argparse
import os

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

UMBRAL_HU = 250.0


def _mascara_suave(seg_path):
    seg = sitk.ReadImage(seg_path)
    m = sitk.Cast(seg > 0, sitk.sitkFloat32)
    return sitk.SmoothingRecursiveGaussian(m, 2.0)


def _registrar_mascaras(seg_rm, seg_ct):
    """Alinea las máscaras cerebrales SynthSeg de RM y TC (misma forma)."""
    f, m = _mascara_suave(seg_rm), _mascara_suave(seg_ct)
    ini = sitk.CenteredTransformInitializer(
        f, m, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.MOMENTS)
    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMeanSquares()
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(2.0, 1e-4, 300, 0.6)
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetShrinkFactorsPerLevel([4, 2, 1])
    reg.SetSmoothingSigmasPerLevel([2, 1, 0])
    reg.SetInitialTransform(ini, inPlace=False)
    tx = reg.Execute(f, m)
    print("registro de máscaras cerebrales: MSE %.4f" % reg.GetMetricValue())
    return tx


def _registrar_ct_rm(rm, ct, inicial=None):
    f = sitk.Cast(rm, sitk.sitkFloat32)
    m = sitk.Clamp(sitk.Cast(ct, sitk.sitkFloat32), sitk.sitkFloat32, -200, 1600)
    ini = inicial if inicial is not None else sitk.CenteredTransformInitializer(
        f, m, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.MOMENTS)
    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=64)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.05, seed=11)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(1.0, 1e-4, 400, 0.6)
    reg.SetOptimizerScalesFromPhysicalShift()
    if inicial is not None:
        # Ya alineado por las máscaras: solo refinamiento fino.
        reg.SetOptimizerAsRegularStepGradientDescent(0.3, 1e-4, 200, 0.6)
        reg.SetShrinkFactorsPerLevel([2, 1])
        reg.SetSmoothingSigmasPerLevel([1, 0])
    else:
        reg.SetShrinkFactorsPerLevel([8, 4, 2, 1])
        reg.SetSmoothingSigmasPerLevel([3, 2, 1, 0])
    reg.SetInitialTransform(ini, inPlace=False)
    tx = reg.Execute(f, m)
    print("registro TC->RM: MI %.4f (%s)" % (
        reg.GetMetricValue(), reg.GetOptimizerStopConditionDescription()[:50]))
    return tx


def craneo(ct_path, salida, referencia=None, espaciado=0.5,
           seg_rm=None, seg_ct=None):
    ct = sitk.ReadImage(ct_path, sitk.sitkFloat32)
    if referencia:
        rm = sitk.ReadImage(referencia, sitk.sitkFloat32)
        inicial = (_registrar_mascaras(seg_rm, seg_ct)
                   if seg_rm and seg_ct else None)
        tx = _registrar_ct_rm(rm, ct, inicial)
        sp = rm.GetSpacing()
        tam = [int(round(rm.GetSize()[i] * sp[i] / espaciado)) for i in range(3)]
        rejilla = sitk.Image(tam, sitk.sitkFloat32)
        rejilla.SetSpacing((espaciado,) * 3)
        rejilla.SetOrigin(rm.GetOrigin())
        rejilla.SetDirection(rm.GetDirection())
        ct = sitk.Resample(ct, rejilla, tx, sitk.sitkLinear, -1024.0)
    a = sitk.GetArrayFromImage(ct)
    hueso = ndimage.gaussian_filter(a, 0.5) > UMBRAL_HU
    hueso = ndimage.binary_closing(hueso, iterations=1)
    # Contorno del cuerpo (piel): el cabezal y la mesa de la TC están fuera.
    cuerpo = a > -400
    # Apertura de ~4 mm: separa el cabezal donde apoya sobre la piel.
    it = max(1, int(round(4.0 / min(ct.GetSpacing()))))
    cuerpo = ndimage.binary_opening(cuerpo, iterations=it)
    lab, n = ndimage.label(cuerpo)
    if n:
        cuerpo = lab == 1 + int(np.argmax(ndimage.sum(cuerpo, lab, range(1, n + 1))))
    for k in range(cuerpo.shape[0]):
        cuerpo[k] = ndimage.binary_fill_holes(cuerpo[k])
    lab, n = ndimage.label(hueso)
    if n:
        idx = range(1, n + 1)
        tam = ndimage.sum(hueso, lab, idx)
        dentro = ndimage.sum(cuerpo, lab, idx) / np.maximum(tam, 1)
        # Fragmentos óseos de más de 2 cm3 (descarta calcificaciones y ruido)
        # y al menos 90 % dentro del cuerpo (descarta cabezal y mesa).
        vox = float(np.prod(ct.GetSpacing())) / 1000.0
        hueso = np.isin(lab, 1 + np.nonzero((tam * vox > 2.0) & (dentro > 0.9))[0])
    out = sitk.GetImageFromArray(hueso.astype(np.uint8))
    out.CopyInformation(ct)
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    sitk.WriteImage(out, salida)
    if referencia:
        sitk.WriteImage(sitk.Cast(ct, sitk.sitkInt16),
                        salida.replace(".nii.gz", "_ct_en_rm.nii.gz"))
    print("cráneo %.1f cm3 -> %s" % (
        hueso.sum() * np.prod(ct.GetSpacing()) / 1000, salida))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ct", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument("--referencia")
    p.add_argument("--espaciado", type=float, default=0.5)
    p.add_argument("--seg-rm", help="SynthSeg de la RM (inicialización)")
    p.add_argument("--seg-ct", help="SynthSeg --ct de la TC (inicialización)")
    a = p.parse_args()
    craneo(a.ct, a.salida, a.referencia, a.espaciado, a.seg_rm, a.seg_ct)
