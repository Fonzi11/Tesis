"""
NEUROHUB - Reconstrucción de superficies 3D en Python
=======================================================
Genera mallas de calidad uniforme para todas las estructuras anatómicas.

Por qué este módulo
------------------
El tumor se veía nítido mientras el cerebro y el cráneo aparecían escalonados.
La causa NO era la resolución de los datos: `brain.nii.gz`, `skull.nii.gz` y
`tumor_brats.nii.gz` comparten exactamente el mismo spacing anisotrópico
(0.9375 x 0.9375 x 1.4 mm). El tumor solo parecía mejor porque es una estructura
pequeña: su superficie cabe en pocos píxeles y el escalonado se percibe poco. El
cerebro y el cráneo abarcan casi todo el volumen, así que la misma escalera de
vóxeles se ve sobre una superficie mucho mayor.

La diferencia real era doble:

1. `marching_cubes` corría sobre la rejilla original y anisotrópica, así que la
   frontera se cortaba justo en los límites de vóxel.
2. La reconstrucción delegaba en 3D Slicer, cuya conversión usaba un
   `oversampling_factor` bajo, y que no siempre está disponible.

Este módulo reconstruye todo en Python puro, sin depender de Slicer:

  1. Re-muestreo isótropo: la máscara se lleva a una rejilla cúbica con el menor
     espaciado del volumen, de modo que un vóxel vale lo mismo en los tres ejes.
     Esto elimina la diferencia de calidad entre estructuras.
  2. Suavizado gaussiano ligero: hace la transición de la superficie continua
     en lugar de a saltos.
  3. Marching cubes sobre la rejilla refinada.
  4. Suavizado Taubin: conserva el volumen (a diferencia de Laplace, que encoge
     la malla).

Resultado: mismo tratamiento y misma calidad para cerebro, cráneo, tumor y
vasos, sin importar su tamaño.
"""

import os

import numpy as np
from scipy.ndimage import (gaussian_filter, binary_fill_holes, label as nd_label,
                           sum as nd_sum, zoom)
from skimage import measure

try:
    import trimesh
except ImportError:  # pragma: no cover - trimesh es opcional
    trimesh = None

# Parámetros por estructura.
#   sigma              suavizado gaussiano en vóxeles de la rejilla isótropa.
#   taubin_iter        iteraciones de Taubin (conserva volumen).
#   factor_isotropia   espaciado objetivo = menor spacing original * factor.
#                       1.0 = rejilla original, 0.5 = doble resolución por eje.
#
# Todos los perfiles son idénticos a propósito: ver la nota de
# FACTOR_ISOTROPIA más abajo. Cerebro, cráneo y tumor se reconstruyen con la
# MISMA rejilla isótropa, el MISMO sigma y el MISMO Taubin, de modo que la
# superficie se ve igual de definida en los tres casos, sea cual sea su tamaño.
# ---------------------------------------------------------------------------
# RESOLUCIÓN ÚNICA PARA TODAS LAS ESTRUCTURAS
# ---------------------------------------------------------------------------
# Cerebro, cráneo y tumor comparten EXACTAMENTE el mismo perfil. Antes cada
# estructura tenía el suyo (el tumor con factor 1.0 = rejilla original, el cerebro
# y el cráneo con 0.65) y esa era la causa de que el tumor se viera nítido y las
# masas grandes escalonadas: no era la imagen, era la rejilla de reconstrucción.
#
# Un único factor para las tres estructuras garantiza que el borde se calcule con
# la misma densidad de vóxeles en todos los casos, así que se ven igual de
# definido sea cual sea su tamaño.
#
# FACTOR_ISOTROPIA = 0.5 lleva la rejilla de 0.9375 mm a ~0.47 mm, es decir
# DOBLE resolución por eje que el volumen original. Es el máximo útil con estos
# datos: el contenido real de la máscara no aporta detalle por debajo del vóxel,
# y bajar más solo multiplica el tamaño del archivo y el coste de render sin
# ganar superficie. Se puede subir con NEUROHUB_FACTOR_ISOTROPIA=0.35 si se
# necesita más, a costa de mallas mucho mayores.
FACTOR_ISOTROPIA = float(os.environ.get("NEUROHUB_FACTOR_ISOTROPIA", "0.5"))

# Perfil común: mismo sigma y mismo Taubin para las tres estructuras, para que
# el acabado de la superficie sea idéntico y no dependa del tamaño del objeto.
PERFIL_UNIFORME = {
    "sigma": 1.0,
    "taubin_iter": 30,
    "factor_isotropia": FACTOR_ISOTROPIA,
}

PERFIL_CALIDAD = {
    "cerebro": PERFIL_UNIFORME,
    "craneo": PERFIL_UNIFORME,
    "tumor": PERFIL_UNIFORME,
}

PERFIL_POR_DEFECTO = PERFIL_UNIFORME


