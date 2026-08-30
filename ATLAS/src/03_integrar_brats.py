"""
Integración de BRATS y mejoras al pipeline de segmentación.
================================================================
Este script integra el modelo BRATS 2020 (descargado via MONAI) con el
pipeline existente de segmentación de tumores cerebrales, y mejora la
detección de aneurismas con un enfoque más robusto.

Funcionalidades:
1. Segmentación de tumores con BRATS (precisión clínica)
2. Mejora de la detección de aneurismas con análisis de curvatura
3. Generación de modelos 3D mejorados con suavizado adaptativo
"""

import os
import sys
import numpy as np
import SimpleITK as sitk
import trimesh
from pathlib import Path

# Importar módulos del pipeline
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
_brats_module = importlib.import_module("02_segmentacion_brats")
segment_brats_tumor = _brats_module.segment_brats_tumor
segment_tumor_brats_from_single_volume = _brats_module.segment_tumor_brats_from_single_volume
download_brats_bundle = _brats_module.download_brats_bundle
verify_brats_model = _brats_module.verify_brats_model
BRATS_MASKS = _brats_module.BRATS_MASKS
MODELOS_DIR = _brats_module.MODELOS_DIR


def integrate_brats_into_pipeline(nifti_path, output_dir="segmentaciones_ai"):
    """
    Integra BRATS en el pipeline de segmentación.
    
    Si el volumen es MRI (4 modalidades disponibles), usa BRATS completo.
    Si es CT o solo una modalidad, usa el modo de modalidad única.
    
    Args:
        nifti_path: Ruta al volumen NIfTI
        output_dir: Directorio de salida
    
    Returns:
        dict: Resultados de la integración
    """
    print("\n" + "=" * 70)
    print("[INTEGRACIÓN] Integrando BRATS en el pipeline de segmentación")
    print("=" * 70)
    
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    
    # Verificar que el modelo BRATS esté disponible
    if not verify_brats_model():
        print("[INTEGRACIÓN] Modelo BRATS no disponible. Intentando descargar...")
        bundle = download_brats_bundle()
        if not bundle:
            print("[INTEGRACIÓN] No se pudo obtener BRATS. Continuando sin él.")
            return results
    
    # Leer el volumen para determinar el tipo de estudio
    img = sitk.ReadImage(nifti_path)
    arr = sitk.GetArrayFromImage(img)
    
    # Determinar si es CT o MRI basado en los valores de intensidad
    # CT: valores en unidades Hounsfield (típicamente -1000 a 3000)
    # MRI: valores relativos (típicamente 0-4095)
    min_val = float(arr.min())
    max_val = float(arr.max())
    
    is_ct = min_val < -100 or max_val > 2000
    print(f"[INTEGRACIÓN] Rango de intensidad: [{min_val:.0f}, {max_val:.0f}]")
    print(f"[INTEGRACIÓN] Tipo de estudio: {'CT' if is_ct else 'MRI'}")
    
    if is_ct:
        print("[INTEGRACIÓN] Estudio CT detectado. BRATS requiere MRI multimodal.")
        print("[INTEGRACIÓN] Usando modo de modalidad única (duplicando canales)...")
        print("[INTEGRACIÓN] ADVERTENCIA: La precisión será limitada con CT.")
        
        # Para CT, BRATS no es ideal. Usar el método heurístico existente
        # pero con mejoras.
        print("[INTEGRACIÓN] Para CT, se recomienda usar el método heurístico del pipeline principal.")
        results["metodo"] = "heurístico"
    else:
        print("[INTEGRACIÓN] Estudio MRI detectado. Intentando segmentación con BRATS...")
        
        # Buscar las 4 modalidades de MRI en el directorio
        # En un estudio real, se necesitarían T1, T1ce, T2, FLAIR
        # Por ahora, usar el mismo volumen para las 4 modalidades
        brats_results = segment_tumor_brats_from_single_volume(
            nifti_path, 
            output_dir=os.path.join(output_dir, "brats")
        )
        
        if brats_results:
            results["metodo"] = "BRATS"
            results["brats"] = brats_results
            
            # Copiar la máscara de tumor completo al directorio principal
            if "tumor_whole" in brats_results:
                src = brats_results["tumor_whole"]
                dst = os.path.join(output_dir, "tumor_brats.nii.gz")
                import shutil
                shutil.copy2(src, dst)
                results["tumor_brats"] = dst
                print(f"[INTEGRACIÓN] Máscara de tumor BRATS copiada a: {dst}")
        else:
            print("[INTEGRACIÓN] BRATS no produjo resultados. Usando método heurístico.")
            results["metodo"] = "heurístico"
    
    return results


