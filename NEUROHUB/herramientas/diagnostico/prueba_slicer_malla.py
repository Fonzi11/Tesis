"""Prueba: extraccion con la superficie reconstruida por 3D Slicer."""
import sys
import time

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(APP_ROOT, "src"))

from radiomics.extract import ExtractionConfig, cargar_volumen, extraer_radiomics
from radiomics.masks import de_nifti, magmas_braTS
from radiomics.report import construir_tabla

MRI = r"D:\Tesis\data\nifti\MRBrainTumor1.nii.gz"
TUM = r"D:\Tesis\salidas\segmentaciones_ai\tumor_brats.nii.gz"

volumen, spacing, meta = cargar_volumen(MRI)
rois = magmas_braTS(tumor_roi=de_nifti(TUM, (1, 2, 3), "Tumor"))
print("ROIs:", list(rois))

t0 = time.time()
cfg = ExtractionConfig(bin_count=32, malla_slicer=True, slicer_suavizado=0.5)
resultado = extraer_radiomics(volumen, rois, cfg)
print("CON malla de Slicer: %.1f s" % (time.time() - t0))

t0 = time.time()
resultado_ref = extraer_radiomics(
    volumen, rois, ExtractionConfig(bin_count=32))
print("SIN malla de Slicer (skimage): %.1f s" % (time.time() - t0))

print()
print("%-10s %12s %12s %10s" % ("ROI", "MeshVol(mm3)", "Area(mm2)", "Sphericity"))
for roi, rasgos in resultado.items():
    print("%-10s %12.1f %12.1f %10.4f" % (
        roi, rasgos["original_MeshVolume_mm3"],
        rasgos["original_SurfaceArea_mm2"], rasgos["original_Sphericity"]))
print("%-10s %12.1f %12.1f %10.4f" % (
    "  (skimage)", resultado_ref["Tumor_SNFH"]["original_MeshVolume_mm3"],
    resultado_ref["Tumor_SNFH"]["original_SurfaceArea_mm2"],
    resultado_ref["Tumor_SNFH"]["original_Sphericity"]))

# Los rasgos de textura NO deben depender de la malla.
diferencias = []
for roi, rasgos in resultado.items():
    ref = resultado_ref[roi]
    for k, v in rasgos.items():
        if k.startswith("original_") and ("GLCM" in k or "GLRLM" in k
                                          or "GLSZM" in k or "NGTDM" in k
                                          or "LSH" in k or "LSZM" in k):
            if abs(v - ref[k]) > 1e-9:
                diferencias.append((roi, k, v, ref[k]))
print()
print("desajustes de textura al cambiar de malla:", len(diferencias))
for d in diferencias[:5]:
    print("  ", d)

tabla = construir_tabla(resultado, {"Estudio": "MRBrainTumor1"})
print()
print(tabla)

# Ningún descriptor debe ser NaN ni infinito: en un informe clínico un valor
# no finito es peor que un descriptor ausente, porque no se distingue.
import math

rois_nombres = tabla.rois()
columnas = tabla.columnas()
valores = [tabla.valor(r, c) for r in rois_nombres for c in columnas]
no_finitos = [v for v in valores if not math.isfinite(v)]
print("ROIs: %s | rasgos/ROI: %d" % (rois_nombres, tabla.n_rasgos()))
print("valores totales: %d | no finitos: %d" % (len(valores), len(no_finitos)))
