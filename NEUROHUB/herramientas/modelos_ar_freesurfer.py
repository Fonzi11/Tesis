"""Modelos 3D translúcidos para realidad aumentada a partir de FreeSurfer.

Entrada por caso:
  * segmentación FreeSurfer SynthSeg con ``--parc`` (etiquetas ASEG + DKT),
  * segmentación del tumor con etiquetas BraTS (1 necrosis, 2 edema, 4 realce).

Salida por caso (``<salida>/<caso>/``):
  * ``<caso>_AR.glb``        escena completa, materiales PBR con alphaMode BLEND,
  * ``<caso>_AR_ligero.glb`` la misma escena con ~1/4 de triángulos (HoloLens),
  * ``stl/<id>.stl``         cada estructura en mm, coordenadas LPS (3D Slicer),
  * ``resumen.json``         volúmenes, triángulos, colores y opacidades.

Todas las mallas comparten el mismo sistema de coordenadas físico, de modo que
anatomía y tumor quedan superpuestos sin registro adicional. En glTF el modelo
se centra en el cerebro, en metros, con +Y superior y +Z anterior.
"""
import argparse
import json
import os
import sys

import numpy as np
import SimpleITK as sitk
import trimesh
from scipy import ndimage

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "src"))
from calidad_mallas import _asegurar_normales_exteriores, malla_alta_calidad  # noqa: E402

# Lóbulos a partir de la parcelación Desikan-Killiany (índice dentro de 1000/2000).
LOBULOS = {
    "frontal": [3, 12, 14, 17, 18, 19, 20, 27, 28, 32],
    "motora": [24],  # giro precentral: corteza motora primaria
    "parietal": [8, 22, 25, 29, 31],
    "temporal": [1, 6, 7, 9, 15, 16, 30, 33, 34],
    "occipital": [5, 11, 13, 21],
    "cingulado": [2, 10, 23, 26],
    "insula": [35],
}
COLOR_LOBULO = {
    "frontal": (0.36, 0.62, 0.95), "motora": (0.98, 0.80, 0.20),
    "parietal": (0.40, 0.85, 0.55), "temporal": (0.98, 0.58, 0.30),
    "occipital": (0.72, 0.52, 0.95), "cingulado": (0.95, 0.45, 0.70),
    "insula": (0.35, 0.85, 0.85),
}

# id, nombre, etiquetas, color RGB, opacidad, perfil de malla, triángulos objetivo
ANATOMIA = []
for hemi, base, lado in (("izq", 1000, "izquierda"), ("der", 2000, "derecha")):
    for lobulo, indices in LOBULOS.items():
        ANATOMIA.append((
            "corteza_%s_%s" % (lobulo, hemi),
            "Corteza %s %s" % (lobulo, lado),
            [base + i for i in indices], COLOR_LOBULO[lobulo], 0.16,
            {"sigma_mm": 0.7, "taubin_iter": 25, "objetivo_mm": 0.5}, 1.0))
