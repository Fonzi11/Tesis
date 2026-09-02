import os
import SimpleITK as sitk
import subprocess
import sys
import shutil
import importlib
import textwrap
import zipfile
import numpy as np
import trimesh
from skimage import measure

colab_drive = None
colab_files = None


def _load_colab_drive_module():
    try:
        return importlib.import_module("google.colab.drive")
    except ModuleNotFoundError:
        return None


def _load_colab_files_module():
    try:
        return importlib.import_module("google.colab.files")
    except ModuleNotFoundError:
        return None


def is_colab_environment():
    global colab_drive
    if colab_drive is None:
        colab_drive = _load_colab_drive_module()
    return colab_drive is not None


def setup_colab_dicom_upload(upload_dir="/content/dicom_uploads"):
    global colab_files
    if not is_colab_environment():
        print(" La carga interactiva de DICOM est disponible solo en Colab.")
        return None

    if colab_files is None:
        colab_files = _load_colab_files_module()

    if colab_files is None:
        print(" No se pudo cargar google.colab.files en este entorno.")
        return None

    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir)
    os.makedirs(upload_dir, exist_ok=True)

    print(" INTERFAZ DE CARGA DE ESTUDIOS DICOM")
    print("Comprime tu carpeta DICOM en un .zip y sbelo aqu.")
    uploaded = colab_files.upload()

    for filename in uploaded.keys():
        if filename.lower().endswith(".zip"):
            print(f"\nExtrayendo '{filename}'...")
            with zipfile.ZipFile(filename, "r") as zip_ref:
                zip_ref.extractall(upload_dir)
            print("[+] Extraccin completada con xito")
        else:
            print(f" '{filename}' no es .zip. Moviendo archivo a la carpeta de trabajo...")
            shutil.move(filename, os.path.join(upload_dir, filename))

    total_files = 0
    for root, _, files in os.walk(upload_dir):
        total_files += len(files)

    print(f" Total de archivos listos para procesar: {total_files}")
    print(f"Ruta configurada: {upload_dir}")
    return upload_dir


def mount_drive_if_colab(mount_point="/content/drive"):
    if not is_colab_environment():
        print(" Entorno local detectado. Google Drive solo se monta automticamente en Colab.")
        return False

    print("[Colab] Montando Google Drive...")
    colab_drive.mount(mount_point)
    return True


def install_colab_dependencies():
    if not is_colab_environment():
        return

    print("[Colab] Verificando/instalando dependencias del pipeline...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "SimpleITK",
        "TotalSegmentator",
        "pyvista",
        "trimesh",
        "nibabel",
    ]
    subprocess.run(cmd, check=True)


def _find_first_dicom_series(dicom_root):
    """Busca recursivamente la primera serie DICOM vlida dentro de una carpeta."""
    reader = sitk.ImageSeriesReader()

    # Primero intentamos directamente en la ruta raz.
    series_ids = reader.GetGDCMSeriesIDs(dicom_root)
    if series_ids:
        series_id = series_ids[0]
        file_names = reader.GetGDCMSeriesFileNames(dicom_root, series_id)
        if file_names:
            return dicom_root, series_id, file_names

    # Si no hay serie en raz, buscamos en subcarpetas.
    for current_dir, _, _ in os.walk(dicom_root):
        series_ids = reader.GetGDCMSeriesIDs(current_dir)
        if not series_ids:
            continue

        series_id = series_ids[0]
        file_names = reader.GetGDCMSeriesFileNames(current_dir, series_id)
        if file_names:
            return current_dir, series_id, file_names

    return None, None, []


def dicom_to_nifti(dicom_dir, output_file="volumen_paciente.nii.gz"):
    print(f"[1/3] Leyendo serie DICOM desde: {dicom_dir}...")
    series_dir, series_id, dicom_names = _find_first_dicom_series(dicom_dir)
    if not dicom_names:
        raise RuntimeError(
            "No se encontr ninguna serie DICOM vlida. "
            "Verifica que la carpeta contenga archivos DICOM (pueden estar en subcarpetas)."
        )

    print(f"   Serie detectada en: {series_dir}")
    print(f"   ID de serie: {series_id}")
    print(f"   Archivos encontrados: {len(dicom_names)}")

    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(dicom_names)
    
    # Ejecutar la lectura y guardar el volumen
    image = reader.Execute()
    sitk.WriteImage(image, output_file)
    print(f"[+] Volumen NIfTI guardado en: {output_file}")
    return output_file


def _is_nifti_file(path):
    lower_path = path.lower()
    return lower_path.endswith(".nii") or lower_path.endswith(".nii.gz")


def resolve_input_volume(input_path, output_nifti):
    """Resuelve la entrada del pipeline: NIfTI directo o conversin desde DICOM."""
    if os.path.isfile(input_path) and _is_nifti_file(input_path):
        print(f"[1/3] NIfTI detectado. Se usar directamente: {input_path}")
        return input_path

    if os.path.isdir(input_path):
        # Permite que la carpeta de entrada contenga un NIfTI suelto.
        for root, _, files in os.walk(input_path):
            for file_name in files:
                if _is_nifti_file(file_name):
                    nifti_path = os.path.join(root, file_name)
                    print(f"[1/3] NIfTI detectado en carpeta. Se usar directamente: {nifti_path}")
                    return nifti_path

        # Si no hay NIfTI, se intenta como DICOM.
        return dicom_to_nifti(input_path, output_nifti)

    raise RuntimeError(
        "La ruta de entrada no es vlida. Proporciona una carpeta con DICOM o un archivo .nii/.nii.gz"
    )


def _build_totalsegmentator_command(input_nifti, output_dir, fast_mode=False):
    # Ejecutar siempre con el intrprete activo evita inconsistencias con wrappers .EXE.
    comando = [
        sys.executable,
        "-m",
        "totalsegmentator.bin.TotalSegmentator",
        "-i",
        input_nifti,
        "-o",
        output_dir,
    ]
    if fast_mode:
        comando.append("--fast")
    return comando