def perfil_de(estructura):
    """Perfil de calidad de una estructura, con valores por defecto."""
    return PERFIL_CALIDAD.get(estructura, PERFIL_POR_DEFECTO)


def _espaciado_objetivo(spacing, factor_isotropia):
    """Espaciado isótropo objetivo a partir del spacing original (sx, sy, sz)."""
    sx, sy, sz = [float(v) for v in spacing[:3]]
    objetivo = min(sx, sy, sz) * float(factor_isotropia)
    # Nunca por debajo de 0.3 mm: por debajo la superficie no gana detalle real
    # y el coste de memoria y tiempo crece sin servicio.
    return max(objetivo, 0.3)


def zoom_lineal(campo, factores):
    """Re-muestreo trilineal de un campo 3D con un factor por eje.

    `factores` viene en el orden de los ejes del array (k, j, i), que es
    distinto del orden (sx, sy, sz) en que SimpleITK reporta el espaciado.
    Se usa ndimage.zoom porque interpola eje a eje: una malla de 88 M de vóxeles
    con map_coordinates exigiría construir la rejilla completa de coordenadas en
    memoria, que es lo que agota la RAM.
    """
    if all(abs(f - 1.0) < 1e-6 for f in factores):
        return campo
    campo = gaussian_filter(campo, sigma=0.6)  # prefiltrado: evita el escalonado
    return zoom(campo, zoom=factores, order=1, mode="constant", grid_mode=False)


def _reducir_componentes(mask, min_voxels):
    """Quita islas de ruido y rellena huecos internos.

    Sin esto las superficies salen con esquirlas sueltas que se ven como ruido
    al factorizar la malla, y con agujeros en lugar de ser cerradas.
    """
    if min_voxels and min_voxels > 1:
        etiquetas, numero = nd_label(mask)
        if numero > 1:
            tamanos = nd_sum(mask, etiquetas, range(1, numero + 1))
            conservar = np.isin(etiquetas, 1 + np.nonzero(tamanos >= min_voxels)[0])
            mask = conservar.astype(np.uint8)
    return binary_fill_holes(mask > 0).astype(np.uint8)



def malla_alta_calidad(mask, spacing, estructura="", min_voxels=0,
                       perfil=None, verbose=True):
    """Convierte una máscara binaria en una malla suave de calidad uniforme.

    Args:
        mask: matriz 3D binaria (orden k-j-i, como la devuelve SimpleITK).
        spacing: espaciado del volumen en mm, como (sx, sy, sz).
        estructura: nombre usado para elegir el perfil de calidad.
        min_voxels: descarta componentes menores que este tamaño.
        perfil: sobrescribe el perfil de la estructura.
        verbose: si True, informa del detalle generado.

    Returns:
        (verts, faces) con vértices en mm, o arrays vacíos si la máscara no tiene
        contenido.
    """
    if mask is None or np.count_nonzero(mask) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)

    cfg = dict(perfil or perfil_de(estructura))
    sigma = float(cfg.get("sigma", 0.6))
    taubin_iter = int(cfg.get("taubin_iter", 25))
    factor_isotropia = float(cfg.get("factor_isotropia", 1.0))

    datos = _reducir_componentes((np.asarray(mask) > 0).astype(np.uint8), min_voxels)

    # Los volúmenes BraTS son de 112x256x256 vóxeles y casi todo es fondo. Sin
    # recortar al recuadro que envuelve la estructura, el refinamiento pediría 88
    # millones de vóxeles y agota la memoria. Recortando, el coste pasa a ser
    # proporcional al tamaño real de la anatomía.
    indices = np.nonzero(datos)
    if len(indices[0]) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    limites = [(int(eje.min()), int(eje.max()) + 1) for eje in indices]
    # +1 vóxel de margen: la superficie cae justo en el borde del objeto y sin
    # aire alrededor marching_cubes la recortaría.
    recorte = tuple(slice(max(0, lo - 1), min(datos.shape[i], hi + 1))
                    for i, (lo, hi) in enumerate(limites))
    datos = datos[recorte]

    objetivo = _espaciado_objetivo(spacing, factor_isotropia)
    # Factores de ampliación por eje del array (k, j, i). El spacing de SimpleITK
    # viene en (sx, sy, sz), el orden inverso al del array, así que se invierte
    # para que cada eje reciba su propio factor.
    sx, sy, sz = [float(v) for v in spacing[:3]]
    factores = [sz / objetivo, sy / objetivo, sx / objetivo]
    refinado = any(f > 1.05 for f in factores)

    campo = datos.astype(np.float32)
    if refinado:
        campo = zoom_lineal(campo, factores)
        if sigma > 0:
            campo = gaussian_filter(campo, sigma=sigma)
    elif sigma > 0:
        # Sin re-muestreo el sigma se escala al vóxel original, para que el
        # suavizado sea equivalente en milímetros en los tres ejes.
        campo = gaussian_filter(campo, sigma=[sigma * f for f in factores])

    verts, faces, _, _ = measure.marching_cubes(
        campo, level=0.5, spacing=(objetivo, objetivo, objetivo), method="lorensen")
    # Devuelve la malla a su posición original dentro del volumen recortado.
    origen = np.array([recorte[0].start, recorte[1].start, recorte[2].start])
    verts = verts + origen * objetivo

    if len(verts) == 0 or len(faces) == 0:
        return verts, faces

    if taubin_iter > 0 and trimesh is not None:
        try:
            malla = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
            trimesh.smoothing.filter_taubin(malla, iterations=taubin_iter)
            verts = np.asarray(malla.vertices)
            faces = np.asarray(malla.faces)
        except Exception as error:
            print(f"[CALIDAD] Taubin no aplicado en {estructura}: {error}")

    # SimpleITK entrega los ejes en orden k-j-i; se invierte a x-y-z para que el
    # visor lo pinte con la anatomía en la orientación esperada.
    verts = verts[:, ::-1].copy()

    if verbose:
        modo = "refinada" if refinado else "directa"
        print(f"[CALIDAD] {estructura or 'malla':10s} {modo:8s} "
              f"spacing={objetivo:.3f}mm sigma={sigma:.2f} "
              f"taubin={taubin_iter} -> {len(verts):,} verts, {len(faces):,} caras")
    return verts, faces