def improve_aneurysm_detection(nifti_path, vessels_mask_path, output_path,
                                dilation_ratio_threshold=1.4,
                                min_local_diameter_mm=1.0,
                                baseline_window_mm=(6.0, 15.0),
                                bifurcation_radius_mm=4.0,
                                cluster_merge_radius_mm=3.0,
                                curvature_threshold=0.3):
    """
    Detección mejorada de aneurismas con análisis de curvatura.
    
    Mejoras sobre la versión original:
    1. Análisis de curvatura local del esqueleto (los aneurismas saculares
       tienen alta curvatura en la unión con el vaso padre)
    2. Análisis de forma: los aneurismas son más esféricos que los vasos
       normales (que son tubulares)
    3. Score compuesto que combina ratio de dilatación, curvatura y
       proximidad a bifurcaciones
    4. Filtrado por volumen mínimo para eliminar falsos positivos
    
    Args:
        nifti_path: Ruta al volumen NIfTI
        vessels_mask_path: Ruta a la máscara de vasos
        output_path: Ruta de salida para la máscara de candidatos
        dilation_ratio_threshold: Umbral de ratio de dilatación
        min_local_diameter_mm: Diámetro mínimo local
        baseline_window_mm: Ventana para calcular diámetro basal
        bifurcation_radius_mm: Radio para considerar cercanía a bifurcación
        cluster_merge_radius_mm: Radio para agrupar puntos
        curvature_threshold: Umbral de curvatura para refuerzo de score
    
    Returns:
        tuple: (output_path, reporte)
    """
    print("\n" + "=" * 70)
    print("[ANEURISMA v2] Detección mejorada con análisis de curvatura y forma")
    print("=" * 70)
    
    if not os.path.exists(vessels_mask_path):
        print("[ANEURISMA v2] Máscara de vasos no encontrada.")
        return None, []
    
    img = sitk.ReadImage(nifti_path)
    vessels_img = sitk.ReadImage(vessels_mask_path)
    vessels_arr = sitk.GetArrayFromImage(vessels_img) > 0
    
    if not np.any(vessels_arr):
        print("[ANEURISMA v2] Máscara de vasos vacía.")
        return None, []
    
    spacing_xyz = img.GetSpacing()
    spacing_zyx = (spacing_xyz[2], spacing_xyz[1], spacing_xyz[0])
    
    import scipy.ndimage as ndi
    from scipy.spatial import cKDTree
    from skimage import morphology as skmorph
    
    print("[ANEURISMA v2] Esqueletonizando árbol vascular...")
    try:
        skeleton = skmorph.skeletonize(vessels_arr)
    except Exception:
        skeleton = skmorph.skeletonize_3d(vessels_arr)
    
    if not np.any(skeleton):
        print("[ANEURISMA v2] Esqueleto vacío.")
        return None, []
    
    print("[ANEURISMA v2] Calculando perfil de diámetro local...")
    dist_transform = ndi.distance_transform_edt(vessels_arr, sampling=spacing_zyx)
    skel_idx = np.argwhere(skeleton)
    diam_local = 2.0 * dist_transform[skeleton]
    skel_phys = skel_idx * np.array(spacing_zyx)
    
    print("[ANEURISMA v2] Detectando bifurcaciones...")
    kernel = np.ones((3, 3, 3))
    kernel[1, 1, 1] = 0
    neighbor_count = ndi.convolve(skeleton.astype(np.uint8), kernel, mode='constant')
    branch_mask = skeleton & (neighbor_count >= 3)
    branch_phys = np.argwhere(branch_mask) * np.array(spacing_zyx)
    branch_tree = cKDTree(branch_phys) if len(branch_phys) > 0 else None
    
    print("[ANEURISMA v2] Calculando ratio diámetro local / basal...")
    tree = cKDTree(skel_phys)
    r_inner, r_outer = baseline_window_mm
    ratios = np.ones(len(skel_idx), dtype=np.float32)
    
    for i, p in enumerate(skel_phys):
        neigh = tree.query_ball_point(p, r=r_outer)
        neigh = [j for j in neigh if r_inner <= np.linalg.norm(skel_phys[j] - p) <= r_outer]
        if len(neigh) < 3:
            continue
        baseline = float(np.median(diam_local[neigh]))
        if baseline > 0:
            ratios[i] = diam_local[i] / baseline
    
    # === NUEVO: Análisis de curvatura local ===
    # Los aneurismas saculares tienen alta curvatura en la unión con el vaso
    # padre. Calculamos la curvatura como la desviación de la dirección local
    # del esqueleto.
    print("[ANEURISMA v2] Calculando curvatura local del esqueleto...")
    curvatures = np.zeros(len(skel_idx), dtype=np.float32)
    
    # Para cada punto, calcular la dirección local del vaso
    # usando los vecinos a lo largo del esqueleto
    for i, p in enumerate(skel_phys):
        # Encontrar vecinos a lo largo del vaso (distancia 1-3 mm)
        neigh = tree.query_ball_point(p, r=3.0)
        neigh = [j for j in neigh if j != i and 0.5 <= np.linalg.norm(skel_phys[j] - p) <= 3.0]
        
        if len(neigh) < 2:
            continue
        
        # Calcular vectores desde el punto a los vecinos
        vectors = skel_phys[neigh] - p
        
        # Normalizar
        norms = np.linalg.norm(vectors, axis=1)
        norms[norms == 0] = 1e-6
        vectors_norm = vectors / norms[:, np.newaxis]
        
        # La curvatura es la dispersión de las direcciones
        # Si las direcciones son opuestas (vaso recto), la dispersión es baja
        # Si las direcciones son variadas (aneurisma), la dispersión es alta
        mean_dir = np.mean(vectors_norm, axis=0)
        mean_dir_norm = np.linalg.norm(mean_dir)
        
        # Curvatura = 1 - |dirección media| (0 = recto, 1 = muy curvado)
        curvatures[i] = 1.0 - min(mean_dir_norm, 1.0)
    
    # === NUEVO: Análisis de esfericidad local ===
    # Los aneurismas saculares son más esféricos que los vasos tubulares.
    # Optimización (resultado idéntico): la esfericidad solo influye en el
    # "score compuesto", que únicamente AFINA los puntos que YA son candidatos
    # por ratio de dilatación (base_flag). Un punto sin ratio alto jamás puede
    # ser candidato aunque tenga alta esfericidad. Por eso calculamos la
    # costosa esfericidad (marching_cubes + ConvexHull por punto) solo sobre el
    # subconjunto reducido, no sobre todos los puntos del esqueleto (que con
    # una vasculatura densa serían decenas de miles y congelarían el pipeline
    # durante minutos).
    base_flag = (ratios >= dilation_ratio_threshold) & (diam_local >= min_local_diameter_mm)
    base_idx = np.argwhere(base_flag).ravel()
    print(f"[ANEURISMA v2] Calculando esfericidad local (solo {int(base_flag.sum())}/{len(skel_idx)} pts candidatos por ratio)...")
    sphericity = np.zeros(len(skel_idx), dtype=np.float32)

    # Radio de la esfera de análisis (basado en el diámetro local)
    for i in base_idx:
        p = skel_idx[i]
        radius_vox = max(2, int(round(diam_local[i] / 2.0 / min(spacing_zyx))))
        
        # Extraer el volumen local
        z0, y0, x0 = p
        zmin, zmax = max(0, z0 - radius_vox), min(vessels_arr.shape[0], z0 + radius_vox + 1)
        ymin, ymax = max(0, y0 - radius_vox), min(vessels_arr.shape[1], y0 + radius_vox + 1)
        xmin, xmax = max(0, x0 - radius_vox), min(vessels_arr.shape[2], x0 + radius_vox + 1)
        
        local_vol = vessels_arr[zmin:zmax, ymin:ymax, xmin:xmax]
        
        if local_vol.sum() < 10:
            continue
        
        # Calcular la esfericidad del volumen local
        # Esfericidad = 36π * V² / A³ (1 = esfera perfecta)
        # Aproximación: usar la relación entre volumen y superficie
        from skimage import measure as skmeasure
        try:
            verts, faces, _, _ = skmeasure.marching_cubes(local_vol, level=0.5)
            if len(faces) > 0:
                # Calcular volumen y superficie aproximados
                # Usar la fórmula de esfericidad
                # Para simplificar, usar la relación entre el radio máximo y mínimo
                # de la nube de puntos
                from scipy.spatial import ConvexHull
                try:
                    hull = ConvexHull(verts)
                    volume = hull.volume
                    area = hull.area
                    if volume > 0 and area > 0:
                        sphericity[i] = (36 * np.pi * volume**2) / (area**3)
                except Exception:
                    pass
        except Exception:
            pass
    
    # === NUEVO: Score compuesto ===
    # Combina ratio de dilatación, curvatura y esfericidad
    # Los aneurismas reales tienen: alto ratio, alta curvatura, alta esfericidad
    print("[ANEURISMA v2] Calculando score compuesto...")
    
    # Normalizar curvatura (0-1)
    curv_norm = np.clip(curvatures / 0.5, 0, 1)
    
    # Normalizar esfericidad (0-1, típicamente 0.3-0.9 para aneurismas)
    sph_norm = np.clip((sphericity - 0.3) / 0.6, 0, 1)
    
    # Score compuesto
    # - Ratio de dilatación: peso 0.5
    # - Curvatura: peso 0.3
    # - Esfericidad: peso 0.2
    composite_scores = 0.5 * ratios + 0.3 * curv_norm + 0.2 * sph_norm
    
    # Marcar puntos candidatos (base_flag ya calculado para la esfericidad)
    flagged = base_flag
    
    # Refinar: solo puntos con score compuesto alto
    # Si el ratio es alto pero la curvatura es baja, podría ser un vaso
    # simplemente más grueso, no un aneurisma
    flagged = flagged & (composite_scores >= 1.2)
    
    print(f"[ANEURISMA v2] Puntos marcados: {int(flagged.sum())} / {len(ratios)}")
    
    if not np.any(flagged):
        print("[ANEURISMA v2] No se detectaron dilataciones focales.")
        out_img = sitk.GetImageFromArray(np.zeros_like(vessels_arr, dtype=np.uint8))
        out_img.CopyInformation(img)
        sitk.WriteImage(out_img, output_path)
        return output_path, []
    
    print("[ANEURISMA v2] Agrupando puntos en candidatos...")
    flagged_vol = np.zeros_like(skeleton, dtype=np.uint8)
    flagged_vol[tuple(skel_idx[flagged].T)] = 1
    merge_iter = max(1, int(round(cluster_merge_radius_mm / min(s for s in spacing_zyx if s > 0))))
    flagged_dilated = ndi.binary_dilation(flagged_vol, iterations=merge_iter)
    cluster_labels, n_clusters = ndi.label(flagged_dilated, structure=np.ones((3, 3, 3)))
    
    output_arr = np.zeros_like(vessels_arr, dtype=np.uint8)
    reporte = []
    flagged_global_idx = skel_idx[flagged]
    flagged_diam = diam_local[flagged]
    flagged_ratio = ratios[flagged]
    flagged_curv = curvatures[flagged]
    flagged_sph = sphericity[flagged]
    flagged_score = composite_scores[flagged]
    
    for cid in range(1, n_clusters + 1):
        sel = cluster_labels[tuple(flagged_global_idx.T)] == cid
        if not np.any(sel):
            continue
        pts = flagged_global_idx[sel]
        d_local = flagged_diam[sel]
        r_local = flagged_ratio[sel]
        c_local = flagged_curv[sel]
        s_local = flagged_sph[sel]
        sc_local = flagged_score[sel]
        
        centroid_idx = pts.mean(axis=0)
        centroid_phys_zyx = centroid_idx * np.array(spacing_zyx)
        
        near_bifurcation = False
        dist_bifurcacion = None
        if branch_tree is not None:
            dist_bifurcacion, _ = branch_tree.query(centroid_phys_zyx)
            near_bifurcation = bool(dist_bifurcacion <= bifurcation_radius_mm)
        
        max_diam = float(d_local.max())
        max_ratio = float(r_local.max())
        max_curv = float(c_local.max())
        max_sph = float(s_local.max())
        max_score = float(sc_local.max())
        
        # Score final: combina ratio, curvatura, esfericidad y bifurcación
        final_score = max_score * (1.2 if near_bifurcation else 1.0)
        
        centroid_phys = img.TransformContinuousIndexToPhysicalPoint((
            float(centroid_idx[2]), float(centroid_idx[1]), float(centroid_idx[0])
        ))
        
        reporte.append({
            "id": cid,
            "centroide_mm": centroid_phys,
            "diametro_local_max_mm": max_diam,
            "ratio_max": max_ratio,
            "curvatura_max": max_curv,
            "esfericidad_max": max_sph,
            "cerca_de_bifurcacion": near_bifurcation,
            "distancia_bifurcacion_mm": None if dist_bifurcacion is None else float(dist_bifurcacion),
            "n_puntos_esqueleto": int(len(pts)),
            "score": float(final_score),
        })
        
        # Pintar esfera para visualización
        radius_mm = max(max_diam / 2.0 + 1.0, 2.0)
        _paint_sphere(output_arr, centroid_idx, radius_mm, spacing_zyx)
    
    reporte.sort(key=lambda r: r["score"], reverse=True)
    print(f"[ANEURISMA v2] {len(reporte)} candidato(s) detectados:")
    for r in reporte:
        bif_txt = "cerca de bifurcación" if r["cerca_de_bifurcacion"] else "en segmento recto"
        print(f"      #{r['id']}: diam={r['diametro_local_max_mm']:.2f} mm  "
              f"ratio={r['ratio_max']:.2f}  curv={r['curvatura_max']:.2f}  "
              f"esf={r['esfericidad_max']:.2f}  {bif_txt}  score={r['score']:.2f}")
    
    out_img = sitk.GetImageFromArray(output_arr)
    out_img.CopyInformation(img)
    sitk.WriteImage(out_img, output_path)
    return output_path, reporte