def _ensure_totalsegmentator_runtime_requirements():
    """Asegura dependencias de runtime que algunas versiones de TotalSegmentator requieren."""
    try:
        import pkg_resources  # noqa: F401
    except ModuleNotFoundError:
        print("Instalando runtime faltante: setuptools<81 (incluye pkg_resources)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "setuptools<81"], check=True)


def run_ai_segmentation(input_nifti, output_dir="segmentaciones_ai", fast_mode=False):
    print(f"\n[2/3] Iniciando inferencia de IA con TotalSegmentator...")
    os.makedirs(output_dir, exist_ok=True)
    _ensure_totalsegmentator_runtime_requirements()

    if fast_mode:
        print("   -> Modo RAPIDO (--fast): resolucion ~3mm. Mas veloz, menos detalle de borde.")
    else:
        print("   -> Modo MAXIMA RESOLUCION (sin --fast): resolucion nativa del modelo (~1.5mm). "
              "Mas lento (puede tomar varios minutos mas que en modo rapido), pero el limite de "
              "detalle del cerebro/craneo pasa a ser la resolucion original del escaneo, no el modelo.")

    comando = _build_totalsegmentator_command(input_nifti, output_dir, fast_mode=fast_mode)
    env = os.environ.copy()
    # Compatibilidad con checkpoints de nnUNet/TotalSegmentator en versiones recientes de PyTorch.
    env.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    
    try:
        subprocess.run(comando, check=True, env=env)
        print(f"[+] Segmentacin completada. Mscaras guardadas en: {output_dir}")
    except subprocess.CalledProcessError as e:
        print(f" Error ejecutando TotalSegmentator: {e}")
        print("   Tip: revisa el mensaje de error justo arriba para la causa raz (modelo, dependencia o formato).")


def build_mesh(mask_path, output_stl, smooth_iterations=10, gaussian_sigma_mm=0.5):
    """
    Genera malla 3D al MAXIMO DETALLE y SUAVIDAD.
    Aplica un filtro Gaussiano 3D a la mascara antes de extraer la geometria.
    Esto elimina por completo el aspecto de 'bloques' (Minecraft) y crea
    superficies organicas perfectas.

    gaussian_sigma_mm se especifica en milimetros fisicos (no en voxeles) y se
    convierte a un sigma distinto por eje usando el spacing real -- antes el
    sigma era 1.0 "voxel" fijo en los 3 ejes, lo cual en un volumen con
    espaciado anisotropico (tipico en CT clinico: ~0.5mm en plano pero 2-5mm
    de grosor de corte) distorsiona la geometria de forma muy desigual segun
    el eje. Un sigma menor preserva mas detalle anatomico fino (giros/surcos
    cerebrales, forma de foramenes craneales); uno mayor prioriza suavidad.
    """
    print(f"\n[3/3] Generando malla organica de alta resolucion: {os.path.basename(mask_path)}...", flush=True)
    if not os.path.exists(mask_path):
        return None

    mask_img = sitk.ReadImage(mask_path)
    mask_arr = sitk.GetArrayFromImage(mask_img)

    if np.max(mask_arr) <= 0:
        return None

    spacing_xyz = mask_img.GetSpacing()
    spacing_zyx = (spacing_xyz[2], spacing_xyz[1], spacing_xyz[0])

    print(f"   -> Aplicando suavizado Gaussiano 3D calibrado a {gaussian_sigma_mm} mm fisicos por eje...", flush=True)
    import scipy.ndimage
    # sigma por eje en voxeles = sigma deseado en mm / tamano de voxel en ese eje.
    # Asi el suavizado es fisicamente isotropico (igual en mm en los 3 ejes)
    # incluso si el voxel no lo es -- antes sigma=1.0 fijo en voxeles causaba
    # muchisimo mas blur fisico en el eje de mayor espaciado (tipicamente Z).
    sigma_per_axis = tuple(gaussian_sigma_mm / s for s in spacing_zyx)
    smoothed_mask = scipy.ndimage.gaussian_filter(mask_arr.astype(np.float32), sigma=sigma_per_axis)

    # Extraer malla al 50% del gradiente
    verts_zyx, faces, _, _ = measure.marching_cubes(
        smoothed_mask,
        level=0.5,
        spacing=spacing_zyx,
        step_size=1
    )
    verts_xyz = verts_zyx[:, ::-1]
    mesh = trimesh.Trimesh(vertices=verts_xyz, faces=faces, process=True)

    print(f"   Poligonos extraidos: {len(mesh.faces):,}", flush=True)

    if smooth_iterations > 0:
        print("   -> Aplicando pulido final de malla (Taubin)...", flush=True)
        try:
            trimesh.smoothing.filter_taubin(mesh, iterations=smooth_iterations)
        except Exception:
            pass

    mesh.export(output_stl)
    print(f"[+] Malla guardada: {output_stl}", flush=True)
    return output_stl


def generate_tumor_mask(nifti_path, brain_mask_path, output_tumor_path,
                         min_volume_mm3=150.0, structuring_radius_mm=1.5,
                         min_score=0.35, seed_percentile=95.0, growth_percentile=80.0,
                         max_growth_radius_mm=20.0, exclusion_mask_paths=None):
    """
    Deteccion de tumor por Morfologia Matematica -- v3 (nucleo + histeresis de extension).

    v2 solo capturaba el nucleo mas brillante (percentil 95) de cada tumor.
    En un tumor real heterogeneo (nucleo con realce + borde/edema mas tenue),
    eso deja fuera la mayor parte del volumen real -- en pruebas sinteticas
    con un halo de menor intensidad alrededor del nucleo, v2 solo capturaba
    ~12% del volumen real del tumor.

    v3 separa DETECCION de DELIMITACION, con el mismo principio de histeresis
    de dos umbrales que ya se uso para vasos:
      1. NUCLEO (semilla): umbral estricto (seed_percentile) + apertura
         morfologica calibrada en mm -- igual que v2. Sirve para DETECTAR
         (puntuar forma/tamano/intensidad) y para excluir venas/ruido delgado.
      2. EXTENSION (histeresis): umbral permisivo (growth_percentile), TAMBIEN
         abierto morfologicamente (para que una vena delgada que pase el
         umbral permisivo no sea un canal de fuga), usado como mascara limite
         para una dilatacion condicionada desde el nucleo aceptado
         (scipy.ndimage.binary_dilation con parametro mask). La dilatacion
         esta acotada a max_growth_radius_mm para que el crecimiento no se
         escape indefinidamente a traves de tejido conectado de intensidad
         intermedia -- una region-growing sin cota de distancia es el error
         clasico que hace que este tipo de metodo "invada" tejido sano.

    El volumen/score reportado sigue basandose en las propiedades del NUCLEO
    (forma/tamano/intensidad), no en la extension ya crecida -- porque la
    extension puede ser irregular (edema) y no es un buen indicador de
    "que tan tumoral" es la masa; solo indica cuanto ocupa.
    """
    print("\n[+] Detectando tumor (nucleo solido + histeresis de extension real)...")
    if not os.path.exists(brain_mask_path):
        return None

    img = sitk.ReadImage(nifti_path)
    mask = sitk.ReadImage(brain_mask_path)
    img_arr = sitk.GetArrayFromImage(img).astype(np.float32)
    mask_arr = sitk.GetArrayFromImage(mask).astype(np.uint8)

    brain_voxels = img_arr[mask_arr > 0]
    total_vox = len(brain_voxels)
    if total_vox == 0:
        return None

    import scipy.ndimage as ndi

    spacing_xyz = img.GetSpacing()
    voxel_volume_mm3 = spacing_xyz[0] * spacing_xyz[1] * spacing_xyz[2]
    mean_voxel_size_mm = voxel_volume_mm3 ** (1.0 / 3.0)

    print("   -> Paso 1: Aislar el nucleo (umbral estricto)...")
    seed_threshold = float(np.percentile(brain_voxels, seed_percentile))
    seed_candidate_mask = (img_arr > seed_threshold) & (mask_arr > 0)

    if exclusion_mask_paths:
        for excl_path in exclusion_mask_paths:
            if excl_path and os.path.exists(excl_path):
                excl_arr = sitk.GetArrayFromImage(sitk.ReadImage(excl_path)) > 0
                if excl_arr.shape == seed_candidate_mask.shape:
                    seed_candidate_mask &= ~excl_arr
                    print(f"      Excluyendo estructura conocida: {os.path.basename(excl_path)}")

    print(f"   -> Paso 2: Apertura morfologica del nucleo, calibrada a {structuring_radius_mm} mm...")
    struct = ndi.generate_binary_structure(3, 1)
    iterations = max(1, int(round(structuring_radius_mm / mean_voxel_size_mm)))
    opened_seed_mask = ndi.binary_opening(seed_candidate_mask, structure=struct, iterations=iterations)

    print(f"   -> Paso 3: Preparando mascara de extension (umbral permisivo, tambien abierta)...")
    growth_threshold = float(np.percentile(brain_voxels, growth_percentile))
    growth_mask_raw = (img_arr > growth_threshold) & (mask_arr > 0)
    # Igual que con el nucleo: abrir la mascara de crecimiento para que el
    # halo/edema (solido) sobreviva, pero una vena delgada que tambien pase
    # el umbral permisivo NO sea un canal por el que el crecimiento se filtre
    # fuera del tumor real.
    growth_mask = ndi.binary_opening(growth_mask_raw, structure=struct, iterations=iterations)
    growth_iterations = max(1, int(round(max_growth_radius_mm / mean_voxel_size_mm)))

    print("   -> Paso 4: Puntuando nucleos candidatos (tamano + forma + intensidad)...")
    tumor_arr = np.zeros_like(mask_arr, dtype=np.uint8)
    labeled_seed, n_seed = ndi.label(opened_seed_mask)
    candidatos = []

    if n_seed > 0:
        slices = ndi.find_objects(labeled_seed)
        for comp_id in range(1, n_seed + 1):
            sl = slices[comp_id - 1]
            if sl is None:
                continue
            comp_local = labeled_seed[sl] == comp_id
            size_vox = int(comp_local.sum())
            volume_mm3 = size_vox * voxel_volume_mm3
            if volume_mm3 < min_volume_mm3:
                continue

            eroded_local = ndi.binary_erosion(comp_local, structure=struct)
            surface_vox = size_vox - int(eroded_local.sum())
            surface_mm2 = max(surface_vox * (mean_voxel_size_mm ** 2), 1e-6)
            sphericity = (np.pi ** (1.0 / 3.0)) * ((6.0 * volume_mm3) ** (2.0 / 3.0)) / surface_mm2
            sphericity = float(min(sphericity, 1.0))

            mean_intensity = float(img_arr[sl][comp_local].mean())
            intensity_contrast = (mean_intensity - seed_threshold) / max(seed_threshold, 1e-6)
            intensity_score = float(np.clip(intensity_contrast, 0.0, 1.0))
            size_score = float(np.clip(volume_mm3 / 2000.0, 0.0, 1.0))

            # Score compuesto heuristico (NO es una probabilidad clinica
            # calibrada): combina forma solida/redondeada, tamano relativo
            # e intensidad del NUCLEO por encima del umbral estricto.
            score = 0.45 * sphericity + 0.30 * size_score + 0.25 * intensity_score

            seed_full = np.zeros_like(mask_arr, dtype=bool)
            seed_full[sl][comp_local] = True

            candidatos.append({
                "seed_full": seed_full, "volumen_nucleo_mm3": volume_mm3,
                "esfericidad": sphericity, "score": score,
            })

    candidatos.sort(key=lambda c: c["score"], reverse=True)
    aceptados = [c for c in candidatos if c["score"] >= min_score]

    if aceptados:
        print(f"   -> {len(aceptados)} nucleo(s) aceptado(s) de {len(candidatos)} evaluado(s); "
              f"expandiendo cada uno hasta {max_growth_radius_mm} mm dentro del halo de "
              f"intensidad permisiva (dilatacion condicionada, sin fuga por ruido)...")
        for i, c in enumerate(aceptados, start=1):
            # Dilatacion condicionada (region growing acotado): crece el
            # nucleo hacia afuera SOLO dentro de growth_mask, limitada a
            # growth_iterations pasos -- captura el halo/edema real conectado
            # sin invadir tejido sano arbitrariamente lejano.
            region = ndi.binary_dilation(c["seed_full"], structure=struct,
                                          iterations=growth_iterations, mask=growth_mask)
            tumor_arr[region] = 1

            vol_total_mm3 = float(region.sum()) * voxel_volume_mm3
            vol_pct = 100.0 * vol_total_mm3 / (total_vox * voxel_volume_mm3)
            centroid_full = ndi.center_of_mass(region)
            centroid_phys = img.TransformContinuousIndexToPhysicalPoint(
                (centroid_full[2], centroid_full[1], centroid_full[0])
            )
            print(f"      #{i}: nucleo={c['volumen_nucleo_mm3']:.1f} mm3  "
                  f"extension_total={vol_total_mm3:.1f} mm3 ({vol_pct:.2f}% del cerebro)  "
                  f"esfericidad_nucleo={c['esfericidad']:.2f}  score={c['score']:.2f}  "
                  f"centroide(mm)={tuple(round(v, 1) for v in centroid_phys)}")
    else:
        print("   -> No se encontro ningun nucleo tumoral con score suficiente "
              "(podria estar sano, o min_score es muy exigente).")

    out_img = sitk.GetImageFromArray(tumor_arr)
    out_img.CopyInformation(img)
    sitk.WriteImage(out_img, output_tumor_path)
    return output_tumor_path


def _warn_if_not_contrast_study(image):
    """
    Verificacion best-effort de que el estudio es angiografico con contraste.
    NIfTI no preserva de forma fiable las etiquetas DICOM originales (el tag
    ContrastBolusAgent, 0018|0010, solo sobrevive si la conversion lo
    propago explicitamente), asi que esto es una advertencia informativa,
    no una validacion garantizada.
    """
    tag = "0018|0010"
    try:
        if image.HasMetaDataKey(tag) and image.GetMetaData(tag).strip():
            print(f"   -> Contraste detectado en metadatos ({tag}): {image.GetMetaData(tag)}")
            return True
    except Exception:
        pass
    print("   -> [!] No se pudo confirmar por metadatos que el estudio tiene contraste. "
          "La deteccion de vasos/aneurisma asume un estudio CTA/MRA; verifica "
          "manualmente el protocolo de adquisicion antes de confiar en el resultado.")
    return False


def _resample_isotropic(sitk_image, target_spacing_mm=None, interpolator=sitk.sitkLinear,
                         min_spacing_floor_mm=0.15):
    """
    Remuestrea sitk_image a espaciado isotropico. Si target_spacing_mm es None,
    usa el eje de espaciado nativo MAS FINO disponible (maxima resolucion sin
    inventar detalle que el escaneo no tiene), con un piso de seguridad
    (min_spacing_floor_mm) para evitar tamanos de volumen absurdos si algun
    metadato de espaciado viniera corrupto.
    """
    original_spacing = sitk_image.GetSpacing()
    if target_spacing_mm is None:
        target_spacing_mm = max(min(original_spacing), min_spacing_floor_mm)
    original_size = sitk_image.GetSize()
    new_size = [max(1, int(round(osz * ospc / target_spacing_mm)))
                for osz, ospc in zip(original_size, original_spacing)]
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing((target_spacing_mm,) * 3)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(sitk_image.GetDirection())
    resampler.SetOutputOrigin(sitk_image.GetOrigin())
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(0)
    resampler.SetInterpolator(interpolator)
    return resampler.Execute(sitk_image), target_spacing_mm


def _crop_to_mask_bbox(image, mask_arr_zyx, margin_mm=5.0):
    """Recorta `image` (sitk) al bounding box fisico de mask_arr_zyx (mismo grid que image), con margen."""
    import scipy.ndimage as ndi
    mask_bin = (mask_arr_zyx > 0).astype(np.uint8)
    obj_slices = ndi.find_objects(mask_bin)
    if not obj_slices or obj_slices[0] is None:
        return image
    sl = obj_slices[0]
    spacing_xyz = image.GetSpacing()
    size_xyz = image.GetSize()
    margin_vox = [int(np.ceil(margin_mm / spacing_xyz[i])) for i in range(3)]
    idx_x0 = max(0, sl[2].start - margin_vox[0]); idx_x1 = min(size_xyz[0], sl[2].stop + margin_vox[0])
    idx_y0 = max(0, sl[1].start - margin_vox[1]); idx_y1 = min(size_xyz[1], sl[1].stop + margin_vox[1])
    idx_z0 = max(0, sl[0].start - margin_vox[2]); idx_z1 = min(size_xyz[2], sl[0].stop + margin_vox[2])
    start = (int(idx_x0), int(idx_y0), int(idx_z0))
    size = (int(idx_x1 - idx_x0), int(idx_y1 - idx_y0), int(idx_z1 - idx_z0))
    return sitk.RegionOfInterest(image, size, start)


def generate_vessels_mask(nifti_path, brain_mask_path, output_vessels_path,
                           frangi_sigmas_mm=(0.5, 1.0, 1.5, 2.0),
                           target_spacing_mm=None, intensity_percentile=None):
    """
    Deteccion de venas y arterias -- v3 (isotropico + histeresis intensidad + vesselness).

    v2 aplicaba Frangi usando un unico sigma "en voxeles" derivado del tamano
    de voxel PROMEDIO -- esto es incorrecto en un volumen anisotropico (muy
    comun en CT clinico: p.ej. 0.5mm en plano pero 3mm de grosor de corte),
    porque el filtro de Frangi asume que una distancia de "1 voxel" significa
    lo mismo en los 3 ejes. En una prueba con espaciado 0.5x0.5x3.0mm, ese
    error producia una mascara con MAS DE 55,000 voxeles de falso positivo
    (contra 840 voxeles reales de un vaso de prueba) -- consistente con
    "identifico mal las venas y arterias".

    v3 corrige esto:
      1. Recorta al bounding box del cerebro (abarata el resto del proceso).
      2. REMUESTREA a espaciado isotropico usando el eje nativo mas fino
         (maxima resolucion real disponible, sin inventar detalle) antes de
         calcular Frangi -- asi "1 voxel" de verdad significa lo mismo en
         los 3 ejes.
      3. Frangi + umbral de OTSU sobre el mapa de vesselness (adaptativo a
         los datos, en vez de un percentil fijo arbitrario).
      4. Histeresis igual que v2 (conservar componentes del umbral de
         intensidad que tocan la zona tubular), porque Frangi solo sigue
         subestimando dilataciones tipo aneurisma -- por eso NUNCA se usa
         como mascara final, solo como validador de forma.
      5. Remuestrea la mascara final de vuelta a la resolucion NATIVA del
         estudio (el resto del pipeline, incluida la reconstruccion de
         malla, sigue trabajando a resolucion original).
    """
    print("\n[+] Detectando venas y arterias del cerebro (isotropico + histeresis intensidad+Frangi)...")
    if not os.path.exists(brain_mask_path):
        return None

    img = sitk.ReadImage(nifti_path)
    mask = sitk.ReadImage(brain_mask_path)
    _warn_if_not_contrast_study(img)

    mask_arr_native = sitk.GetArrayFromImage(mask)
    if not np.any(mask_arr_native > 0):
        return None

    import scipy.ndimage as ndi
    from skimage import filters as skfilters
    from skimage.filters import threshold_otsu

    print("   -> Recortando al bounding box del cerebro...")
    img_crop = _crop_to_mask_bbox(img, mask_arr_native, margin_mm=5.0)
    mask_crop = _crop_to_mask_bbox(mask, mask_arr_native, margin_mm=5.0)

    print("   -> Remuestreando a resolucion isotropica nativa (maxima precision) para el filtro de vesselness...")
    img_iso, iso_spacing = _resample_isotropic(img_crop, target_spacing_mm, sitk.sitkLinear)
    mask_iso, _ = _resample_isotropic(mask_crop, iso_spacing, sitk.sitkNearestNeighbor)
    print(f"      spacing nativo: {tuple(round(s, 2) for s in img.GetSpacing())} mm  ->  "
          f"spacing isotropico usado: {iso_spacing:.3f} mm  (volumen: {img_iso.GetSize()}, "
          f"puede tardar mas que en baja resolucion)")

    img_iso_arr = sitk.GetArrayFromImage(img_iso).astype(np.float32)
    mask_iso_arr = sitk.GetArrayFromImage(mask_iso) > 0

    brain_voxels_iso = img_iso_arr[mask_iso_arr]
    if len(brain_voxels_iso) == 0:
        return None

    mean_val = np.mean(brain_voxels_iso)
    std_val = np.std(brain_voxels_iso)
    threshold = mean_val + 3.0 * std_val
    intensity_mask = mask_iso_arr & (img_iso_arr > threshold)

    if not np.any(intensity_mask):
        print("   -> No hay voxeles por encima del umbral de intensidad.")
        vessels_iso = np.zeros_like(mask_iso_arr, dtype=np.uint8)
    else:
        sigmas_vox = sorted(set(max(1, int(round(s / iso_spacing))) for s in frangi_sigmas_mm))
        print(f"   -> Calculando vesselness (Frangi, sigmas={sigmas_vox} voxeles isotropicos)...")
        vesselness = skfilters.frangi(img_iso_arr, sigmas=sigmas_vox, black_ridges=False)
        vesselness[~mask_iso_arr] = 0

        if not np.any(vesselness > 0):
            print("   -> Vesselness nulo en la region cerebral; se usa solo el umbral de intensidad.")
            vessels_iso = intensity_mask.astype(np.uint8)
        else:
            otsu_t = threshold_otsu(vesselness[vesselness > 0])
            frangi_mask = vesselness > otsu_t
            print(f"   -> Umbral de Otsu sobre vesselness: {otsu_t:.4f}")

            print("   -> Histeresis: conservando componentes conexos validados por vesselness...")
            labeled, n_comp = ndi.label(intensity_mask, structure=np.ones((3, 3, 3)))
            touched_labels = np.unique(labeled[frangi_mask & (labeled > 0)])
            touched_labels = touched_labels[touched_labels > 0]
            vessels_iso = np.isin(labeled, touched_labels).astype(np.uint8)

            n_descartados = n_comp - len(touched_labels)
            print(f"   -> Componentes conservados: {len(touched_labels)} / {n_comp} "
                  f"({n_descartados} descartados por no tener soporte tubular)")

    vessels_iso_img = sitk.GetImageFromArray(vessels_iso)
    vessels_iso_img.CopyInformation(img_iso)

    print("   -> Remuestreando la mascara final de vuelta a la resolucion nativa...")
    vessels_native = sitk.Resample(vessels_iso_img, img, sitk.Transform(), sitk.sitkNearestNeighbor, 0)
    sitk.WriteImage(vessels_native, output_vessels_path)
    return output_vessels_path


def _paint_sphere(volume_zyx, center_idx_zyx, radius_mm, spacing_zyx):
    """Pinta una esfera solida (radio en mm) centrada en center_idx_zyx (z,y,x) dentro de volume_zyx."""
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


def generate_aneurysm_candidates(nifti_path, vessels_mask_path, output_path,
                                  dilation_ratio_threshold=1.5,
                                  min_local_diameter_mm=1.0,
                                  baseline_window_mm=(6.0, 15.0),
                                  bifurcation_radius_mm=4.0,
                                  cluster_merge_radius_mm=3.0):
    """
    Deteccion de candidatos a aneurisma sobre la mascara vascular.

    No existia una etapa dedicada a esto en la version original: la mascara
    de vasos por si sola no distingue un vaso normal de uno con una
    dilatacion focal. El metodo implementado aqui:

      1. Esqueletoniza la mascara vascular -> grafo de lineas centrales.
      2. Mide el diametro local en cada punto del esqueleto via la
         transformada de distancia euclidiana (radio = distancia al fondo
         mas cercano, en mm reales usando el espaciado fisico).
      3. Para cada punto, calcula un diametro "basal" = mediana del
         diametro de los puntos del esqueleto que estan a una distancia
         intermedia (baseline_window_mm) a lo largo del vaso -- ni
         demasiado cerca (podrian ser parte de la misma dilatacion) ni
         demasiado lejos (otro segmento vascular distinto).
      4. Marca como candidato todo punto cuyo diametro local supere
         dilation_ratio_threshold veces su diametro basal (criterio
         analogo al usado clinicamente para aneurismas aorticos, adaptado
         aqui a vasculatura cerebral) Y cuyo diametro absoluto supere
         min_local_diameter_mm (evita marcar ruido en vasos muy delgados,
         donde el ratio es numericamente inestable).
      5. Agrupa puntos marcados cercanos en candidatos discretos, y calcula
         la distancia de cada uno al nodo de bifurcacion (grado>=3) mas
         cercano: 80-90% de los aneurismas saculares intracraneales ocurren
         en bifurcaciones, asi que esta distancia se usa como refuerzo de
         confianza en el score, no como filtro excluyente.

    Limitacion explicita: el tamano reportado de cada candidato es el
    conteo de puntos del esqueleto agrupados, NO un volumen segmentado del
    saco aneurismatico (eso requeriria una etapa adicional de crecimiento
    de region). El resultado debe tratarse como una lista de coordenadas
    candidatas para revision humana, no como un diagnostico.
    """
    print("\n[+] Buscando candidatos a aneurisma (perfil de diametro sobre el esqueleto vascular)...")
    if not os.path.exists(vessels_mask_path):
        return None, []

    img = sitk.ReadImage(nifti_path)
    vessels_img = sitk.ReadImage(vessels_mask_path)
    vessels_arr = sitk.GetArrayFromImage(vessels_img) > 0

    if not np.any(vessels_arr):
        print("   -> Mascara de vasos vacia; no hay candidatos que buscar.")
        return None, []

    spacing_xyz = img.GetSpacing()
    spacing_zyx = (spacing_xyz[2], spacing_xyz[1], spacing_xyz[0])

    import scipy.ndimage as ndi
    from scipy.spatial import cKDTree
    from skimage import morphology as skmorph

    print("   -> Esqueletonizando arbol vascular...")
    try:
        skeleton = skmorph.skeletonize(vessels_arr)
    except Exception:
        skeleton = skmorph.skeletonize_3d(vessels_arr)  # compatibilidad con scikit-image antiguo

    if not np.any(skeleton):
        print("   -> El esqueleto resulto vacio; se omite la deteccion de aneurisma.")
        return None, []

    print("   -> Perfil de diametro local (transformada de distancia euclidiana)...")
    dist_transform = ndi.distance_transform_edt(vessels_arr, sampling=spacing_zyx)
    skel_idx = np.argwhere(skeleton)
    diam_local = 2.0 * dist_transform[skeleton]
    skel_phys = skel_idx * np.array(spacing_zyx)

    print("   -> Detectando bifurcaciones (grado de conectividad >= 3)...")
    kernel = np.ones((3, 3, 3))
    kernel[1, 1, 1] = 0
    neighbor_count = ndi.convolve(skeleton.astype(np.uint8), kernel, mode='constant')
    branch_mask = skeleton & (neighbor_count >= 3)
    branch_phys = np.argwhere(branch_mask) * np.array(spacing_zyx)
    branch_tree = cKDTree(branch_phys) if len(branch_phys) > 0 else None

    print("   -> Calculando ratio diametro local / diametro basal...")
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

    flagged = (ratios >= dilation_ratio_threshold) & (diam_local >= min_local_diameter_mm)
    print(f"   -> Puntos del esqueleto marcados: {int(flagged.sum())} / {len(ratios)}")

    if not np.any(flagged):
        print("   -> No se detectaron dilataciones focales por encima del umbral.")
        out_img = sitk.GetImageFromArray(np.zeros_like(vessels_arr, dtype=np.uint8))
        out_img.CopyInformation(img)
        sitk.WriteImage(out_img, output_path)
        return output_path, []

    print("   -> Agrupando puntos marcados en candidatos discretos...")
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

    for cid in range(1, n_clusters + 1):
        sel = cluster_labels[tuple(flagged_global_idx.T)] == cid
        if not np.any(sel):
            continue
        pts = flagged_global_idx[sel]
        d_local = flagged_diam[sel]
        r_local = flagged_ratio[sel]

        centroid_idx = pts.mean(axis=0)  # (z, y, x)
        centroid_phys_zyx = centroid_idx * np.array(spacing_zyx)

        near_bifurcation = False
        dist_bifurcacion = None
        if branch_tree is not None:
            dist_bifurcacion, _ = branch_tree.query(centroid_phys_zyx)
            near_bifurcation = bool(dist_bifurcacion <= bifurcation_radius_mm)

        max_diam = float(d_local.max())
        max_ratio = float(r_local.max())
        # Score heuristico (no calibrado clinicamente): premia mayor
        # dilatacion relativa, y da un plus si esta cerca de una
        # bifurcacion (ubicacion tipica de aneurismas saculares).
        score = max_ratio * (1.3 if near_bifurcation else 1.0)

        centroid_phys = img.TransformContinuousIndexToPhysicalPoint((
            float(centroid_idx[2]), float(centroid_idx[1]), float(centroid_idx[0])
        ))

        reporte.append({
            "id": cid,
            "centroide_mm": centroid_phys,
            "diametro_local_max_mm": max_diam,
            "ratio_max": max_ratio,
            "cerca_de_bifurcacion": near_bifurcation,
            "distancia_bifurcacion_mm": None if dist_bifurcacion is None else float(dist_bifurcacion),
            "n_puntos_esqueleto": int(len(pts)),
            "score": float(score),
        })

        # Pintar una esfera de radio fisico (diametro/2 + margen) en el
        # centroide, para que el candidato sea visualizable/exportable
        # como malla 3D en las etapas siguientes del pipeline.
        radius_mm = max(max_diam / 2.0 + 1.0, 2.0)
        _paint_sphere(output_arr, centroid_idx, radius_mm, spacing_zyx)

    reporte.sort(key=lambda r: r["score"], reverse=True)
    print(f"   -> {len(reporte)} candidato(s) a dilatacion focal / aneurisma:")
    for r in reporte:
        bif_txt = "cerca de bifurcacion" if r["cerca_de_bifurcacion"] else "en segmento recto"
        print(f"      #{r['id']}: diam_local_max={r['diametro_local_max_mm']:.2f} mm  "
              f"ratio={r['ratio_max']:.2f}  {bif_txt}  score={r['score']:.2f}  "
              f"centroide(mm)={tuple(round(v, 1) for v in r['centroide_mm'])}")
    print("   -> IMPORTANTE: esto es una lista de candidatos para revision humana, no un diagnostico.")

    out_img = sitk.GetImageFromArray(output_arr)
    out_img.CopyInformation(img)
    sitk.WriteImage(out_img, output_path)
    return output_path, reporte


def generate_skull_mask(nifti_path, output_skull_path):
    print("\n[+] Extrayendo cráneo por umbral HU...")
    img = sitk.ReadImage(nifti_path)
    img_arr = sitk.GetArrayFromImage(img)
    skull_arr = np.zeros_like(img_arr)
    skull_arr[img_arr > 300] = 1 # Umbral de hueso en CT
    out_img = sitk.GetImageFromArray(skull_arr)
    out_img.CopyInformation(img)
    sitk.WriteImage(out_img, output_skull_path)
    return output_skull_path


def export_stl_to_single_fbx(stl_path, output_fbx, color_rgba=(1.0, 1.0, 1.0, 1.0),
                              roughness=0.6, metallic=0.0, emission=(0, 0, 0, 1),
                              subsurface=0.0, subsurface_color=(1, 1, 1, 1),
                              subdiv_levels=0, max_faces=None):
    """
    Exporta un STL a FBX con material PBR completo.

    MODO CLINICO (maximo realismo anatomico): por defecto NO subdivide
    (subdiv_levels=0, antes nivel 2 = 16x poligonos -> FBX de 90-230 MB) y
    NO decima la geometria (max_faces=None) para preservar la forma nativa
    de la malla. La decimacion/optimizacion para Unity/HoloLens/Quest solo
    se activa si se pasa explicitamente max_faces.
    Parametros:
    - color_rgba       : Color base (R, G, B, Alpha)
    - roughness        : 0=espejo, 1=mate
    - metallic         : 0=plastico, 1=metal
    - emission         : Color de emision (para efectos de brillo)
    - subsurface       : Translucencia subcutanea (para tejido organico real)
    - subsurface_color : Color de la luz interna translucida
    - subdiv_levels    : Niveles de subdivision (0=off, por defecto para calidad clinica)
    - max_faces        : (Opcional, MR) Si la malla supera esta cantidad, se decima.
                         Por defecto None -> se exporta con TODA la fidelidad nativa.
    """
    if not os.path.exists(stl_path):
        return None
    try:
        import bpy
        import math

        # ---- Decimacion previa si la malla es demasiado densa para MR ----
        if max_faces and max_faces > 0:
            import trimesh
            try:
                m = trimesh.load(stl_path, force="mesh")
                if len(m.faces) > max_faces:
                    import fast_simplification
                    red = 1.0 - (max_faces / len(m.faces))
                    print(f"   -> Decimando para realidad mixta: {len(m.faces):,} -> {max_faces:,} caras")
                    vs, fc = fast_simplification.simplify(
                        m.vertices, m.faces, target_reduction=red)
                    simp = trimesh.Trimesh(vertices=vs, faces=fc, process=True)
                    decim_path = stl_path.rsplit(".", 1)[0] + "_decimada_mr.stl"
                    simp.export(decim_path)
                    stl_path = decim_path
            except ImportError:
                pass
            except Exception as e:
                print(f"   [!] No se pudo decimar: {e}")

        print(f"\n[4/4] Exportando FBX con material PBR: {os.path.basename(output_fbx)}...")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if bpy.data.objects.get("Cube"):
            bpy.data.objects.remove(bpy.data.objects["Cube"], do_unlink=True)

        # Importar STL
        if hasattr(bpy.ops.wm, 'stl_import'):
            bpy.ops.wm.stl_import(filepath=stl_path.replace('\\', '/'))
        else:
            bpy.ops.import_mesh.stl(filepath=stl_path.replace('\\', '/'))

        obj = bpy.context.selected_objects[0]
        obj.name = os.path.basename(output_fbx).replace('.fbx', '')
        obj.scale = (0.001, 0.001, 0.001)
        obj.rotation_euler = (math.radians(90), 0, 0)

        # Smooth shading maximo
        bpy.ops.object.shade_smooth()
        # Autosmooth para preservar bordes duros en angulos grandes
        if hasattr(obj.data, 'use_auto_smooth'):
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(60)

        # === MATERIAL PBR COMPLETO ===
        mat = bpy.data.materials.new(name="Mat_" + obj.name)
        mat.use_nodes = True
        mat.blend_method = 'OPAQUE'

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Nodo output
        output_node = nodes.new('ShaderNodeOutputMaterial')
        output_node.location = (400, 0)

        # Principled BSDF (shader fisico principal)
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.location = (0, 0)

        # --- Propiedades del material ---
        bsdf.inputs['Base Color'].default_value = color_rgba
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Alpha'].default_value = color_rgba[3]

        # Subsurface scattering (simula luz pasando por tejido organico)
        if subsurface > 0.0:
            if 'Subsurface Weight' in bsdf.inputs:          # Blender 4.x
                bsdf.inputs['Subsurface Weight'].default_value = subsurface
            elif 'Subsurface' in bsdf.inputs:               # Blender 3.x
                bsdf.inputs['Subsurface'].default_value = subsurface
            if 'Subsurface Color' in bsdf.inputs:
                bsdf.inputs['Subsurface Color'].default_value = subsurface_color
            if 'Subsurface Radius' in bsdf.inputs:
                bsdf.inputs['Subsurface Radius'].default_value = (1.0, 0.2, 0.1)

        # Emision (para tumor fosforescente)
        if any(c > 0 for c in emission[:3]):
            if 'Emission Color' in bsdf.inputs:             # Blender 4.x
                bsdf.inputs['Emission Color'].default_value = emission
                bsdf.inputs['Emission Strength'].default_value = 1.5
            elif 'Emission' in bsdf.inputs:                 # Blender 3.x
                bsdf.inputs['Emission'].default_value = emission

        links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

        # Tambien aplicar color de vertices (fallback para visores simples)
        try:
            if not obj.data.vertex_colors:
                obj.data.vertex_colors.new()
            vc = obj.data.vertex_colors.active
            rgb = (color_rgba[0], color_rgba[1], color_rgba[2], 1.0)
            for loop in obj.data.loops:
                vc.data[loop.index].color = rgb
        except Exception:
            pass

        # Asignar material al objeto
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        # === SUBDIVISION OPCIONAL (por defecto DESACTIVADA para realidad mixta) ===
        # Antes se aplicaba nivel 2 (16x poligonos) y se exportaban FBX de
        # ~100-230 MB, imposibles de cargar en tiempo real en dispositivos MR.
        # Ahora solo se subdivide si se pide explicitamente via subdiv_levels.
        if subdiv_levels and subdiv_levels > 0:
            print(f"   -> Aplicando Subdivision Surface (nivel {subdiv_levels})...")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            subsurf_mod = obj.modifiers.new(name="Subdiv", type='SUBSURF')
            subsurf_mod.levels = subdiv_levels
            subsurf_mod.render_levels = subdiv_levels
            subsurf_mod.subdivision_type = 'CATMULL_CLARK'
            bpy.ops.object.modifier_apply(modifier="Subdiv")
        print(f"   -> Poligonos a exportar: {len(obj.data.polygons):,}")

        # Aplicar transformaciones y exportar
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.export_scene.fbx(
            filepath=output_fbx.replace('\\', '/'),
            use_selection=True,
            axis_forward='-Z',
            axis_up='Y',
            mesh_smooth_type='FACE',
            use_mesh_modifiers=True,
            colors_type='SRGB',
            add_leaf_bones=False,
        )
        print(f"[+] FBX PBR creado: {output_fbx}")
        return output_fbx
    except ImportError:
        print("[!] 'bpy' no instalado. Ejecuta: pip install bpy")
        return None
    except Exception as e:
        print(f"[!] Error exportando FBX: {e}")
        return None


if __name__ == "__main__":
    if is_colab_environment():
        mount_drive_if_colab("/content/drive")
        install_colab_dependencies()

        RUTA_DICOM = setup_colab_dicom_upload("/content/dicom_uploads")
        RUTA_NIFTI = "/content/volumen_paciente.nii.gz"
        RUTA_SEGMENTACIONES = "/content/drive/MyDrive/Tesis_Neuro/Segmentaciones_AI"
    else:
        RUTA_DICOM = "D:/Tesis/data/dicom_paciente_01"
        RUTA_NIFTI = "./volumen_paciente.nii.gz"
        RUTA_SEGMENTACIONES = "./segmentaciones_ai"

    if not os.path.exists(RUTA_DICOM):
        print(f" No existe la carpeta DICOM o NIfTI: {RUTA_DICOM}")
    else:
        try:
            nifti_path = resolve_input_volume(RUTA_DICOM, RUTA_NIFTI)
        except RuntimeError as e:
            print(f" {e}")
            sys.exit(1)

        run_ai_segmentation(nifti_path, RUTA_SEGMENTACIONES, fast_mode=False)
        
        RUTA_MASCARA_CEREBRO = os.path.join(RUTA_SEGMENTACIONES, "brain.nii.gz")
        RUTA_MASCARA_CRANEO = os.path.join(RUTA_SEGMENTACIONES, "skull.nii.gz")
        RUTA_MASCARA_TUMOR = os.path.join(RUTA_SEGMENTACIONES, "tumor.nii.gz")
        RUTA_MASCARA_VASOS = os.path.join(RUTA_SEGMENTACIONES, "vasos.nii.gz")
        
        if not os.path.exists(RUTA_MASCARA_CRANEO):
            generate_skull_mask(nifti_path, RUTA_MASCARA_CRANEO)
            
        generate_tumor_mask(nifti_path, RUTA_MASCARA_CEREBRO, RUTA_MASCARA_TUMOR)
        generate_vessels_mask(nifti_path, RUTA_MASCARA_CEREBRO, RUTA_MASCARA_VASOS)

        RUTA_MASCARA_ANEURISMA = os.path.join(RUTA_SEGMENTACIONES, "aneurisma_candidatos.nii.gz")
        _, reporte_aneurismas = generate_aneurysm_candidates(
            nifti_path, RUTA_MASCARA_VASOS, RUTA_MASCARA_ANEURISMA
        )

        # ===== 5 FBX INDIVIDUALES CON MAXIMO DETALLE Y MATERIALES PBR =====
        if os.path.exists(RUTA_MASCARA_CEREBRO):
            stl_brain = build_mesh(RUTA_MASCARA_CEREBRO, "./Cerebro_Completo.stl",
                                    smooth_iterations=1, gaussian_sigma_mm=0.3)
            if stl_brain:
                export_stl_to_single_fbx(
                    stl_brain, "./Cerebro_Completo.fbx",
                    color_rgba=(0.76, 0.60, 0.58, 0.85),
                    roughness=0.75,
                    metallic=0.0,
                    subsurface=0.35,
                    subsurface_color=(0.9, 0.45, 0.35, 1.0),
                )

        if os.path.exists(RUTA_MASCARA_TUMOR):
            stl_tumor = build_mesh(RUTA_MASCARA_TUMOR, "./Tumor.stl", smooth_iterations=1)
            if stl_tumor:
                export_stl_to_single_fbx(
                    stl_tumor, "./Tumor.fbx",
                    color_rgba=(0.4, 0.0, 0.9, 1.0),
                    roughness=0.45,
                    metallic=0.0,
                    emission=(0.3, 0.0, 0.6, 1.0),
                    subsurface=0.1,
                    subsurface_color=(0.6, 0.0, 0.8, 1.0),
                )

        if os.path.exists(RUTA_MASCARA_VASOS):
            stl_vasos = build_mesh(RUTA_MASCARA_VASOS, "./Venas_Arterias.stl", smooth_iterations=1)
            if stl_vasos:
                export_stl_to_single_fbx(
                    stl_vasos, "./Venas_Arterias.fbx",
                    color_rgba=(0.85, 0.05, 0.05, 1.0),
                    roughness=0.2,
                    metallic=0.05,
                    subsurface=0.2,
                    subsurface_color=(1.0, 0.2, 0.2, 1.0),
                )

        if os.path.exists(RUTA_MASCARA_CRANEO):
            stl_craneo = build_mesh(RUTA_MASCARA_CRANEO, "./Craneo.stl",
                                     smooth_iterations=1, gaussian_sigma_mm=0.3)
            if stl_craneo:
                export_stl_to_single_fbx(
                    stl_craneo, "./Craneo.fbx",
                    color_rgba=(0.92, 0.88, 0.78, 1.0),
                    roughness=0.85,
                    metallic=0.0,
                    subsurface=0.08,
                    subsurface_color=(1.0, 0.95, 0.80, 1.0),
                )

        # Candidatos a aneurisma: solo se exportan si generate_aneurysm_candidates
        # efectivamente encontro alguna dilatacion focal (reporte_aneurismas no vacio).
        if os.path.exists(RUTA_MASCARA_ANEURISMA) and reporte_aneurismas:
            stl_aneurisma = build_mesh(RUTA_MASCARA_ANEURISMA, "./Aneurisma_Candidatos.stl", smooth_iterations=1)
            if stl_aneurisma:
                export_stl_to_single_fbx(
                    stl_aneurisma, "./Aneurisma_Candidatos.fbx",
                    color_rgba=(1.0, 0.55, 0.0, 1.0),
                    roughness=0.35,
                    metallic=0.0,
                    emission=(1.0, 0.35, 0.0, 1.0),
                    subsurface=0.05,
                    subsurface_color=(1.0, 0.6, 0.2, 1.0),
                )