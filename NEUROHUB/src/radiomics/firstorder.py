"""
Rasgos de primera orden (intensidad) según IBSI.

Se calculan sobre los valores de la ROI ya transformados por `filters`. Se
dividen en dos grupos:

  * estadisticos directos: media, varianza, percentiles...
  * rasgos de histograma discreto: entropia, uniformidad, percentiles, que
    dependen de la cuantizacion (binCount y esquema de escala) exactamente
    igual que en PyRadiomics.

Todos devuelven `float('nan')` en lugar de lanzar excepcion cuando la ROI es
degenerada (0 o 1 voxel), para que un fallo de un descriptor no tumbe el
calculo completo de la tabla.
"""

import numpy as np

EPS = 1e-12


# =============================================================================
# HELPERS
# =============================================================================
def _seguro(fn, *args, **kwargs):
    """Ejecuta `fn` y traduce cualquier error a NaN."""
    try:
        valor = fn(*args, **kwargs)
    except (ValueError, ZeroDivisionError, FloatingPointError, TypeError):
        return float("nan")
    if valor is None:
        return float("nan")
    valor = float(valor)
    return valor if np.isfinite(valor) else float("nan")


def _entropia(p, base=2):
    """Entropía de Shannon de una distribución, ignorando los ceros."""
    p = p[p > 0]
    if p.size == 0:
        return float("nan")
    total = p.sum()
    if total <= 0:
        return float("nan")
    p = p / total
    if base == 2:
        return float(-(p * np.log2(p)).sum())
    return float(-(p * np.log(p)).sum())


def cuantizar(valores, bin_count=32, valor_min=None, valor_max=None):
    """
    Cuantiza los valores a `bin_count` niveles dentro de [min, max].

    Es el esquema de PyRadiomics: la señal reescala a enteros en
    [1, binCount] y la etiqueta 0 se reserva para el fondo. Los valores fuera
    de rango se recortan a los extremos.
    """
    v = np.asarray(valores, dtype=np.float64)
    if v.size == 0:
        return np.zeros(0, dtype=np.uint32)
    lo = float(v.min()) if valor_min is None else float(valor_min)
    hi = float(v.max()) if valor_max is None else float(valor_max)
    if hi <= lo:
        return np.ones(v.size, dtype=np.uint32)
    escala = (bin_count - 1) / (hi - lo)
    q = np.floor((v - lo) * escala) + 1.0
    return np.clip(q, 1, bin_count).astype(np.uint32)


def _percentil(v, p):
    return float(np.percentile(v, p))



