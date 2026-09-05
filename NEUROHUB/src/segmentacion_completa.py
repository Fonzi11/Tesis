"""
NEUROHUB - Segmentación Completa y Exportación 3D
==================================================
Segmenta cerebro, cráneo, venas, arterias y tumor a partir de
las máscaras existentes (generadas con TotalSegmentator y BraTS).

Genera mallas 3D de máxima resolución (marching cubes) de cada
estructura por separado y las exporta a STL + FBX (para Unity).
"""

import os
import sys
import numpy as np
from pathlib import Path

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import SimpleITK as sitk
try:
    from scipy import ndimage
    from skimage import measure
    from scipy.ndimage import gaussian_filter, binary_fill_holes
except ImportError as e:
    print(f"[SEG3D] Dependencia faltante: {e}")


# =============================================================================
# DIRECTORIOS
# =============================================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
SALIDAS_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")
SEG_AI_DIR = os.path.join(SALIDAS_DIR, "segmentaciones_ai")
MALLAS_DIR = os.path.join(SALIDAS_DIR, "mallas")
FBX_DIR = os.path.join(SALIDAS_DIR, "fbx")

os.makedirs(MALLAS_DIR, exist_ok=True)
os.makedirs(FBX_DIR, exist_ok=True)

# =============================================================================
# CONFIGURACIÓN DE ESTRUCTURAS
# =============================================================================
ESTRUCTURAS = {
    "cerebro": {
        "mascara": "brain.nii.gz",
        "color": (0.65, 0.67, 0.72),
        "dilatacion": 0,
    },
    "craneo": {
        "mascara": "skull.nii.gz",
        "color": (0.90, 0.88, 0.82),
        "dilatacion": 0,
    },
    "tumor": {
        "mascara": "tumor_brats.nii.gz",
        "color": (0.78, 0.15, 0.86),
        "dilatacion": 2,
    },
    "vasos": {
        "mascara": "vasos.nii.gz",
        "color": (0.80, 0.20, 0.20),
        "dilatacion": 2,
    },
}


def cargar_mascara(nombre_mascara):
    """Carga una máscara NIfTI y devuelve (array, imagen_sitk)."""
    ruta = os.path.join(SEG_AI_DIR, nombre_mascara)
    if not os.path.exists(ruta):
        print(f"[SEG3D] [!] Máscara no encontrada: {ruta}")
        return None, None
    img = sitk.ReadImage(ruta)
    arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
    return arr, img


# Fracción máxima de la extensión del cráneo que puede ocupar un tumor
# realista. En datos sintéticos/ruidosos, tanto BRATS de modalidad única
# como el método morfológico pueden "fundir" tejido brillante disperso y
# producir blobs que abarcan el cerebro entero. Ningún tumor real llega a
# más de ~40% del diámetro mayor del cráneo.
_MAX_FRACCION_EXTENSION_TUMOR = 0.40


def _cargar_tumor_plausible():
    """
    Carga la mejor máscara de tumor disponible evitando blobs difusos.

    Orden de preferencia:
      1. tumor_brats.nii.gz      (segmentación IA) si su extensión es plausible.
      2. tumor_heuristica.nii.gz (método morfológico corregido/localizado).
      3. tumor_heur.nii.gz / tumor.nii.gz (otros respaldos).

    Si la única máscara disponible tiene una extensión mayor que
    _MAX_FRACCION_EXTENSION_TUMOR del cráneo, se descarta silenciosamente
    (es un artefacto de sobre-segmentación, no un tumor).
    """
    import SimpleITK as sitk_

    candidatas = [
        "tumor_brats.nii.gz",
        "tumor_heuristica.nii.gz",
        "tumor_heur.nii.gz",
        "tumor.nii.gz",
    ]

    # Extensión del cráneo (mm) para la cota de plausibilidad.
    span_craneo_mm = 218.0  # diametro mayor aproximado de skull.nii.gz
    try:
        skull = sitk.ReadImage(os.path.join(SEG_AI_DIR, "skull.nii.gz"))
        sarr = (sitk.GetArrayFromImage(skull) > 0)
        if sarr.any():
            ssp = skull.GetSpacing()
            sz, sy, sx = np.nonzero(sarr)
            span_craneo_mm = max((sz.max() - sz.min()) * ssp[2],
                                 (sy.max() - sy.min()) * ssp[1],
                                 (sx.max() - sx.min()) * ssp[0])
    except Exception:
        pass
    max_span_mm = _MAX_FRACCION_EXTENSION_TUMOR * span_craneo_mm

    for nombre in candidatas:
        ruta = os.path.join(SEG_AI_DIR, nombre)
        if not os.path.exists(ruta):
            continue
        try:
            img = sitk_.ReadImage(ruta)
            arr = (sitk_.GetArrayFromImage(img) > 0).astype(np.uint8)
            if arr.sum() == 0:
                continue
            sp = img.GetSpacing()
            z, y, x = np.nonzero(arr > 0)
            span_mm = max((z.max() - z.min()) * sp[2],
                          (y.max() - y.min()) * sp[1],
                          (x.max() - x.min()) * sp[0])
            if span_mm > max_span_mm:
                print(f"[SEG3D] [!] {nombre}: extensión {span_mm:.0f} mm > "
                      f"{max_span_mm:.0f} mm (blob difuso, se descarta).")
                continue
            return arr, img, nombre
        except Exception as e:
            print(f"[SEG3D] [!] Error leyendo tumor {nombre}: {e}")
            continue
    return None, None, None


