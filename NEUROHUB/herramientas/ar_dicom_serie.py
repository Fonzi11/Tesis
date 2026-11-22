"""Convierte una serie DICOM concreta (por número de serie) a NIfTI.

    python ar_dicom_serie.py <carpeta_dicom> <numero_serie> <salida.nii.gz>

Si varias series comparten número se elige la de más cortes.

Corrección de inclinación del gantry: en una TC inclinada los cortes se
apilan a lo largo del eje Z de la mesa, no de la normal del plano. Un lector
que supone apilado normal (ITK) produce una cizalla que deforma la anatomía
varios milímetros en los extremos. Aquí cada corte se desplaza dentro de su
plano la componente tangencial de su posición real, de modo que el apilado
queda perpendicular y la geometría (origen + dirección + espaciado) es exacta.
"""
import collections
import os
import sys

import numpy as np
import pydicom
import SimpleITK as sitk
from scipy import ndimage


def _leer(carpeta, numero):
    series = collections.defaultdict(list)
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            try:
                d = pydicom.dcmread(ruta)
            except Exception:
                continue
            if str(getattr(d, "SeriesNumber", "")) == str(numero) and "PixelData" in d:
                series[d.SeriesInstanceUID].append(d)
    if not series:
        raise SystemExit("No existe la serie %s en %s" % (numero, carpeta))
    return max(series.values(), key=len)


def convertir(carpeta, numero, salida):
    cortes = _leer(carpeta, numero)
    iop = np.array(cortes[0].ImageOrientationPatient, dtype=float)
    fila, col = iop[:3], iop[3:]
    normal = np.cross(fila, col)
    pos = np.array([np.array(c.ImagePositionPatient, dtype=float) for c in cortes])
    orden = np.argsort(pos @ normal)
    cortes = [cortes[i] for i in orden]
    pos = pos[orden]
    # Elimina cortes duplicados (misma posición).
    _, unicos = np.unique(np.round(pos @ normal, 3), return_index=True)
    cortes = [cortes[i] for i in sorted(unicos)]
    pos = pos[sorted(unicos)]

    dy, dx = (float(v) for v in cortes[0].PixelSpacing)  # fila, columna
    d_normal = pos @ normal
    paso = float(np.median(np.diff(d_normal)))
    rel = pos - pos[0]
    tangencial = rel - np.outer(rel @ normal, normal)
    desp_col = tangencial @ fila / dx   # desplazamiento en columnas (eje i)
    desp_fil = tangencial @ col / dy    # desplazamiento en filas (eje j)
    inclinado = np.abs(np.r_[desp_col, desp_fil]).max() > 0.05

    vol = np.empty((len(cortes), cortes[0].Rows, cortes[0].Columns), np.float32)
    for k, c in enumerate(cortes):
        a = c.pixel_array.astype(np.float32) * float(getattr(c, "RescaleSlope", 1)) \
            + float(getattr(c, "RescaleIntercept", 0))
        a = np.maximum(a, -1024.0)  # relleno fuera del círculo de reconstrucción
        if inclinado:
            # La imagen del corte k está desplazada (desp) respecto al apilado
            # normal; se traslada para que su píxel (0,0) caiga en pos[0] + k*n.
            a = ndimage.shift(a, (desp_fil[k], desp_col[k]), order=1,
                              mode="constant", cval=-1024.0)
        vol[k] = a
    # Remuestreo de la normal a espaciado uniforme (por si faltan cortes).
    z_uniforme = d_normal[0] + paso * np.arange(int(round((d_normal[-1] - d_normal[0]) / paso)) + 1)
    if len(z_uniforme) != len(d_normal) or np.abs(d_normal - d_normal[0] - paso * np.arange(len(d_normal))).max() > 0.02:
        idx = np.interp(z_uniforme, d_normal, np.arange(len(d_normal)))
        vol = ndimage.map_coordinates(
            vol, np.meshgrid(idx, np.arange(vol.shape[1]), np.arange(vol.shape[2]),
                             indexing="ij"), order=1)

    img = sitk.GetImageFromArray(np.round(vol).astype(np.int16))
    img.SetSpacing((dx, dy, paso))
    img.SetOrigin(tuple(pos[0]))
    img.SetDirection(tuple(np.column_stack([fila, col, normal]).ravel()))
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    sitk.WriteImage(img, salida)
    print(salida, img.GetSize(), [round(s, 3) for s in img.GetSpacing()],
          "gantry inclinado corregido" if inclinado else "sin inclinación")


if __name__ == "__main__":
    convertir(sys.argv[1], sys.argv[2], sys.argv[3])
