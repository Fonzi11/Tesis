"""
Descubrimiento de rutas y de mallas STL para los visores.

Concentra todo el conocimiento del sistema de archivos (que es la parte que
mas se equivoca cuando el pipeline cambia) en un unico modulo sin Qt, de modo
que tanto la ventana principal como el visor 3D consulten exactamente las
mismas carpetas.

Rutas canonicas (identicas a las de `main.py` y `segmentacion_completa`):

    <raiz>/salidas/mallas              -> STL de maxima resolucion
    <raiz>/salidas/fbx                 -> FBX de exportacion
    <raiz>/salidas/segmentaciones_ai   -> NIfTI de las segmentaciones
    <raiz>/salidas/segmentaciones_ai/vistas_2d -> PNG de los cortes
"""

import os

import numpy as np

# src/ui_qt/mesh_store.py -> src/ui_qt -> src -> NEUROHUB -> <raiz>
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
RAIZ_DIR = os.path.dirname(BASE_DIR)

SALIDAS_DIR = os.path.join(RAIZ_DIR, "salidas")
MALLAS_DIR = os.path.join(SALIDAS_DIR, "mallas")
FBX_DIR = os.path.join(SALIDAS_DIR, "fbx")
SEG_AI_DIR = os.path.join(SALIDAS_DIR, "segmentaciones_ai")
SLICES_DIR = os.path.join(SEG_AI_DIR, "vistas_2d")
MODELOS_DIR = os.path.join(RAIZ_DIR, "archivo", "modelos_3d")

# Orden en que se dibujan las estructuras: primero las envolventes
# (craneo, cerebro) y despues las internas (tumor, aneurisma), que es
# como se presenta el caso en las Reuniones de Neuroimagen.
ORDEN_ESTRUCTURAS = ["craneo", "cerebro", "tumor", "aneurisma"]


def existe(path):
    return bool(path) and os.path.isdir(path)


def es_vacio(path):
    """True si el directorio no existe o no contiene archivos."""
    if not existe(path):
        return True
    return not any(os.scandir(path))


# ----------------------------------------------------------------------
def escanear_mallas(dirs=None, fbx_dir=None):
    """Descubre las estructuras 3D disponibles.

    Se consultan varias carpetas porque cada etapa escribe en un sitio
    distinto: los STL de `salidas/mallas` (fuente principal, geometria real)
    y los FBX de exportacion (solo se listan si no hay STL equivalente, para no
    duplicar la misma estructura en la lista de capas).

    La clave es el nombre de archivo en minusculas; el material se resuelve con
    `pbr.resolve_pbr`, que aplica los alias.
    """
    from .pbr import resolve_pbr

    modelos = {}
    IGNORED_KEYS = {"arterias", "venas", "vasos", "venas_arterias", "arteries", "veins", "vessels"}

    def _add(stl_path, name, fbx=None):
        key = os.path.splitext(name)[0].lower()
        if key in IGNORED_KEYS:
            return
        meta = resolve_pbr(key)
        modelos[key] = {
            "fbx": fbx,
            "stl": stl_path,
            "name": name,
            "label": meta.get("label", key.replace("_", " ").title()),
            "display": meta.get("display", "#8B8B8B"),
            "color_rgba": meta.get("color_rgba", (0.6, 0.6, 0.6, 1.0)),
        }

    for d in (dirs or [MALLAS_DIR, MODELOS_DIR]):
        if not existe(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".stl"):
                _add(os.path.join(d, f), f)

    # FBX de exportacion: solo anaden estructuras que no tengan STL.
    if existe(fbx_dir):
        for f in sorted(os.listdir(fbx_dir)):
            if not f.lower().endswith(".fbx"):
                continue
            key = os.path.splitext(f)[0].lower()
            if key in modelos:
                continue
            base = os.path.splitext(f)[0]
            for d in (MALLAS_DIR,):
                stl = os.path.join(d, base + ".stl")
                if os.path.isfile(stl):
                    _add(stl, f, fbx=os.path.join(fbx_dir, f))
                    break

    # Regla clinica mutua exclusion: Un paciente tiene tumor O aneurisma, NUNCA ambos.
    if "tumor" in modelos and "aneurisma" in modelos:
        del modelos["aneurisma"]

    # Orden estable: el de mayor interes clinico primero (ver ORDEN).
    def _rank(key):
        for i, name in enumerate(ORDEN_ESTRUCTURAS):
            if name in key:
                return i
        return len(ORDEN_ESTRUCTURAS)

    return dict(sorted(modelos.items(), key=lambda kv: _rank(kv[0])))


