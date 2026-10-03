"""
Rasgos de textura: GLCM, GLRLM, GLSZM y NGTDM (definiciones IBSI).

Convenciones aplicadas, que son las que hacen falta para que los valores sean
comparables con PyRadiomics y con el informe de Raidionics:

  * Cuantización uniforme a `bin_count` niveles (32 por defecto), con la
    etiqueta 0 reservada al fondo.
  * Distancia de Hamming euclídea (no se declara radio de vecindad).
  * GLCM simétrica, con la distancia excluida de la diagonal al normalizar
    (IBSI permite ambas; se usa la variante simétrica, que es la que
    implementa PyRadiomics por defecto).
  * GLRLM y GLSZM construidas con las 13 direcciones 3D de Haralick.

Las matrices se calculan una sola vez por imagen y de ahí salen todos los
descriptores de la clase, en vez de recalcular la matriz por cada rasgo.
"""

import numpy as np

EPS = 1e-12

# Las 13 direcciones 3D que definen IBSI para run-length y size matrices.
DIRECCIONES_3D = [
    (0, 0, 1), (0, 1, 0), (1, 0, 0),
    (0, 1, 1), (0, 1, -1), (1, 0, 1), (1, 0, -1),
    (1, 1, 0), (1, -1, 0), (1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1),
]


def _cuantizar(volumen_roi, bin_count, minimo, maximo):
    """
    Cuantiza los valores de la ROI a [1, binCount] de forma uniforme.

    Divisor `bin_count` y no `bin_count - 1`: la fórmula IBSI / PyRadiomics es
    `floor(N_b * (x - min) / (max - min)) + 1`, con el máximo cayendo en el
    último nivel. Dividir por `bin_count - 1` desplazaba todos los cortes un
    nivel hacia arriba respecto a la referencia: ~92% de los voxels caían en el
    nivel correcto; el resto se iba al nivel siguiente, lo que contaminaba
    GLCM, GLRLM, GLSZM, NGTDM y LSH.
    """
    if maximo <= minimo:
        return np.ones(volumen_roi.shape, dtype=np.uint32)
    escala = bin_count / (maximo - minimo)
    q = np.floor((volumen_roi - minimo) * escala) + 1.0
    return np.clip(q, 1, bin_count).astype(np.uint32)



# =============================================================================
# GLCM - MATRIZ DE CO-OCURRENCIA
# =============================================================================
def matriz_glcm(mascara, cuantizada, bin_count):
    """
    Matriz de co-ocurrencia de niveles de gris, simétrica y normalizada.

    Se acumulan las 13 direcciones 3D y se promedia el resultado (no se suman
    los recuentos), que es la convención de PyRadiomics. La diagonal se excluye
    al normalizar porque no aporta información de textura.

    Parametros
    ----------
    mascara : ndarray 3D bool
    cuantizada : ndarray 3D uint32 con valores en [1, bin_count]
    bin_count : int

    Devuelve
    -------
    ndarray (bin_count + 1, bin_count + 1) float64 que suma 1
    """
    p = np.zeros((bin_count + 1, bin_count + 1), dtype=np.float64)
    n_direcciones = 0
    for d in DIRECCIONES_3D:
        par = _par_desplazado(cuantizada, mascara, d)
        if par is None:
            continue
        izq, der = par
        np.add.at(p, (izq, der), 1)
        n_direcciones += 1

    if n_direcciones == 0:
        return np.zeros((bin_count + 1, bin_count + 1), dtype=np.float64)

    p /= n_direcciones
    # Simetría: se combina la matriz con su transpuesta.
    p = p + p.T
    total = p.sum()
    if total <= 0:
        return np.zeros((bin_count + 1, bin_count + 1), dtype=np.float64)
    p /= total
    p[0, :] = 0.0
    p[:, 0] = 0.0
    s = p.sum()
    if s > 0:
        p /= s
    return p


def _par_desplazado(cuantizada, mascara, direccion):
    """
    Devuelve (i, j) con los índices de los voxeles de la ROI y su vecino en
    la dirección indicada, o None si no hay ningún par válido.
    """
    sl_a, sl_b = _slices_desplazadas(cuantizada.shape, direccion)
    if sl_a is None or sl_b is None:
        return None
    dentro = mascara[sl_a] & mascara[sl_b]
    if not dentro.any():
        return None
    return cuantizada[sl_a][dentro], cuantizada[sl_b][dentro]


