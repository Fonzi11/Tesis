"""
NEUROHUB - Segmentación Completa Anatómica y Exportación 3D Clínica
====================================================================
Segmenta cerebro, cráneo, venas, arterias y subestructuras tumorales
con precisión anatómica a partir de máscaras NIfTI y volúmenes BraTS/MR.

Genera mallas 3D de alta resolución (marching cubes con filtrado orgánico
gaussiano y suavizado Taubin conservador de volumen) para evitar artefactos
de vóxel escalonados y bloques desconectados. Exporta a STL y FBX.
"""

import os
import sys
import importlib
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

try:
    import trimesh
except ImportError:
    trimesh = None


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
# CONFIGURACIÓN DE ESTRUCTURAS ANATÓMICAS
# =============================================================================
ESTRUCTURAS = {
    "cerebro": {
        "mascara": "brain.nii.gz",
        "color": (0.83, 0.67, 0.62),      # Rosa grisáceo orgánico (#D4A69A)
        "sigma_smooth": 0.8,
        "taubin_iter": 60,
        "min_component_voxels": 500,
    },
    "craneo": {
        "mascara": "skull.nii.gz",
        "color": (0.91, 0.88, 0.83),      # Hueso marfil cálido (#E8E0D4)
        "sigma_smooth": 0.6,
        "taubin_iter": 50,
        "min_component_voxels": 500,
    },
    "tumor": {
        "mascara": "tumor_brats.nii.gz",
        "color": (0.75, 0.15, 0.43),      # Magenta/Crimson tumoral (#C0256E)
        "sigma_smooth": 0.8,
        "taubin_iter": 40,
        "min_component_voxels": 20,
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


def _cargar_tumor_plausible(preferir=None):
    """
    Carga la mejor máscara de tumor disponible evitando blobs difusos.

    Orden de preferencia:
      0. `preferir` (NIfTI de delineado manual), si se pasa y tiene contenido.
      1. tumor_brats.nii.gz      (segmentación IA) si su extensión es plausible.
      2. tumor_heuristica.nii.gz (método morfológico corregido/localizado).
      3. tumor_heur.nii.gz / tumor.nii.gz (otros respaldos).

    El parámetro `preferir` es lo que hace que el delineado manual del visor 2D
    tenga prioridad sobre la segmentación automática: si el usuario ha
    corregido la máscara a mano, esa es la que debe convertirse en malla, y no
    la que produjo el modelo automatico.

    Si la única máscara disponible tiene una extensión mayor que
    _MAX_FRACCION_EXTENSION_TUMOR del cráneo, se descarta silenciosamente
    (es un artefacto de sobre-segmentación, no un tumor).
    """
    import SimpleITK as sitk_

    candidatas = []
    if preferir:
        candidatas.append(preferir)
    candidatas += [
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
        # `nombre` puede venir como ruta absoluta (mascara manual), y
        # os.path.join ignoraria SEG_AI_DIR en ese caso; aun asi se resuelve
        # de forma explicita para no depender de ese comportamiento.
        ruta = nombre if os.path.isabs(nombre) \
            else os.path.join(SEG_AI_DIR, nombre)
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


def _cargar_estructura(nombre, cfg, preferir_tumor=None):
    """Carga la máscara de una estructura con manejo especial para el tumor.

    `preferir_tumor` es la ruta de la máscara de delineado MANUAL. Cuando se
    pasa, el tumor se construye SIEMPRE a partir de ella, saltándose la
    selección automática: es lo que el usuario ha corregido a mano en el
    visor 2D y es lo que debe verse en 3D.
    """
    if nombre == "tumor":
        if not preferir_tumor or not os.path.exists(preferir_tumor):
            print("[SEG3D] tumor: se omite hasta que exista una "
                  "delineación manual con lápiz.")
            return None, None
        cargada = _cargar_mascara_externa(preferir_tumor)
        if cargada is None:
            print(f"[SEG3D] [!] La máscara manual {preferir_tumor} no se pudo "
                  "leer; se omite el tumor.")
            return None, None
        arr, img = cargada
        brain_path = os.path.join(os.path.dirname(preferir_tumor),
                                  "brain.nii.gz")
        if os.path.exists(brain_path):
            brain = sitk.ReadImage(brain_path)
            if (arr.shape != sitk.GetArrayFromImage(brain).shape
                    or img.GetSpacing() != brain.GetSpacing()
                    or img.GetOrigin() != brain.GetOrigin()
                    or img.GetDirection() != brain.GetDirection()):
                img = sitk.Resample(
                    img, brain, sitk.Transform(), sitk.sitkNearestNeighbor,
                    0, sitk.sitkUInt8)
                arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
            brain_arr = (sitk.GetArrayFromImage(brain) > 0).astype(np.uint8)
            if arr.shape == brain_arr.shape:
                arr = (arr & brain_arr).astype(np.uint8)
            if arr.sum() == 0:
                print("[SEG3D] [!] La delineación manual no intersecta "
                      "el cerebro; se omite para evitar un tumor flotante.")
                return None, None
        print(f"[SEG3D] tumor: máscara MANUAL -> {preferir_tumor}")
    else:
        arr, img = cargar_mascara(cfg["mascara"])

    if arr is None:
        return None, None

    bin_arr = (arr > 0).astype(np.uint8)

    # Filtrar componentes inconexos muy pequeños (ruido flotante)
    min_voxels = cfg.get("min_component_voxels", 0)
    if min_voxels > 0 and bin_arr.sum() > 0:
        labels, num = ndimage.label(bin_arr)
        if num > 1:
            sizes = ndimage.sum(bin_arr, labels, range(1, num + 1))
            mask_clean = np.zeros_like(bin_arr)
            for cid in range(1, num + 1):
                if sizes[cid - 1] >= min_voxels:
                    mask_clean[labels == cid] = 1
            bin_arr = mask_clean

    return bin_arr, img


def _cargar_mascara_externa(ruta):
    """Carga una máscara NIfTI de CUALQUIER ruta como (arr, imagen).

    Se usa para la máscara delineada a mano, que no vive en `SEG_AI_DIR`. Se
    valida que tenga voxels: una máscara vacía produciría una malla degenerada
    y, peor, un tumor "desaparecido" en 3D sin avisar.
    """
    import SimpleITK as sitk_

    try:
        img = sitk_.ReadImage(ruta)
    except Exception as e:
        print(f"[SEG3D] [!] No se pudo leer {ruta}: {e}")
        return None
    arr = (sitk_.GetArrayFromImage(img) > 0).astype(np.uint8)
    if arr.sum() == 0:
        print(f"[SEG3D] [!] {ruta} está vacía (se ignora).")
        return None
    return arr, img


def _restringir_craneo_a_cerebro(craneo, cerebro, spacing,
                                 margen_mm=25.0):
    """Elimina extension de cuello/columna de una mascara de cráneo.

    En MRI TotalSegmentator puede devolver un componente conectado que baja
    desde la base del cráneo hacia las vértebras. Esa región no corresponde a
    la envolvente craneal que se exporta a Unity y produce un STL alargado.
    La máscara cerebral proporciona una referencia anatómica del estudio; se
    conserva el cráneo dentro de su caja física más un margen uniforme.
    """
    skull = np.asarray(craneo, dtype=bool)
    brain = np.asarray(cerebro, dtype=bool)
    if skull.shape != brain.shape or not skull.any() or not brain.any():
        return skull.astype(np.uint8)

    sx, sy, sz = (float(v) for v in spacing[:3])
    margen_vox = np.ceil(
        np.array([margen_mm / sz, margen_mm / sy, margen_mm / sx],
                 dtype=float)).astype(int)
    limites = []
    for eje, margen in enumerate(margen_vox):
        indices = np.flatnonzero(np.any(brain, axis=tuple(
            i for i in range(3) if i != eje)))
        limites.append((
            max(0, int(indices.min()) - int(margen)),
            min(skull.shape[eje], int(indices.max()) + int(margen) + 1),
        ))

    dentro = np.zeros_like(skull, dtype=bool)
    dentro[
        limites[0][0]:limites[0][1],
        limites[1][0]:limites[1][1],
        limites[2][0]:limites[2][1],
    ] = True
    resultado = skull & dentro
    if not resultado.any():
        return skull.astype(np.uint8)

    if int(resultado.sum()) < max(1000, int(skull.sum() * 0.35)):
        print("[SEG3D] Aviso: la restricción del cráneo eliminaría demasiada "
              "anatomía; se conserva la máscara original.")
        return skull.astype(np.uint8)
    eliminados = int(skull.sum() - resultado.sum())
    if eliminados:
        print(f"[SEG3D] Cráneo: se eliminan {eliminados:,} voxels "
              "fuera de la envolvente cerebral.")
    return resultado.astype(np.uint8)


# =============================================================================
# RECONSTRUCCIÓN DE MALLAS 3D (MÁXIMA RESOLUCIÓN)
# =============================================================================
def mascara_a_malla(mask, spacing, smooth=1.0, taubin_iter=45):
    """
    Convierte una máscara binaria en una malla 3D suave y continua
    usando Marching Cubes con filtrado gaussiano previo y suavizado Taubin.
    Preserva el volumen anatómico real sin crear escalones ni bloques.

    Args:
        mask: matriz 3D binaria (numpy)
        spacing: (sx, sy, sz) espaciado del volumen
        smooth: sigma del suavizado gaussiano
        taubin_iter: iteraciones de suavizado Taubin conservador de volumen

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
            data, level=0.45,
            spacing=(spacing[2], spacing[1], spacing[0]),
            method="lorensen"
        )
    except Exception as e:
        print(f"[SEG3D] Error marching_cubes: {e}")
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)

    if len(verts) == 0 or len(faces) == 0:
        return verts, faces

    # Suavizado orgánico Taubin mediante trimesh si está disponible
    if taubin_iter > 0:
        try:
            import trimesh
            m = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
            trimesh.smoothing.filter_taubin(m, iterations=taubin_iter)
            verts = m.vertices
            faces = m.faces
        except Exception as e:
            print(f"[SEG3D] Warning en suavizado Taubin: {e}")

    return verts, faces


def generar_mallas_3d(mri_path=None, salida_dir=None, mascara_tumor=None):
    """
    Genera todas las mallas 3D a máxima resolución y las guarda como STL.
    Utiliza 3D Slicer para la reconstrucción exacta de arterias, venas y estructuras.

    `mascara_tumor` es la ruta de una máscara NIfTI de DELINEADO MANUAL. Si se
    pasa y tiene contenido, el tumor se reconstruye a partir de ella en lugar
    de la segmentación automática, y NO se delega en 3D Slicer (Slicer lee
    siempre las máscaras de `SEG_AI_DIR` por su cuenta, así que descartaría lo
    que el usuario acaba de corregir a mano). Este es el mecanismo que
    convierte lo delineado en 2D en la malla que se ve en 3D.

    Returns:
        dict: {estructura: {stl, verts, faces, voxels, volumen_mm3}}
    """
    salida_dir = salida_dir or MALLAS_DIR
    os.makedirs(salida_dir, exist_ok=True)

    resultados = {}

    # No conservar un STL tumoral de una corrida anterior: si esta ejecución
    # no recibe una delineación manual, ese archivo sería una salida falsa.
    if not (mascara_tumor and os.path.exists(mascara_tumor)):
        tumor_stl = os.path.join(salida_dir, "tumor.stl")
        if os.path.exists(tumor_stl):
            try:
                os.remove(tumor_stl)
                print("[SEG3D] tumor.stl anterior eliminado: falta "
                      "delineación manual.")
            except OSError as error:
                print(f"[SEG3D] [!] No se pudo eliminar {tumor_stl}: {error}")

    import subprocess
    import shutil

    slicer_exe = r"D:\APPS\3D Slicer 5.12.3\Slicer.exe"
    if not os.path.exists(slicer_exe):
        slicer_exe = shutil.which("Slicer.exe") or shutil.which("Slicer")

    script_slicer = os.path.join(SRC_DIR, "slicer_reconstruct.py")

    # Hay delineado manual -> ruta nativa, que sí admite la máscara elegida.
    # Sin él, Slicer es más rápido y su geometría es equivalente.
    # Slicer lee directamente skull.nii.gz y no conoce la corrección
    # anatómica aplicada abajo; para este caso se usa la ruta nativa.
    usar_slicer = not (mascara_tumor and os.path.exists(mascara_tumor)) \
        and not (
            os.path.exists(os.path.join(SEG_AI_DIR, "brain.nii.gz"))
            and os.path.exists(os.path.join(SEG_AI_DIR, "skull.nii.gz"))
        )

    if usar_slicer and slicer_exe and os.path.exists(slicer_exe) \
            and os.path.exists(script_slicer):
        print(f"[SEG3D] Reconstruyendo arterias, venas y mallas con 3D Slicer ({slicer_exe})...")
        try:
            cmd = [slicer_exe, "--no-main-window", "--no-splash", "--python-script", script_slicer]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if proc.returncode == 0:
                print("[SEG3D] [OK] Reconstrucción anatómica con 3D Slicer completada")
                import trimesh
                
                colores_est = {
                    "cerebro": (0.83, 0.67, 0.62),
                    "craneo": (0.91, 0.88, 0.83),
                    "tumor": (0.75, 0.15, 0.43),
                }

                for est_name, col in colores_est.items():
                    stl_path = os.path.join(salida_dir, f"{est_name}.stl")
                    if os.path.exists(stl_path):
                        try:
                            mesh = trimesh.load(stl_path)
                            verts = np.asarray(mesh.vertices)
                            faces = np.asarray(mesh.faces)
                            resultados[est_name] = {
                                "stl": stl_path,
                                "verts": verts,
                                "faces": faces,
                                "voxels": len(verts),
                                "volumen_mm3": mesh.volume if mesh.is_volume else 0.0,
                                "volumen_cm3": (mesh.volume / 1000.0) if mesh.is_volume else 0.0,
                                "color": col,
                            }
                            print(f"[SEG3D] [OK] {est_name:10s} (Slicer): {len(verts):6d} verts, {len(faces):6d} caras")
                        except Exception as e:
                            print(f"[SEG3D] Error cargando STL {est_name}: {e}")

                if resultados:
                    if not (mascara_tumor and os.path.exists(mascara_tumor)):
                        resultados.pop("tumor", None)
                        tumor_stl = os.path.join(salida_dir, "tumor.stl")
                        if os.path.exists(tumor_stl):
                            os.remove(tumor_stl)
                    print(f"\n[SEG3D] [DONE] Se generaron {len(resultados)} estructuras con 3D Slicer")
                    return resultados
        except Exception as e:
            print(f"[SEG3D] Fallback nativo tras error en Slicer: {e}")

    # Fallback si Slicer no estuviera disponible
    mri_arr = None
    if mri_path and os.path.exists(mri_path):
        try:
            mri_img = sitk.ReadImage(mri_path)
            mri_arr = sitk.GetArrayFromImage(mri_img)
        except Exception:
            pass

    mascaras = {}
    for nombre, cfg in ESTRUCTURAS.items():
        arr, img = _cargar_estructura(nombre, cfg, preferir_tumor=mascara_tumor)
        if arr is not None:
            mascaras[nombre] = (arr, img)

    if not mascaras:
        print("[SEG3D] [X] No se encontraron máscaras en salidas/segmentaciones_ai/")
        return {}

    if "craneo" in mascaras and "cerebro" in mascaras:
        craneo_arr, craneo_img = mascaras["craneo"]
        cerebro_arr, _cerebro_img = mascaras["cerebro"]
        craneo_arr = _restringir_craneo_a_cerebro(
            craneo_arr, cerebro_arr, craneo_img.GetSpacing())
        mascaras["craneo"] = (craneo_arr, craneo_img)
        ruta_limpia = os.path.join(salida_dir, "skull_cleaned.nii.gz")
        imagen_limpia = sitk.GetImageFromArray(craneo_arr.astype(np.uint8))
        imagen_limpia.CopyInformation(craneo_img)
        sitk.WriteImage(imagen_limpia, ruta_limpia, useCompression=True)
        print(f"[SEG3D] [OK] Máscara craneal corregida guardada en {ruta_limpia}")

    for nombre, cfg in ESTRUCTURAS.items():
        if nombre not in mascaras:
            continue

        mask_arr, mask_img = mascaras[nombre]
        spacing = mask_img.GetSpacing()
        if mask_arr is None or mask_arr.sum() == 0:
            print(f"[SEG3D] [!] {nombre}: máscara vacía")
            continue

        sigma = cfg.get("sigma_smooth", 1.0)
        t_iter = cfg.get("taubin_iter", 45)

        try:
            calidad = importlib.import_module("calidad_mallas")
            verts, faces = calidad.malla_alta_calidad(
                mask_arr, spacing, estructura=nombre,
                min_voxels=cfg.get("min_component_voxels", 0),
                verbose=False,
            )
        except Exception:
            verts, faces = mascara_a_malla(
                mask_arr, spacing, smooth=sigma, taubin_iter=t_iter)

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
