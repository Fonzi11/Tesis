"""
Paridad numerica entre el motor NEUROHUB y PyRadiomics 3.0.1.

PyRadiomics es la implementacion de referencia IBSI de facto: si un descriptor
no coincide con el, el descriptor es el que esta mal. Este guion corre AMBOS
motores sobre la MISMA imagen y la MISMA ROI, y compara descriptor a descriptor.

Para que la comparacion sea significativa hay que fijar exactamente la misma
configuracion en los dos lados:

  * binCount / binWidth identicos (mismo ancho de bin y mismo numero de niveles)
  * re-segmentacion desactivada en ambos; si no, cada motor rehace su propio
    suavizado y se compararian membranas distintas
  * normalizacion desactivada en ambos
  * la mascara se pasa como binaria, no como label map

Detalle importante: PyRadiomics se llama igual que el motor propio
(`radiomics` en los dos casos), asi que no se puede importar por nombre. El
paquete de referencia se carga por ruta con importlib, Leaving `radiomics` en
sys.modules apuntando al codigo de NEUROHUB.
"""

import importlib.util
import math
import os
import sys
import traceback

import numpy as np

RAIZ_PYRADIOMICS = r"D:\Tesis\pyradiomics-3.0.1"
SRC_NEUROHUB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src")

# PyRadiomics hace imports ABSOLUTOS internos (`from radiomics import
# _cmatrices`), asi que el nombre `radiomics` le tiene que pertenecer a el. Por
# eso PyRadiomics se importa de forma normal y NEUROHUB, que solo usa imports
# relativos, se carga por ruta bajo otro nombre.
sys.path.insert(0, RAIZ_PYRADIOMICS)
import radiomics as pyradiomics            # noqa: E402  referencia

_esp = importlib.util.spec_from_file_location(
    "neurohub_rad",
    os.path.join(SRC_NEUROHUB, "radiomics", "__init__.py"),
    submodule_search_locations=[os.path.join(SRC_NEUROHUB, "radiomics")])
neurohub = importlib.util.module_from_spec(_esp)
sys.modules["neurohub_rad"] = neurohub
_esp.loader.exec_module(neurohub)

import SimpleITK as sitk                    # noqa: E402

MRI = r"D:\Tesis\data\nifti\MRBrainTumor1.nii.gz"
TUMOR = r"D:\Tesis\salidas\segmentaciones_ai\tumor_brats.nii.gz"

BIN_COUNT = 32
BIN_WIDTH = 25
ETIQUETA = 1          # SNFH en el mapa BraTS


# PyRadiomics 3.0.1 pone la clase SIEMPRE en el nombre, en minusculas para
# texturas (`original_glcm_Autocorrelation`) y tal cual para firstorder y
# shape (`original_firstorder_Mean`, `original_shape_Elongation`).
#
# El motor propio usa la clase en mayusculas (`original_GLCM_...`) y la OMITE
# por completo en firstorder, shape y LSH/LSZM (`original_Mean`,
# `original_Elongation`, `LSH_Mean`). Esa omision es justamente lo que impide
# que el CSV sea intercambiable con PyRadiomics y Raidionics, asi que aqui se
# traduce el nombre de la referencia al del motor bajo prueba.
TEXTURAS = ("glcm", "gldm", "glrlm", "glszm", "ngtdm")


def nombre_py_a_nh(pyname):
    """
    `original_glcm_Autocorrelation` -> `original_GLCM_Autocorrelation`
    `original_firstorder_Mean`      -> `original_Mean`
    `original_shape_Elongation`     -> `original_Elongation`

    PyRadiomics separa la clase del descriptor con guion bajo y en minusculas
    para texturas; el motor propio la escribe en mayusculas y la omite en
    firstorder/shape/LSH. Se traduce clase a clase en vez de aplicar una
    conversion global, porque los nombres de descriptor ya contienen guiones
    bajos que hay que conservar intactos.
    """
    if "_LSH_" in pyname or "_LSZM_" in pyname:
        # LSH/LSZM no llevan prefijo de imagen en ninguno de los dos motores.
        return pyname.replace("_LSH_", "LSH_").replace("_LSZM_", "LSZM_")

    for clase in TEXTURAS:
        token = clase + "_"
        if token in pyname:
            cabeza, _, cola = pyname.partition(token)
            # `original_glcm_X`: el token `glcm_` se come el guion que lo
            # separa del prefijo, asi que hay que reponerlo.
            return "%s_%s_%s" % (cabeza.rstrip("_"), clase.upper(), cola)

    for clase in ("firstorder_", "shape_"):
        if clase in pyname:
            cabeza, _, cola = pyname.partition(clase)
            return "%s%s" % (cabeza, cola)

    return pyname


