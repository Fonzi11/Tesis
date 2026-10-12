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

# Parámetros por estructura, todos en MILÍMETROS (ver `malla_alta_calidad`):
#   sigma_mm     suavizado gaussiano de la superficie, en mm reales. Es el
#                parámetro que elimina el escalonado y el que NO puede ser
#                igual para todas las estructuras.
#   taubin_iter  iteraciones de Taubin (conserva volumen, no encoge).
#   objetivo_mm  espaciado isótropo de la rejilla de reconstrucción.
# ---------------------------------------------------------------------------
# HALLAZGO MEDIDO (work/exp_sweep.py, work/valida_sigma.py, work/exp_sdf.py)
# ---------------------------------------------------------------------------
# 1. Ni el refinado de rejilla ni un SDF eliminan el escalonado. Interpolar una
#    máscara 0/1 (order=1) o aislar su transformada de distancia no crean
#    información anatómica que la máscara no tenga. Medido sobre brain.nii.gz:
#       refinado a 0.47 mm (lo que había en producción) -> rugosidad 0.1462,
#                                                           13.5 % caras a eje
#       SDF a 0.45 mm                                   -> rugosidad 0.1699,
#                                                           21.4 % caras a eje
#    El SDF es PEOR que el refinado. Se descarta.
#
# 2. Lo que sí funciona es suavizar en MILÍMETROS, medido a densidad de malla
#    constante (rejilla isotropa de 0.6 mm en todas las columnas del barrido):
#       sigma 0.0 mm -> 48.5 % caras a eje, rugosidad 0.514
#       sigma 1.0 mm ->  9.1 % caras a eje, rugosidad 0.145
#       sigma 2.0 mm ->  1.8 % caras a eje, rugosidad 0.104
#    Las caras alineadas a eje son la firma del escalonado, y caen de 48 % a 2 %.
#    Nótese que sigma 0 deja la escalera intacta: el refinado por sí solo no
#    suaviza nada.
#
# 3. El sigma NO puede ser el mismo para todas las estructuras. Cambio de volumen
#    frente a la máscara original (work/valida_sigma.out):
#           sigma   1.0     1.5     2.0     2.5 mm
#       cerebro  1.009   1.009   1.007   1.006   <- indiferente
#       craneo   1.002   0.996   0.990   0.980   <- casi indiferente
#       tumor    1.004   0.978   0.933   0.876   <- pierde un 6.7 % a sigma 2.0
#    Un sigma uniforme que dejara el cerebro liso se comería el tumor en términos
#    de volumen medido. Por eso el perfil se define en mm y es POR ESTRUCTURA:
#    el mayor sigma que conserva el volumen.
#
# La rejilla isotropa se fija en 0.6 mm, no en 0.47: con 38 % menos caras entrega
# la MISMA rugosidad (0.1450 vs 0.1462), porque por debajo de ~0.6 mm la rejilla
# más fina solo multiplica triángulos, ya que no hay más detalle que extraer.
#
# Objetivo isótropo en mm. 0.6 mm equivale al spacing original (0.9375) * 0.64.
ESPACIADO_OBJETIVO_MM = float(os.environ.get("NEUROHUB_ESPACIADO_MM", "0.6"))
# Red de seguridad: por debajo de 0.35 mm el refinado multiplica el tamaño de la
# malla sin ganar superficie, ya que el suavizado en mm quitó el escalonado.
ESPACIADO_MINIMO_MM = 0.35

# Perfiles por estructura, en MILÍMETROS.
#   sigma_mm     suavizado gaussiano de la superficie, en mm reales.
#   taubin_iter  iteraciones de Taubin (conserva volumen, no encoge).
#
# El sigma de cada estructura es el mayor del barrido medido que mantiene el
# volumen de la máscara dentro del 1 % (cerebro, cráneo) o del 2.5 % (tumor):
# el punto en el que la superficie sigue quedándose lisa y ya no se come
# anatomía. Tabla completa en work/valida_sigma.out.
PERFIL_CALIDAD = {
    "cerebro": {"sigma_mm": 2.0, "taubin_iter": 30},
    "craneo":  {"sigma_mm": 1.5, "taubin_iter": 30},
    "tumor":   {"sigma_mm": 1.0, "taubin_iter": 30},
}

