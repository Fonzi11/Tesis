"""
Transformaciones de imagen IBSI (log, square, exponential, gradient, wavelet).

Las transformaciones se aplican al volumen COMPLETO dentro del bbox de la ROI
(con margen) y despues se leen los valores en los voxeles de la mascara, que es
lo que define el estandar IBSI. El recorte al bbox es una optimizacion: no
altera el valor de ningun voxel de la ROI, salvo en el borde, que IBSI marca
como no computable.
"""

import numpy as np

# =============================================================================
# TRANSFORMACIONES DE IMAGEN
# =============================================================================
def _gauss_recortado(volumen, mascara, sigma, truncate=3.0):
    """
    Filtro gaussiano 3D restringido al bbox de la ROI.

    Un sigma de 1.5 voxeles sobre el volumen entero de 256x256x112 cuesta mas
    que el propio calculo de los rasgos, asi que se recorta primero al
    sub-bloque que contiene la ROI mas un margen de 3 sigma.
    """
    from scipy.ndimage import gaussian_filter

    if sigma is None or sigma <= 0:
        return volumen
    idx = np.argwhere(mascara)
    if idx.size == 0:
        return volumen
    margen = int(np.ceil(sigma * truncate))
    lo = np.maximum(idx.min(0) - margen, 0)
    hi = np.minimum(idx.max(0) + margen + 1, np.array(mascara.shape))
    sl = (slice(lo[0], hi[0]), slice(lo[1], hi[1]), slice(lo[2], hi[2]))
    salida = np.array(volumen, dtype=np.float64, copy=True)
    salida[sl] = gaussian_filter(volumen[sl], sigma=sigma, truncate=truncate)
    return salida
def transformar(volumen, mascara, filtro, sigma=None):
    """
    Devuelve una copia de `volumen` con la transformacion IBSI indicada.

    Parametros
    ----------
    volumen : ndarray 3D float
    mascara : ndarray 3D bool
    filtro : str
        original | log_sigma | square | exponential | gradient
    sigma : float
        Sigma en voxeles para log_sigma.
    """
    v = np.asarray(volumen, dtype=np.float64)

    if filtro in ("original", None):
        return v
    if filtro == "square":
        return v ** 2
    if filtro == "exponential":
        return np.exp(v)
    if filtro == "gradient":
        return _magnitud_gradiente(v)
    if filtro == "log_sigma":
        s = sigma if sigma else 1.5
        return np.log(_gauss_recortado(v, mascara, s) + 1.0)
    return v


def _magnitud_gradiente(volumen):
    """
    Magnitud del gradiente: raiz de la suma de derivadas parciales al cuadrado.

    Es la imagen base de la familia `gradient` de IBSI; se calcula con el
    operador de Sobel, que es la aproximacion estandar cuando no se
    aprovecha la direccion de voxel.
    """
    from scipy.ndimage import sobel

    gz = sobel(volumen, axis=0, mode="nearest")
    gy = sobel(volumen, axis=1, mode="nearest")
    gx = sobel(volumen, axis=2, mode="nearest")
    return np.sqrt(gz ** 2 + gy ** 2 + gx ** 2)


def descomponer_wavelet(volumen, mascara, sigma=1.0, niveles=(2, 5)):
    """
    Descomposicion wavelet: highpass = original - lowpass.

    Devuelve {nombre: volumen} con los canales que PyRadiomics expone:
    `wavelet-highpass` (sigma·2), `wavelet-L2-highpass` (sigma·5) y el
    `wavelet-L2-lowpass` final. Solo se calculan texturas sobre los highpass;
    el lowpass es la imagen suavizada sobre la que ya se calcula `original`.
    """
    canales = {}
    actual = np.asarray(volumen, dtype=np.float64)
    for nivel in niveles:
        s = sigma * nivel
        lowpass = _gauss_recortado(actual, mascara, s)
        prefijo = "" if nivel == 2 else f"-L{nivel}"
        canales[f"wavelet{prefijo}-highpass"] = actual - lowpass
        if nivel == niveles[-1]:
            canales[f"wavelet{prefijo}-lowpass"] = lowpass
        actual = lowpass
    return canales