def rutas_serie(study_dir=None):
    """Devuelve el dict de rutas de trabajo de un estudio.

    `study_dir` es la carpeta que contiene los datos de entrada del caso. Si es
    None se usan las rutas globales de `salidas/`, que es como funcionaba la
    aplicacion Tk.
    """
    if not study_dir:
        return {
            "estudio": None,
            "segmentaciones": SEG_AI_DIR,
            "mallas": MALLAS_DIR,
            "fbx": FBX_DIR,
            "slices": SLICES_DIR,
        }
    return {
        "estudio": os.path.abspath(study_dir),
        "segmentaciones": os.path.join(study_dir, "segmentaciones_ai"),
        "mallas": os.path.join(study_dir, "mallas"),
        "fbx": os.path.join(study_dir, "fbx"),
        "slices": os.path.join(study_dir, "segmentaciones_ai", "vistas_2d"),
    }


def listar_cortes(slices_dir=SLICES_DIR):
    """Devuelve {eje: ruta_png} de las vistas 2D generadas.

    Los nombres que produce `_generar_vistas_2d` son `corte_axial.png`,
    `corte_coronal.png` y `corte_sagital.png`.
    """
    cortes = {}
    if not existe(slices_dir):
        return cortes
    for f in sorted(os.listdir(slices_dir)):
        if not f.lower().endswith(".png"):
            continue
        base = os.path.splitext(f)[0].lower()
        eje = "axial"
        for e in ("axial", "coronal", "sagital"):
            if e in base:
                eje = e
                break
        cortes[eje] = os.path.join(slices_dir, f)
    return cortes


# Nombres del volumen del paciente, en el orden de preferencia. El visor 2D
# necesita el volumen (no los PNG) para poder navegar y delinear: sin él solo
# se puede mirar una imagen fija.
NOMBRES_VOLUMEN = (
    "volumen_paciente.nii.gz",   # lo que escribe el pipeline
    "MRBrainTumor1.nii.gz",      # muestra del repositorio
    "t1.nii.gz",                 # volunteer de ejemplo
)

# Subcarpetas donde puede estar el volumen, en orden de preferencia. El
# pipeline lo deja en `segmentaciones_ai`, pero un caso suelto puede traerlo
# en la raiz o en `volumen`: se miran todas para no depender de donde vino.
SUBCARPETAS_VOLUMEN = ("segmentaciones_ai", "volumen", "nifti", "")

# Sufijos de los volumenes BraTS multimodales. Un caso real NO se llama
# `MRBrainTumor1.nii.gz`: trae una imagen por modalidad
# (`<id>_t1.nii.gz`, `<id>_t1ce.nii.gz`, `<id>_t2.nii.gz`, `<id>_flair.nii.gz`)
# y la de FLAIR es la que se usa para delineado de tumor, porque es donde el
# edema y la parte realzada del tumor se ven mejor. Sin esta lista, `buscar_volumen`
# devolvia None para todo caso de verdad, el visor 2D se caia al modo
# visor-de-PNG y los botones de Pincel y Borrar quedaban DESACTIVADOS: era el
# motivo de que "dibujar y borrar no funcionaba".
SUFIJOS_VOLUMEN_BRATS = ("flair", "t1ce", "t2", "t1")

# Sufijos que SI son máscaras y jamas deben tomarse como imagen de fondo.
SUFIJOS_MASCARA = ("seg", "mask", "label")

# Raices anatomicas de los NOMBRES de etiqueta (TotalSegmentator y similares).
# No se listan todas: son casi cien y crecerian con cada modelo. Es una red de
# seguridad por NOMBRE, para cuando no se puede leer el fichero; la red real es
# `_parece_imagen`.
RAICES_ETIQUETA = (
    "adrenal", "vertebra", "vertebrae", "aorta", "aneurysm", "artery",
    "vein", "vena", "arteria", "venae", "lung", "liver", "kidney", "spleen",
    "stomach", "pancreas", "thyroid", "colon", "bladder", "prostate", "uter",
    "heart", "myocard", "esoph", "trachea", "rib", "sternum", "scapula",
    "clavicle", "pelvis", "femur", "humer", "tibia", "fibula", "ulna",
    "radius", "vertebra", "skull", "brain", "cerebell", "brainstem",
    "eyeball", "optic", "face", "mouth", "tongue", "pharyn", "laryn",
    "sinus", "ear", "nose", "muscle", "glute", "quadrice", "hamstring",
    "tendon", "ligament", "cartilage", "bone", "marrow", "hip", "knee",
    "ankle", "wrist", "hand", "foot", "shoulder", "elbow", "knee",
)

