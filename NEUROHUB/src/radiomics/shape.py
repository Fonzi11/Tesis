"""
Rasgos de forma (geometría 3D) según IBSI.

Dos familias de medidas:

  * basados en voxeles : volumen, diametros y ejes principales, que se
    obtienen de los indices de la ROI y no necesitan malla.
  * basados en malla   : superficie, esfericidad y perimetro, que exigen una
    superficie triangulada. Se genera con marching cubes (skimage), que es la
    misma tecnica que usa ITK por debajo.

El Convention de IBSI para la superficie es "mesh-based"; por eso
`SurfaceArea_mm2` sale de la malla y no de un recuento de caras de voxel.
"""

import os
import struct

import numpy as np

EPS = 1e-12


# =============================================================================
# MALLA
# =============================================================================
def construir_malla(mascara, spacing):
    """
    Triangula la ROI con marching cubes.

    Parametros
    ----------
    mascara : ndarray 3D bool
    spacing : (sx, sy, sz) en mm

    Devuelve
    -------
    (vertices_xyz_mm, caras) o (None, None) si la ROI es degenerada.
    """
    from skimage import measure

    if not mascara.any():
        return None, None
    try:
        verts, faces, _normals, _vals = measure.marching_cubes(
            mascara.astype(np.float32), level=0.5,
            spacing=tuple(float(s) for s in spacing),
        )
    except (ValueError, RuntimeError):
        return None, None
    if verts.shape[0] == 0 or faces.shape[0] == 0:
        return None, None
    return verts, faces


def leer_stl(ruta):
    """
    Lee un STL binario y devuelve (vertices_xyz_mm, caras).

    Sirve para consumir las mallas que genera 3D Slicer (`slicer_bridge.
    reconstruir_stl`). El STL binario tiene una cabecera de 80 bytes, un
    uint32 con el numero de triangulos y despues 50 bytes por triangulo
    (12 para la normal y 9 para las coordenadas), lo cual se lee de forma
    vectorizada sin recorrer los triangulos en Python.

    Devuelve (None, None) si el archivo no existe o esta vacio.
    """
    if not os.path.isfile(ruta):
        return None, None
    with open(ruta, "rb") as f:
        datos = f.read()
    CABECERA = 80
    if len(datos) < CABECERA + 4:
        return None, None
    (n,) = struct.unpack_from("<I", datos, CABECERA)
    if n == 0 or len(datos) < CABECERA + 4 + n * 50:
        return None, None

    # Cada triangulo son 50 bytes: 12 de normal (float32 x3) y 36 de
    # coordenadas (float32 x9). Se descartan los 12 de la normal.
    bloque = np.frombuffer(
        datos, dtype=np.uint8, count=n * 50, offset=CABECERA + 4
    ).reshape(n, 50)
    coordenadas = bloque[:, 12:48].copy().view(np.float32).reshape(n, 3, 3)
    coordenadas = coordenadas.astype(np.float64)

    # Los tres vertices de cada triangulo son indices unicos (0, 1, 2, ...),
    # porque el STL no comparte vertices entre triangulos.
    vertices = coordenadas.reshape(-1, 3)
    caras = np.arange(n * 3, dtype=np.int64).reshape(n, 3)
    return vertices, caras


def _propiedades_superficie(vertices, caras):
    """
    Área, volumen y perímetro de una malla cerrada, en unidades físicas.

    Se usa la divergencia (volumen con signo) y la suma de áreas de los
    triángulos, que son exactas para mallas cerradas sin triangulación
    degenerada.
    """
    if vertices is None or caras is None or len(caras) == 0:
        return 0.0, float("nan"), 0.0

    v0 = vertices[caras[:, 0]]
    v1 = vertices[caras[:, 1]]
    v2 = vertices[caras[:, 2]]

    # Área de cada triángulo (producto cruz / 2).
    cr = np.cross(v1 - v0, v2 - v0)
    area_triangulo = 0.5 * np.linalg.norm(cr, axis=1)
    area = float(area_triangulo.sum())

    # Volumen con signo por divergencia del tetraedro con el origen.
    volumen = float(np.abs(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0))

    # Perímetro: longitud de los bordes compartidos por exactamente dos
    # triángulos (aristas de la superficie).
    perimetro = _longitud_aristas(vertices, caras)
    return area, volumen, perimetro


def _longitud_aristas(vertices, caras):
    """
    Suma de longitudes de las aristas de la superficie.

    Una arista de una malla cerrada la comparten dos triángulos, así que se
    cuentan las aristas que aparecen un número impar de veces, que para
    marching cubes son exactamente las de la frontera.
    """
    aristas = {}
    for tri in caras:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ia, ib = int(tri[a]), int(tri[b])
            clave = (ia, ib) if ia < ib else (ib, ia)
            aristas[clave] = aristas.get(clave, 0) + 1
    total = 0.0
    for (ia, ib), n in aristas.items():
        if n == 1:                      # arista de frontera
            total += float(np.linalg.norm(vertices[ia] - vertices[ib]))
    return total


