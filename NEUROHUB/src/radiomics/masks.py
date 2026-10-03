"""
Definicion de mascaras y regiones de interes (ROI) en formato Raids-RADS.

Raidionics no calcula radiomics sobre "el tumor" como un bloque unico, sino
sobre los compartimentos que define el sistema Raids-RADS:

    NETC  necrosis / tejido no realzado
    ET    tejido realzado con contraste
    SNFH  hiperintensidad en FLAIR
    TC    tumor core = ET + NETC
    WT    whole tumor = ET + NETC + SNFH

Aqui se reproducen esas definiciones junto con las estructuras anatomicas de
interes para neuroimagen (cerebro, craneo, cerebelo, tronco, ventriculos,
hipocampo...), y las funciones que las construyen a partir de los NIfTI que
produce el pipeline de NEUROHUB.

Los nombres de archivo son los que escribe `segmentacion_completa` y
`03_integrar_brats`, de modo que estas ROI se resuelven sin conversiones.
"""

import os

# =============================================================================
# COMPARTIMENTOS TUMORALES (Raids-RADS)
# =============================================================================
# Orden clinico: de mas interno a mas externo.
COMPARTIMENTOS_TUMOR = ["NETC", "ET", "SNFH"]

# Composicion de cada region derivada. Los valores son conjuntos de etiquetas.
COMPOSICION = {
    "NETC": {"NETC"},
    "ET": {"ET"},
    "SNFH": {"SNFH"},
    "TC": {"ET", "NETC"},
    "WT": {"ET", "NETC", "SNFH"},
    "TUMOR": {"ET", "NETC", "SNFH"},
}

# Etiquetas enteras que usa `03_integrar_brats` al fusionar las mascaras BraTS.
# BraTS publica Enhancing(1)/Necrotic(2)/Edema(3); aqui se adopta esa misma
# convencion para que un NIfTI de third-party se pueda leer sin remapear.
ETIQUETA_ET = 1
ETIQUETA_NETC = 2
ETIQUETA_SNFH = 3



# =============================================================================
# ESTRUCTURAS ANATOMICAS
# =============================================================================
# clave -> nombre de etiqueta en el esquema Raids-RADS / TotalSegmentator.
ANATOMIA = {
    "cerebro":        "brain",
    "craneo":         "skull",
    "cerebelo":       "cerebellum",
    "tronco":         "brainstem",
    "hipocampo_izq":  "hippocampusleft",
    "hipocampo_der":  "hippocampusright",
    "ventriculo_lat": "lateralventricleleft",
    "ventriculo_III": "thirdventricle",
}

# Orden de presentacion clinico (de mayor a menor volumen habitual).
ORDEN_ANATOMICO = ["cerebro", "cerebelo", "tronco", "craneo",
                   "ventriculo_lat", "ventriculo_III",
                   "hipocampo_izq", "hipocampo_der"]

# =============================================================================
# UNIDADES
# =============================================================================
UNIDADES_RANO = {
    "volumen_mm3": "mm3",
    "volumen_cm3": "cm3",
    "diametro_mm": "mm",
    "superficie_mm2": "mm2",
}


