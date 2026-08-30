"""
Segmentación de tumores cerebrales con BRATS (BraTS 2020) via MONAI.
=====================================================================
Este módulo integra el modelo preentrenado BRATS 2020 de MONAI para
segmentación precisa de tumores cerebrales (ET - enhancing tumor,
WT - whole tumor, TC - tumor core) en imágenes de resonancia magnética
multimodal (T1, T1ce, T2, FLAIR).

El modelo BRATS es el estándar de oro en segmentación de gliomas y
proporciona una precisión mucho mayor que los métodos heurísticos
de umbralización.

ARQUITECTURA DEL MODELO (SegResNet):
- in_channels: 4 (T1, T1ce, T2, FLAIR)
- out_channels: 3 (ET, NCR, ED)
- ROI: [240, 240, 160]
- Post-procesamiento: sigmoid + umbral 0.5
- Mapeo de etiquetas:
  - Canal 0 (NCR) > 0.5 → etiqueta 1 (necrosis)
  - Canal 1 (ED) > 0.5 → etiqueta 2 (edema)
  - Canal 2 (ET) > 0.5 → etiqueta 4 (tumor realzado)
"""

import os
import sys
import subprocess
import numpy as np
import SimpleITK as sitk
import torch
from pathlib import Path

# =============================================================================
# CONFIGURACIÓN DE BRATS
# =============================================================================

# Nombre del bundle en MONAI Model Zoo
BRATS_BUNDLE_NAME = "brats_mri_segmentation"
BRATS_BUNDLE_VERSION = "0.4.4"

# Directorio donde se guardarán los modelos descargados
MODELOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modelos_preentrenados")
MODELOS_DIR = os.path.abspath(MODELOS_DIR)

# Etiquetas de BRATS 2020 (según el post-procesamiento del bundle)
BRATS_LABELS = {
    0: "Fondo",
    1: "Necrosis (NCR)",
    2: "Edema peritumoral (ED)",
    4: "Tumor realzado (ET)",
}

# Mapeo a máscaras clínicas
BRATS_MASKS = {
    "tumor_core": [1, 4],       # TC = NCR + ET
    "tumor_whole": [1, 2, 4],   # WT = NCR + ED + ET
    "tumor_enhancing": [4],     # ET = solo realce
}


def _check_monai_installed():
    """Verifica que MONAI esté instalado."""
    try:
        import monai  # noqa: F401
        return True
    except ImportError:
        return False