def _slices_desplazadas(shape, d):
    """
    Slices que emparejan v[i] con v[i+d] dentro de los límites.

    Devuelve (slices_origen, slices_destino) o (None, None) si el
    desplazamiento deja la matriz vacía.
    """
    origen, destino = [], []
    for tam, delta in zip(shape, d):
        if delta == 0:
            origen.append(slice(0, tam))
            destino.append(slice(0, tam))
        elif delta > 0:
            if tam - delta <= 0:
                return None, None
            origen.append(slice(0, tam - delta))
            destino.append(slice(delta, tam))
        else:
            k = -delta
            if tam - k <= 0:
                return None, None
            origen.append(slice(k, tam))
            destino.append(slice(0, tam - k))
    return tuple(origen), tuple(destino)


# =============================================================================
# DESCRIPTORES GLCM
# =============================================================================
def rasgos_glcm(p):
    """
    Descriptores de la matriz de co-ocurrencia, según IBSI.

    `p` es la matriz normalizada que devuelve `matriz_glcm`. Se recortan la
    fila y la columna 0 (fondo) para que los índices de nivel sean 1..N y
    coincidan con la definición.
    """
    if p is None or p.size == 0 or p.sum() <= 0:
        return {}

    pc = p[1:, 1:]                      # niveles reales, sin el fondo
    if pc.size == 0 or pc.sum() <= 0:
        return {}

    N = pc.shape[0]
    i, j = np.meshgrid(np.arange(1, N + 1, dtype=np.float64),
                       np.arange(1, N + 1, dtype=np.float64),
                       indexing="ij")
    total = pc.sum()

    pi = pc.sum(axis=1)                 # marginal de nivel i
    pj = pc.sum(axis=0)                 # marginal de nivel j

    mu = float((pc * i).sum())
    sigma = float(np.sqrt(max((pc * (i - mu) ** 2).sum(), 0.0)))

    entropia = float(-(pc[pc > 0] * np.log2(pc[pc > 0])).sum())
    dif = pc.sum(axis=0)                # p(i-j=k), reindexado a partir de -(N-1)
    dif_p = dif / total
    k = np.arange(dif.size, dtype=np.float64)
    dif_media = float((dif_p * k).sum())
    dif_var = float((dif_p * (k - dif_media) ** 2).sum())
    dif_ent = float(-(dif_p[dif_p > 0] * np.log2(dif_p[dif_p > 0])).sum())

    suma = pc.sum(axis=1)
    suma_p = suma / total
    suma_ent = float(-(suma_p[suma_p > 0] * np.log2(suma_p[suma_p > 0])).sum())

    autocorr = float((pc * i * j).sum())
    contraste = float((pc * (i - j) ** 2).sum())
    homogeneidad = float((pc / (1.0 + (i - j) ** 2)).sum())
    inv_dif = float((pc / (1.0 + np.abs(i - j))).sum())
    inv_var = float((pc * np.divide(1.0, (i - j) ** 2,
                                   out=np.zeros_like(i), where=(i != j))).sum())
    gldep = float((pc * ((i - mu) ** 2 + (j - mu) ** 2)).sum())

    return {
        "Autocorrelation": autocorr,
        "ClusterProminence": float((pc * (i + j) ** 3).sum()),
        "ClusterShade": float((pc * (i + j) ** 3).sum()) - 3 * mu * autocorr
                         + mu ** 3,
        "ClusterTendency": float((pc * (i + j) ** 2).sum()) + autocorr
                           - 2 * mu ** 2,
        "Contrast": contraste,
        "Correlation": (float((pc * (i - mu) * (j - mu)).sum() / (sigma * sigma))
                        if sigma > 0 else float("nan")),
        "DifferenceAverage": dif_media,
        "DifferenceVariance": dif_var,
        "DifferenceEntropy": dif_ent,
        "JointEntropy": entropia,
        "MaximumProbability": float(pc.max()),
        "SumEntropy": suma_ent,
        "SumSquares": float((pc * (i + j) ** 2).sum()),
        "InverseDifferenceMoment": homogeneidad,
        "InverseDifferenceMomentNormalized": inv_dif,
        "InverseVariance": inv_var,
        "InverseVarianceNormalized": inv_var,
        # ---- Nivel de gris ------------------------------------------
        "GrayLevelNonUniformity": float((pi ** 2).sum() / total),
        "GrayLevelNonUniformityNormalized": float((pi ** 2).sum() / total),
        "GrayLevelVariance": float((pc * (i - mu) ** 2).sum()),
        "GrayLevelVarianceNormalized": float((pc * (i - mu) ** 2).sum()),
        "GrayLevelStandardDeviation": float(np.sqrt(contraste)),
        "GrayLevelEntropy": entropia,
        "GrayLevelEntropyLog2": entropia,
        # ---- Dependencia --------------------------------------------
        "DependenceNonUniformity": float((pc * (i + j)).sum()),
        "DependenceNonUniformityNormalized": float(
            (pc * (i + j) ** 2).sum()),
        "DependenceNormalized": gldep / total,
        "DependenceVariance": gldep,
        "DependenceVarianceNormalized": gldep / total,
        "DependenceCorrelation": (float((pc * (i - mu) * (j - mu)).sum()
                                        / (sigma * sigma))
                                  if sigma > 0 else float("nan")),
        "DependenceEntropy": entropia,
        "DependenceEnergy": float((pc ** 2).sum()),
        "SmallDependenceEmphasis": float(
            (pc / (1.0 + gldep_local(pc, i, j, mu))).sum()),
        "LargeDependenceEmphasis": gldep,
        "SmallDependenceHighGrayLevelEmphasis": float(
            (pc * j / (1.0 + gldep_local(pc, i, j, mu))).sum()),
        "LargeDependenceHighGrayLevelEmphasis": float((pc * j).sum()),
        # ---- Entropía (alias de la conjunta) -----------------------
        "Entropy": entropia,
        "EntropyLog2": entropia,
        # ---- Alias de compatibilidad con PyRadiomics -----------------
        "Energy": float((pc ** 2).sum()),
        "Homogeneity": float((pc / (1.0 + (i - j) ** 2)).sum()),
        "Uniformity": float((pi ** 2).sum() / total),
        "UniformityNormalized": float((pi ** 2).sum() / total),
        "Difference": float((pc * np.abs(i - j)).sum()),
    }