class MaskLabelMap:
    """
    Mapa de etiquetas voxel a voxel con su geometria fisica.

    Es el unico objeto que necesitan los rasgos: sabe los indices de los
    voxeles que pertenecen a la ROI y el volumen fisico de cada vóxel, que es
    lo que convierte "cuantos voxeles" en milimetros cubicos reales.

    Se construye con `de_nifti` (SimpleITK) o `de_array` (para volumen ya
    cargados en memoria).
    """

    __slots__ = ("array", "spacing", "origin", "direction", "etiquetas",
                 "nombre")

    def __init__(self, array, spacing, etiquetas, nombre="ROI",
                 origin=(0.0, 0.0, 0.0), direction=None):
        self.array = array
        self.spacing = tuple(float(s) for s in spacing)
        self.origin = tuple(float(o) for o in origin)
        self.direction = direction
        self.etiquetas = set(etiquetas)
        self.nombre = nombre

    # ------------------------------------------------------------------
    @property
    def voxeles_mm3(self):
        """Volumen fisico de un vóxel (mm3)."""
        sx, sy, sz = self.spacing
        return sx * sy * sz

    @property
    def n_voxeles(self):
        """Voxeles totales de la ROI (cualquier etiqueta de `etiquetas`)."""
        return int(_contar(self.array, self.etiquetas))

    def mascara(self):
        """
        Array booleano con la ROI completa, para calculos geometricos.

        Devuelve un array 3D de bool con la misma forma que el mapa de
        etiquetas, que es lo que esperan tanto los rasgos de forma como las
        texturas.
        """
        return _mascara(self.array, self.etiquetas)

    def subregion(self, etiquetas, nombre=None):
        """Crea una ROI nueva restringida a un subconjunto de etiquetas."""
        return MaskLabelMap(
            self.array, self.spacing, etiquetas,
            nombre or self.nombre, self.origin, self.direction,
        )

    def etiqueta_presente(self, etiqueta):
        """True si la ROI contiene al menos un voxel de esa etiqueta."""
        return _contar(self.array, {etiqueta}) > 0

    def resumen(self):
        """Diccionario de conteos por etiqueta, para la consola de la UI."""
        out = {}
        for e in sorted(self.etiquetas):
            n = _contar(self.array, {e})
            if n:
                out[e] = n
        return out

    def __repr__(self):
        return (f"<MaskLabelMap {self.nombre} etiquetas={sorted(self.etiquetas)} "
                f"spacing={self.spacing} voxeles={self.n_voxeles}>")


# =============================================================================
# CONSTRUCTORES
# =============================================================================
def _mascara(array, etiquetas):
    out = None
    for e in etiquetas:
        m = (array == e)
        out = m if out is None else (out | m)
    return out if out is not None else (array == -1)


def _contar(array, etiquetas):
    total = 0
    for e in etiquetas:
        total += int((array == e).sum())
    return total



def de_nifti(ruta, etiquetas, nombre=None):
    """
    Carga un NIfTI y devuelve la ROI que ocupa `etiquetas`.

    `etiquetas` puede ser un int o un iterable de ints. Se acepta tambien la
    convencion BraTS, donde la mascara es binaria (1 = tumor) y se pide
    `etiquetas=(1,)`.
    """
    import SimpleITK as sitk

    if not ruta or not os.path.exists(ruta):
        raise FileNotFoundError(ruta)
    img = sitk.ReadImage(ruta)
    arr = sitk.GetArrayFromImage(img)          # (z, y, x)
    if isinstance(etiquetas, int):
        etiquetas = {etiquetas}
    return MaskLabelMap(
        arr, img.GetSpacing(), etiquetas,
        nombre or os.path.splitext(os.path.basename(ruta))[0],
        img.GetOrigin(), img.GetDirection(),
    )


def de_array(array, spacing, etiquetas, nombre="ROI"):
    """ROI a partir de un array ya en memoria (indice [z, y, x])."""
    if isinstance(etiquetas, int):
        etiquetas = {etiquetas}
    return MaskLabelMap(array, spacing, etiquetas, nombre)


# =============================================================================
# ESTRUCTURA DE LAS ROI
# =============================================================================
def estructura_mascara(tumor_roi, incluir_anatomia=True, incluir_tumor=True,
                       solo_rois_no_vacias=True):
    """
    Arma el diccionario `{nombre_roi: MaskLabelMap}` que consume el extractor.

    Es la equivalencia funcional de `RadiomicsStudy` de Raidionics: dada una
    mascara de tumor fusionada, devuelve el mismo juego de ROI que calcula la
    aplicacion (compartimentos + anatomia), de modo que las columnas del CSV
    generado sean las mismas.

    Parametros
    ----------
    tumor_roi : MaskLabelMap
        Mapa de etiquetas con al menos los compartimentos del tumor.
    incluir_anatomia : bool
        Anade cerebro/craneo/ventriculos/hipocampo mediante `rois_raidionics`.
    incluir_tumor : bool
        Anade los compartimentos y las regiones derivadas TC/WT.
    solo_rois_no_vacias : bool
        Descarta ROI sin voxeles, que generarian NaN en todas las columnas y
        ensuciarian el informe.
    """
    rois = {}

    # ---- Compartimentos tumorales (Raids-RADS) ------------------------
    if incluir_tumor:
        for comp in COMPARTIMENTOS_TUMOR:
            rois[f"Tumor_{comp}"] = tumor_roi.subregion(
                {comp}, f"Tumor_{comp}")

    # ---- Regiones derivadas -------------------------------------------
    for nombre, composicion in COMPOSICION.items():
        if nombre in ("NETC", "ET", "SNFH"):
            continue
        rois[nombre] = tumor_roi.subregion(composicion, nombre)

    # ---- Anatomia ------------------------------------------------------
    if incluir_anatomia:
        rois.update(rois_raidionics(tumor_roi,
                                   solo_no_vacias=solo_rois_no_vacias))

    if solo_rois_no_vacias:
        rois = {k: v for k, v in rois.items() if v.n_voxeles > 0}

    return rois