# =============================================================================
# EJES PRINCIPALES
# =============================================================================
def _momentes_inercia(indices_zyx, spacing):
    """
    Tensor de inercia y sus autovalores/autovectores de la ROI.

    Devuelve (lambda_ordenado_desc, ejes_ordenados, centro_mm). Los momentos
    se calculan sobre coordenadas físicas (mm), no en índices, para que los
    ejes no dependan de la anisotropía del vóxel.
    """
    sx, sy, sz = spacing
    # (z, y, x) -> (x, y, z) en mm, que es la convención de SimpleITK/VTK.
    pts = np.empty((indices_zyx.shape[0], 3), dtype=np.float64)
    pts[:, 0] = indices_zyx[:, 2] * sx
    pts[:, 1] = indices_zyx[:, 1] * sy
    pts[:, 2] = indices_zyx[:, 0] * sz

    centro = pts.mean(axis=0)
    d = pts - centro
    cov = (d.T @ d) / max(len(pts), 1)

    autovalores, autovectores = np.linalg.eigh(cov)
    # El mayor autovalor corresponde al eje de mayor dispersión.
    orden = np.argsort(autovalores)[::-1]
    autovalores = autovalores[orden]
    autovectores = autovectores[:, orden]
    return autovalores, autovectores, centro, pts