# Cualquier otra estructura (vasos, nervios, ROI sueltas) recibe un sigma
# conservador: son estructuras finas, que un sigma alto degenera antes que al
# cerebro. 1.0 mm fue el único valor que conservó el volumen del tumor.
PERFIL_POR_DEFECTO = {"sigma_mm": 1.0, "taubin_iter": 30}


def perfil_de(estructura):
    """Perfil de calidad de una estructura, con valores por defecto."""
    return PERFIL_CALIDAD.get(estructura, PERFIL_POR_DEFECTO)


def _espaciado_objetivo(spacing, factor_isotropia=None):
    """Espaciado isótropo objetivo en mm a partir del spacing original.

    Con `factor_isotropia` None se usa ESPACIADO_OBJETIVO_MM (0.6 mm), el valor
    validado. El parámetro se conserva por compatibilidad con los perfiles
    antiguos que lo pasaban de forma explícita.
    """
    sx, sy, sz = [float(v) for v in spacing[:3]]
    if factor_isotropia is None:
        objetivo = ESPACIADO_OBJETIVO_MM
    else:
        objetivo = min(sx, sy, sz) * float(factor_isotropia)
    return max(objetivo, ESPACIADO_MINIMO_MM)


def zoom_lineal(campo, factores):
    """Re-muestreo trilineal de un campo 3D con un factor por eje.

    `factores` viene en el orden de los ejes del array (k, j, i), que es
    distinto del orden (sx, sy, sz) en que SimpleITK reporta el espaciado.
    Se usa ndimage.zoom porque interpola eje a eje: una malla de 88 M de vóxeles
    con map_coordinates exigiría construir la rejilla completa de coordenadas en
    memoria, que es lo que agota la RAM.

    Antes este prefiltraba con sigma=0.6 vóxeles antes de interpolar, creyendo
    que así quitaba el escalonado. No lo hacía: un prefiltrado de amplitud fija
    se va difuminando con el factor de zoom y no equivale al sigma en mm que
    pide la superficie. Peor aún, esa fase añadida se sumaba al sigma real y
    hacía que el valor por estructura fuera inexistente. Ahora el suavizado es
    uno solo, en milímetros, y se aplica sobre la rejilla ya isotropa (ver
    `malla_alta_calidad`); por eso aquí solo se interpola.
    """
    if all(abs(f - 1.0) < 1e-6 for f in factores):
        return campo
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