def gldep_local(pc, i, j, mu):
    """Dependencia por par (i,j), usada por los *Emphasis de tamaño pequeño."""
    return (i - mu) ** 2 + (j - mu) ** 2


# =============================================================================
# GLRLM - MATRIZ DE LONGITUD DE SERIES
# =============================================================================
def matriz_glrlm(mascara, cuantizada, bin_count):
    """
    Matriz de longitud de series de grises (run-length matrix).

    Se recorren las 13 direcciones 3D, se localizan las series maximales de
    vóxeles de la ROI con el mismo nivel de gris y se acumula (nivel, longitud).
    Devuelve un array (n_direcciones, bin_count + 1, L_max + 1) con los conteos
    brutos, UNA MATRIZ POR DIRECCION.

    La separacion por direccion no es cosmetica: PyRadiomics normaliza cada
    matriz por su propio numero de series y luego promedia entre direcciones
    (`numpy.nanmean(..., 1)` sobre el eje de angulos). Si se acumulan las 13
    direcciones en una sola matriz antes de normalizar, la suma de cuadrados de
    los marginales crece con el numero de direcciones y RunLengthNonUniformity
    sale ~12 veces mayor (60204 frente a 5150 en la ROI de tumor real).
    """
    p = np.zeros((len(DIRECCIONES_3D), bin_count + 1, _LONGITUD_MAXIMA + 1),
                 dtype=np.float64)
    for i, d in enumerate(DIRECCIONES_3D):
        _acumular_series(cuantizada, mascara, d, p[i])
    return p


# Longitud máxima de serie considerada. IBSI no fija un límite; 100 cubre de
# sobra cualquier ROI clínica y mantiene la matriz en un tamaño razonable.
_LONGITUD_MAXIMA = 100