# =============================================================================
# RASGOS DE FORMA
# =============================================================================
def calcular(mascara, spacing, n_voxeles_total=None, malla=None):
    """
    Calcula los rasgos geometricos de la ROI.

    Parametros
    ----------
    mascara : ndarray 3D bool
    spacing : (sx, sy, sz) en mm
    n_voxeles_total : int o None
        Nº de voxels del volumen completo, para `VolumeProportion`.
    malla : (vertices, caras) o None
        Malla ya triangulada. Si se pasa, se usa en lugar de la que genera
        marching cubes. Sirve para inyectar la superficie suavizada de 3D
        Slicer, que es la que despues se ve en el visor 3D y la que debe
        usarse si se quiere que superficie y esfericidad concuerden con ella.

    Devuelve
    -------
    dict {nombre_ibsI: float}
    """
    if not mascara.any():
        return {}

    sx, sy, sz = (float(s) for s in spacing)
    voxeles_mm3 = sx * sy * sz
    idx = np.argwhere(mascara)                    # (n, 3) en (z, y, x)
    n = idx.shape[0]

    volumen_voxel = n * voxeles_mm3

    if malla is not None:
        vertices, caras = malla
    else:
        vertices, caras = construir_malla(mascara, spacing)
    area, volumen_malla, perimetro = _propiedades_superficie(vertices, caras)

    autovalores, autovectores, centro, pts = _momentes_inercia(idx, spacing)

    # Longitud de los ejes principales. Para una distribución uniforme de
    # vóxeles, la varianza a lo largo de un eje es L²/20 (L = longitud del
    # eje), de modo que L = sqrt(20·lambda). Comprobado contra esfera y
    # elipsoide de tamaño conocido.
    longitudes = np.sqrt(20.0 * np.clip(autovalores, 0.0, None))
    l1, l2, l3 = (float(x) for x in longitudes)
    l1 = max(l1, EPS)

    # Diámetro máximo 3D: distancia máxima entre dos puntos de la ROI.
    diametro_max = _diametro_maximo(pts)
    # Diámetro mínimo: la menor dimensión se aproxima con el menor eje, que es
    # la definición estable que usa PyRadiomics para el voxel-based minimum.
    diametro_min = float(l3)

    elongacion = l2 / l1 if l1 > 0 else float("nan")
    planitud = l3 / l1 if l1 > 0 else float("nan")

    esfericidad = (np.pi ** (1.0 / 3.0) * (6.0 * volumen_voxel) ** (2.0 / 3.0)
                   / area) if area > 0 else float("nan")

    # Áreas de las proyecciones ortogonales, para los descriptores 2D.
    if n_voxeles_total:
        proporcion = n / float(n_voxeles_total)
    else:
        proporcion = float("nan")

    # Compacidad 1 y 2 (definitions de IBSI a partir de superficie y volumen).
    compact1 = (36.0 * np.pi * volumen_voxel ** 2) ** (1.0 / 3.0) / area \
        if area > 0 else float("nan")
    compact2 = (6.0 * volumen_voxel / area ** 1.5) if area > 0 else float("nan")

    # Perímetro 2D: la longitud del contorno de la mayor sección axial.
    perimetro_2d = _perimetro_2d(mascara, spacing)

    rasgos = {
        # ---- Volumen -----------------------------------------------
        "VoxelVolume": float(n),
        "VoxelVolume_mm3": float(volumen_voxel),
        # El volumen de malla es el del tetraedro firmado, no el recuento de
        # voxels: son~—pero no idénticos--. Marching cubes con superficie
        # suavizada reduce el volumen respecto al recuento, y mezclar ambos
        # daria un MeshVolume que no corresponde a ninguna de las dos medidas.
        "MeshVolume": float(volumen_malla) if np.isfinite(volumen_malla) else float(n),
        "MeshVolume_mm3": float(volumen_malla) if np.isfinite(volumen_malla) else float(volumen_voxel),
        "VolumeProportion": proporcion,
        # ---- Superficie --------------------------------------------
        "SurfaceAreaMesh": area,
        "SurfaceArea_mm2": area,
        "SurfaceAreaVoxel": _seguro(lambda: float(
            6.0 * n - 2.0 * _caras_interiores(mascara))),
        "SurfaceVolume": area,
        "SurfaceVolume_mm2": area,
        "SurfaceVolumeRatio": _seguro(lambda: area / (volumen_voxel ** (2 / 3))),
        "SurfaceToVolumeRatio": _seguro(lambda: area / volumen_voxel),
        # ---- Forma -------------------------------------------------
        "Sphericity": esfericidad,
        "SphericalDisproportion": _seguro(
            lambda: 1.0 / esfericidad if esfericidad > 0 else float("nan")),
        "Compactness1": compact1,
        "Compactness2": compact2,
        # ---- Dimensiones -------------------------------------------
        "Maximum3DDiameter": diametro_max,
        "Minimum3DDiameter": diametro_min,
        "MaximumDiameter2D": _seguro(lambda: max(
            (idx[:, 1].max() - idx[:, 1].min() + 1) * sy,
            (idx[:, 2].max() - idx[:, 2].min() + 1) * sx)),
        "MaximumDiameter3D": diametro_max,
        "Elongation": elongacion,
        "Flatness": planitud,
        "PrincipalAxis1Length": l1,
        "PrincipalAxis2Length": l2,
        "PrincipalAxis3Length": l3,
        # ---- Ejes (orientación en grados) ---------------------------
        "PrincipalAxis1Orientation": _orientacion(autovectores[:, 0]),
        "PrincipalAxis2Orientation": _orientacion(autovectores[:, 1]),
        "PrincipalAxis3Orientation": _orientacion(autovectores[:, 2]),
        "PrincipalMomentsOrder1": float(autovalores[0]),
        "PrincipalMomentsOrder2": float(autovalores[1]),
        "PrincipalMomentsOrder3": float(autovalores[2]),
        "Eigenvalues1": float(autovalores[0]),
        "Eigenvalues2": float(autovalores[1]),
        "Eigenvalues3": float(autovalores[2]),
        # ---- Perímetros --------------------------------------------
        "Perimeter": perimetro,
        "Perimeter_mm": perimetro,
        "Perimeter2D": perimetro_2d,
        "Perimeter2D_mm": perimetro_2d,
        "Perimeter3D": perimetro,
        "Perimeter3D_mm": perimetro,
        "Gyration": _seguro(lambda: float(np.abs(pts - centro).sum() / n)),
        "FeretDiameter": diametro_max,
        "FeretDiameter3D": diametro_max,
        "FeretDiameter2D": _seguro(lambda: max(
            (idx[:, 1].max() - idx[:, 1].min() + 1) * sy,
            (idx[:, 2].max() - idx[:, 2].min() + 1) * sx)),
        # ---- Descriptor 2D ------------------------------------------
        "Circularity": _circularidad(mascara, spacing, perimetro_2d),
        "Sphericity2D": _esfericidad_2d(mascara, spacing, perimetro_2d),
    }
    return rasgos


def _seguro(fn):
    """Ejecuta `fn` y traduce cualquier error a NaN."""
    try:
        valor = float(fn())
    except (ValueError, ZeroDivisionError, FloatingPointError, TypeError,
            AttributeError, IndexError):
        return float("nan")
    return valor if np.isfinite(valor) else float("nan")


