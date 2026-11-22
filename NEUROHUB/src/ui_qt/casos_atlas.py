"""
Catálogo de los casos ATLAS listos para revisar.

Cada caso es una carpeta de `salidas/modelos_ar_freesurfer/<caso>` generada por
`herramientas/modelos_ar_freesurfer.py` (mallas STL en LPS mm y `resumen.json`)
y, opcionalmente, por `herramientas/ar_visor2d.py` (volúmenes 2D en una sola
rejilla). Todas las estructuras de un caso comparten sistema de coordenadas,
que es lo que la carpeta global `salidas/mallas` no garantizaba: allí convivían
mallas de pacientes distintos y el visor las superponía desalineadas.
"""

import json
import os

from .mesh_store import RAIZ_DIR

CASOS_DIR = os.path.join(RAIZ_DIR, "salidas", "modelos_ar_freesurfer")

# Grupos de capas: los mismos que usa la app de realidad mixta (Unity), en el
# orden en que se "pelan" de fuera hacia dentro.
GRUPOS = [
    ("craneo", "Cráneo"),
    ("corteza", "Corteza cerebral"),
    ("sustancia_blanca", "Sustancia blanca"),
    ("cerebelo_tronco", "Cerebelo y tronco"),
    ("ventriculos", "Ventrículos"),
    ("profundas", "Núcleos profundos"),
    ("vasos", "Vasos"),
    ("lesion", "Lesión"),
]
NOMBRE_GRUPO = dict(GRUPOS)


def grupo_de(clave):
    """Grupo de capa de una estructura a partir de su identificador."""
    k = (clave or "").lower()
    if k.startswith(("tumor", "aneurisma", "lesion")):
        return "lesion"
    if k.startswith(("craneo", "skull")):
        return "craneo"
    if k.startswith(("arteria", "vaso", "vena")):
        return "vasos"
    if k.startswith(("corteza", "fs_cortex", "cerebro")):
        return "corteza"
    if k.startswith(("sustancia_blanca", "fs_white", "freesurfer_")):
        return "sustancia_blanca"
    if k.startswith(("cerebelo", "tronco", "fs_cerebellum", "fs_brainstem")):
        return "cerebelo_tronco"
    if k.startswith(("ventriculo", "fs_ventricles")):
        return "ventriculos"
    return "profundas"


def _hex(rgb):
    r, g, b = (max(0, min(255, int(round(float(c) * 255)))) for c in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


_DESCRIPCION = {
    "tumor_02": ("HUSI · Tumor 02", "RM 3D + TC del paciente"),
    "aneurisma_05": ("HUSI · Aneurisma 05", "TC + angio-TC del paciente"),
}


def _titulo(caso_id):
    if caso_id in _DESCRIPCION:
        return _DESCRIPCION[caso_id]
    if caso_id.startswith("brats_"):
        return (f"BraTS 2021 · {caso_id.split('_', 1)[1]}",
                "RM multiparamétrica pública")
    return (caso_id.replace("_", " ").title(), "")


def cargar_caso(carpeta):
    """Lee un caso. Devuelve None si la carpeta no es un caso ATLAS válido."""
    resumen_path = os.path.join(carpeta, "resumen.json")
    if not os.path.isfile(resumen_path):
        return None
    try:
        with open(resumen_path, encoding="utf-8") as f:
            resumen = json.load(f)
    except (OSError, ValueError):
        return None

    caso_id = resumen.get("caso") or os.path.basename(carpeta)
    modelos = {}
    lesion_tipo = None
    for est in resumen.get("estructuras", []):
        stl = os.path.join(carpeta, est.get("stl", ""))
        if not os.path.isfile(stl):
            continue
        clave = est["id"]
        grupo = grupo_de(clave)
        if grupo == "lesion":
            lesion_tipo = "aneurisma" if clave.startswith("aneurisma") else "tumor"
        color = est.get("color") or (0.7, 0.7, 0.7)
        modelos[clave] = {
            "stl": stl,
            "label": est.get("nombre") or clave.replace("_", " ").capitalize(),
            "display": _hex(color),
            "color_rgba": (float(color[0]), float(color[1]), float(color[2]), 1.0),
            "opacity": float(est.get("opacidad", 1.0)),
            "grupo": grupo,
            "volumen_cm3": est.get("volumen_cm3"),
        }
    if not modelos:
        return None

    titulo, subtitulo = _titulo(caso_id)
    visor = os.path.join(carpeta, "visor2d")
    v2d = None
    if os.path.isfile(os.path.join(visor, "imagen.nii.gz")):
        info = {}
        try:
            with open(os.path.join(visor, "info.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        v2d = {
            "imagen": os.path.join(visor, "imagen.nii.gz"),
            "anatomia": _si_existe(os.path.join(visor, "anatomia.nii.gz")),
            "lesion": _si_existe(os.path.join(visor, "lesion.nii.gz")),
            "info": info,
        }
    return {
        "id": caso_id,
        "titulo": titulo,
        "subtitulo": subtitulo,
        "carpeta": carpeta,
        "lesion": lesion_tipo,
        "modelos": modelos,
        "visor2d": v2d,
        "segmentacion": resumen.get("segmentacion_anatomica", ""),
        "segmentacion_lesion": resumen.get("segmentacion_tumor")
        or resumen.get("segmentacion_lesion", ""),
        "triangulos": resumen.get("triangulos_total"),
    }


def _si_existe(ruta):
    return ruta if os.path.isfile(ruta) else None


def listar_casos(base=CASOS_DIR):
    """Casos válidos de `base`, primero los del HUSI y luego los públicos."""
    if not os.path.isdir(base):
        return []
    casos = []
    for nombre in sorted(os.listdir(base)):
        if nombre.startswith("_"):
            continue
        caso = cargar_caso(os.path.join(base, nombre))
        if caso is not None:
            casos.append(caso)
    casos.sort(key=lambda c: (c["id"].startswith("brats_"), c["id"]))
    return casos