# El último campo es el peso relativo en el reparto del presupuesto de
# triángulos (se multiplica por la superficie de la malla): las estructuras
# pequeñas y el tumor reciben más densidad porque se miran de cerca.
ANATOMIA += [
    ("sustancia_blanca_izq", "Sustancia blanca izquierda", [2],
     (0.92, 0.92, 0.88), 0.06, {"sigma_mm": 0.8, "taubin_iter": 25}, 0.6),
    ("sustancia_blanca_der", "Sustancia blanca derecha", [41],
     (0.92, 0.92, 0.88), 0.06, {"sigma_mm": 0.8, "taubin_iter": 25}, 0.6),
    ("ventriculos", "Sistema ventricular", [4, 5, 14, 15, 43, 44],
     (0.25, 0.55, 1.00), 0.55, {"sigma_mm": 0.8, "taubin_iter": 25}, 1.0),
    ("talamo", "Tálamos", [10, 49], (0.20, 0.80, 0.30), 0.80, None, 1.5),
    ("caudado", "Núcleos caudados", [11, 50], (0.55, 0.85, 1.00), 0.80, None, 1.5),
    ("putamen", "Putámenes", [12, 51], (0.95, 0.55, 0.75), 0.80, None, 1.5),
    ("globo_palido", "Globos pálidos", [13, 52], (0.30, 0.40, 0.95), 0.80, None, 1.5),
    ("hipocampo", "Hipocampos", [17, 53], (1.00, 0.85, 0.30), 0.85, None, 1.5),
    ("amigdala", "Amígdalas", [18, 54], (0.40, 0.95, 0.90), 0.85, None, 1.5),
    ("accumbens", "Núcleos accumbens", [26, 58], (1.00, 0.65, 0.20), 0.85, None, 1.5),
    ("diencefalo_ventral", "Diencéfalo ventral", [28, 60],
     (0.65, 0.40, 0.25), 0.70, None, 1.0),
    ("tronco_encefalico", "Tronco encefálico", [16], (0.55, 0.75, 0.35), 0.55,
     {"sigma_mm": 1.0, "taubin_iter": 30}, 1.0),
    ("cerebelo", "Cerebelo", [7, 8, 46, 47], (0.92, 0.75, 0.45), 0.35,
     {"sigma_mm": 0.8, "taubin_iter": 25}, 0.8),
]
# Tumor: capas anidadas para que ninguna superficie coincida con otra (evita
# parpadeo por z-fighting en el visor AR). La capa exterior es la extensión
# total con edema, muy translúcida; dentro, el tumor con realce y la necrosis.
# ``volumen`` indica las etiquetas cuyo volumen se informa para cada capa.
TUMOR = [
    ("tumor_edema", "Edema peritumoral (extensión total)", [1, 2, 4],
     (0.30, 0.90, 0.95), 0.25, {"sigma_mm": 1.0, "taubin_iter": 30}, 3.0),
    ("tumor_realce", "Tumor con realce", [1, 4], (1.00, 0.15, 0.25), 0.85,
     {"sigma_mm": 0.8, "taubin_iter": 30}, 4.0),
    ("tumor_necrosis", "Núcleo necrótico", [1], (1.00, 0.85, 0.10), 0.95,
     {"sigma_mm": 0.8, "taubin_iter": 30}, 4.0),
]
VOLUMEN_INFORMADO = {"tumor_edema": [2], "tumor_realce": [4],
                     "tumor_necrosis": [1]}

# Capas binarias opcionales (máscara 0/1 en su propia rejilla).
EXTRAS = {
    # Envoltura ósea fina: suavizado bajo para no abrir la calota.
    "craneo": ("Cráneo", (0.93, 0.90, 0.82), 0.18,
               {"sigma_mm": 0.5, "taubin_iter": 20, "objetivo_mm": 0.6}, 0.5),
    "arterias": ("Arterias intracraneales", (0.86, 0.10, 0.12), 0.90,
                 {"sigma_mm": 0.3, "taubin_iter": 12, "objetivo_mm": 0.35}, 2.0),
    "aneurisma": ("Aneurisma sacular", (1.00, 0.85, 0.10), 0.95,
                  {"sigma_mm": 0.35, "taubin_iter": 15, "objetivo_mm": 0.3}, 6.0),
}

# Presupuesto de triángulos por caso. Completo: Quest 3 / escritorio;
# ligero: HoloLens 2 y móviles.
PRESUPUESTO_COMPLETO = 700000
PRESUPUESTO_LIGERO = 175000


def _cargar(ruta):
    img = sitk.ReadImage(ruta)
    return img, sitk.GetArrayFromImage(img)


def _a_fisico(verts, img):
    """Vértices (mm en ejes de índice x,y,z) -> coordenadas físicas LPS."""
    d = np.array(img.GetDirection()).reshape(3, 3)
    return np.asarray(img.GetOrigin()) + verts @ d.T


def _sin_aristas_anomalas(verts, faces, factor=8.0):
    """Quita triángulos con alguna arista > factor x la mediana.

    Red de seguridad frente a colapsos de la decimación que unen islas
    distintas y producen "agujas" de varios centímetros.
    """
    if len(faces) == 0:
        return verts, faces
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    largo = np.max(np.stack([np.linalg.norm(a - b, axis=1),
                             np.linalg.norm(b - c, axis=1),
                             np.linalg.norm(c - a, axis=1)]), axis=0)
    return verts, faces[largo <= factor * float(np.median(largo))]