# =============================================================================
# RASGOS DE PRIMERA ORDEN
# =============================================================================
def calcular(valores, bin_count=32):
    """
    Calcula todos los rasgos de primera orden sobre `valores`.

    Parametros
    ----------
    valores : ndarray 1D float
        Intensidades de la ROI, ya transformadas.
    bin_count : int
        Nº de bins del histograma discreto (32 por defecto, como PyRadiomics).

    Devuelve
    -------
    dict {nombre_ibsI: float}. Un ROI vacia devuelve {}; cualquier error
    puntual produce NaN en ese descriptor en vez de tumbar la tabla entera.
    """
    v = np.asarray(valores, dtype=np.float64).ravel()
    if v.size == 0:
        return {}

    total = float(v.size)
    media = float(v.mean())
    varianza = float(v.var(ddof=0))              # poblacional, como IBSI
    desviacion = float(np.sqrt(varianza)) if varianza >= 0 else float("nan")
    minimo, maximo = float(v.min()), float(v.max())
    mediana = float(np.median(v))
    p10, p90, p99 = (_percentil(v, p) for p in (10, 90, 99))
    iqr = p90 - p10
    energia = v ** 2
    e_energia = float(energia.sum())

    # Sesgo y curtosis con normalización de Fisher (desviación de la unidad).
    if desviacion > 0:
        z = (v - media) / desviacion
        sesgo = float((z ** 3).mean())
        curtosis = float((z ** 4).mean()) - 3.0
    else:
        sesgo = curtosis = float("nan")

    # ---- Estadísticos directos --------------------------------------
    rasgos = {
        "Mean": media,
        "Median": mediana,
        "Minimum": minimo,
        "Maximum": maximo,
        "Range": maximo - minimo,
        "Variance": varianza,
        "StandardDeviation": desviacion,
        "Skewness": sesgo,
        "Kurtosis": curtosis,
        "Energy": e_energia,
        "InterquartileRange": iqr,
        "Percentile_1": _percentil(v, 1),
        "Percentile_10": p10,
        "Percentile_90": p90,
        "Percentile_99": p99,
        # Rango de atípicos: percentiles delimitados por 1.5·IQR, que es la
        # convención de PyRadiomics para una distribución normal.
        "UpperOutlierRange": _seguro(lambda: maximo - p90),
        "LowerOutlierRange": _seguro(lambda: p10 - minimo),
        "RootMeanSquared": _seguro(lambda: float(np.sqrt(energia.mean()))),
        "MeanAbsoluteDeviation": _seguro(lambda: float(np.abs(v - media).mean())),
        "RobustMeanAbsoluteDeviation": _seguro(
            lambda: float(np.abs(v - mediana).mean())),
        "RobustMeanAbsoluteDeviationMedian": _seguro(
            lambda: float(np.abs(v - mediana).mean() / mediana)
            if abs(mediana) > EPS else float("nan")),
        # ---- Descriptores del conjunto de energía (v²) ---------------
        "EnergyMean": e_energia / total,
        "EnergyMedian": mediana,
        "EnergyMinimum": float(energia.min()),
        "EnergyMaximum": float(energia.max()),
        "EnergyRange": float(energia.max() - energia.min()),
        "EnergySkewness": _sesgo_energia(energia),
        "EnergyKurtosis": _curtosis_energia(energia),
    }

    # ---- Señal logarítmica (IBSI usa log(x + 1)) --------------------
    vlog = np.log(v + 1.0)
    log_var = float(vlog.var(ddof=0))
    log_sd = float(np.sqrt(log_var)) if log_var >= 0 else float("nan")
    if log_sd > 0:
        z = (vlog - float(vlog.mean())) / log_sd
        log_sesgo = float((z ** 3).mean())
        log_curt = float((z ** 4).mean()) - 3.0
    else:
        log_sesgo = log_curt = float("nan")

    rasgos.update({
        "MeanLog": float(vlog.mean()),
        "VarianceLog": log_var,
        "RootMeanSquaredLog": _seguro(lambda: float(np.sqrt((vlog ** 2).mean()))),
        "EnergyLog2": _entropia(_hist(vlog)),
        "ExponentialEnergy": _seguro(lambda: float(np.exp(v).sum())),
        "ExponentialEnergyLog2": _entropia(_hist(np.exp(v))),
    })

    # ---- Histograma discreto (32 bins) -------------------------------
    conteo = np.bincount(cuantizar(v, bin_count), minlength=bin_count + 1)
    conteo = conteo[1:].astype(np.float64)       # la etiqueta 0 es el fondo
    prob = conteo / total
    uniformidad = float((prob ** 2).sum())
    entropia = _entropia(prob)

    rasgos.update({
        "Entropy": entropia,
        "EntropyLog2": entropia,
        "Uniformity": uniformidad,
        "UniformityNormalized": uniformidad,
        "EnergyEntropy": entropia,
        "EnergyEntropyLog2": entropia,
    })
    return rasgos


def _hist(valores, bins=32):
    """Histograma normalizado de `bins` cajas, para la entropía."""
    conteo, _ = np.histogram(valores, bins=bins)
    total = conteo.sum()
    return conteo / total if total > 0 else conteo.astype(np.float64)


def _sesgo_energia(energia):
    """Sesgo (tercer momento) del conjunto de energía ya calculado."""
    media = float(energia.mean())
    sd = float(energia.std())
    if sd <= 0:
        return float("nan")
    return float((((energia - media) / sd) ** 3).mean())


def _curtosis_energia(energia):
    """Curtosis (cuarto momento, normalizada) del conjunto de energía."""
    media = float(energia.mean())
    sd = float(energia.std())
    if sd <= 0:
        return float("nan")
    return float((((energia - media) / sd) ** 4).mean()) - 3.0