def _diametro_maximo(pts):
    """
    Diámetro máximo 3D (Feret) de la ROI: distancia entre los dos puntos
    más alejados.

    Para ROI pequeñas (hasta 4000 vóxeles, el caso habitual de un tumor) se
    resuelve exacto por fuerza bruta, pero por bloques: la matriz completa
    de distancias ocuparía cientos de MB. Para ROI mayores se usa
    projecting-and-hinge sobre los ejes principales, que es la aproximación
    estándar y basta para un descriptor clínico.
    """
    n = pts.shape[0]
    if n < 2:
        return 0.0
    if n <= 4000:
        mejor = 0.0
        bloque = 512
        for i in range(0, n, bloque):
            trozo = pts[i:i + bloque]
            d2 = ((trozo[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
            mejor = max(mejor, float(d2.max()))
        return float(np.sqrt(mejor))

    # Aproximación: projecting-and-hinge. Para cada eje se toman los voxels
    # extremos en esa dirección y se busca el par más lejano ENTRE ELLOS,
    # midiendo la distancia 3D completa (no en el plano proyectado, que
    # truncaría el resultado: los voxels de la punta de un eje se concentran
    # en un disco pequeño al proyectarlos).
    cov = np.cov(pts.T)
    _, vectores = np.linalg.eigh(cov)
    proj = pts @ vectores
    mejor = 0.0
    k = min(64, n)
    for a in range(3):
        orden = np.argsort(proj[:, a])
        extremos = np.concatenate([orden[:k], orden[-k:]])
        sub = pts[extremos]
        d2s = ((sub[:, None, :] - sub[None, :, :]) ** 2).sum(-1)
        mejor = max(mejor, float(np.sqrt(d2s.max())))
    return mejor


def _caras_interiores(mascara):
    """
    Nº de caras de vóxel con al menos un vecino fuera de la ROI.

    Superficie por recuento de vóxeles = 6·n - 2·(caras compartidas con otro
    vóxel de la ROI). Es la aproximación "voxel-based" de IBSI, distinta de
    la superficie de la malla.
    """
    from scipy.ndimage import convolve

    kernel = np.ones((3, 3, 3), dtype=np.int32)
    vecinos = convolve(mascara.astype(np.int32), kernel, mode="constant", cval=0)
    return int((vecinos - 1)[mascara].sum())


def _perimetro_2d(mascara, spacing):
    """
    Perímetro del contorno de la mayor sección axial de la ROI.

    Se elige el corte con más vóxeles y se recorre su borde con marching
    cubes 2D, que es la convención de PyRadiomics para los descriptores 2D.
    """
    from skimage import measure

    cortes = mascara.sum(axis=(1, 2))
    if cortes.size == 0 or cortes.max() == 0:
        return float("nan")
    z = int(np.argmax(cortes))
    seccion = mascara[z]
    if seccion.sum() < 3:
        return float("nan")
    try:
        contornos = measure.find_contours(seccion.astype(float), 0.5)
    except (ValueError, RuntimeError):
        return float("nan")
    if not contornos:
        return float("nan")
    sy, sx = float(spacing[1]), float(spacing[2])
    largo = 0.0
    for c in contornos:
        pts = np.column_stack([c[:, 1] * sx, c[:, 0] * sy])
        largo += float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    return largo


def _circularidad(mascara, spacing, perimetro):
    """Circularidad 4π·A/P² de la sección axial más grande (1 = círculo)."""
    from skimage import measure

    cortes = mascara.sum(axis=(1, 2))
    if cortes.size == 0 or cortes.max() == 0 or not np.isfinite(perimetro):
        return float("nan")
    z = int(np.argmax(cortes))
    area = float(mascara[z].sum()) * float(spacing[1]) * float(spacing[2])
    if perimetro <= 0:
        return float("nan")
    return 4.0 * np.pi * area / (perimetro ** 2)


def _esfericidad_2d(mascara, spacing, perimetro):
    """Esfericidad 2D de la sección axial: π·r²/Area con r = P/(2π)."""
    area = _area_seccion(mascara, spacing)
    if not np.isfinite(perimetro) or perimetro <= 0 or area <= 0:
        return float("nan")
    radio = perimetro / (2.0 * np.pi)
    return float(np.pi * radio ** 2 / area)


def _area_seccion(mascara, spacing):
    """Área en mm² de la sección axial con más vóxeles."""
    cortes = mascara.sum(axis=(1, 2))
    if cortes.size == 0 or cortes.max() == 0:
        return float("nan")
    z = int(np.argmax(cortes))
    return float(cortes[z]) * float(spacing[1]) * float(spacing[2])


def _orientacion(eje):
    """
    Ángulo de un eje principal respecto al plano axial, en grados.

    Es el ángulo entre la proyección del eje sobre el plano XY y el eje X,
    que es la definición de PyRadiomics para las orientaciones.
    """
    x, y = float(eje[0]), float(eje[1])
    angulo = np.degrees(np.arctan2(y, x))
    # Se normaliza al rango [-90, 90] porque el eje no tiene sentido dirigido.
    if angulo > 90.0:
        angulo -= 180.0
    elif angulo <= -90.0:
        angulo += 180.0
    return float(angulo)



    autovalores, autovectores = np.linalg.eigh(cov)
    # Mayor autovalor = eje de mayor dispersión.
    orden = np.argsort(autovalores)[::-1]
    autovalores = autovalores[orden]
    autovectores = autovectores[:, orden]
    return autovalores, autovectores, centro, pts