def cargar_para_pyradiomics(ruta_img, ruta_mascara):
    """Devuelve (imagen, mascara_binaria) en la geometria de la MRI."""
    img = sitk.ReadImage(ruta_img)
    msk = sitk.ReadImage(ruta_mascara)
    msk = (sitk.GetArrayFromImage(msk) == ETIQUETA).astype(np.uint8)
    msk_sitk = sitk.GetImageFromArray(msk)
    msk_sitk.CopyInformation(img)      # geometria identica a la de la imagen
    return img, msk_sitk


def main():
    img, msk = cargar_para_pyradiomics(MRI, TUMOR)

    # ---------------- PyRadiomics (referencia) -------------------------
    print("Ejecutando PyRadiomics %s (referencia)..."
          % pyradiomics.__version__, flush=True)
    extractor = pyradiomics.featureextractor.RadiomicsFeatureExtractor()
    extractor.settings["binCount"] = BIN_COUNT
    # binWidth tiene PRIORIDAD sobre binCount en PyRadiomics: si se deja puesto,
    # la ROI (rango 98-295 en este caso) se recorta en ~8 niveles de ancho 25 y
    # el motor propio, que cuantiza en `bin_count` niveles equiespaciados, usa
    # 32. Estarian comparando dos discretizaciones distintas. Con binWidth=None
    # ambos cuantizan en el mismo numero de niveles.
    extractor.settings["binWidth"] = None
    extractor.settings["resampledPixelSpacing"] = None
    extractor.settings["normalize"] = False
    extractor.settings["correctMask"] = False
    extractor.settings["geometry"] = {}
    extractor.enableAllFeatures()
    salida_py = extractor.execute(img, msk, label=ETIQUETA)
    # execute() anade un bloque de diagnostico que no son rasgos.
    referencia = {k: v for k, v in salida_py.items()
                  if not k.startswith("diagnostics")}
    numericos_py = {}
    vectoriales = []
    for k, v in referencia.items():
        if isinstance(v, (int, float, np.number)):
            numericos_py[k] = float(v)
        elif isinstance(v, np.ndarray) and v.size >= 1:
            # Los rasgos vectoriales (Eigenvalues, Elongation, ...) se
            # comparan por su primer componente; el resto son los otros ejes.
            numericos_py[k] = float(np.asarray(v).ravel()[0])
            vectoriales.append(k)
    print("  PyRadiomics devolvio %d descriptores numericos (%d vectoriales)"
          % (len(numericos_py), len(vectoriales)))

    # ---------------- NEUROHUB (motor bajo prueba) ---------------------
    print("Ejecutando NEUROHUB %s..." % neurohub.__version__, flush=True)
    vol, spacing, meta = neurohub.cargar_volumen(MRI)
    roi = neurohub.MaskLabelMap.from_nifti(TUMOR, (1, 2, 3), "Tumor") \
        if hasattr(neurohub.MaskLabelMap, "from_nifti") else None
    if roi is None:
        roi = neurohub.masks.de_nifti(TUMOR, (1, 2, 3), "Tumor") \
            .subregion((ETIQUETA,))
    cfg = neurohub.ExtractionConfig(
        bin_count=BIN_COUNT, normalize=False,
        resegmentacion=False, calcular_textura=True)
    propio = neurohub.extraer_radiomics(vol, {"Tumor": roi}, cfg)["Tumor"]
    print("  NEUROHUB devolvio %d descriptores" % len(propio))

    # ---------------- COMPARACION -------------------------------------
    #
    # Tolerancia: PyRadiomics acumula las texturas en C sobre float32, y el
    # orden de recorrido de los voxels puede diferir del nuestro, asi que una
    # desviacion relativa de ~1e-5 es ruido de punto flotante, no un error de
    # implementacion. Se usa 1e-4 como corte.
    TOLERANCIA = 1e-4

    comunes = 0
    coinciden = 0
    desviaciones = []
    faltan_nh = []

    for pyname, valorpy in numericos_py.items():
        nhname = nombre_py_a_nh(pyname)
        if nhname not in propio:
            faltan_nh.append((pyname, nhname))
            continue
        comunes += 1
        a, b = float(valorpy), float(propio[nhname])
        if not (math.isfinite(a) and math.isfinite(b)):
            # PyRadiomics devuelve 0 en vez de NaN cuando la matriz degenera
            # (p. ej. GLCM de una ROI de un solo voxel). Se registra aparte.
            if math.isnan(a) and math.isnan(b):
                coinciden += 1
            else:
                desviaciones.append((nhname, a, b, "NaN/finito"))
            continue
        error = abs(a - b) / max(abs(a), abs(b), 1e-12)
        if error <= TOLERANCIA:
            coinciden += 1
        else:
            desviaciones.append((nhname, a, b, "%.2e" % error))

    traducidos = {nombre_py_a_nh(k) for k in numericos_py}
    faltan_py = sorted(n for n in propio if n not in traducidos)

    print()
    print("=" * 72)
    print("COMPARACION NEUROHUB  vs  PyRadiomics 3.0.1")
    print("=" * 72)
    print("ROI                     : tumor (etiqueta %d) sobre %s"
          % (ETIQUETA, os.path.basename(MRI)))
    print("Descriptores comparables: %d" % comunes)
    print("Coinciden (<=%.0e rel)  : %d  (%.1f%%)"
          % (TOLERANCIA, coinciden, 100.0 * coinciden / max(comunes, 1)))
    print("Desviaciones            : %d" % len(desviaciones))
    print("Solo en PyRadiomics     : %d" % len(faltan_nh))
    print("Solo en NEUROHUB       : %d" % len(faltan_py))
    print()

    if desviaciones:
        print("--- Desviaciones (peor primero) ---")
        for nhname, a, b, err in sorted(
                desviaciones, key=lambda d: d[3], reverse=True)[:50]:
            print("  %-50s py=%-13.6g nh=%-13.6g rel=%s" % (nhname, a, b, err))
        print()
    if faltan_nh:
        print("--- Presentes en PyRadiomics, ausentes en NEUROHUB ---")
        for pyname, nhname in faltan_nh[:40]:
            print("  %-46s -> %s" % (pyname, nhname))
        print()
    if faltan_py:
        print("--- Presentes en NEUROHUB, ausentes en PyRadiomics ---")
        for nhname in faltan_py[:40]:
            print("  %s" % nhname)
        print()

    return coinciden, comunes, len(desviaciones), len(faltan_nh), len(faltan_py)