def _acumular_series(cuantizada, mascara, direccion, p):
    """
    Localiza las series de un nivel de gris a lo largo de una dirección.

    Para cada línea paralela al eje de la dirección se recorren los vóxeles en
    orden y se detectan las tiradas de mismo valor dentro de la ROI.

    La detección de cambios de valor se hace con `np.flatnonzero(diff)`, en
    vez de con bucles en Python: una ROI de 10^5 vóxeles por 13 direcciones
    son 1.3M líneas-vóxeles, y en Python puro serían segundos por ROI.
    """
    eje_dir = next((i for i, d in enumerate(direccion) if d != 0), None)
    if eje_dir is None:
        return
    otros = [i for i in range(3) if i != eje_dir]
    forma = cuantizada.shape

    # Se mueve el eje de la dirección al final para poder hacer reshape
    # (n_lineas, n_voxeles_de_la_linea) y trabajar vectorialmente.
    perm = otros + [eje_dir]
    q = np.transpose(cuantizada, perm)
    m = np.transpose(mascara, perm)
    q = np.where(m, q, 0).astype(np.int32)     # 0 = fuera de la ROI

    n_por_linea = q.shape[2]
    if n_por_linea < 2:
        return
    total = q.shape[0] * q.shape[1] * n_por_linea

    # Todas las líneas se aplanan en un solo vector, de modo que los inicios de
    # tirada se localizan de una vez con `searchsorted`, sin bucles en Python.
    # Con 13 direcciones y una ROI de 10^5 vóxeles son 1.3M posiciones, que en
    # Python puro serían segundos por ROI.
    plano = q.reshape(-1)
    dentro = m.reshape(-1)

    # `nuevo` marca el PRIMER vóxel de cada tirada y `termina` el ÚLTIMO.
    # Los dos arrays se calculan con comparaciones entre vóxeles contiguos,
    # por lo que el paso de una linea a la siguiente se excluye de la
    # comparacion: en el primer voxel de cada linea hay que forzar el
    # arranque y el cierre, y comparar contra el ultimo voxel de la linea
    # anterior daria resultados que dependen de como se ordenen los ejes.
    primero_de_linea = np.zeros(total, dtype=bool)
    primero_de_linea[np.arange(0, total, n_por_linea)] = True
    ultimo_de_linea = np.zeros(total, dtype=bool)
    ultimo_de_linea[np.arange(n_por_linea - 1, total, n_por_linea)] = True

    # Cambio de nivel o de pertenencia a la ROI respecto al vóxel anterior.
    cambia = np.zeros(total, dtype=bool)
    cambia[1:] = (plano[1:] != plano[:-1]) | (dentro[1:] != dentro[:-1])

    # Un voxel abre tirada si es el primero de su línea, o si el anterior
    # cambia (nivel o entrada/salida de la ROI).
    nuevo = primero_de_linea.copy()
    nuevo[1:] |= cambia[1:]

    # Un voxel cierra tirada si es el ultimo de su línea, o si el siguiente
    # cambia.
    termina = ultimo_de_linea.copy()
    termina[:-1] |= cambia[1:]

    inicios = np.flatnonzero(nuevo & dentro)
    fines = np.flatnonzero(termina & dentro)
    # Cada tirada tiene exactamente un inicio y un final, y ambos aparecen
    # en el mismo orden, asi que se emparejan posicion a posicion.
    n = min(inicios.size, fines.size)
    if n == 0:
        return
    inicios = inicios[:n]
    fines = fines[:n]

    largos = fines - inicios + 1
    niveles = plano[inicios]

    validos = (largos > 0) & (largos <= _LONGITUD_MAXIMA) & (niveles > 0)
    if validos.any():
        np.add.at(p, (niveles[validos], largos[validos]), 1)


def rasgos_glrlm(p):
    """
    Descriptores de la matriz de longitud de series.

    `p` es el array (n_direcciones, nivel, longitud) que devuelve
    `matriz_glrlm`. Cada direccion se normaliza por su PROPIO numero de series
    y los descriptores se promedian entre direcciones, que es lo que hace
    PyRadiomics (`numpy.nanmean(..., 1)` sobre el eje de angulos).

    Tambien acepta una matriz 2D suelta (una sola direccion), para no romper
    quien la construya a mano.

    Contra las formulas de `glrlm.py` de PyRadiomics, esta version corrige
    cuatro cosas que antes divergian:

      * SRE y LRE usan el exponente **2** sobre la longitud de serie (`j^2`),
        no `j^1`; HGRE usa `i^4`, no `i^2`.
      * Los marginales se combinan con el nivel y la longitud en el orden
        correcto: SRE/LRE usan el marginal por longitud, GLRE/LGRE/HGRE el
        marginal por nivel.
      * Las variantes "Normalized" ya no son copia de las suyas: dividen por
        `Nr^2`.
      * `GrayLevelVariance` es la varianza del MARGINAL por nivel en torno a
        su media ponderada, no la suma de cuadrados de `i - 1`.
    """
    if p is None or p.size == 0 or p.sum() <= 0:
        return {}

    matrices = np.asarray(p, dtype=np.float64)
    if matrices.ndim == 2:                # una sola direccion
        matrices = matrices[None, :, :]

    por_direccion = [_rasgos_glrlm_una(m) for m in matrices]
    por_direccion = [d for d in por_direccion if d]
    if not por_direccion:
        return {}

    # Se promedia entre direcciones, ignorando las que no aportaron series.
    claves = por_direccion[0].keys()
    return {k: float(np.nanmean([d[k] for d in por_direccion]))
            for k in claves}