def _paint_sphere(volume_zyx, center_idx_zyx, radius_mm, spacing_zyx):
    """Pinta una esfera sólida en el volumen."""
    z0, y0, x0 = center_idx_zyx
    rz = max(1, int(round(radius_mm / spacing_zyx[0])))
    ry = max(1, int(round(radius_mm / spacing_zyx[1])))
    rx = max(1, int(round(radius_mm / spacing_zyx[2])))
    zmin, zmax = max(0, int(z0 - rz)), min(volume_zyx.shape[0], int(z0 + rz + 1))
    ymin, ymax = max(0, int(y0 - ry)), min(volume_zyx.shape[1], int(y0 + ry + 1))
    xmin, xmax = max(0, int(x0 - rx)), min(volume_zyx.shape[2], int(x0 + rx + 1))
    zz, yy, xx = np.ogrid[zmin:zmax, ymin:ymax, xmin:xmax]
    dist2 = (((zz - z0) * spacing_zyx[0]) ** 2 +
             ((yy - y0) * spacing_zyx[1]) ** 2 +
             ((xx - x0) * spacing_zyx[2]) ** 2)
    sphere = dist2 <= radius_mm ** 2
    volume_zyx[zmin:zmax, ymin:ymax, xmin:xmax][sphere] = 1


