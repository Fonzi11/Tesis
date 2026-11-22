"""Segmenta el tumor de un paciente real con el modelo BraTS de ATLAS.

Reproduce el preprocesado del conjunto BraTS para que el SegResNet reciba
datos del mismo dominio con el que fue entrenado:

1. Registro rígido (información mutua) de T1, T2 y FLAIR sobre T1-Gd.
2. Remuestreo a 1 mm isotrópico con la orientación de vóxel de BraTS.
3. Extracción del cerebro con la máscara de FreeSurfer SynthSeg.
4. Inferencia por ventana deslizante y limpieza de componentes espurias.

La segmentación resultante se devuelve al espacio original de T1 (el mismo
que usa SynthSeg) con etiquetas BraTS: 1 necrosis, 2 edema, 4 realce.
"""
import argparse
import os
import sys

import nibabel as nib
import numpy as np
import SimpleITK as sitk
import torch
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(RAIZ, "src"))


def _registrar_rigido(fija, movil):
    fija_f = sitk.Cast(fija, sitk.sitkFloat32)
    movil_f = sitk.Cast(movil, sitk.sitkFloat32)
    inicial = sitk.CenteredTransformInitializer(
        fija_f, movil_f, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY)
    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=48)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.05, seed=7)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsRegularStepGradientDescent(
        learningRate=1.0, minStep=1e-4, numberOfIterations=200,
        relaxationFactor=0.6)
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetShrinkFactorsPerLevel([4, 2, 1])
    reg.SetSmoothingSigmasPerLevel([2, 1, 0])
    reg.SetInitialTransform(inicial, inPlace=False)
    transformada = reg.Execute(fija_f, movil_f)
    print("  registro: métrica final %.4f, %s" % (
        reg.GetMetricValue(), reg.GetOptimizerStopConditionDescription()[:60]))
    return transformada


def _rejilla_brats(referencia, plantilla_brats):
    """Rejilla 1 mm con la dirección de BraTS que cubre la referencia."""
    brats = sitk.ReadImage(plantilla_brats)
    direccion = np.array(brats.GetDirection()).reshape(3, 3)
    tam = np.array(referencia.GetSize())
    esquinas = []
    for i in (0, tam[0] - 1):
        for j in (0, tam[1] - 1):
            for k in (0, tam[2] - 1):
                esquinas.append(referencia.TransformIndexToPhysicalPoint(
                    (int(i), int(j), int(k))))
    esquinas = np.array(esquinas)
    # Coordenadas en el sistema de ejes BraTS.
    locales = esquinas @ direccion
    minimo, maximo = locales.min(0), locales.max(0)
    size = np.ceil(maximo - minimo).astype(int) + 1
    origen = direccion @ minimo
    rejilla = sitk.Image([int(s) for s in size], sitk.sitkFloat32)
    rejilla.SetSpacing((1.0, 1.0, 1.0))
    rejilla.SetDirection(tuple(direccion.ravel()))
    rejilla.SetOrigin(tuple(origen))
    return rejilla


def _array_xyz(imagen):
    # nibabel/MONAI leen el NIfTI en orden (x, y, z); SimpleITK da (z, y, x).
    return np.transpose(sitk.GetArrayFromImage(imagen), (2, 1, 0))


