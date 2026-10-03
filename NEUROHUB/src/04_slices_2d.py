"""
=====================================================================
 Vista 2D de alta calidad con tumor resaltado
=====================================================================
Genera los cortes axial, coronal y sagital a maxima calidad y los guarda como
PNG.

Este modulo es un ENVOLTORIO de `volumen_2d.Volumen2D`: el render (windowing
por tejido, CLAHE, realce de borde, overlay verde con borde opaco) vive
unicamente alli, de modo que el PNG que se exporta y lo que se ve en el visor
interactivo sean EXACTAMENTE la misma imagen. Antes cada uno tenia su propia
rutina de normalizado y los dos se veian distintos.

Por que no se re-muestrea la mascara
------------------------------------
`Volumen2D` exige que volumen y mascara compartan rejilla y falla con un
error claro si no es asi. Superponer dos rejillas distintas daria un tumor
desplazado respecto al tejido, que es peor que no dibujar nada.

Uso:
    from volumen_2d import Volumen2D
    vol = Volumen2D('volumen.nii.gz', 'tumor_brats.nii.gz')
    vol.exportar_vistas('salidas/vistas_2d')
"""

import os
import sys

# `04_...` no es un paquete: se importa con importlib. Para que este modulo
# encuentre `volumen_2d` este se carga desde el mismo directorio `src`.
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import numpy as np  # noqa: E402

from volumen_2d import EJES, Volumen2D  # noqa: E402

# Resolucion del lado mayor del PNG exportado. 1024 px es lo que espera
# `tests/test_slices.py` y lo que se usa para presentación.
RESOLUCION_PNG = 1024

NOMBRES = dict(EJES)      # "axial" -> 0, "coronal" -> 1, "sagital" -> 2


def exportar_vistas(volumen, dir_salida, alto=RESOLUCION_PNG,
                    indices=None, con_pie=True):
    """Escribe los cortes pedidos de un `Volumen2D` ya cargado.

    `indices` es {eje: corte}. Si falta un eje, se elige el corte con mas
    tumor de ese eje, que es lo que se quiere en una presentacion: la
    rebanada donde la lesion se ve mejor.

    Returns: {eje: ruta_png}.
    """
    from PIL import Image

    os.makedirs(dir_salida, exist_ok=True)
    salidas = {}
    for eje in ("axial", "coronal", "sagital"):
        idx = (indices or {}).get(eje)
        if idx is None:
            idx = volumen.indice_mas_tumor(eje)
        rgb, info = volumen.render_corte(eje, idx, alto=alto)
        if con_pie:
            rgb = volumen.render_texto(
                rgb,
                f"{_nombre_eje(eje)}   |   Tumor   |   corte "
                f"{info['indice'] + 1}/{info['n_cortes']}",
                alto_total=alto)
        ruta = os.path.join(dir_salida, f"corte_{eje}.png")
        Image.fromarray(rgb, mode="RGB").save(ruta, format="PNG", optimize=True)
        salidas[eje] = ruta
    return salidas


def generar_vistas_2d(volumen_path, mascara_path, dir_salida,
                      escala=None, solo_ejes=None, alto=RESOLUCION_PNG,
                      indices=None):
    """Genera los cortes 2D con el tumor resaltado y los guarda como PNG.

    Args:
        volumen_path : NIfTI del volumen del paciente (misma rejilla que la
                        máscara).
        mascara_path : NIfTI de la máscara de tumor, alineada con el volumen.
        dir_salida   : directorio donde se guardan los PNG (se crea si falta).
        escala       : OBSOLETO y sin efecto. Se conserva para no romper las
                       llamadas antiguas: el re-muestreo bilineal del motor
                       comun ya hace ese papel.
        solo_ejes    : lista opcional de ejes {0,1,2} o {"axial", ...}.
        alto         : lado mayor del PNG en píxeles (1024 por defecto).
        indices      : {eje: corte} para fijar la rebanada de cada plano.

    Returns:
        dict: {eje: ruta_png} con las imágenes generadas.
    """
    del escala  # parámetro histórico: ya no aplica
    volumen = _resolver_entradas(volumen_path, mascara_path)
    ejes = _normalizar_ejes(solo_ejes)
    if len(ejes) == 3:
        return exportar_vistas(volumen, dir_salida, alto=alto, indices=indices)

    os.makedirs(dir_salida, exist_ok=True)
    from PIL import Image
    salidas = {}
    for eje in ejes:
        idx = (indices or {}).get(eje)
        if idx is None:
            idx = volumen.indice_mas_tumor(eje)
        rgb, info = volumen.render_corte(eje, idx, alto=alto)
        rgb = volumen.render_texto(
            rgb, f"{_nombre_eje(eje)}   |   Tumor   |   corte "
                 f"{info['indice'] + 1}/{info['n_cortes']}",
            alto_total=alto)
        ruta = os.path.join(dir_salida, f"corte_{eje}.png")
        Image.fromarray(rgb, mode="RGB").save(ruta, format="PNG", optimize=True)
        salidas[eje] = ruta
    return salidas