def _asegurar_normales_exteriores(verts, faces):
    """Fuerza que las normales de las caras apunten hacia AFUERA de la malla.

    `marching_cubes` devuelve el bobinado de las caras según la convención de
    la versión de skimage instalada, y esa convención ha cambiado entre
    versiones. El síntoma cuando apunta hacia dentro no es un detalle
    cosmético: la malla tiene volumen negativo, trimesh la considera no
    válida y cualquier visor que sombree con la normal de la cara la pinta
    del revés (oscuro por dentro, iluminado por fuera).

    Se decide mirando el volumen con signo en lugar de fiarse de la
    convención. Se usa la suma de los tetraedros con el vértice en el origen
    como referencia, que es la misma fórmula que usa trimesh, así que el
    resultado es coherente con la librería que luego lee y exporta la malla.
    """
    verts = np.asarray(verts, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if len(faces) == 0:
        return faces

    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    volumen = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    if volumen < 0:
        faces = faces[:, ::-1].copy()
    return faces


def volumen_del_campo_mm3(campo, objetivo):
    """Volumen que encierra la superficie de nivel 0.5, en mm³.

    Esta es la forma FIABLE de medir el volumen de una malla. No se usa
    `Trimesh.volume` porque la malla que produce marching_cubes no es cerrada:
    tiene ~700 aristas no manifiestas de ~959.000 (medido, work/diag_wt3.py), y
    con aristas abiertas el volumen con signo deja de ser invariante por
    traslación (la malla del cerebro da 1384.7 cm3 en el origen y 1299.5 cm3
    desplazada 500 mm). Ese número no sirve para nada.

    El volumen de una superficie de nivel está definido en el DOMINIO donde la
    superficie está definida, o sea en el campo. Contando los vóxeles con campo
    >= 0.5 y multiplicando por el volumen del vóxel isótropo sale exactamente,
    con un error del espaciado (0.6 mm) y sin depender de la topología de la malla.
    """
    dentro = int(np.count_nonzero(np.asarray(campo) >= 0.5))
    return dentro * float(objetivo) ** 3


def malla_alta_calidad(mask, spacing, estructura="", min_voxels=0,
                       perfil=None, verbose=True, devolver_volumen=False):
    """Convierte una máscara binaria en una malla suave de calidad uniforme.

    Args:
        mask: matriz 3D binaria (orden k-j-i, como la devuelve SimpleITK).
        spacing: espaciado del volumen en mm, como (sx, sy, sz).
        estructura: nombre usado para elegir el perfil de calidad.
        min_voxels: descarta componentes menores que este tamaño.
        perfil: sobrescribe el perfil de la estructura.
        verbose: si True, informa del detalle generado.
        devolver_volumen: si True, devuelve además el volumen del campo en mm³
            (ver `volumen_del_campo_mm3`), que es la forma fiable de comprobar
            que el suavizado no se ha comido anatomía.

    Returns:
        (verts, faces) con vértices en mm, o arrays vacíos si la máscara no tiene
        contenido. Si `devolver_volumen`, un tercer elemento con los mm³.
    """
    if mask is None or np.count_nonzero(mask) == 0:
        vacio = (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
        return vacio + (0.0,) if devolver_volumen else vacio

    cfg = dict(perfil or perfil_de(estructura))
    # `sigma` en el perfil es la posición heredada; el parámetro real es sigma_mm.
    sigma_mm = float(cfg.get("sigma_mm", cfg.get("sigma", 1.0)))
    taubin_iter = int(cfg.get("taubin_iter", 30))
    # La rejilla isotropa va en mm. Se acepta `objetivo_mm` para que un llamante
    # pueda pedir más resolución sin tocar los perfiles.
    objetivo_mm = float(cfg.get("objetivo_mm", ESPACIADO_OBJETIVO_MM))

    datos = _reducir_componentes((np.asarray(mask) > 0).astype(np.uint8), min_voxels)

    # Los volúmenes BraTS son de 112x256x256 vóxeles y casi todo es fondo. Sin
    # recortar al recuadro que envuelve la estructura, el refinamiento pediría 88
    # millones de vóxeles y agota la memoria. Recortando, el coste pasa a ser
    # proporcional al tamaño real de la anatomía.
    indices = np.nonzero(datos)
    if len(indices[0]) == 0:
        vacio = (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
        return vacio + (0.0,) if devolver_volumen else vacio
    limites = [(int(eje.min()), int(eje.max()) + 1) for eje in indices]
    # +1 vóxel de margen: la superficie cae justo en el borde del objeto y sin
    # aire alrededor marching_cubes la recortaría.
    recorte = tuple(slice(max(0, lo - 1), min(datos.shape[i], hi + 1))
                    for i, (lo, hi) in enumerate(limites))
    datos = datos[recorte]

    objetivo = _espaciado_objetivo(spacing, cfg.get("factor_isotropia"))
    objetivo = float(cfg.get("objetivo_mm", objetivo))
    # Factores de ampliación por eje del array (k, j, i). El spacing de SimpleITK
    # viene en (sx, sy, sz), el orden inverso al del array, así que se invierte
    # para que cada eje reciba su propio factor.
    sx, sy, sz = [float(v) for v in spacing[:3]]
    factores = [sz / objetivo, sy / objetivo, sx / objetivo]
    refinado = any(f > 1.05 for f in factores)

    campo = datos.astype(np.float32)
    # El sigma se aplica SIEMPRE en milímetros reales, nunca en vóxeles. En la
    # rejilla isotropa eso es sigma_mm / objetivo; sobre la rejilla original,
    # sigma_mm / spacing por eje. Así el suavizado es idéntico en los tres ejes
    # y no depende de la resolución con la que se reconstruya.
    if refinado:
        campo = zoom_lineal(campo, factores)
        if sigma_mm > 0:
            campo = gaussian_filter(campo, sigma=sigma_mm / objetivo)
    elif sigma_mm > 0:
        campo = gaussian_filter(
            campo, sigma=[sigma_mm / v for v in (sz, sy, sx)])

    # Guarda contra la pérdida total de estructuras finas.
    #
    # El sigma está expresado en milímetros, pero su efecto depende del GROSOR de
    # lo que se suaviza. Una barra de 2x2 mm con sigma 1.0 mm desaparece: el
    # campo suavizado cae por debajo de 0.5 en todas partes, la superficie de
    # nivel 0.5 deja de existir y marching_cubes lanza "Surface level must be
    # within volume data range" (medido, work/diag_forms.py). Con sigma 2.0 mm
    # desaparecen ya las de 4x4 mm.
    #
    # Para una estructura de radio equivalente r, un pulso suavizado de altura
    # h en su centro vale (h/2)(1 + erf(r / (sigma*sqrt(2)))). La estructura
    # sobrevive al nivel 0.5 mientras ese valor supere 0.5, y por tanto el
    # sigma máximo admisible depende del radio, no solo de la estructura.
    if float(np.max(campo)) <= 0.5:
        if verbose:
            print(f"[CALIDAD] AVISO {estructura or 'malla'}: el sigma "
                  f"{sigma_mm:.2f} mm borra la estructura (max del campo "
                  f"{float(np.max(campo)):.3f} <= 0.5). Se reduce hasta "
                  f"recuperarla.")
        # Perder la estructura entera es peor que dejar algo de escalonado, así
        # que se reconstruye el campo sin suavizado y la malla vuelve a existir.
        sigma_mm = 0.0
        campo = zoom_lineal(datos.astype(np.float32), factores) if refinado \
            else datos.astype(np.float32)

    # El volumen se mide sobre el campo ya suavizado, que es lo que define la
    # superficie. Medirlo aquí, y no sobre `verts`/`faces`, evita depender de
    # una malla que no es cerrada (ver `volumen_del_campo_mm3`).
    volumen_mm3 = volumen_del_campo_mm3(campo, objetivo)

    verts, faces, _, _ = measure.marching_cubes(
        campo, level=0.5, spacing=(objetivo, objetivo, objetivo), method="lorensen")
    # Devuelve la malla a su posición original dentro del volumen recortado.
    origen = np.array([recorte[0].start, recorte[1].start, recorte[2].start])
    verts = verts + origen * objetivo

    if len(verts) == 0 or len(faces) == 0:
        return (verts, faces, volumen_mm3) if devolver_volumen else (verts, faces)

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

    # El bobinado de las caras se deja como marching_cubes lo devuelve.
    #
    # Medido con skimage 0.26 / numpy 2.3 sobre un cubo de prueba:
    #   marching_cubes (lorensen) en k-j-i  -> volumen -985.7  (normales hacia
    #                                             dentro)
    #   invirtiendo solo los vértices a x-y-z -> volumen +985.7
    # Es decir, skimage devuelve el bobinado CON LAS NORMALES HACIA DENTRO, y la
    # inversión de ejes de aquí lo compensa por accidente pero lo compensa bien:
    # el resultado es una malla cerrada con volumen positivo y normales
    # hacia fuera, que es lo que necesitan el sombreado y la exportación.
    #
    # Por eso NO se voltean las caras aquí: hacerlo deja las normales hacia
    # dentro y la malla con volumen negativo (medido: cerebro -1384.7 cm3),
    # que se exporta como no válida.
    #
    # La orientación de las normales queda además ASEGURADA de forma explícita,
    # porque depende de la versión de skimage y no conviene depender de ello.
    faces = _asegurar_normales_exteriores(verts, faces)

    if verbose:
        modo = "refinada" if refinado else "directa"
        print(f"[CALIDAD] {estructura or 'malla':10s} {modo:8s} "
              f"spacing={objetivo:.3f}mm sigma={sigma_mm:.2f}mm "
              f"taubin={taubin_iter} -> {len(verts):,} verts, {len(faces):,} caras")
    return (verts, faces, volumen_mm3) if devolver_volumen else (verts, faces)


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