def segmentar(t1, t1ce, t2, flair, synthseg, salida, plantilla_brats):
    imgs = {k: sitk.ReadImage(v, sitk.sitkFloat32) for k, v in
            {"t1": t1, "t1ce": t1ce, "t2": t2, "flair": flair}.items()}
    fija = imgs["t1ce"]
    rejilla = _rejilla_brats(fija, plantilla_brats)

    canales, transformadas = {}, {}
    for nombre in ("t1ce", "t1", "t2", "flair"):
        print("Alineando %s" % nombre.upper())
        tx = (sitk.Euler3DTransform() if nombre == "t1ce"
              else _registrar_rigido(fija, imgs[nombre]))
        transformadas[nombre] = tx
        # Un único remuestreo directo a la rejilla BraTS evita interpolar dos veces.
        canales[nombre] = sitk.Resample(imgs[nombre], rejilla, tx,
                                        sitk.sitkBSpline, 0.0)

    # SynthSeg está en el espacio de T1: se lleva a la rejilla con T1 -> T1-Gd.
    seg_fs = sitk.ReadImage(synthseg)
    tx_t1 = transformadas["t1"]
    cerebro = sitk.Resample(seg_fs, rejilla, tx_t1, sitk.sitkNearestNeighbor, 0)
    cerebro = _array_xyz(cerebro) > 0
    cerebro = ndimage.binary_closing(cerebro, iterations=3)
    cerebro = ndimage.binary_fill_holes(cerebro)
    cerebro = ndimage.binary_dilation(cerebro, iterations=1)

    volumen = np.stack([_array_xyz(canales[n]) for n in
                        ("t1ce", "t1", "t2", "flair")]).astype(np.float32)
    volumen[:, ~cerebro] = 0.0
    # BraTS recorta intensidades extremas antes de normalizar.
    for c in range(4):
        dentro = volumen[c][cerebro]
        lo, hi = np.percentile(dentro, (0.5, 99.5))
        volumen[c] = np.where(cerebro, np.clip(volumen[c], lo, hi), 0.0)

    from monai.inferers import SlidingWindowInferer
    from monai.transforms import NormalizeIntensity
    import importlib
    brats = importlib.import_module("02_segmentacion_brats")
    modelo, device = brats.load_brats_model(
        os.path.join(RAIZ, "modelos_preentrenados", "brats_mri_segmentation"))
    if modelo is None:
        raise RuntimeError("No se pudo cargar el modelo BraTS.")
    tensor = NormalizeIntensity(nonzero=True, channel_wise=True)(
        torch.from_numpy(volumen)).unsqueeze(0).to(device)
    inferer = SlidingWindowInferer(roi_size=(240, 240, 160), sw_batch_size=1,
                                   overlap=0.5, mode="gaussian")
    print("Inferencia BraTS en %s, volumen %s" % (device, volumen.shape[1:]))
    with torch.no_grad():
        salida_red = inferer(tensor, modelo)
    etiquetas = brats._postprocess_output(salida_red, volumen.shape[1:])
    etiquetas[~cerebro] = 0

    # Conserva solo la lesión principal: componentes del tumor completo
    # conectadas al núcleo de mayor tamaño.
    completo = etiquetas > 0
    comp, n = ndimage.label(completo)
    if n > 1:
        nucleo = np.isin(etiquetas, (1, 4))
        tam_nucleo = ndimage.sum(nucleo, comp, range(1, n + 1))
        tam_total = ndimage.sum(completo, comp, range(1, n + 1))
        principal = int(np.argmax(tam_nucleo if tam_nucleo.max() > 0
                                  else tam_total)) + 1
        etiquetas[comp != principal] = 0

    seg = sitk.GetImageFromArray(np.transpose(etiquetas, (2, 1, 0)))
    seg.CopyInformation(rejilla)
    # De la rejilla BraTS (espacio T1-Gd) al espacio original de T1.
    seg_t1 = sitk.Resample(seg, imgs["t1"], tx_t1.GetInverse(),
                           sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    sitk.WriteImage(seg_t1, salida)
    for etiqueta, nombre in ((1, "necrosis"), (2, "edema"), (4, "realce")):
        print("  %-9s %8.1f cm3" % (nombre, (etiquetas == etiqueta).sum() / 1000))
    return salida


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for nombre in ("t1", "t1ce", "t2", "flair", "synthseg", "salida"):
        p.add_argument("--" + nombre, required=True)
    p.add_argument("--plantilla-brats", required=True,
                   help="Cualquier NIfTI BraTS para copiar su orientación")
    a = p.parse_args()
    segmentar(a.t1, a.t1ce, a.t2, a.flair, a.synthseg, a.salida,
              a.plantilla_brats)


if __name__ == "__main__":
    main()