def _cargar_estructura(nombre, cfg):
    """Carga la máscara de una estructura con manejo especial para el tumor."""
    if nombre == "tumor":
        arr, img, usado = _cargar_tumor_plausible()
        if arr is None:
            print("[SEG3D] [!] tumor: sin máscara plausible (se omite).")
        else:
            print(f"[SEG3D] tumor: máscara usada -> {usado}")
        return arr, img
    return cargar_mascara(cfg["mascara"])


def separar_vasos(vasos_mask, mri_arr=None):
    """
    Separa la máscara de vasos en arterias y venas mediante heurística.

    Estrategia (dada la ausencia de MRA/CTA):
      - Componentes de gran calibre en posición anterior-media
        y con intensidad brillante alta en T1 → ARTERIAS
      - El resto → VENAS (incluyendo senos venosos y drenaje)

    Returns:
        (arterias_mask, venas_mask): dos matrices binarias uint8
    """
    if vasos_mask is None:
        return None, None

    mask = vasos_mask > 0
    if mask.sum() == 0:
        return None, None

    labels, num = ndimage.label(mask)
    sizes = ndimage.sum(mask, labels, range(1, num + 1))

    cx = mask.shape[2] // 2
    cy = mask.shape[1] // 2

    arterias = np.zeros_like(mask)
    venas = np.zeros_like(mask)

    for cid in range(1, num + 1):
        comp = labels == cid
        n = int(sizes[cid - 1])
        if n < 1:
            continue

        coords = np.argwhere(comp)
        if len(coords) == 0:
            continue
        mean_z = coords[:, 0].mean()
        mean_y = coords[:, 1].mean()
        mean_x = coords[:, 2].mean()

        d_center = np.sqrt((mean_x - cx) ** 2 + (mean_y - cy) ** 2)

        # Umbrales geométricos
        es_periferia = d_center > mask.shape[1] * 0.35
        es_superior = mean_z > mask.shape[0] * 0.45
        es_inferior = mean_z < mask.shape[0] * 0.65

        # Criterio de arteria: vaso grueso NO periférico y superior
        # (las arterias cerebrales entran por la base y son centrales)
        es_arteria = (n > 40 and es_inferior and not es_periferia)

        if es_arteria:
            arterias[comp] = 1
        else:
            venas[comp] = 1

    # Si hay demasiadas pocas arterias, promover los componentes
    # centrales más grandes que lleguen a la base del cerebro
    if arterias.sum() > 0 and arterias.sum() / max(venas.sum(), 1) < 0.15:
        # Promover componentes centrales grandes (mayoría son arterias)
        center_mask = np.zeros_like(mask)
        for cid in range(1, num + 1):
            comp = labels == cid
            coords = np.argwhere(comp)
            if len(coords) == 0:
                continue
            mz = coords[:, 0].mean()
            if mz < mask.shape[0] * 0.7:
                center_mask[comp] = 1
        # De los centrales, promover los más grandes hasta 25% del total
        target_add = int(mask.sum() * 0.25) - arterias.sum()
        if target_add > 0:
            central_labels, central_num = ndimage.label(
                center_mask & ~arterias)
            if central_num > 0:
                central_sizes = ndimage.sum(mask, central_labels,
                                            range(1, central_num + 1))
                order = np.argsort(central_sizes)[::-1]
                added = 0
                for ci in order:
                    if added >= target_add:
                        break
                    comp = central_labels == (ci + 1)
                    arterias[comp] = 1
                    venas[comp] = 0
                    added += int(central_sizes[ci])

    # Fallback: si no se separaron arterias, tomar las más grandes
    if arterias.sum() == 0 and venas.sum() > 0:
        order = np.argsort(sizes)[::-1][:max(1, num // 10)]
        for cid in order:
            comp = labels == (cid + 1)
            arterias[comp] = 1
            venas[comp] = 0

    if venas.sum() == 0 and arterias.sum() > 0:
        venas = arterias.copy()

    return arterias.astype(np.uint8), venas.astype(np.uint8)


# =============================================================================
# RECONSTRUCCIÓN DE MALLAS 3D (MÁXIMA RESOLUCIÓN)
# =============================================================================
def mascara_a_malla(mask, spacing, smooth=0.6):
    """
    Convierte una máscara binaria en una malla 3D (verts, faces) usando
    marching cubes a máxima resolución (un vóxel por vóxel).

    Args:
        mask: matriz 3D binaria (numpy)
        spacing: (sx, sy, sz) espaciado del volumen
        smooth: sigma del suavizado gaussiano (0 = sin suavizado)

    Returns:
        (verts, faces): tupla con vértices y caras de la malla
    """
    if mask is None or mask.sum() == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)

    data = mask.astype(np.float32)

    if smooth > 0:
        data = gaussian_filter(data, sigma=smooth)

    try:
        verts, faces, _, _ = measure.marching_cubes(
            data, level=0.5,
            spacing=(spacing[2], spacing[1], spacing[0]),
            method="lorensen"
        )
    except Exception as e:
        print(f"[SEG3D] Error marching_cubes: {e}")
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)

    return verts, faces