def _decimar(verts, faces, objetivo):
    if len(faces) > objetivo:
        # Decimación cuádrica de VTK con preservación de volumen. Se descartó
        # fast_simplification: con reducciones > 95 % colapsaba islas pequeñas
        # sobre un vértice lejano (aristas de hasta 107 mm).
        import pyvista as pv
        malla = pv.PolyData(np.asarray(verts, np.float64),
                            np.c_[np.full(len(faces), 3), faces].ravel())
        malla = malla.decimate(1.0 - objetivo / float(len(faces)),
                               volume_preservation=True)
        verts = np.asarray(malla.points, np.float64)
        faces = malla.faces.reshape(-1, 4)[:, 1:].astype(np.int64)
    return _sin_aristas_anomalas(verts, faces)


def _malla(mask, img, nombre, perfil):
    sx, sy, sz = img.GetSpacing()
    # Descarta islas de menos de ~20 mm3: ruido de segmentación.
    min_vox = max(1, int(round(20.0 / (sx * sy * sz))))
    verts, faces = malla_alta_calidad(
        mask, img.GetSpacing(), estructura=nombre, min_voxels=min_vox,
        perfil=perfil, verbose=False)
    if len(faces) == 0:
        return None
    return _a_fisico(verts, img), faces


def _limpiar(verts, faces):
    m = trimesh.Trimesh(verts, faces, process=True)
    m.remove_unreferenced_vertices()
    m.faces = _asegurar_normales_exteriores(m.vertices, m.faces)
    return m


def _repartir(crudas, presupuesto):
    """Triángulos por estructura proporcionales a superficie x peso."""
    pesos = np.array([c["area"] * c["peso"] for c in crudas])
    cuota = presupuesto * pesos / pesos.sum()
    return [int(max(3000, min(len(c["faces"]), q))) for c, q in zip(crudas, cuota)]


def _lps_a_gltf(v, centro):
    """LPS (mm) -> glTF (m): +X izquierda del paciente, +Y superior, +Z anterior."""
    c = (v - centro) / 1000.0
    return np.column_stack([c[:, 0], c[:, 2], -c[:, 1]])


def _escena(mallas, centro, fraccion=1.0):
    escena = trimesh.Scene()
    for item in mallas:
        m = item["malla"]
        v, f = m.vertices, m.faces
        if fraccion < 1.0:
            v, f = _decimar(v, f, max(2000, int(len(f) * fraccion)))
        r, g, b = item["color"]
        material = trimesh.visual.material.PBRMaterial(
            name="mat_" + item["id"],
            baseColorFactor=[r, g, b, item["opacidad"]],
            metallicFactor=0.0, roughnessFactor=0.55,
            alphaMode="BLEND" if item["opacidad"] < 0.999 else "OPAQUE",
            doubleSided=item["opacidad"] < 0.999)
        tm = trimesh.Trimesh(_lps_a_gltf(v, centro), f, process=False)
        tm.visual = trimesh.visual.TextureVisuals(material=material)
        escena.add_geometry(tm, node_name=item["id"], geom_name=item["id"])
    return escena