def malla_a_stl(verts, faces, ruta):
    """Guarda la malla en STL. Devuelve True si el archivo se escribió."""
    if len(verts) == 0 or len(faces) == 0:
        return False
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        malla = trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                                faces=np.asarray(faces, dtype=np.int64),
                                process=False)
        malla.export(ruta)
        return os.path.isfile(ruta) and os.path.getsize(ruta) > 0
    except Exception as error:
        print(f"[CALIDAD] Error guardando STL {ruta}: {error}")
        return False


def malla_a_dict(verts, faces):
    """Envuelve la malla en el formato que consume el visor 3D."""
    return {"verts": np.asarray(verts, dtype=np.float32),
            "faces": np.asarray(faces, dtype=np.int32)}


def rugosidad_alta_frecuencia(verts, faces, percentil=95):
    """Mide la rugosidad normalizada de una malla, sin unidades.

    Para cada vértice toma la distancia al centroide de sus vecinos inmediatos y
    la divide por su distancia media a esos mismos vecinos. Ese cociente vale
    ~0.11 en una esfera perfecta y sube cuando la superficie se granula, con lo
    que permite comparar mallas de distinto tamaño y resolución bajo el mismo
    criterio.

    Es la métrica que comprueba que el resultado final sea tan suave como el
    tumor: si el cerebro o el cráneo quedan por debajo del valor del tumor, la
    diferencia de aspecto ya no está en la malla.
    """
    import trimesh as tm

    malla = tm.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                       faces=np.asarray(faces, dtype=np.int64), process=True)
    vecinos = malla.vertex_neighbors
    v = np.asarray(malla.vertices)

    valores = []
    for indice, adyacentes in enumerate(vecinos):
        if len(adyacentes) < 3:
            continue
        idx = np.asarray(adyacentes)
        centroide = v[idx].mean(axis=0)
        distancia = np.linalg.norm(v[indice] - centroide)
        alcance = np.linalg.norm(v[idx] - v[indice], axis=1).mean()
        if alcance > 1e-9:
            valores.append(distancia / alcance)
    if not valores:
        return 0.0
    return float(np.percentile(valores, percentil))


def rugosidad(verts, faces, percentil=90.0):
    """Mide la rugosidad de una malla en milímetros.

    Para cada vértice calcula la distancia al centroide de sus vecinos
    inmediatos. En una superficie suave ese valor es comparable al lado medio
    del triángulo; en una superficie granulada crece, porque los vértices
    alternan entre salientes y entrantes.

    Devuelve el percentil pedido de esas distancias, en mm. Sirve para
    comparar la calidad entre estructuras con el mismo criterio.
    """
    import trimesh as tm

    malla = tm.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                       faces=np.asarray(faces, dtype=np.int64), process=True)
    vecinos = malla.vertex_neighbors
    mascara = np.array([len(ns) >= 3 for ns in vecinos])
    if not mascara.any():
        return 0.0

    v = np.asarray(malla.vertices)
    acumulador = np.zeros_like(v)
    conteo = np.zeros(len(v), dtype=np.int64)
    for adyacentes in vecinos:
        if adyacentes:
            idx = np.asarray(adyacentes)
            acumulador[idx] += v[idx]
            conteo[idx] += 1
    con_vecinos = conteo > 0
    centroides = np.zeros_like(v)
    centroides[con_vecinos] = acumulador[con_vecinos] / conteo[con_vecinos, None]

    distancias = np.linalg.norm(v - centroides, axis=1)
    return float(np.percentile(distancias[mascara & con_vecinos], percentil))