def generar_mallas_3d(mri_path=None, salida_dir=None):
    """
    Genera todas las mallas 3D a máxima resolución y las guarda como STL.

    Returns:
        dict: {estructura: {stl, verts, faces, voxels, volumen_mm3}}
    """
    salida_dir = salida_dir or MALLAS_DIR
    os.makedirs(salida_dir, exist_ok=True)

    resultados = {}

    mri_arr = None
    if mri_path and os.path.exists(mri_path):
        try:
            mri_img = sitk.ReadImage(mri_path)
            mri_arr = sitk.GetArrayFromImage(mri_img)
        except Exception:
            pass

    mascaras = {}
    for nombre, cfg in ESTRUCTURAS.items():
        arr, img = _cargar_estructura(nombre, cfg)
        if arr is not None:
            mascaras[nombre] = (arr, img.GetSpacing())

    if not mascaras:
        print("[SEG3D] [X] No se encontraron máscaras en salidas/segmentaciones_ai/")
        return {}

    for nombre, cfg in ESTRUCTURAS.items():
        if nombre not in mascaras:
            continue

        mask_arr, spacing = mascaras[nombre]
        if mask_arr is None or mask_arr.sum() == 0:
            print(f"[SEG3D] [!] {nombre}: máscara vacía")
            continue

        if cfg.get("dilatacion", 0) > 0:
            from scipy.ndimage import binary_dilation
            struct_el = np.ones((3, 3, 3), dtype=bool)
            mask_arr = binary_dilation(mask_arr > 0, struct_el,
                                       iterations=cfg["dilatacion"]).astype(np.uint8)

        verts, faces = mascara_a_malla(mask_arr, spacing)

        if len(verts) == 0 or len(faces) == 0:
            print(f"[SEG3D] [!] {nombre}: malla vacía")
            continue

        stl_path = os.path.join(salida_dir, f"{nombre}.stl")
        try:
            import trimesh
            mesh = trimesh.Trimesh(vertices=verts, faces=faces)
            mesh.export(stl_path)
        except Exception as e:
            print(f"[SEG3D] Error exportando STL {nombre}: {e}")
            stl_path = None

        voxel_volume = np.prod(spacing)
        volumen_mm3 = float(mask_arr.sum()) * voxel_volume

        resultados[nombre] = {
            "stl": stl_path,
            "verts": verts,
            "faces": faces,
            "voxels": int(mask_arr.sum()),
            "volumen_mm3": volumen_mm3,
            "volumen_cm3": volumen_mm3 / 1000.0,
            "color": cfg["color"],
        }
        print(f"[SEG3D] [OK] {nombre}: {len(verts)} vértices, "
              f"{len(faces)} caras, volumen {volumen_mm3/1000:.1f} cm³")

    # Procesar venas y arterias por separado
    if "vasos" in mascaras:
        vasos_arr, spacing = mascaras["vasos"]
        if vasos_arr is not None and vasos_arr.sum() > 0:
            arterias, venas = separar_vasos(vasos_arr, mri_arr)

            for sub_nombre, sub_mask in [("arterias", arterias), ("venas", venas)]:
                if sub_mask is None or sub_mask.sum() == 0:
                    print(f"[SEG3D] [!] {sub_nombre}: vacía")
                    continue

                verts, faces = mascara_a_malla(sub_mask, spacing)
                if len(verts) == 0:
                    continue

                stl_path = os.path.join(salida_dir, f"{sub_nombre}.stl")
                try:
                    import trimesh
                    mesh = trimesh.Trimesh(vertices=verts, faces=faces)
                    mesh.export(stl_path)
                except Exception as e:
                    print(f"[SEG3D] Error exportando STL {sub_nombre}: {e}")
                    stl_path = None

                voxel_volume = np.prod(spacing)
                volumen_mm3 = float(sub_mask.sum()) * voxel_volume
                color = ((0.85, 0.10, 0.10) if sub_nombre == "arterias"
                         else (0.10, 0.20, 0.75))
                resultados[sub_nombre] = {
                    "stl": stl_path,
                    "verts": verts,
                    "faces": faces,
                    "voxels": int(sub_mask.sum()),
                    "volumen_mm3": volumen_mm3,
                    "volumen_cm3": volumen_mm3 / 1000.0,
                    "color": color,
                }
                print(f"[SEG3D] [OK] {sub_nombre}: {len(verts)} vértices, "
                      f"{len(faces)} caras")

    print(f"\n[SEG3D] [DONE] Se generaron {len(resultados)} estructuras en {salida_dir}")
    return resultados


