"""Convierte las series 3D del caso tumor_02 (estudio 926684) a NIfTI.

Selecciona las series por SeriesDescription para no depender del orden de
exportación y deja T1, T1 con gadolinio, FLAIR y T2 en la misma carpeta.
"""
import os
import sys
import SimpleITK as sitk

SERIES = {
    "t1": "SAG T1 3D",
    "t1ce": "GADOLINIO",
    "flair": "3D_FLAIR_SHC",
    "t2": "AXI T2",
}


def preparar(dicom_dir, salida_dir):
    os.makedirs(salida_dir, exist_ok=True)
    lector = sitk.ImageSeriesReader()
    encontrados = {}
    for raiz, _, _ in os.walk(dicom_dir):
        for uid in lector.GetGDCMSeriesIDs(raiz) or ():
            archivos = lector.GetGDCMSeriesFileNames(raiz, uid)
            meta = sitk.ImageFileReader()
            meta.SetFileName(archivos[0])
            meta.LoadPrivateTagsOn()
            meta.ReadImageInformation()
            desc = meta.GetMetaData("0008|103e").strip() if meta.HasMetaDataKey("0008|103e") else ""
            for clave, buscada in SERIES.items():
                # Solo la serie volumetrica completa (la de mas cortes).
                if desc == buscada and len(archivos) > len(encontrados.get(clave, ())):
                    encontrados[clave] = archivos
    rutas = {}
    for clave, archivos in encontrados.items():
        lector.SetFileNames(archivos)
        imagen = lector.Execute()
        ruta = os.path.join(salida_dir, "tumor_02_%s.nii.gz" % clave)
        sitk.WriteImage(imagen, ruta)
        rutas[clave] = ruta
        print(clave, len(archivos), imagen.GetSize(), imagen.GetSpacing())
    faltan = set(SERIES) - set(rutas)
    if faltan:
        raise SystemExit("Faltan series: %s" % ", ".join(sorted(faltan)))
    return rutas


if __name__ == "__main__":
    preparar(sys.argv[1], sys.argv[2])
