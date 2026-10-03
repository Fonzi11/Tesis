"""
Orquestador de la extracción: imagen + ROI -> tabla de rasgos.

Es la pieza equivalente a `SimpleITK` / `FeatureExtractor` de PyRadiomics y a
`RadiomicsStudy` de Raidionics. Recibe un volumen y un mapa de etiquetas, y
devuelve un diccionario de rasgos con la nomenclatura IBSI.

El flujo, para cada ROI:

    1. Se recorta la imagen al bbox de la ROI (con margen) para no filtrar ni
       cuantizar un volumen entero por cada ROI.
    2. Se calculan los rasgos de FORMA (solo geometría, no dependen de la
       imagen).
    3. Para cada transformación IBSI (original, log_sigma, square,
       exponential, gradient, wavelet) se calculan los de PRIMERA ORDEN.
    4. Para cada imagen transformada se construyen las matrices de TEXTURA
       (GLCM, GLRLM, GLSZM, NGTDM) y se extraen sus descriptores.
    5. Se calculan los histogramas escalados (LSH / LSZM), que son la
       versión discretizada de los rasgos de primera orden.

Un fallo en un descriptor concreto produce NaN y no interrumpe la extracción:
un informe con un descriptor perdido es más útil que ningún informe.
"""

import os
import time

import numpy as np

from . import firstorder, shape as shape_mod, texture
from .features import (
    DESCRIPCIONES, FILTROS_IMAGEN, RASGOS_PRIMERA_ORDEN, RASGOS_TEXTURA,
)

# Las texturas son caras (GLSZM y NGTDM sobre todo). Este es el número de ROI
# a las que se les calculan TODAS las texturas; a partir de ahí, solo
# `original`. Es el mismo compromiso que hace PyRadiomics con `binCount` y que
# Raidionics con su modo "rápido", y evita que un atlas de 40 estructuras tarde
# horas.
MAX_ROIS_TEXTURA_COMPLETA = 8


class ExtractionConfig:
    """
    Parámetros de la extracción, con los valores por defecto de PyRadiomics.

    Los atributos se pueden cambiar antes de llamar a `extractor`; se comparan
    por valor para no recalcular una extracción idéntica.
    """

    def __init__(self, bin_count=32, bin_width=25, resegmentacion=False,
                 resegmentacion_sigma=None, enable_gaussian_sigma=None,
                 normalize=False, normalize_scale=100, normalize_zscore=False,
                 interpolador="linear", enable_rasgos=True,
                 calcular_textura=True, texturas_completas=True,
                 imagenes=["original"], solo_roi=None, verbose=False,
                 malla_slicer=False, slicer_suavizado=0.5,
                 limite_textura_completa=MAX_ROIS_TEXTURA_COMPLETA):
        self.bin_count = int(bin_count)
        self.bin_width = float(bin_width)
        self.resegmentacion = bool(resegmentacion)
        self.resegmentacion_sigma = resegmentacion_sigma
        self.enable_gaussian_sigma = enable_gaussian_sigma
        self.normalize = bool(normalize)
        self.normalize_scale = normalize_scale
        self.normalize_zscore = bool(normalize_zscore)
        self.interpolador = interpolador
        self.enable_rasgos = bool(enable_rasgos)
        self.calcular_textura = bool(calcular_textura)
        self.texturas_completas = bool(texturas_completas)
        # Imágenes sobre las que se extraen rasgos: nombres de FILTROS_IMAGEN
        # más los canales wavelet ("wavelet-highpass", "wavelet-L2-highpass").
        self.imagenes = list(imagenes)
        self.solo_roi = solo_roi
        # `malla_slicer` reconstruye la superficie con 3D Slicer (marching
        # cubes suavizado) en vez de la de skimage. La superficie condiciona
        # SurfaceArea, Sphericity y Compactness, asi que debe ser la misma que
        # se ve en el visor 3D del visor para que ambos coincidan.
        self.malla_slicer = bool(malla_slicer)
        self.slicer_suavizado = float(slicer_suavizado)
        # `None` = sin tope: todas las ROI reciben todas las texturas.
        self.limite_textura_completa = (
            None if limite_textura_completa is None
            else int(limite_textura_completa))
        self.verbose = bool(verbose)

    def clave(self):
        """
        Tupla de los campos que afectan al resultado.

        Es la clave de la caché de extracciones: si dos configuraciones
        producen la misma clave, sus resultados son idénticos y se puede
        reutilizar el ya calculado. Cualquier campo que cambie un descriptor
        tiene que estar aquí; si se olvida uno, la caché devolverá resultados
        de una configuración anterior sin avisar.
        """
        return (self.bin_count, self.bin_width, self.resegmentacion,
                self.normalize, self.normalize_scale, self.normalize_zscore,
                tuple(self.imagenes), self.calcular_textura,
                self.texturas_completas, tuple(sorted(self.solo_roi))
                if self.solo_roi else None,
                self.malla_slicer, self.slicer_suavizado,
                self.limite_textura_completa)

    def __repr__(self):
        return (f"ExtractionConfig(bins={self.bin_count}, "
                f"imagenes={self.imagenes}, texturas={self.calcular_textura})")