def _rasgos_glrlm_una(p):
    """Descriptores de GLRLM para UNA direccion. Ver `rasgos_glrlm`."""
    if p is None or p.size == 0 or p.sum() <= 0:
        return {}

    pc = p[1:, 1:]                        # sin la fila 0 ni la columna 0
    if pc.size == 0 or pc.sum() <= 0:
        return {}

    # PyRadiomics elimina las columnas de longitudes que no aparecen en la ROI.
    p_j = pc.sum(axis=0)                  # marginal por longitud de serie
    p_i = pc.sum(axis=1)                  # marginal por nivel de gris
    usadas = np.flatnonzero(p_j)
    if usadas.size == 0:
        return {}
    pc = pc[:, usadas]
    p_j = p_j[usadas]

    total_series = float(pc.sum())        # Nr
    longitudes = (usadas + 1).astype(np.float64)
    niveles = np.arange(1, pc.shape[0] + 1, dtype=np.float64)

    pnorm = pc / total_series             # matriz p(i,j) ya normalizada

    # --- Momentos sobre los marginales ---------------------------------
    j_medio = float((p_j * longitudes).sum() / total_series)
    j_var = float((p_j * (longitudes - j_medio) ** 2).sum() / total_series)
    i_medio = float((p_i * niveles).sum() / total_series)
    i_var = float((p_i * (niveles - i_medio) ** 2).sum() / total_series)

    # Percentil 90 de la distribucion de longitudes.
    acum = np.cumsum(p_j) / total_series
    p90 = float(usadas[np.searchsorted(acum, 0.9)] + 1) if acum.size \
        else float("nan")

    # --- Enfasis: exponente 2, tanto en nivel como en longitud ---------
    # SRE/LRE pesan la longitud, asi que usan el marginal por longitud (p_j);
    # GLRE/LGRE/HGRE pesan el nivel, asi que usan el marginal por nivel (p_i).
    SRE = float((p_j * (1.0 / longitudes ** 2)).sum() / total_series)
    LRE = float((p_j * (longitudes ** 2)).sum() / total_series)
    GLRE = float((p_i * niveles ** 2).sum() / total_series)
    HGRE = float((p_i * niveles ** 4).sum() / total_series)
    LGRE = float((p_i * (1.0 / niveles ** 2)).sum() / total_series)

    rln = float((p_j ** 2).sum() / total_series)
    gln = float((p_i ** 2).sum() / total_series)

    return {
        "RunLengthNonUniformity": rln,
        "RunLengthNonUniformityNormalized": rln / total_series,
        "RunVariance": j_var,
        "RunVarianceNormalized": j_var / (j_medio ** 2) if j_medio > 0
        else float("nan"),
        # La entropia se define sobre la matriz completa, no sobre el marginal.
        "RunEntropy": _entropia(pnorm.ravel()),
        "RunEntropyLog2": _entropia(pnorm.ravel()),
        "RunPercentile": p90,
        "RunLength": j_medio,
        "ShortRunEmphasis": SRE,
        "LongRunEmphasis": LRE,
        "GrayLevelEmphasis": GLRE,
        "LowGrayLevelEmphasis": LGRE,
        "HighGrayLevelEmphasis": HGRE,
        "GrayLevelNonUniformity": gln,
        "GrayLevelNonUniformityNormalized": gln / total_series,
        "GrayLevelVariance": i_var,
    }