# =============================================================================
# EXPORTACIÓN FBX PARA UNITY (usando Blender/bpy)
# =============================================================================
def exportar_fbx_bpy(stl_dir=None, fbx_dir=None):
    """
    Exporta todos los STL a un único FBX combinado usando Blender (bpy).

    Cada estructura se coloca en un objeto 3D separado, con su color,
    y todos se exportan al mismo archivo FBX para Unity.

    Returns:
        list: rutas de archivos FBX generados
    """
    import bpy

    stl_dir = stl_dir or MALLAS_DIR
    fbx_dir = fbx_dir or FBX_DIR
    os.makedirs(fbx_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)

    colores = {
        "cerebro": (0.65, 0.67, 0.72),
        "craneo": (0.90, 0.88, 0.82),
        "tumor": (0.78, 0.15, 0.86),
        "venas": (0.10, 0.20, 0.75),
        "arterias": (0.85, 0.10, 0.10),
        "vasos": (0.80, 0.20, 0.20),
    }

    stl_files = sorted([f for f in os.listdir(stl_dir)
                        if f.lower().endswith(".stl")])
    fbx_out = []

    for stl_file in stl_files:
        nombre = Path(stl_file).stem
        stl_path = os.path.join(stl_dir, stl_file)

        bpy.ops.wm.stl_import(filepath=stl_path)
        mesh_obj = bpy.context.active_object
        if mesh_obj is None:
            print(f"[FBX] [!] No se pudo importar {stl_file}")
            continue

        mesh_obj.name = nombre

        color = colores.get(nombre, (0.7, 0.7, 0.7))
        mat = bpy.data.materials.new(name=f"mat_{nombre}")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (
            color[0], color[1], color[2], 1.0)
        mat.node_tree.nodes["Principled BSDF"].inputs[9].default_value = 0.8
        mesh_obj.data.materials.append(mat)

        print(f"[FBX] <- Importado: {nombre}")

    # UN SOLO modelo: unir todas las estructuras en un único objeto que
    # conserva los materiales de cada una. Salida: un único FBX.
    bpy.ops.object.select_all(action="DESELECT")
    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in mesh_objects:
        o.select_set(True)
    if mesh_objects:
        bpy.context.view_layer.objects.active = mesh_objects[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = "NEUROHUB"
        print(f"[FBX] Objeto único: {joined.name} "
              f"({len(joined.data.polygons):,} caras, "
              f"{len(joined.data.materials)} materiales)")

    fbx_path = os.path.join(fbx_dir, "neurohub_completo.fbx")
    bpy.ops.export_scene.fbx(
        filepath=fbx_path,
        use_selection=False,
        apply_unit_scale=False,
        axis_forward='-Z',
        axis_up='Y',
    )
    fbx_out.append(fbx_path)
    print(f"[FBX] [OK] Exportado: {fbx_path}")

    return fbx_out


def exportar_un_fbx_por_malla(stl_dir=None, fbx_dir=None):
    """
    Exporta cada malla STL a su propio archivo FBX (para Unity).
    Opción recomendada: cada estructura como un asset separado.
    """
    import bpy

    stl_dir = stl_dir or MALLAS_DIR
    fbx_dir = fbx_dir or FBX_DIR
    os.makedirs(fbx_dir, exist_ok=True)

    colores = {
        "cerebro": (0.65, 0.67, 0.72),
        "craneo": (0.90, 0.88, 0.82),
        "tumor": (0.78, 0.15, 0.86),
        "venas": (0.10, 0.20, 0.75),
        "arterias": (0.85, 0.10, 0.10),
        "vasos": (0.80, 0.20, 0.20),
    }

    stl_files = sorted([f for f in os.listdir(stl_dir)
                        if f.lower().endswith(".stl")])
    fbx_out = []

    for stl_file in stl_files:
        nombre = Path(stl_file).stem
        stl_path = os.path.join(stl_dir, stl_file)

        bpy.ops.wm.read_factory_settings(use_empty=True)

        bpy.ops.wm.stl_import(filepath=stl_path)
        mesh_obj = bpy.context.active_object
        if mesh_obj is None:
            continue

        mesh_obj.name = nombre

        color = colores.get(nombre, (0.7, 0.7, 0.7))
        mat = bpy.data.materials.new(name=f"mat_{nombre}")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (
            color[0], color[1], color[2], 1.0)
        mat.node_tree.nodes["Principled BSDF"].inputs[9].default_value = 0.8
        mesh_obj.data.materials.append(mat)

        fbx_path = os.path.join(fbx_dir, f"{nombre}.fbx")
        bpy.ops.export_scene.fbx(
            filepath=fbx_path,
            use_selection=False,
            apply_unit_scale=False,
            axis_forward='-Z',
            axis_up='Y',
        )
        fbx_out.append(fbx_path)
        print(f"[FBX] [OK] {nombre}.fbx")

    return fbx_out


# =============================================================================
# PIPELINE COMPLETA
# =============================================================================
def exportar_para_unity(mri_path=None):
    """
    Pipeline completa: genera mallas 3D y exporta FBX para Unity.

    Args:
        mri_path: ruta al volumen MRI (opcional, usado para separar vasos)

    Returns:
        dict: resumen de la exportación
    """
    print("=" * 60)
    print("NEUROHUB - Segmentación y Exportación 3D para Unity")
    print("=" * 60)

    print("\n[1/3] Generando mallas 3D de máxima resolución...")
    resultados = generar_mallas_3d(mri_path)

    if not resultados:
        print("[EXPORT] [X] No se pudieron generar las mallas")
        return {}

    print("\n[2/3] Exportando FBX combinado (todos visibles a la vez)...")
    try:
        fbx_all = exportar_fbx_bpy()
    except Exception as e:
        print(f"[EXPORT] [!] Error exportando FBX combinado: {e}")
        fbx_all = []

    print("\n[3/3] FBX individuales desactivados: el pipeline exporta UN SOLO "
          "modelo combinado (salidas/fbx/neurohub_completo.fbx).")
    print("      (Si llegaras a necesitarlos: exportar_un_fbx_por_malla())")
    fbx_sep = []

    print("\n" + "=" * 60)
    print("RESUMEN DE EXPORTACIÓN:")
    print("=" * 60)
    for nombre, res in resultados.items():
        print(f"  - {nombre:12s} | {res['voxels']:>8,} voxels | "
              f"{res['volumen_cm3']:>8.2f} cm³")

    print("\n  Archivos FBX generados:")
    for f in fbx_sep:
        print(f"    [OK] {f}")

    return {
        "mallas": resultados,
        "fbx_combinado": fbx_all,
        "fbx_individuales": fbx_sep,
    }


if __name__ == "__main__":
    mri = os.path.join(DATA_DIR, "nifti", "MRBrainTumor1.nii.gz")
    exportar_para_unity(mri)