def exportar_mascara(volumen, ruta_mascara):
    """Guarda la máscara del `Volumen2D` en la rejilla del volumen.

    Es el puente entre el delineado manual del visor 2D y el pipeline: la malla
    3D que se genere después sale de este archivo.
    """
    return volumen.guardar_mascara(ruta_mascara, formato="NIfTI")


def _normalizar_slice(slice2d, lo=None, hi=None, gamma=0.85):
    """Compatibilidad: normaliza un corte con la ventana del volumen.

    Se conserva porque otras herramientas lo usan; delega en el mismo
    criterio (percentiles robustos sobre TEJIDO + gamma) que aplica el motor
    común, de modo que no haya dos criterios de contraste conviviendo.
    """
    arr = np.asarray(slice2d, dtype=np.float32)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    if lo is None or hi is None:
        no_cero = valid[np.abs(valid) > 1e-6]
        if no_cero.size >= 0.3 * valid.size and no_cero.size > 256:
            valid = no_cero
        lo, hi = np.percentile(valid, [0.5, 99.5])
    if hi - lo < 1e-6:
        hi = lo + 1e-6
    img = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    return (np.power(img, gamma) * 255.0).astype(np.uint8)


def _slice_mas_tumor(mask3d, eje):
    """Compatibilidad: (indice, area) del corte con más tumor en el eje dado."""
    e = eje if isinstance(eje, int) else EJES[eje]
    otros = tuple(i for i in (0, 1, 2) if i != e)
    area = (mask3d > 0).sum(axis=otros)
    if area.max() <= 0:
        return mask3d.shape[e] // 2, 0
    idx = int(np.argmax(area))
    return idx, int(area[idx])


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    salidas = os.path.join(os.path.dirname(base), "salidas",
                           "segmentaciones_ai")
    vol = os.path.join(salidas, "volumen_paciente.nii.gz")
    if not os.path.exists(vol):
        vol = os.path.join(os.path.dirname(base), "data", "nifti",
                           "MRBrainTumor1.nii.gz")
    masc = os.path.join(salidas, "tumor_brats.nii.gz")
    if not os.path.exists(vol) or not os.path.exists(masc):
        print(f"Volumen o máscara no disponibles ({vol} / {masc}).")
        sys.exit(1)
    print("Generadas:", generar_vistas_2d(
        vol, masc, os.path.join(salidas, "vistas_2d")))


def _resolver_entradas(volumen_path, mascara_path):
    """Carga el par volumen/mascara con el motor comun.

    Los errores de archivo se traducen aquí: `Volumen2D` lanza ValueError si
    las rejillas no cuadran, que es un problema de datos del caso y no un
    error de sintaxis del pipeline.
    """
    if not os.path.exists(volumen_path):
        raise FileNotFoundError(f"Volumen no encontrado: {volumen_path}")
    if not os.path.exists(mascara_path):
        raise FileNotFoundError(
            f"Máscara de tumor no encontrada: {mascara_path}")
    return Volumen2D(volumen_path, mascara_path)


def _nombre_eje(eje):
    """Texto legible del eje, venga como indice o como cadena."""
    if isinstance(eje, str):
        return eje.capitalize()
    return {0: "Axial", 1: "Coronal", 2: "Sagital"}[int(eje)]


def _normalizar_ejes(solo_ejes):
    """Convierte `solo_ejes` (0/1/2 o nombres) a la lista de tres ejes."""
    if not solo_ejes:
        return ["axial", "coronal", "sagital"]
    salida = []
    for e in solo_ejes:
        if isinstance(e, str):
            clave = e.strip().lower()
            if clave not in EJES:
                raise ValueError(f"Eje desconocido: {e!r}")
            salida.append(clave)
        else:
            salida.append(next(k for k, v in NOMBRES.items() if v == int(e)))
    return salida