# Una imagen de RM/CT tiene muchos valores de gris distintos; una etiqueta
# multi-clase, poquisimas. El corte separates es holgado a proposito: una
# mascara binaria da 2, y una segmentacion de TotalSegmentator, menos de 100.
IMAGEN_MIN_VALORES = 48

_cache_gris = {}


def _cuantos_valores(ruta):
    """(ok, n_valores) leyendo la NIfTI. `ok=False` si no se pudo leer."""
    clave = os.path.normcase(os.path.abspath(ruta))
    if clave in _cache_gris:
        return _cache_gris[clave]
    res = (False, 0)
    try:
        import SimpleITK as sitk

        img = sitk.ReadImage(ruta)
        # Muestreo: no hace falta recorrer el volumen entero para distinguir
        # una imagen de una etiqueta, y asi el coste no depende del tamano.
        arr = sitk.GetArrayViewFromImage(img)
        paso = max(1, int(arr.size ** 0.5) // 512)
        res = (True, int(np.unique(arr.reshape(-1)[::paso]).size))
    except Exception:                                       # noqa: BLE001
        res = (False, 0)
    _cache_gris[clave] = res
    return res


def _parece_imagen(ruta):
    """True si `ruta` es una IMAGEN y no una etiqueta.

    El fallo que motiva esto: `vertebrae_T2.nii.gz` cumple el patron BraTS
    `*_t2.nii.gz`, asi que `listar_volumenes` lo elegia como fondo del visor 2D.
    El panel se llenaba con una mascara de vertebra en escala de grises y el
    tumor delineado encima: en pantalla "no se ve nada" que Reconozcas. Se
    comprueba el CONTENIDO, no el nombre, porque el nombre no basta.
    """
    ok, n = _cuantos_valores(ruta)
    if not ok:
        # Sin SimpleITK (o con un NIfTI raro) solo se puede mirar el nombre.
        base = os.path.basename(ruta).lower()
        return not any(base.startswith(r) or f"_{r}" in base
                       for r in RAICES_ETIQUETA)
    return n >= IMAGEN_MIN_VALORES


def _es_nombre_volumen(base):
    """True si `base` (nombre en minusculas) parece una IMAGEN, no una máscara.

    Se descarta cualquier nombre que sea una segmentacion (`*_seg`, `*_label`)
    o una mascara generica, porque superponer la mascara sobre si misma
    daria una imagen de tumor solido en lugar de tejido.
    """
    if any(s in base for s in SUFIJOS_MASCARA):
        return False
    # `tumor`, `brain`, `skull`... son etiquetas, no la imagen del paciente.
    if any(f"_{e}" in base or base.startswith(e)
           for e in ("tumor", "brain", "skull", "neces", "arter", "vena")):
        return False
    return not any(base.startswith(r) or f"_{r}" in base
                   for r in RAICES_ETIQUETA)


def listar_volumenes(*directorios):
    """Rutas NIfTI de IMAGEN candidatas a ser el volumen del paciente.

    Devuelve la lista ordenada por preferencia: primero los nombres conocidos
    (`NOMBRES_VOLUMEN`), luego las BraTS por sufijo de modalidad, y por ultimo
    cualquier otra NIfTI que no sea una mascara. `buscar_volumen` usa esta
    funcion, de modo que un caso con el nombre que sea entra igual.
    """
    vistos, out = set(), []

    def _add(ruta):
        clave = os.path.normcase(os.path.abspath(ruta))
        if clave not in vistos:
            vistos.add(clave)
            out.append(ruta)

    candidatos = []
    for base in _directorios_candidatos(directorios):
        try:
            entradas = sorted(os.listdir(base))
        except OSError:
            continue
        for f in entradas:
            if not f.lower().endswith((".nii", ".nii.gz")):
                continue
            ruta = os.path.join(base, f)
            if not os.path.isfile(ruta):
                continue
            candidatos.append((f, ruta))

    # 1) Nombres conocidos, tal cual estan definidos arriba.
    for nombre in NOMBRES_VOLUMEN:
        for f, ruta in candidatos:
            if f.lower() == nombre.lower():
                _add(ruta)
    # 2) BraTS multimodal, por sufijo de modalidad (flair tiene prioridad).
    #    Se comprueba el CONTENIDO: `vertebrae_T2.nii.gz` tambien acaba en
    #    `_t2.nii.gz` y era una etiqueta, no la imagen del paciente.
    for sufijo in SUFIJOS_VOLUMEN_BRATS:
        for f, ruta in candidatos:
            b = f.lower()
            if b.endswith(f"_{sufijo}.nii.gz") or b == f"{sufijo}.nii.gz":
                if _parece_imagen(ruta):
                    _add(ruta)
    # 3) Cualquier otra imagen que no sea una mascara.
    for f, ruta in candidatos:
        if _es_nombre_volumen(f.lower()) and _parece_imagen(ruta):
            _add(ruta)
    return out

# Nombres de la máscara de tumor, en el orden de preferencia. El manual va
# primero: si el usuario ha delineado, esa es la que manda.
NOMBRES_MASCARA_TUMOR = (
    "tumor_manual.nii.gz",
    "tumor_brats.nii.gz",
    "tumor_heuristica.nii.gz",
    "tumor_heur.nii.gz",
    "tumor.nii.gz",
)


def _directorios_candidatos(directorios):
    """Normaliza la lista de directorios a probar, sin repetir y en orden."""
    vistos, out = set(), []
    for d in (directorios or []):
        if not d:
            continue
        for sub in SUBCARPETAS_VOLUMEN:
            base = os.path.abspath(os.path.join(d, sub)) if sub \
                else os.path.abspath(d)
            if base not in vistos and os.path.isdir(base):
                vistos.add(base)
                out.append(base)
    return out


def buscar_volumen(*directorios):
    """Primera ruta de volumen del paciente que exista en los directorios dados.

    Devuelve None si no hay ninguno, que es el caso legitimo de un estudio sin
    imagen: el visor 2D cae entonces al modo visor-de-PNG.

    Antes solo miraba una lista corta de nombres fijos (`volumen_paciente`,
    `MRBrainTumor1`, `t1`), que no incluye los nombres reales de BraTS. Con un
    caso de verdad devolvia None siempre, y el visor 2D se quedaba sin imagen
    navegable y SIN herramientas de delineado. Ahora delega en
    `listar_volumenes`, que ademas descarta las mascaras.
    """
    volumenes = listar_volumenes(*directorios)
    return volumenes[0] if volumenes else None


def buscar_mascara_tumor(*directorios):
    """Primera ruta de máscara de tumor existente, priorizando la manual."""
    for base in _directorios_candidatos(directorios):
        for nombre in NOMBRES_MASCARA_TUMOR:
            ruta = os.path.join(base, nombre)
            if os.path.isfile(ruta):
                return ruta
    return None


def buscar_mascara_compatible(mascaras, volumen_path):
    """Primera máscara de `mascaras` que COMPARTE REJILLA con el volumen.

    Existe por un fallo que hacia inutilizable el delineado manual: si la
    máscara elegida no cuadraba con la imagen, `Volumen2D.cargar_mascara`
    levanta `ValueError` a proposito, y `_cargar_volumen_2d` se comia la
    excepcion haciendo `set_volumen(None)`. El visor se quedaba vacio y los
    botones de Pincel y Borrar, desactivados. Ahora se recorren las candidatas
    en orden y se devuelve la primera que encaja en tamaño, de modo que un
    tumor_brats de otra rejilla ya no impide pintar a mano.
    """
    if not volumen_path or not os.path.exists(volumen_path):
        return None
    try:
        import SimpleITK as sitk

        ref = sitk.ReadImage(volumen_path)
        tamano = ref.GetSize()
    except Exception:                                       # noqa: BLE001
        return mascaras[0] if mascaras else None

    for ruta in mascaras or []:
        if not ruta or not os.path.exists(ruta):
            continue
        try:
            if sitk.ReadImage(ruta).GetSize() == tamano:
                return ruta
        except Exception:                                   # noqa: BLE001
            continue
    return None


def listar_mascaras_tumor(*directorios):
    """Rutas de máscara de tumor candidatas, en orden de preferencia.

    La manual va primero, luego las del pipeline, y al final la segmentación
    BraTS (`*_seg.nii.gz`), que es como se llama la máscara en los datos
    reales y no aparecía en la lista de nombres.
    """
    vistas, out = set(), []

    def _add(ruta):
        clave = os.path.normcase(os.path.abspath(ruta))
        if clave not in vistas:
            vistas.add(clave)
            out.append(ruta)

    for base in _directorios_candidatos(directorios):
        for nombre in NOMBRES_MASCARA_TUMOR:
            ruta = os.path.join(base, nombre)
            if os.path.isfile(ruta):
                _add(ruta)
        try:
            entradas = sorted(os.listdir(base))
        except OSError:
            continue
        for f in entradas:
            b = f.lower()
            if not b.endswith((".nii", ".nii.gz")):
                continue
            if b.endswith("_seg.nii.gz") or b.endswith("_seg.nii"):
                _add(os.path.join(base, f))
    return out
