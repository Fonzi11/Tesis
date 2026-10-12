"""
Segmentación de tumores cerebrales con BRATS (BraTS 2020) via MONAI.
=====================================================================
Este módulo integra el modelo preentrenado BRATS 2020 de MONAI para
segmentación precisa de tumores cerebrales (ET - enhancing tumor,
WT - whole tumor, TC - tumor core) en imágenes de resonancia magnética
multimodal (T1ce, T1, T2, FLAIR).

El modelo BRATS es el estándar de oro en segmentación de gliomas y
proporciona una precisión mucho mayor que los métodos heurísticos
de umbralización.

ARQUITECTURA DEL MODELO (SegResNet):
- in_channels: 4 (T1ce, T1, T2, FLAIR)
- out_channels: 3 (TC, WT, ET)
- ROI: [240, 240, 160]
- Post-procesamiento: sigmoid + umbral 0.5
- Mapeo de etiquetas:
  - Canal 0 (TC) y canal 2 (ET) → NCR/ET
  - Canal 1 (WT) fuera de TC → etiqueta 2 (edema)
"""

import os
import sys
import subprocess
import numpy as np
import SimpleITK as sitk
import torch
from pathlib import Path

try:
    from hardware_backend import describe_backends
except ImportError:
    from src.hardware_backend import describe_backends

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