def _malla_de_slicer(roi, suavizado=0.5):
    """
    Reconstruye con 3D Slicer la superficie de una ROI y devuelve la malla.

    Devuelve (None, None) si Slicer no esta disponible o si falla la
    reconstruccion, de modo que la extraccion continua con la malla de
    skimage: perder la precision de superficie es preferible a perder todos
    los rasgos.
    """
    import tempfile

    try:
        from . import slicer_bridge
        if not slicer_bridge.disponible():
            return None, None
        with tempfile.TemporaryDirectory(prefix="neurohub_malla_") as tmp:
            nifti = os.path.join(tmp, "roi.nii.gz")
            stl = os.path.join(tmp, "roi.stl")
            _guardar_nifti(roi, nifti)
            slicer_bridge.reconstruir_stl(
                nifti, stl, suavizado=suavizado)
            return shape_mod.leer_stl(stl)
    except Exception:
        return None, None


def _guardar_nifti(roi, ruta):
    """Escribe una `MaskLabelMap` como NIfTI para consumirlo desde Slicer."""
    import SimpleITK as sitk

    mapa = roi.mascara().astype(np.uint8)
    img = sitk.GetImageFromArray(mapa)
    sx, sy, sz = roi.spacing
    img.SetSpacing((sx, sy, sz))
    img.SetOrigin(roi.origin)
    if roi.direction is not None:
        img.SetDirection(tuple(roi.direction))
    sitk.WriteImage(img, ruta, True)


# =============================================================================
# CARGA DE IMAGEN
# =============================================================================
def cargar_volumen(ruta):
    """
    Carga un NIfTI y devuelve (array_zyx, spacing, metadatos).

    El array es float64, que es lo que necesitan las transformaciones (log,
    exponential, square) sin riesgo de desbordamiento de enteros.
    """
    import SimpleITK as sitk

    if not ruta or not os.path.exists(ruta):
        raise FileNotFoundError(ruta)
    img = sitk.ReadImage(ruta)
    arr = sitk.GetArrayFromImage(img).astype(np.float64)
    meta = {
        "spacing": img.GetSpacing(),
        "origin": img.GetOrigin(),
        "direction": img.GetDirection(),
        "n_voxeles": int(arr.size),
        "tipo": img.GetPixelIDTypeAsString(),
    }
    return arr, meta["spacing"], meta


def normalizar_intensidad(volumen, escala=100, zscore=False):
    """
    Normaliza la imagen al rango 0..`escala` (PyRadiomics `normalize`).

    Sin esto, los rasgos de textura dependen de la escala de la RM: dos
    estudios del mismo tumor Acquisition dan valores distintos. Se usa
    min-max sobre los valores de la ROI, que es lo que hace PyRadiomics.
    """
    v = np.asarray(volumen, dtype=np.float64)
    if v.size == 0:
        return v
    lo, hi = float(v.min()), float(v.max())
    if hi <= lo:
        return np.zeros_like(v)
    salida = (v - lo) / (hi - lo) * float(escala)
    if zscore:
        mu, sd = float(salida.mean()), float(salida.std())
        if sd > 0:
            salida = (salida - mu) / sd
    return salida


# =============================================================================
# IMÁGENES IBSI
# =============================================================================
def _imagenes_ibsI(volumen, mascara, nombres):
    """
    Devuelve `{nombre: (prefijo, volumen)}` con las imágenes pedidas.

    Los nombres son los de `FILTROS_IMAGEN` más los canales wavelet. El
    prefijo es el que se antepone a los descriptores, de modo que los rasgos
    de `log_sigma_2` se llamen `log_sigma_2_Mean` y no se mezclen con los de la
    imagen original.
    """
    from . import filters

    salida = {}
    for nombre in nombres:
        if nombre == "original":
            salida[nombre] = ("original", volumen)
        elif nombre.startswith("log_sigma_"):
            sigma = float(nombre.rsplit("_", 1)[-1]) + 0.5
            salida[nombre] = (nombre, filters.transformar(
                volumen, mascara, "log_sigma", sigma))
        elif nombre == "square":
            salida[nombre] = ("square", filters.transformar(
                volumen, mascara, "square"))
        elif nombre == "exponential":
            salida[nombre] = ("exponential", filters.transformar(
                volumen, mascara, "exponential"))
        elif nombre == "gradient":
            salida[nombre] = ("gradient", filters.transformar(
                volumen, mascara, "gradient"))
        elif nombre == "wavelet":
            for clave, vol in filters.descomponer_wavelet(
                    volumen, mascara).items():
                if clave.endswith("highpass"):
                    salida[clave] = (clave, vol)
    return salida