# Defectos confirmados contra PyRadiomics 3.0.1 que quedan PENDIENTES, para no
# perderlos al retomar el trabajo:
#
# 1. NOMBRES. El motor propio omite la clase en firstorder/shape/LSH
#    (`original_Mean`, `original_Elongation`, `LSH_Mean`), y PyRadiomics la
#    escribe siempre (`original_firstorder_Mean`, `original_shape_Elongation`).
#    Sin eso el CSV no es intercambiable, que es un requisito explicito.
#
# 2. FALTANTES. 49 descriptores de PyRadiomics no existen en el motor:
#    MajorAxisLength, MinorAxisLength, LeastAxisLength,
#    Maximum2DDiameterRow/Column/Slice, SurfaceArea, 10Percentile,
#    90Percentile, TotalEnergy, LSZM_* y las variantes *Log2.
#
# 3. GLSZM. GrayLevelNonUniformityNormalized, ZonePercentage y ZoneVariance
#    estan mal calculados (errores del 99%): las magnitudes apuntan a que se
#    normalizan por el numero de voxels en vez de por el numero de zonas.
#
# 4. NGTDM. Complexity y Contrast se diferencian en casi un factor 10 y Strength
#    a la mitad; hay que revisar la construccion de la matriz.
#
# 5. GLCM. SumSquares y ClusterProminence/Shade/Tendency siguen desviados
#    (~8-9%) aunque la matriz ya coincide: es la etapa de features, no la de
#    cuantizacion.
#
# 6. SHAPE. SurfaceVolumeRatio, Sphericity, Maximum3DDiameter y VoxelVolume
#    difieren. VoxelVolume es geometria pura (10 591 en ambos lados deberia
#    coincidir) y SurfaceVolumeRatio sale 13.3 frente a 0.54, lo que apunta a que
#    se divide por el area de la malla en lugar de multiplicar. Ojo: aqui se
#    comparan mallas distintas (skimage suavizada vs marching cubes de PyRadiomics),
#    asi que parte de la diferencia es esperable.
#
# 7. FIRSTORDER. Kurtosis, Uniformity, InterquartileRange y Entropy difieren.
#    InterquartileRange da 25 frente a 13, lo que sugiere que se calcula sobre el
#    histograma cuantizado en vez de sobre los valores originales.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