# El bundle declara este orden exacto de entrada y no el orden alfabético.
BRATS_INPUT_CHANNELS = ("t1ce", "t1", "t2", "flair")
BRATS_OUTPUT_CHANNELS = {
    "tumor_core": 0,
    "tumor_whole": 1,
    "tumor_enhancing": 2,
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
        cuda_enabled = os.environ.get("NEUROHUB_ENABLE_CUDA") == "1"
        device = torch.device(
            "cuda" if cuda_enabled and torch.cuda.is_available() else "cpu"
        )
        print(f"[BRATS] Cargando modelo PyTorch en dispositivo: {device}")
        if device.type == "cpu":
            print(
                "[BRATS] Backend disponible para modelos ONNX: "
                f"{describe_backends()}. Este bundle PyTorch aún no se ejecuta "
                "en DirectML sin una exportación ONNX validada."
            )
        
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
        
        # Una carga parcial produciría una máscara con calidad desconocida.
        model.load_state_dict(state_dict, strict=True)
        model.eval()
        model.to(device)
        
        print("[BRATS] Modelo cargado correctamente")
        return model, device
    
    except Exception as e:
        print(f"[BRATS] Error cargando el modelo: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def _load_brats_onnx_session(bundle_dir):
    """Carga la exportación ONNX y confirma que DirectML está disponible."""
    onnx_path = os.path.join(bundle_dir, "models", "model.onnx")
    if not os.path.exists(onnx_path):
        return None
    try:
        import onnxruntime as ort
        from hardware_backend import preferred_onnx_providers
        providers = preferred_onnx_providers()
        if providers[0] != "DmlExecutionProvider":
            print("[BRATS-ONNX] DirectML no está disponible; no se usará ONNX.")
            return None
        session = ort.InferenceSession(onnx_path, providers=providers)
        if "DmlExecutionProvider" not in session.get_providers():
            raise RuntimeError(
                f"ONNX Runtime no activó DirectML: {session.get_providers()}"
            )
        print(
            "[BRATS-ONNX] AMD activa mediante DirectML: "
            f"{session.get_providers()}"
        )
        return session
    except Exception as exc:
        print(f"[BRATS-ONNX] No se pudo cargar el modelo ONNX: {exc}")
        return None


def _run_onnx_sliding_window(session, input_tensor):
    """Ejecuta las ventanas MONAI mediante el proveedor DirectML."""
    from monai.inferers import SlidingWindowInferer

    def predictor(window):
        output = session.run(
            ["pred"],
            {"image": window.detach().cpu().numpy().astype(np.float32)},
        )[0]
        return torch.from_numpy(output)

    inferer = SlidingWindowInferer(
        roi_size=(240, 240, 160),
        sw_batch_size=1,
        overlap=0.5,
        mode="gaussian",
    )
    return inferer(input_tensor.cpu(), predictor)


def _preprocess_volume(volume_4ch, roi_size=(240, 240, 160)):
    """
    Preprocesa el volumen de 4 canales para el modelo BRATS.
    
    Args:
        volume_4ch: Array numpy de forma [4, D, H, W]
        roi_size: Tamaño del ROI esperado por el modelo (solo informativo;
            la inferencia usa SlidingWindowInferer que maneja cualquier tamaño)
    
    Returns:
        Tensor preprocesado de forma [1, 4, D, H, W]
    """
    from monai.transforms import NormalizeIntensity
    
    # Normalizar cada canal (nonzero, channel_wise)
    normalizer = NormalizeIntensity(nonzero=True, channel_wise=True)
    
    # Convertir a tensor
    tensor = torch.from_numpy(volume_4ch).float()
    
    # Normalizar (añade dim de batch para la transform y la quita después)
    tensor = normalizer(tensor)
    
    # Añadir dimensión de batch: [1, 4, D, H, W]
    return tensor.unsqueeze(0)


def _postprocess_output(output, original_shape):
    """
    Post-procesa la salida del modelo BRATS.
    
    El bundle produce 3 canales independientes (sigmoid):
    - Canal 0: TC (tumor core)
    - Canal 1: WT (whole tumor)
    - Canal 2: ET (tumor realzado)

    Se convierten a etiquetas clínicas: ET -> 4, TC sin ET -> NCR (1) y
    WT fuera de TC -> edema (2).
    
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
    
    # TC incluye NCR+ET y WT incluye NCR+ED+ET.
    tumor_core = output[BRATS_OUTPUT_CHANNELS["tumor_core"]] > 0
    tumor_whole = output[BRATS_OUTPUT_CHANNELS["tumor_whole"]] > 0
    et = output[BRATS_OUTPUT_CHANNELS["tumor_enhancing"]] > 0
    ncr = tumor_core & ~et
    ed = tumor_whole & ~tumor_core

    seg = np.zeros(output.shape[1:], dtype=np.uint8)
    # ET (etiqueta 4): prioridad maxima
    seg[et] = 4
    # NCR (etiqueta 1): si no es ET
    seg[~et & ncr] = 1
    # ED (etiqueta 2): si no es ni ET ni NCR
    seg[~et & ~ncr & ed] = 2
    
    # Recortar al tamaño original si se hizo padding
    if seg.shape != original_shape:
        d, h, w = original_shape
        seg = seg[:d, :h, :w]
    
    return seg


def segment_brats_tumor(mri_t1_path, mri_t1ce_path, mri_t2_path, mri_flair_path,
                        output_dir="segmentaciones_brats"):
    """
    Segmenta tumores cerebrales usando el modelo BRATS 2020.
    
    Requiere 4 modalidades de MRI alineadas (T1ce, T1, T2, FLAIR).
    Las cuatro modalidades reales son obligatorias. Duplicar una modalidad
    destruye el contraste diferencial que separa TC, WT y ET.
    
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
    
    if set(available) != set(BRATS_INPUT_CHANNELS):
        faltantes = [name.upper() for name in BRATS_INPUT_CHANNELS
                     if name not in available]
        print("[BRATS] Faltan modalidades obligatorias: "
              f"{', '.join(faltantes)}. Abortando.")
        return None
    

    # === GUARDIA DE ARCHIVOS DUPLICADOS ===
    # El modelo BRATS se entrena con 4 modalidades MRI REALES y alineadas
    # (T1ce, T1, T2, FLAIR) y distingue las subregiones por el CONTRASTE
    # DIFERENCIAL entre ellas (p. ej. el tumor realzado ET es hiperintenso en
    # T1ce respecto a T1; el edema ED se ve en FLAIR). Si todas las "4
    # modalidades" apuntan al MISMO archivo (modalidad única duplicada),
    # duplicar el volumen en los 4 canales destroza ese contraste y el modelo
    # produce una segmentación catastrófica (marca casi todo el cerebro como
    # tumor/edema).
    #
    unique_paths = set()
    for p in available.values():
        unique_paths.add(os.path.abspath(p))
    if len(unique_paths) != 4:
        print("[BRATS] Las cuatro modalidades deben ser archivos distintos y "
              "reales; se usará el método heurístico.")
        print("[BRATS] Se usará el método heurístico morfológico en su lugar.")
        return None

    # Descargar el bundle si es necesario
    bundle_dir = download_brats_bundle()
    if not bundle_dir:
        print("[BRATS] No se pudo obtener el modelo BRATS. Se usará el método heurístico.")
        return None
    
    # Preferir ONNX/DirectML cuando la exportación ya fue validada.
    onnx_session = _load_brats_onnx_session(bundle_dir)
    model = None
    device = torch.device("cpu")
    if onnx_session is None:
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
        
        reference_img = sitk.ReadImage(available["t1ce"])
        original_shape = images["t1ce"].shape
        
        # Construir el volumen de 4 canales
        # El bundle espera [T1ce, T1, T2, FLAIR].
        volume_4ch = np.zeros((4, *original_shape), dtype=np.float32)
        for ch, name in enumerate(BRATS_INPUT_CHANNELS):
            current = sitk.ReadImage(available[name])
            if (current.GetSize() != reference_img.GetSize()
                    or not np.allclose(current.GetSpacing(),
                                       reference_img.GetSpacing(),
                                       rtol=0, atol=1e-4)
                    or not np.allclose(current.GetOrigin(),
                                       reference_img.GetOrigin(),
                                       rtol=0, atol=1e-4)
                    or current.GetDirection() != reference_img.GetDirection()):
                print(f"[BRATS] {name.upper()} no comparte la rejilla espacial "
                      "de T1CE; se aborta para no desalinear la máscara.")
                return None
            volume_4ch[ch] = images[name]
        
        # Preprocesar el volumen
        print("[BRATS] Preprocesando volumen...")
        input_tensor = _preprocess_volume(volume_4ch)
        input_tensor = input_tensor.to(device)
        
        # Ejecutar inferencia con SlidingWindowInferer para manejar cualquier
        # tamaño de volumen (el modelo SegResNet fue entrenado con ROI 240x240x160
        # pero puede inferirse en volúmenes mas grandes con ventana deslizante).
        print("[BRATS] Ejecutando inferencia del modelo (SlidingWindowInferer)...")
        print(
            f"[BRATS] Dispositivo: "
            f"{'AMD Radeon / DirectML' if onnx_session is not None else device}"
        )

        if onnx_session is not None:
            output = _run_onnx_sliding_window(onnx_session, input_tensor)
        else:
            from monai.inferers import SlidingWindowInferer
            inferer = SlidingWindowInferer(
                roi_size=(240, 240, 160),
                sw_batch_size=1,
                overlap=0.5,
                mode="gaussian",
            )
            with torch.no_grad():
                output = inferer(input_tensor, model)
        
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
    Mantiene compatibilidad con el antiguo punto de entrada, pero no ejecuta
    BraTS con una sola modalidad: duplicar canales no es una inferencia válida.
    
    Args:
        nifti_path: Ruta al volumen NIfTI (cualquier modalidad)
        output_dir: Directorio de salida
    
    Returns:
        dict: Resultados de segmentación o None.
    """
    print("\n[BRATS] Se requieren T1CE, T1, T2 y FLAIR reales y alineadas.")
    print("[BRATS] Se usará el método heurístico para modalidad única.")
    return None


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