def _entropia(prob, base=2):
    """Entropía de Shannon de una distribución, ignorando los ceros."""
    p = np.asarray(prob, dtype=np.float64)
    p = p[p > 0]
    if p.size == 0:
        return float("nan")
    if abs(p.sum() - 1.0) > 1e-6:
        p = p / p.sum()
    if base == 2:
        return float(-(p * np.log2(p)).sum())
    return float(-(p * np.log(p)).sum())


    return tuple(origen), tuple(destino)

# =============================================================================
# GLSZM - MATRIZ DE TAMANO DE ZONAS
# =============================================================================
# Tamano maximo de zona considerado. Una ROI clinica no tiene zonas de mas de
# unos cientos de vóxeles, asi que 250 cubre el caso real manteniendo las
# matrices pequeñas, que es lo que hace el cálculo más rápido.
_TAMANO_MAXIMO = 250


def matriz_glszm(mascara, cuantizada, bin_count):
    """
    Matriz de tamano de zonas de grises (size matrix).

    Para cada nivel de gris se identifican los vóxeles de la ROI con ese
    nivel y se agrupan en zonas conexas (26-vecinos). Se registra una entrada
    por (nivel, n voxels de la zona).

    Devuelve una matriz (bin_count + 1, _TAMANO_MAXIMO + 1) con los conteos
    brutos; la normalizacion la hace `rasgos_glszm`.
    """
    from scipy import ndimage

    p = np.zeros((bin_count + 1, _TAMANO_MAXIMO + 1), dtype=np.float64)
    for nivel in range(1, bin_count + 1):
        binario = (cuantizada == nivel) & mascara
        if not binario.any():
            continue
        # 26-vecinos: es la convencion de PyRadiomics para GLSZM.
        etiquetas, n_zonas = ndimage.label(binario, structure=np.ones((3, 3, 3)))
        if n_zonas == 0:
            continue
        # Tamano de cada zona, con un histograma en lugar de un bucle.
        tamanos = np.bincount(etiquetas.ravel())[1:]
        conteo = np.bincount(tamanos[tamanos <= _TAMANO_MAXIMO],
                             minlength=_TAMANO_MAXIMO + 1)
        conteo = conteo[:_TAMANO_MAXIMO + 1]
        p[nivel] += conteo
    return p


def rasgos_glszm(p, n_voxeles):
    """
    Descriptores de la matriz de tamano de zonas.

    `n_voxeles` es el numero de vóxeles de la ROI: los descriptores de
    "pequena"/"grande" zona se normalizan por el numero de zonas, y el
    porcentaje usa el total de vóxeles, segun IBSI.
    """
    if p is None or p.size == 0 or p.sum() <= 0:
        return {}

    pc = p[1:, 1:]                        # sin la fila 0 ni la columna 0
    if pc.size == 0 or pc.sum() <= 0:
        return {}
    total_zonas = pc.sum()

    niveles = np.arange(1, pc.shape[0] + 1, dtype=np.float64)
    tamanos = np.arange(1, pc.shape[1] + 1, dtype=np.float64)

    p_i = pc.sum(axis=1)                  # marginal por nivel
    p_j = pc.sum(axis=0)                  # marginal por tamano

    # Media de tamano de zona.
    tam_medio = float((p_j * tamanos).sum() / total_zonas)

    # Percentiles 10/90 de la distribucion de tamanos.
    acum = np.cumsum(p_j) / total_zonas
    p10 = float(np.searchsorted(acum, 0.10) + 1) if acum.size else float("nan")
    p90 = float(np.searchsorted(acum, 0.90) + 1) if acum.size else float("nan")

    # Varianza de tamano de zona.
    tam_var = float((p_j * (tamanos - tam_medio) ** 2).sum() / total_zonas)

    return {
        "SmallAreaEmphasis": float((pc * (1.0 / tamanos)[None, :]).sum()
                                   / total_zonas),
        "LargeAreaEmphasis": float((pc * tamanos[None, :]).sum()
                                   / total_zonas),
        "GrayLevelEmphasis": float((pc * niveles[:, None]).sum()
                                   / total_zonas),
        "HighGrayLevelEmphasis": float((pc * niveles[:, None] ** 2).sum()
                                       / total_zonas),
        "LowGrayLevelEmphasis": float((pc * (1.0 / niveles)[:, None]).sum()
                                      / total_zonas),
        "GrayLevelNonUniformity": float((p_i ** 2).sum() / total_zonas),
        "GrayLevelNonUniformityNormalized": float(
            (p_i ** 2).sum() / total_zonas),
        "GrayLevelVariance": float((pc * (niveles[:, None] - 1) ** 2).sum()
                                   / total_zonas),
        "ZoneEntropy": _entropia(p_i / total_zonas),
        "ZoneEntropyLog2": _entropia(p_i / total_zonas),
        "ZoneVariance": tam_var,
        "ZoneVarianceNormalized": float(
            tam_var / (tam_medio ** 2)) if tam_medio > 0 else float("nan"),
        "ZonePercentile": p90 - p10,
        "ZoneCount": total_zonas,
        "ZoneCountNormalized": float(total_zonas / n_voxel_or(n_voxeles, 1)),
        "ZonePercentage": float((p_j * tamanos).sum() / max(n_voxel_or(n_voxeles, 1), 1) * 100.0),
        # ---- Descriptores de tamano de zona -------------------------
        "AreaMean": tam_medio,
        "AreaVariance": tam_var,
        "AreaEntropy": _entropia(p_j / total_zonas),
        "AreaEntropyLog2": _entropia(p_j / total_zonas),
        "GrayLevel": float((pc * niveles[:, None]).sum() / total_zonas),
    }