def _recortar(volumen, mascara, margen=0):
    """
    Recorta al bbox de la máscara (con margen) y devuelve (sub_volumen,
    sub_mascara).

    Es una optimización grande: sin recortar, cada ROI pagaría un filtro
    gaussiano sobre el volumen entero de 256×256×112.
    """
    idx = np.argwhere(mascara)
    if idx.size == 0:
        return (np.zeros((0, 0, 0)),
                np.zeros((0, 0, 0), dtype=bool))
    lo = np.maximum(idx.min(0) - margen, 0)
    hi = np.minimum(idx.max(0) + margen + 1, np.array(mascara.shape))
    sl = (slice(lo[0], hi[0]), slice(lo[1], hi[1]), slice(lo[2], hi[2]))
    return volumen[sl], mascara[sl]



# =============================================================================
# EXTRACCIÓN
# =============================================================================
def extraer_radiomics(volumen, rois, config=None, progreso=None,
                      cancelado=None):
    """
    Calcula los rasgos de todas las ROI de un volumen.

    Parametros
    ----------
    volumen : ndarray 3D float
        La imagen, indexada [z, y, x].
    rois : dict {nombre: MaskLabelMap}
        ROI a caracterizar.
    config : ExtractionConfig o None
    progreso : callable o None
        Recibe (fracción 0..1, mensaje) para que la interfaz muestre avance.
    cancelado : callable o None
        Si devuelve True, se detiene la extracción y se devuelve lo parcial.

    Devuelve
    -------
    dict {nombre_roi: {nombre_rasgo: valor}}
    """
    cfg = config or ExtractionConfig()
    volumen = np.asarray(volumen, dtype=np.float64)
    if cfg.normalize:
        volumen = normalizar_intensidad(
            volumen, cfg.normalize_scale, cfg.normalize_zscore)

    nombres_roi = [n for n in rois
                   if (cfg.solo_roi is None or n in set(cfg.solo_roi))]
    if not nombres_roi:
        return {}

    # ROI a las que se calculan todas las texturas: las de más volumen, que
    # son las que el radiólogo mira. El resto lleva solo `original`, que es
    # lo que evita que un atlas de 40 estructuras agote la CPU.
    limite = cfg.limite_textura_completa
    if cfg.texturas_completas and limite is not None \
            and len(nombres_roi) > limite:
        relevantes = set(sorted(
            nombres_roi, key=lambda n: -rois[n].n_voxeles,
        )[:MAX_ROIS_TEXTURA_COMPLETA])
    else:
        relevantes = set(nombres_roi)

    resultados = {}
    total = len(nombres_roi)
    for i_roi, nombre in enumerate(nombres_roi):
        if cancelado is not None and cancelado():
            break

        roi = rois[nombre]
        if roi.n_voxeles == 0:
            continue

        mascaras = roi.mascara()
        sub_vol, sub_mascara = _recortar(volumen, mascaras, margen=4)
        if sub_mascara.sum() == 0:
            continue

        rasgos = {}

        # ---- 1. FORMA (solo depende de la geometría) ----------------
        if cfg.enable_rasgos:
            # La malla se calcula una sola vez por ROI: reconstruirla con
            # Slicer cuesta ~5 s por ROI, y aqui solo hace falta para los
            # rasgos que dependen de la superficie.
            malla = None
            if cfg.malla_slicer:
                malla = _malla_de_slicer(
                    rois[nombre], cfg.slicer_suavizado)
            for k, v in shape_mod.calcular(
                    sub_mascara, roi.spacing,
                    n_voxeles_total=sub_mascara.size,
                    malla=malla).items():
                rasgos[f"original_{k}"] = v

        # ---- 2..4. Imágenes transformadas ---------------------------
        nombres_img = (list(cfg.imagenes) if nombre in relevantes
                       else ["original"])
        # `_imagenes_ibsI` devuelve {nombre: (prefijo, imagen)}, así que cada
        # valor aporta el prefijo de columna y SU PROPIA imagen: hay que leer
        # los vóxeles de `imagen`, no de `sub_vol`, que es la original.
        for prefijo, imagen in _imagenes_ibsI(
                sub_vol, sub_mascara, nombres_img).values():
            valores = imagen[sub_mascara]

            # Primera orden
            for k, v in firstorder.calcular(valores, cfg.bin_count).items():
                rasgos[f"{prefijo}_{k}"] = v

            # Histograma escalado: la forma discretizada de la primera orden
            if prefijo == "original":
                for k, v in _rasgos_lsh(valores, cfg.bin_count).items():
                    rasgos[f"LSH_{k}"] = v

            # Texturas
            if cfg.calcular_textura and nombre in relevantes:
                _anadir_texturas(rasgos, imagen, sub_mascara, prefijo, cfg)

        resultados[nombre] = rasgos
        if progreso is not None:
            progreso((i_roi + 1) / total, f"Radiomics: {nombre}")

    return resultados