def construir(caso, synthseg, tumor, salida, fuente_tumor, extras=None,
               fuente_extras=""):
    destino = os.path.join(salida, caso)
    os.makedirs(os.path.join(destino, "stl"), exist_ok=True)
    img_fs, etiquetas = _cargar(synthseg)
    grupos = [(ANATOMIA, etiquetas, img_fs)]

    if tumor:
        img_tu, tumor_arr = _cargar(tumor)
        # Núcleo tumoral en la rejilla de SynthSeg: se excluye de la anatomía
        # para que ninguna estructura normal atraviese la lesión.
        nucleo = sitk.GetImageFromArray(np.isin(tumor_arr, (1, 4)).astype(np.uint8))
        nucleo.CopyInformation(img_tu)
        nucleo_fs = sitk.GetArrayFromImage(sitk.Resample(
            nucleo, img_fs, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
        etiquetas = np.where(nucleo_fs, 0, etiquetas)
        grupos = [(ANATOMIA, etiquetas, img_fs), (TUMOR, tumor_arr, img_tu)]

    for ident, ruta in (extras or {}).items():
        nombre, color, opac, perfil, peso = EXTRAS[ident]
        img_x, arr_x = _cargar(ruta)
        grupos.append(([(ident, nombre, [1], color, opac, perfil, peso)],
                       (arr_x > 0).astype(np.uint8), img_x))

    crudas = []
    for grupo, arr, img in grupos:
        vox_cm3 = float(np.prod(img.GetSpacing())) / 1000.0
        for ident, nombre, labels, color, opac, perfil, peso in grupo:
            mask = np.isin(arr, labels)
            if mask.sum() == 0:
                print("  %-28s ausente" % ident)
                continue
            res = _malla(mask.astype(np.uint8), img, ident, perfil)
            if res is None:
                continue
            verts, faces = res
            # Volumen exacto de la segmentación (no del campo suavizado, que
            # además rellena cavidades como la necrosis dentro del realce).
            vol = np.isin(arr, VOLUMEN_INFORMADO.get(ident, labels)).sum() * vox_cm3
            crudas.append({
                "id": ident, "nombre": nombre, "verts": verts, "faces": faces,
                "area": trimesh.Trimesh(verts, faces, process=False).area,
                "peso": peso, "color": color, "opacidad": opac, "vol": vol})

    mallas, resumen = [], []
    for c, objetivo in zip(crudas, _repartir(crudas, PRESUPUESTO_COMPLETO)):
        m = _limpiar(*_decimar(c["verts"], c["faces"], objetivo))
        m.export(os.path.join(destino, "stl", c["id"] + ".stl"))
        mallas.append({"id": c["id"], "malla": m, "color": c["color"],
                       "opacidad": c["opacidad"]})
        resumen.append({
            "id": c["id"], "nombre": c["nombre"],
            "volumen_cm3": round(c["vol"], 2),
            "triangulos": int(len(m.faces)), "color": list(c["color"]),
            "opacidad": c["opacidad"], "stl": "stl/%s.stl" % c["id"]})
        print("  %-28s %8.2f cm3 %7d tri" % (c["id"], c["vol"], len(m.faces)))

    # Centro = centroide del parénquima, común a todas las mallas del caso.
    cerebro = np.argwhere(etiquetas > 0)[:, ::-1].astype(np.float64)
    sx, sy, sz = img_fs.GetSpacing()
    centro = _a_fisico(cerebro.mean(0) * np.array([sx, sy, sz]), img_fs)

    glb = os.path.join(destino, "%s_AR.glb" % caso)
    _escena(mallas, centro).export(glb)
    glb_l = os.path.join(destino, "%s_AR_ligero.glb" % caso)
    _escena(mallas, centro,
            fraccion=PRESUPUESTO_LIGERO / PRESUPUESTO_COMPLETO).export(glb_l)

    total = sum(r["triangulos"] for r in resumen)
    info = {
        "caso": caso,
        "segmentacion_anatomica": "FreeSurfer 7.4.1 mri_synthseg --robust --parc",
        "segmentacion_tumor": fuente_tumor or None,
        "otras_capas": fuente_extras or None,
        "coordenadas_stl": "LPS, mm (convención DICOM / 3D Slicer)",
        "coordenadas_glb": "metros, +X izquierda, +Y superior, +Z anterior; "
                           "origen en el centroide cerebral",
        "centro_lps_mm": [round(float(c), 2) for c in centro],
        "triangulos_total": total,
        "glb": os.path.basename(glb), "glb_ligero": os.path.basename(glb_l),
        "estructuras": resumen,
        "revision_clinica_requerida": True,
    }
    with open(os.path.join(destino, "resumen.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
    print("  -> %s (%d estructuras, %d triángulos)" % (glb, len(resumen), total))
    return info


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("caso")
    p.add_argument("--synthseg", required=True)
    p.add_argument("--tumor", help="segmentación con etiquetas BraTS 1/2/4")
    p.add_argument("--salida", required=True)
    p.add_argument("--fuente-tumor", default="")
    for ident in EXTRAS:
        p.add_argument("--" + ident, help="máscara binaria de %s" % ident)
    p.add_argument("--fuente-extras", default="")
    a = p.parse_args()
    extras = {i: getattr(a, i) for i in EXTRAS if getattr(a, i)}
    if not a.tumor and "aneurisma" not in extras:
        p.error("Cada modelo debe incluir la lesión: --tumor o --aneurisma.")
    construir(a.caso, a.synthseg, a.tumor, a.salida, a.fuente_tumor, extras,
              a.fuente_extras)


if __name__ == "__main__":
    main()