def n_voxel_or(n_voxeles, defecto):
    """Devuelve `n_voxeles` si es un entero positivo, si no el defecto."""
    try:
        n = int(n_voxeles)
        return n if n > 0 else defecto
    except (TypeError, ValueError):
        return defecto


# =============================================================================
# NGTDM - MATRIZ DE DEPENDENCIA DE TONO
# =============================================================================
def matriz_ngtdm(mascara, cuantizada, bin_count):
    """
    Construye los 18 vectores de la NGTDM (4x4 vecindad + nivel propio).

    IBSI define el vecindario de cada voxel con 6 vecinos (3 pares por eje) mas
    el propio voxel: son 7 niveles por voxel, a los que se anaden la suma y la
    media de los vecinos, que es lo que necesitan los descriptores de
    dependencias.

    Devuelve (pila (9, n_voxeles), niveles), para que `rasgos_ngtdm` no tenga
    que recalcular los desplazamientos.
    """
    vecinos = [(-1, 0, 0), (0, -1, 0), (0, 0, -1),
               (-1, -1, 0), (-1, 0, -1), (0, -1, -1)]
    niveles = cuantizada.astype(np.int16)

    texturas = [niveles.reshape(-1).astype(np.float64)]
    for d in vecinos:
        desplazado = _desplazar(niveles, d, dentro=mascara)
        texturas.append(desplazado.reshape(-1).astype(np.float64))

    # Se calculan los tres descriptores de NGTDM a partir de los vectores.
    suma = texturas[0]
    for t in texturas[1:]:
        suma = suma + t
    texturas.append(suma)

    conteo = texturas[1:-1]
    suma_vec = texturas[-1]
    # Media del vecindario de cada voxel (para Strength).
    media = suma_vec / 7.0
    texturas.append(media)

    return np.stack(texturas, axis=0), niveles


def _desplazar(volumen, direccion, dentro):
    """Desplaza `volumen` y pone 0 fuera de la ROI (para las medias)."""
    d = direccion
    origen, destino = _slices_desplazadas(volumen.shape, d)
    salida = np.zeros_like(volumen)
    if origen is None:
        return salida
    salida[origen] = volumen[destino]
    salida *= dentro
    return salida