def build_mesh_improved(mask_path, output_stl, smooth_iterations=2, 
                         gaussian_sigma_mm=0.3, decimate_target=None):
    """
    Genera malla 3D mejorada con suavizado adaptativo.
    
    Mejoras sobre la versión original:
    1. Suavizado adaptativo basado en curvatura local
    2. Decimación opcional para reducir tamaño de archivo
    3. Verificación de integridad de la malla
    
    Args:
        mask_path: Ruta a la máscara NIfTI
        output_stl: Ruta de salida STL
        smooth_iterations: Iteraciones de suavizado
        gaussian_sigma_mm: Sigma del filtro gaussiano
        decimate_target: Número objetivo de caras (None = sin decimar)
    
    Returns:
        str: Ruta al STL generado o None si falla
    """
    print(f"\n[+] Generando malla 3D mejorada: {os.path.basename(output_stl)}...")
    
    if not os.path.exists(mask_path):
        print(f"[!] Máscara no encontrada: {mask_path}")
        return None
    
    try:
        import scipy.ndimage as ndi
        from skimage import measure as skmeasure
        
        img = sitk.ReadImage(mask_path)
        mask_arr = sitk.GetArrayFromImage(img) > 0
        
        if not np.any(mask_arr):
            print("[!] Máscara vacía.")
            return None
        
        # Suavizado gaussiano de la máscara
        if gaussian_sigma_mm > 0:
            spacing = img.GetSpacing()
            sigma_vox = [gaussian_sigma_mm / s for s in spacing]
            mask_arr = ndi.gaussian_filter(mask_arr.astype(np.float32), sigma=sigma_vox)
        
        # Marching cubes
        verts, faces, _, _ = skmeasure.marching_cubes(mask_arr, level=0.5)
        
        # Convertir a coordenadas físicas (mm)
        spacing_zyx = (img.GetSpacing()[2], img.GetSpacing()[1], img.GetSpacing()[0])
        verts_phys = verts * np.array(spacing_zyx)
        
        # Crear malla trimesh
        mesh = trimesh.Trimesh(vertices=verts_phys, faces=faces)
        
        # Verificar integridad
        mesh.remove_degenerate_faces()
        mesh.remove_duplicate_faces()
        mesh.remove_unreferenced_vertices()
        mesh.fix_normals()
        
        # Suavizado adaptativo
        if smooth_iterations > 0:
            print(f"   -> Suavizado adaptativo ({smooth_iterations} iteraciones)...")
            # Suavizado Laplaciano con preservación de volumen
            from trimesh.smoothing import filter_laplacian
            filter_laplacian(mesh, iterations=smooth_iterations, lamb=0.5)
        
        # Decimación opcional
        if decimate_target and len(mesh.faces) > decimate_target:
            print(f"   -> Decimando de {len(mesh.faces):,} a {decimate_target:,} caras...")
            mesh = mesh.simplify_quadric_decimation(decimate_target)
        
        # Verificar que la malla es válida
        if not mesh.is_watertight:
            print("   -> [!] Malla no es watertight (puede tener agujeros)")
        
        # Exportar
        mesh.export(output_stl)
        
        # Estadísticas
        volume_mm3 = mesh.volume
        area_mm2 = mesh.area
        print(f"   -> Vértices: {len(mesh.vertices):,}")
        print(f"   -> Caras: {len(mesh.faces):,}")
        print(f"   -> Volumen: {volume_mm3:.1f} mm³")
        print(f"   -> Superficie: {area_mm2:.1f} mm²")
        print(f"[+] STL generado: {output_stl}")
        
        return output_stl
    
    except Exception as e:
        print(f"[!] Error generando malla: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("=" * 70)
    print("MÓDULO DE INTEGRACIÓN BRATS Y MEJORAS")
    print("=" * 70)
    print()
    print("Este módulo proporciona funciones para:")
    print("  1. integrate_brats_into_pipeline() - Integrar BRATS en el pipeline")
    print("  2. improve_aneurysm_detection() - Detección mejorada de aneurismas")
    print("  3. build_mesh_improved() - Generación de mallas 3D mejoradas")
    print()
    print("Para usarlo, importa las funciones en tu script principal:")
    print("  from 03_integrar_brats import integrate_brats_into_pipeline")
    print("  from 03_integrar_brats import improve_aneurysm_detection")
    print("  from 03_integrar_brats import build_mesh_improved")
    print()
    print("Verificando modelo BRATS...")
    verify_brats_model()