def _check_torch_installed():
    """Verifica que PyTorch esté instalado."""
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def install_brats_dependencies():
    """Instala las dependencias necesarias para BRATS si faltan."""
    if not _check_monai_installed():
        print("[BRATS] Instalando MONAI...")
        subprocess.run([sys.executable, "-m", "pip", "install", "monai"], check=True)
    if not _check_torch_installed():
        print("[BRATS] Instalando PyTorch (CPU)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "torch"], check=True)


def download_brats_bundle(force=False):
    """
    Descarga el bundle BRATS 2020 desde MONAI Model Zoo.
    
    Returns:
        str: Ruta al directorio del bundle descargado, o None si falla.
    """
    from monai.bundle import download
    
    os.makedirs(MODELOS_DIR, exist_ok=True)
    bundle_dir = os.path.join(MODELOS_DIR, BRATS_BUNDLE_NAME)
    
    # Verificar si ya existe un bundle válido
    if os.path.exists(bundle_dir) and not force:
        config_path = os.path.join(bundle_dir, "configs", "inference.json")
        model_path = os.path.join(bundle_dir, "models", "model.pt")
        if os.path.exists(config_path) and os.path.exists(model_path):
            print(f"[BRATS] Bundle ya descargado en: {bundle_dir}")
            return bundle_dir
    
    # Limpiar archivos corruptos si existen
    for f in os.listdir(MODELOS_DIR):
        fpath = os.path.join(MODELOS_DIR, f)
        if os.path.isfile(fpath) and os.path.getsize(fpath) < 1000:
            print(f"[BRATS] Eliminando archivo corrupto: {f}")
            os.remove(fpath)
    
    print(f"[BRATS] Descargando bundle '{BRATS_BUNDLE_NAME}' versión {BRATS_BUNDLE_VERSION}...")
    print(f"[BRATS] Esto puede tomar varios minutos (el modelo pesa ~33MB)...")
    
    try:
        download(
            name=BRATS_BUNDLE_NAME,
            version=BRATS_BUNDLE_VERSION,
            bundle_dir=MODELOS_DIR,
            source="github",
        )
        print(f"[BRATS] Bundle descargado correctamente en: {bundle_dir}")
        return bundle_dir
    except Exception as e:
        print(f"[BRATS] Error descargando bundle: {e}")
        return None


def load_brats_model(bundle_dir=None):
    """
    Carga el modelo BRATS SegResNet desde el bundle descargado.
    
    Returns:
        tuple: (modelo, device) o (None, None) si falla.
    """
    if not bundle_dir:
        bundle_dir = os.path.join(MODELOS_DIR, BRATS_BUNDLE_NAME)
    
    model_path = os.path.join(bundle_dir, "models", "model.pt")
    if not os.path.exists(model_path):
        print(f"[BRATS] Modelo no encontrado en: {model_path}")
        return None, None
    
    try:
        from monai.networks.nets import SegResNet
        
        # Crear el modelo con la misma arquitectura que el bundle
        model = SegResNet(
            blocks_down=[1, 2, 2, 4],
            blocks_up=[1, 1, 1],
            init_filters=16,
            in_channels=4,
            out_channels=3,
            dropout_prob=0.2,
        )
        
        # Cargar los pesos
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[BRATS] Cargando modelo en dispositivo: {device}")
        
        checkpoint = torch.load(model_path, map_location=device, weights_only=False)
        
        # El checkpoint puede tener diferentes formatos
        if isinstance(checkpoint, dict):
            if "model" in checkpoint:
                state_dict = checkpoint["model"]
            elif "state_dict" in checkpoint:
                state_dict = checkpoint["state_dict"]
            else:
                # Intentar cargar directamente como state_dict
                state_dict = checkpoint
        else:
            state_dict = checkpoint
        
        # Cargar los pesos en el modelo
        model.load_state_dict(state_dict, strict=False)
        model.eval()
        model.to(device)
        
        print("[BRATS] Modelo cargado correctamente")
        return model, device
    
    except Exception as e:
        print(f"[BRATS] Error cargando el modelo: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def _preprocess_volume(volume_4ch, roi_size=(240, 240, 160)):
    """
    Preprocesa el volumen de 4 canales para el modelo BRATS.
    
    Args:
        volume_4ch: Array numpy de forma [4, D, H, W]
        roi_size: Tamaño del ROI esperado por el modelo
    
    Returns:
        Array preprocesado de forma [1, 4, D', H', W']
    """
    from monai.transforms import NormalizeIntensity
    
    # Normalizar cada canal (nonzero, channel_wise)
    normalizer = NormalizeIntensity(nonzero=True, channel_wise=True)
    
    # Convertir a tensor
    tensor = torch.from_numpy(volume_4ch).float()
    
    # Normalizar
    tensor = normalizer(tensor.unsqueeze(0))
    
    # Padear al tamaño del ROI si es necesario
    target_shape = roi_size
    current_shape = tensor.shape[2:]
    
    # Calcular padding
    pad_d = max(0, target_shape[0] - current_shape[0])
    pad_h = max(0, target_shape[1] - current_shape[1])
    pad_w = max(0, target_shape[2] - current_shape[2])
    
    if pad_d > 0 or pad_h > 0 or pad_w > 0:
        padder = torch.nn.ConstantPad3d(
            (0, pad_w, 0, pad_h, 0, pad_d), 0
        )
        tensor = padder(tensor)
    
    return tensor


def _postprocess_output(output, original_shape):
    """
    Post-procesa la salida del modelo BRATS.
    
    El modelo produce 3 canales de salida (sigmoid):
    - Canal 0: NCR (necrosis)
    - Canal 1: ED (edema)
    - Canal 2: ET (tumor realzado)
    
    El mapeo a etiquetas es:
    - ET > 0.5 → etiqueta 4
    - NCR > 0.5 → etiqueta 1
    - ED > 0.5 → etiqueta 2
    
    Args:
        output: Tensor de salida del modelo [1, 3, D, H, W]
        original_shape: Forma original del volumen [D, H, W]
    
    Returns:
        Array de segmentación con etiquetas 0-4
    """
    if torch.is_tensor(output):
        output = output.detach().cpu().numpy()
    
    if output.ndim == 5:
        output = output[0]  # Quitar batch dim → [3, D, H, W]
    
    # Aplicar sigmoid
    output = 1.0 / (1.0 + np.exp(-output))
    
    # Aplicar umbral 0.5
    output = (output > 0.5).astype(np.uint8)
    
    # Mapear a etiquetas según el post-procesamiento del bundle
    # x[[2]] > 0 → 4 (ET), x[[0]] > 0 → 1 (NCR), x[[1]] > 0 → 2 (ED)
    seg = np.zeros(output.shape[1:], dtype=np.uint8)
    
    # ET tiene prioridad (etiqueta 4)
    seg[output[2] > 0] = 4
    # NCR (etiqueta 1)
    seg[output[0] > 0] = 1
    # ED (etiqueta 2)
    seg[output[1] > 0] = 2
    
    # Recortar al tamaño original si se hizo padding
    if seg.shape != original_shape:
        d, h, w = original_shape
        seg = seg[:d, :h, :w]
    
    return seg


def segment_brats_tumor(mri_t1_path, mri_t1ce_path, mri_t2_path, mri_flair_path,
                        output_dir="segmentaciones_brats"):
    """
    Segmenta tumores cerebrales usando el modelo BRATS 2020.
    
    Requiere 4 modalidades de MRI alineadas (T1, T1ce, T2, FLAIR).
    Si alguna modalidad no está disponible, se puede usar la misma imagen
    para los canales faltantes (con menor precisión).
    
    Args:
        mri_t1_path: Ruta al volumen T1 (NIfTI)
        mri_t1ce_path: Ruta al volumen T1 con contraste (NIfTI)
        mri_t2_path: Ruta al volumen T2 (NIfTI)
        mri_flair_path: Ruta al volumen FLAIR (NIfTI)
        output_dir: Directorio de salida para las máscaras
    
    Returns:
        dict: Diccionario con rutas a las máscaras generadas, o None si falla.
    """
    print("\n" + "=" * 70)
    print("[BRATS] Segmentación de tumor cerebral con modelo BRATS 2020")
    print("=" * 70)
    
    # Verificar dependencias
    if not _check_monai_installed():
        print("[BRATS] MONAI no está instalado. Instalando...")
        install_brats_dependencies()
    
    # Verificar que las imágenes existen
    paths = {
        "t1": mri_t1_path,
        "t1ce": mri_t1ce_path,
        "t2": mri_t2_path,
        "flair": mri_flair_path,
    }
    
    available = {}
    for name, path in paths.items():
        if path and os.path.exists(path):
            available[name] = path
            print(f"[BRATS] Modalidad {name.upper()}: {os.path.basename(path)}")
        else:
            print(f"[BRATS] Modalidad {name.upper()}: NO DISPONIBLE")
    
    if not available:
        print("[BRATS] No hay modalidades de MRI disponibles. Abortando.")
        return None
    
    # Descargar el bundle si es necesario
    bundle_dir = download_brats_bundle()
    if not bundle_dir:
        print("[BRATS] No se pudo obtener el modelo BRATS. Se usará el método heurístico.")
        return None
    
    # Cargar el modelo
    model, device = load_brats_model(bundle_dir)
    if model is None:
        print("[BRATS] No se pudo cargar el modelo BRATS. Se usará el método heurístico.")
        return None
    
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # Leer las imágenes disponibles
        images = {}
        for name, path in available.items():
            img = sitk.ReadImage(path)
            images[name] = sitk.GetArrayFromImage(img).astype(np.float32)
        
        # Si faltan modalidades, usar la primera disponible como relleno
        first_available = list(images.keys())[0]
        reference_img = sitk.ReadImage(available[first_available])
        original_shape = images[first_available].shape
        
        # Construir el volumen de 4 canales
        # BRATS espera: [C=4, D, H, W] con canales [T1, T1ce, T2, FLAIR]
        volume_4ch = np.zeros((4, *original_shape), dtype=np.float32)
        
        channel_map = {"t1": 0, "t1ce": 1, "t2": 2, "flair": 3}
        for name, arr in images.items():
            volume_4ch[channel_map[name]] = arr
        
        # Rellenar canales faltantes con la primera modalidad disponible
        for ch in range(4):
            if np.max(volume_4ch[ch]) == 0:
                volume_4ch[ch] = images[first_available]
        
        # Preprocesar el volumen
        print("[BRATS] Preprocesando volumen...")
        input_tensor = _preprocess_volume(volume_4ch)
        input_tensor = input_tensor.to(device)
        
        # Ejecutar inferencia
        print("[BRATS] Ejecutando inferencia del modelo...")
        print(f"[BRATS] Dispositivo: {device}")
        
        with torch.no_grad():
            output = model(input_tensor)
        
        # Post-procesar la salida
        print("[BRATS] Post-procesando segmentación...")
        seg = _postprocess_output(output, original_shape)
        
        # Generar las máscaras clínicas
        results = {}
        
        for mask_name, labels in BRATS_MASKS.items():
            mask_arr = np.zeros_like(seg, dtype=np.uint8)
            for label in labels:
                mask_arr[seg == label] = 1
            
            mask_img = sitk.GetImageFromArray(mask_arr)
            mask_img.CopyInformation(reference_img)
            
            output_path = os.path.join(output_dir, f"brats_{mask_name}.nii.gz")
            sitk.WriteImage(mask_img, output_path)
            results[mask_name] = output_path
            
            # Estadísticas
            voxel_volume = np.prod(reference_img.GetSpacing())
            volume_mm3 = float(mask_arr.sum()) * voxel_volume
            print(f"[BRATS] {mask_name}: {mask_arr.sum():,} voxeles, {volume_mm3:.1f} mm³")
        
        # Guardar la segmentación completa
        seg_img = sitk.GetImageFromArray(seg)
        seg_img.CopyInformation(reference_img)
        seg_path = os.path.join(output_dir, "brats_segmentacion_completa.nii.gz")
        sitk.WriteImage(seg_img, seg_path)
        results["segmentacion_completa"] = seg_path
        
        # Estadísticas de la segmentación completa
        for label, name in BRATS_LABELS.items():
            count = int((seg == label).sum())
            if count > 0:
                vol = count * np.prod(reference_img.GetSpacing())
                print(f"[BRATS]   {name}: {count:,} voxeles ({vol:.1f} mm³)")
        
        print(f"[BRATS] Segmentación completada. Resultados en: {output_dir}")
        return results
    
    except Exception as e:
        print(f"[BRATS] Error durante la segmentación: {e}")
        import traceback
        traceback.print_exc()
        return None


def segment_tumor_brats_from_single_volume(nifti_path, output_dir="segmentaciones_brats"):
    """
    Segmenta tumor usando BRATS con un solo volumen (duplicando canales).
    
    Esto es un fallback cuando solo se tiene una modalidad. La precisión
    será menor que con las 4 modalidades, pero mejor que los métodos
    heurísticos puros.
    
    Args:
        nifti_path: Ruta al volumen NIfTI (cualquier modalidad)
        output_dir: Directorio de salida
    
    Returns:
        dict: Resultados de segmentación o None.
    """
    print("\n[BRATS] Usando modo de modalidad única (duplicando canales)...")
    print("[BRATS] ADVERTENCIA: La precisión es menor sin las 4 modalidades de MRI.")
    
    # Usar el mismo volumen para las 4 modalidades
    return segment_brats_tumor(
        mri_t1_path=nifti_path,
        mri_t1ce_path=nifti_path,
        mri_t2_path=nifti_path,
        mri_flair_path=nifti_path,
        output_dir=output_dir,
    )


def verify_brats_model():
    """
    Verifica que el modelo BRATS esté correctamente descargado y funcione.
    
    Returns:
        bool: True si el modelo está listo, False si hay problemas.
    """
    print("\n" + "=" * 70)
    print("[VERIFICACIÓN] Comprobando modelo BRATS...")
    print("=" * 70)
    
    # 1. Verificar MONAI
    if not _check_monai_installed():
        print("[VERIFICACIÓN] ✗ MONAI no está instalado")
        return False
    print("[VERIFICACIÓN] ✓ MONAI instalado")
    
    # 2. Verificar PyTorch
    if not _check_torch_installed():
        print("[VERIFICACIÓN] ✗ PyTorch no está instalado")
        return False
    print(f"[VERIFICACIÓN] ✓ PyTorch {torch.__version__} instalado")
    
    # 3. Verificar el bundle
    bundle_dir = os.path.join(MODELOS_DIR, BRATS_BUNDLE_NAME)
    if os.path.exists(bundle_dir):
        config_path = os.path.join(bundle_dir, "configs", "inference.json")
        model_path = os.path.join(bundle_dir, "models", "model.pt")
        if os.path.exists(config_path) and os.path.exists(model_path):
            print(f"[VERIFICACIÓN] ✓ Bundle BRATS encontrado en: {bundle_dir}")
            print(f"[VERIFICACIÓN] ✓ Modelo: {os.path.getsize(model_path) / 1024 / 1024:.1f} MB")
            
            # 4. Verificar que el modelo se puede cargar
            model, device = load_brats_model(bundle_dir)
            if model is not None:
                print("[VERIFICACIÓN] ✓ Modelo cargado correctamente")
                return True
            else:
                print("[VERIFICACIÓN] ✗ No se pudo cargar el modelo")
                return False
        else:
            print(f"[VERIFICACIÓN] ✗ Bundle BRATS incompleto en: {bundle_dir}")
            return False
    else:
        print("[VERIFICACIÓN] ✗ Bundle BRATS no encontrado")
        print("[VERIFICACIÓN]   Ejecuta download_brats_bundle() para descargarlo")
        return False


if __name__ == "__main__":
    # Verificar el modelo
    verify_brats_model()
    
    # Si no está, intentar descargarlo
    if not verify_brats_model():
        print("\n[BRATS] Intentando descargar el modelo...")
        bundle = download_brats_bundle()
        if bundle:
            print(f"[BRATS] Modelo descargado en: {bundle}")
            verify_brats_model()
        else:
            print("[BRATS] No se pudo descargar el modelo automáticamente.")
            print("[BRATS] Puedes descargarlo manualmente desde:")
            print("[BRATS]   https://github.com/Project-MONAI/model-zoo/tree/dev/models/brats_mri_segmentation")