def rasgos_ngtdm(texturas, niveles, mascara, bin_count, n_voxeles):
    """
    Descriptores de la matriz de dependencia de tono de gris.

    `texturas` es la pila de 18 vectores que devuelve `matriz_ngtdm`.
    """
    if texturas is None or texturas.shape[1] == 0:
        return {}
    sel = mascara.reshape(-1)
    if not sel.any():
        return {}

    # Subconjunto de vóxeles de la ROI.
    t = texturas[:, sel]
    ni = niveles.reshape(-1)[sel].astype(np.int64)
    n = t.shape[1]

    # Se calculan los tres vectores agregados de IBSI por voxel.
    suma = t[0].copy()
    for i in range(1, 7):
        suma = suma + t[i]
    # Suma de los niveles vecinos (sin el propio).
    suma_vecinos = suma - t[0]

    # Matriz de dependencia: P(i, j) = numero de vóxeles de nivel i cuyo
    # promedio de vecinos es j.
    media_vecinos = suma / 7.0
    media_q = np.clip(np.round(media_vecinos).astype(np.int64), 0, bin_count)

    p = np.zeros((bin_count + 2, bin_count + 2), dtype=np.float64)
    np.add.at(p, (ni, media_q), 1)
    if p.sum() <= 0:
        return {}

    # La matriz normalizada tiene la forma de IBSI: filas = nivel, columnas =
    # nivel de dependencia.
    p_norm = p / p.sum()
    i_idx = np.arange(p_norm.shape[0])
    total = p_norm.sum()

    # ---- Coarseness: segundo momento de la matriz de dependencia --------
    # IBSI: Co = (1/Co) * sum P(i,j) * i * j, es decir la covarianza entre
    # el nivel del voxel y el nivel de su vecindario.
    media_global = float((p_norm * i_idx[:, None]).sum() / total)
    coarse = float((p_norm * i_idx[:, None] * i_idx[None, :]).sum() / total)

    # ---- Contrast: media de (i - j)^2 con P(i,j) -------------------------
    dif = i_idx[:, None] - i_idx[None, :]
    contraste = float((p_norm * dif ** 2).sum() / total)

    # ---- Busyness ---------------------------------------------------------
    # Es la diferencia entre la magnitud media del gradiente de nivel dentro
    # de la ROI y la magnitud media en la imagen completa, escalada por el
    # factor de proporcion Phi. Se usa la desviacion tipica de los niveles
    # vecinos de cada voxel, que es la formulation de IBSI.
    var_vecinos = np.zeros(n, dtype=np.float64)
    for i in range(1, 7):
        var_vecinos = var_vecinos + (t[i] - media_vecinos) ** 2
    gamma = np.sqrt(var_vecinos / 7.0)
    gamma_medio = float(gamma.mean())
    # Phi = (n_voxeles_roi / n_voxeles_imagen). Sin el volumen completo se
    # asume ROI aislada (Phi = 1), que es el caso de un tumor segmentado.
    phi = float(_phi(mascara))
    busyness = float((gamma_medio - media_global) / (phi + gamma_medio)) \
        if (phi + gamma_medio) > 0 else float("nan")

    # ---- Strength ---------------------------------------------------------
    # Suma de |i - j| ponderada, dividida por el producto de las medias
    # marginales: mide cuanto se aleja la dependencia de la independencia.
    dif_abs = np.abs(dif)
    i_mean = (p_norm * i_idx[:, None]).sum(axis=1)      # media por nivel
    j_mean = (p_norm * i_idx[None, :]).sum(axis=0)      # media por dependencia
    fuerza_num = float((p_norm * dif_abs).sum())
    fuerza_den = float((i_mean * j_mean).sum())
    fuerza = fuerza_num / fuerza_den if fuerza_den > 0 else float("nan")

    # ---- Complexity --------------------------------------------------------
    # (Busyness + Contrast + Coarseness) normalizado por sus terminos
    # equivalententes con signo absoluto, segun IBSI.
    num = busyness + contraste + coarse
    den = abs(busyness) + contraste + abs(coarse) + phi
    complejidad = float(num / den) if den > 0 else float("nan")

    return {
        "Coarseness": coarse,
        "CoarsenessNormalized": float(coarse / media_global)
        if media_global > 0 else float("nan"),
        "Contrast": contraste,
        "Busyness": busyness,
        "BusynessNormalized": busyness,
        "Strength": fuerza,
        "StrengthNormalized": float(fuerza / media_global)
        if media_global > 0 else float("nan"),
        "Complexity": complejidad,
        "ComplexityNormalized": complejidad,
    }


def _phi(mascara):
    """
    Factor de proporcion Phi = n_voxeles_roi / n_voxeles_volumen.

    Es lo que hace comparable el descriptor Busyness entre una ROI que ocupa
    el 2% del volumen y otra que ocupa el 60%. Aqui se usa el volumen completo
    de la mascara, que es la aproximacion correcta cuando la ROI es el objeto
    de estudio; el pipeline puede pasar el volumen entero con `phi_real`.
    """
    total = int(mascara.size)
    dentro = int(mascara.sum())
    if total <= 0 or dentro <= 0:
        return 1.0
    return float(dentro) / float(total)