def _anadir_texturas(rasgos, imagen, mascara, prefijo, cfg):
    """Calcula GLCM/GLRLM/GLSZM/NGTDM y añade sus rasgos al diccionario."""
    valores = imagen[mascara]
    if valores.size == 0:
        return

    # La cuantización usa el rango de la ROI, como PyRadiomics: así un outlier
    # no comprime toda la distribución de la textura.
    minimo, maximo = float(valores.min()), float(valores.max())
    q = np.zeros(imagen.shape, dtype=np.uint32)
    q[mascara] = texture._cuantizar(valores, cfg.bin_count, minimo, maximo)
    n_vox = int(mascara.sum())

    g = texture.matriz_glcm(mascara, q, cfg.bin_count)
    for k, v in texture.rasgos_glcm(g).items():
        rasgos[f"{prefijo}_GLCM_{k}"] = v

    r = texture.matriz_glrlm(mascara, q, cfg.bin_count)
    for k, v in texture.rasgos_glrlm(r).items():
        rasgos[f"{prefijo}_GLRLM_{k}"] = v

    z = texture.matriz_glszm(mascara, q, cfg.bin_count)
    for k, v in texture.rasgos_glszm(z, n_vox).items():
        rasgos[f"{prefijo}_GLSZM_{k}"] = v

    t, n = texture.matriz_ngtdm(mascara, q, cfg.bin_count)
    for k, v in texture.rasgos_ngtdm(
            t, n, mascara, cfg.bin_count, n_vox).items():
        rasgos[f"{prefijo}_NGTDM_{k}"] = v


def _rasgos_lsh(valores, bin_count):
    """Histograma escalado de niveles (LSH), la forma discretizada de FO."""
    from . import firstorder as fo

    q = fo.cuantizar(valores, bin_count)
    conteo = np.bincount(q, minlength=bin_count + 1)[1:].astype(np.float64)
    total = conteo.sum()
    if total <= 0:
        return {}
    prob = conteo / total
    niveles = np.arange(1, bin_count + 1, dtype=np.float64)
    media = float((prob * niveles).sum())
    var = float((prob * (niveles - media) ** 2).sum())

    return {
        "HistogramIntensity": float((conteo * niveles).sum() / total),
        "HistogramIntensityNormalized": media,
        "HistogramIntensityLog2": fo._entropia(prob),
        "Percentile_1": float(np.percentile(valores, 1)),
        "Percentile_10": float(np.percentile(valores, 10)),
        "Percentile_90": float(np.percentile(valores, 90)),
        "Percentile_99": float(np.percentile(valores, 99)),
        "InterquartileRange": (float(np.percentile(valores, 90))
                               - float(np.percentile(valores, 10))),
        "Median": float(np.median(valores)),
        "Variance": var,
        "VarianceLog": float(np.log(valores + 1.0).var()),
        "Skewness": fo._sesgo_energia(valores ** 2 / 2.0),
        "Kurtosis": fo._curtosis_energia(valores ** 2 / 2.0),
        "Range": float(valores.max() - valores.min()),
        "RootMeanSquared": float(np.sqrt((valores ** 2).mean())),
        "RootMeanSquaredLog": float(
            np.sqrt((np.log(valores + 1.0) ** 2).mean())),
        "MeanLog": float(np.log(valores + 1.0).mean()),
        "Energy": float((valores ** 2).sum()),
        "EnergyLog2": fo._entropia(np.log(valores ** 2 + 1.0)),
        "Entropy": fo._entropia(prob),
        "EntropyLog2": fo._entropia(prob),
        "Minimum": float(valores.min()),
        "Maximum": float(valores.max()),
    }


def extractor(rutas,rois, config=None, progreso=None, cancelado=None):
    """
    Atajo de una llamada: carga un NIfTI y extrae los rasgos de las ROI.

    `rutas` puede ser un NIfTI de imagen o un dict `{nombre_roi: ruta_nifti}`
    de ROI ya en disco, que es como las deja el pipeline.
    """
    if isinstance(rutas, dict):
        rois_cargadas = {k: v for k, v in rois.items()}
    else:
        from .masks import de_nifti
        imagen, _spacing, _meta = cargar_volumen(rutas)
        rois_cargadas = rois
    return extraer_radiomics(imagen, rois_cargadas, config, progreso,
                            cancelado)

    return salida