def rois_raidionics(tumor_roi, solo_no_vacias=True):
    """
    ROI anatomicas de un mapa de etiquetas generico.

    Raidionics define su propio esquema de etiquetas (Brain, Skull,
    LateralVentricle, Hippocampus...). Se aceptan las claves internas de
    NEUROHUB y las de TotalSegmentator, de modo que la misma funcion sirva
    para un `brain.nii.gz` de TotalSegmentator o para una mascara fusionada
    por el pipeline.
    """
    import numpy as np

    # (nombre_roi, alias aceptados). Se recorren en orden clinico.
    candidatos = [
        ("cerebro", ("brain", "cerebro", "Brain", 1)),
        ("craneo", ("skull", "craneo", "Skull", 2)),
        ("cerebelo", ("cerebellum", "cerebelo", "Cerebellum", 3)),
        ("tronco", ("brainstem", "tronco", "Brainstem", 4)),
        ("hipocampo_izq", ("hippocampusleft", "hipocampo_izq",
                           "HippocampusLeft", 5)),
        ("hipocampo_der", ("hippocampusright", "hipocampo_der",
                           "HippocampusRight", 6)),
        ("ventriculo_lat", ("lateralventricleleft", "ventriculo_lat",
                            "LateralVentricleLeft", 7)),
        ("ventriculo_III", ("thirdventricle", "ventriculo_III",
                            "ThirdVentricle", 8)),
    ]

    # Se recorre el array una sola vez para descubrir que etiquetas existen
    # de verdad, en vez de lanzar una comparacion completa por cada ROI.
    presentes = set(int(v) for v in np.unique(tumor_roi.array))

    rois = {}
    for nombre, alias in candidatos:
        for e in alias:
            try:
                valor = int(e)
            except (TypeError, ValueError):
                continue
            if valor in presentes:
                rois[nombre] = tumor_roi.subregion({valor}, nombre)
                break

    if solo_no_vacias:
        rois = {k: v for k, v in rois.items() if v.n_voxeles > 0}
    return rois



def magmas_braTS(tumor_roi=None, array=None, spacing=None,
                 etiquetas=(1, 2, 3), nombre="BraTS"):
    """
    Convierte una mascara BraTS multietiqueta en las ROI de Raids-RADS.

    BraTS codifica Enhancing=1, Necrotic(NE/NET)=2 y Edema(FLAIR)=3, que es
    justo la convencion de `COMPARTIMENTOS_TUMOR`. Si la mascara es binaria
    (BraTS de modalidad unica), todo el tumor se atribuye a SNFH, que es la
    lectura conservadora: en una sola secuencia no se puede distinguir realce
    de necrosis.
    """
    import numpy as np

    if tumor_roi is None:
        if array is None:
            raise ValueError("se requiere tumor_roi o array")
        tumor_roi = de_array(array, spacing or (1.0, 1.0, 1.0), etiquetas,
                             nombre)

    presentes = set(int(v) for v in np.unique(tumor_roi.array))
    unicos = presentes & set(etiquetas)

    if not unicos:
        return {}

    if unicos == {1}:
        # Binario: un unico compartamiento, atribuido a SNFH.
        return {
            "Tumor_SNFH": tumor_roi.subregion({1}, "Tumor_SNFH"),
            "WT": tumor_roi.subregion({1}, "WT"),
        }

    mapa = {}
    for comp, etiqueta in (("ET", 1), ("NETC", 2), ("SNFH", 3)):
        if etiqueta in unicos:
            mapa[f"Tumor_{comp}"] = tumor_roi.subregion({etiqueta},
                                                        f"Tumor_{comp}")
    mapa["TC"] = tumor_roi.subregion(unicos & {1, 2}, "TC")
    mapa["WT"] = tumor_roi.subregion(unicos, "WT")
    return {k: v for k, v in mapa.items() if v.n_voxeles > 0}
