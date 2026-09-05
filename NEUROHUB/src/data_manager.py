"""
NEUROHUB - Módulo de Datos y Repositorios
=========================================
Gestión de datasets públicos (BraTS, TCIA, ADAM) y descarga.
"""

import os
import sys
import json
import urllib.request
from pathlib import Path

# =====================================================================
# DIRECTORIOS
# =====================================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
NIFTI_DIR = os.path.join(DATA_DIR, "nifti")
DICOM_DIR = os.path.join(DATA_DIR, "dicom")
OUTPUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")

os.makedirs(NIFTI_DIR, exist_ok=True)
os.makedirs(DICOM_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =====================================================================
# REPOSITORIOS PÚBLICOS DE DATOS CON ANOTACIONES
# =====================================================================
# Lista de datasets públicos con tumores/aneurismas identificados
DATASETS = [
    {
        "id": "brats",
        "nombre": "BraTS 2021 (Brain Tumor Segmentation)",
        "descripcion": (
            "Imágenes MRI multimodales de gliomas con segmentación experta. "
            "Incluye ET (tumor realzado), ED (edema), NCR (necrosis). "
            "Formato: NIfTI (.nii.gz) - 4 modalidades."
        ),
        "tipo": "TUMOR",
        "formato": "NIfTI",
        "anotaciones": "ET=4, ED=2, NCR=1 (máscaras _seg.nii.gz)",
        "fuente": "https://huggingface.co/datasets/rocky93/BraTS_segmentation",
        "libre": True,
    },
    {
        "id": "tcia",
        "nombre": "TCIA - GBM & LGG (The Cancer Imaging Archive)",
        "descripcion": (
            "Collecciones TCIA-GBM y TCIA-LGG con segmentaciones de gliomas "
            "aprobadas por neurorradiólogos expertos. Formato: DICOM."
        ),
        "tipo": "TUMOR",
        "formato": "DICOM",
        "anotaciones": "Máscaras expertas de segmentación",
        "fuente": "https://www.cancerimagingarchive.net/",
        "libre": True,
    },
    {
        "id": "adam",
        "nombre": "ADAM Challenge (Aneurysm Detection)",
        "descripcion": (
            "Dataset público para detección y segmentación de aneurismas "
            "intracraneales. Incluye máscaras de aneurismas etiquetadas."
        ),
        "tipo": "ANEURISMA",
        "formato": "NIfTI",
        "anotaciones": "Máscaras binarias de aneurisma + bounding boxes",
        "fuente": "https://adam.isi.uu.nl/",
        "libre": True,
    },
]

# =====================================================================
# FUNCIONES UTILITARIAS
# =====================================================================

def listar_datasets() -> list:
    """Devuelve la lista de datasets disponibles."""
    return list(DATASETS)


def listar_archivos_nifti(filtro=None):
    """Lista archivos NIfTI en el directorio de datos."""
    resultados = []
    if os.path.isdir(NIFTI_DIR):
        for root, _, files in os.walk(NIFTI_DIR):
            for f in sorted(files):
                if f.lower().endswith((".nii", ".nii.gz")):
                    if filtro and filtro.lower() not in f.lower():
                        continue
                    resultados.append({
                        "archivo": f,
                        "ruta": os.path.join(root, f),
                        "directorio": os.path.relpath(root, NIFTI_DIR),
                    })
    return resultados


def listar_archivos_dicom(filtro=None):
    """Lista directorios DICOM en el directorio de datos (sin warnings)."""
    resultados = []
    # Ruta de escape temprana si dir no existe
    if not os.path.isdir(DICOM_DIR):
        return resultados
    # Recorrer solo directorios que contengan archivos DICOM
    try:
        import SimpleITK as sitk
        reader = sitk.ImageSeriesReader()
        for root, dirs, files in os.walk(DICOM_DIR):
            # Skip si no hay archivos .dcm en esta carpeta
            dcm_present = any(f.lower().endswith((".dcm", ".dicom", ".ima"))
                              for f in files)
            if not dcm_present:
                continue
            try:
                series_ids = reader.GetGDCMSeriesIDs(root)
            except Exception:
                series_ids = []
            if series_ids:
                name = Path(root).name
                if filtro and filtro.lower() not in name.lower():
                    continue
                resultados.append({
                    "directorio": root,
                    "series": len(series_ids),
                    "nombre": name,
                })
    except ImportError:
        pass
    return resultados


def cargar_volumen(path, serie_uid=None):
    """
    Carga un volumen médico desde cualquier origen soportado.

    Soporta:
      - Archivo NIfTI (.nii / .nii.gz)      -> SimpleITK ReadImage
      - Directorio DICOM (serie o series)    -> ImageSeriesReader
      - Archivo .dcm suelto dentro de una serie -> lee su serie
      - Imagen DICOM única (sin serie)

    Args:
        path: ruta al archivo o directorio.
        serie_uid: (opcional) UID de la serie DICOM a cargar cuando el
                   directorio contiene varias series. Si omite, carga la
                   primera serie encontrada.

    Returns:
        sitk.Image o None si no se pudo cargar.
    """
    if not path or not os.path.exists(path):
        return None

    import SimpleITK as sitk

    # --- Directorio: es una serie DICOM (o varias) ---
    if os.path.isdir(path):
        try:
            reader = sitk.ImageSeriesReader()
            series_ids = reader.GetGDCMSeriesIDs(path)
            if not series_ids:
                return None
            uid = serie_uid or series_ids[0]
            if uid not in series_ids:
                uid = series_ids[0]
            file_names = reader.GetGDCMSeriesFileNames(path, uid)
            if not file_names:
                return None
            reader.SetFileNames(file_names)
            reader.MetaDataDictionaryArrayUpdateOn()
            reader.LoadPrivateTagsOn()
            return reader.Execute()
        except Exception:
            return None

    # --- Archivo .dcm: intenta cargar la serie que lo contiene ---
    if path.lower().endswith((".dcm", ".dicom", ".ima")):
        padre = os.path.dirname(path)
        try:
            reader = sitk.ImageSeriesReader()
            series_ids = reader.GetGDCMSeriesIDs(padre)
            for uid in series_ids:
                nombres = reader.GetGDCMSeriesFileNames(padre, uid)
                if path in nombres:
                    reader.SetFileNames(nombres)
                    reader.MetaDataDictionaryArrayUpdateOn()
                    return reader.Execute()
            # Sin serie: intenta leer como imagen única
            return sitk.ReadImage(path)
        except Exception:
            try:
                return sitk.ReadImage(path)
            except Exception:
                return None

    # --- NIfTI u otro formato que SimpleITK sepa leer ---
    try:
        return sitk.ReadImage(path)
    except Exception:
        return None


def descargar_braTS_muestra(num_pacientes=5, mods=("flair", "t1ce", "t2", "t1", "seg"), salida=None):
    """
    Descarga una muestra de BraTS2021 desde HuggingFace.
    Cada paciente incluye 4 modalidades MRI + máscara de segmentación (_seg).
    """
    salida = salida or NIFTI_DIR
    HF_REPO = "rocky93/BraTS_segmentation"
    API_TREE = f"https://huggingface.co/api/datasets/{HF_REPO}/tree/main"
    BASE_RAW = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"

    def _http_json(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)

    try:
        tree = _http_json(API_TREE)
        pacientes = sorted(n["path"] for n in tree
                           if n.get("type") == "directory"
                           and n["path"].startswith("BraTS2021_"))
        sel = pacientes[:num_pacientes]
        descargados = []
        for pid in sel:
            dest = os.path.join(salida, pid)
            os.makedirs(dest, exist_ok=True)
            for mod in mods:
                fname = f"{pid}_{mod}.nii.gz"
                out = os.path.join(dest, fname)
                if os.path.exists(out) and os.path.getsize(out) > 1000:
                    continue
                url = f"{BASE_RAW}/{pid}/{fname}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as f:
                    f.write(resp.read())
            descargados.append(pid)
            print(f"[DATOS] Descargado: {pid}")
        return descargados
    except Exception as e:
        print(f"[DATOS] Error descargando BraTS: {e}")
        return []


def exportar_para_neuronavegacion(nifti_path, mascara_path, salida_dir=None):
    """
    Exporta NIfTI + máscara a formatos compatibles con neuronavegación.

    Los sistemas de neuronavegación (Medtronic, BrainLab) aceptan:
    - STL (superficies 3D del tumor/aneurisma)
    - NIfTI (volúmenes con coordenadas espaciales)

    Esta función convierte la máscara a STL y guarda el NIfTI original.
    """
    import SimpleITK as sitk
    import numpy as np
    import trimesh
    from skimage import measure

    salida_dir = salida_dir or os.path.join(OUTPUT_DIR, "neuronavegacion")
    os.makedirs(salida_dir, exist_ok=True)

    if not os.path.exists(mascara_path) or not os.path.exists(nifti_path):
        return {"error": "Ruta de entrada no encontrada"}

    mask_img = cargar_volumen(mascara_path)
    if mask_img is None:
        return {"error": "No se pudo cargar la máscara"}
    mask_arr = sitk.GetArrayFromImage(mask_img)

    sp = mask_img.GetSpacing()
    verts, faces, _, _ = measure.marching_cubes(
        mask_arr, level=0.5,
        spacing=(sp[2], sp[1], sp[0])
    )

    mesh = trimesh.Trimesh(vertices=verts, faces=faces)
    base_name = Path(mascara_path).stem.replace(".nii", "")
    stl_path = os.path.join(salida_dir, f"{base_name}_surf.stl")
    mesh.export(stl_path)

    import shutil
    nifti_out = os.path.join(salida_dir, Path(nifti_path).name)
    shutil.copy2(nifti_path, nifti_out)

    voxel_volume = np.prod(sp)
    volumen_mm3 = float(mask_arr.sum()) * voxel_volume

    return {
        "stl": stl_path,
        "nifti": nifti_out,
        "volumen_mm3": volumen_mm3,
        "volumen_cm3": volumen_mm3 / 1000.0,
        "directorio": salida_dir,
    }


def exportar_whole_brain_stl(nifti_path, salida_dir=None):
    """Exporta el volumen cerebral como STL para neuronavegación/3D."""
    import SimpleITK as sitk
    import numpy as np
    import trimesh
    from skimage import measure, filters
    from scipy import ndimage

    salida_dir = salida_dir or os.path.join(OUTPUT_DIR, "neuronavegacion")
    os.makedirs(salida_dir, exist_ok=True)

    img = cargar_volumen(nifti_path)
    if img is None:
        return {"error": "No se pudo cargar el volumen"}
    arr = sitk.GetArrayFromImage(img)

    vals = arr[arr > 0]
    threshold = filters.threshold_otsu(vals) if len(vals) else 0
    brain_mask = arr > threshold * 0.5

    brain_mask = ndimage.binary_erosion(brain_mask, iterations=2)
    brain_mask = ndimage.binary_dilation(brain_mask, iterations=2)

    sp = img.GetSpacing()
    verts, faces, _, _ = measure.marching_cubes(
        brain_mask, level=0.5,
        spacing=(sp[2], sp[1], sp[0])
    )

    mesh = trimesh.Trimesh(vertices=verts, faces=faces)
    stl_path = os.path.join(salida_dir, "cerebro_completo.stl")
    mesh.export(stl_path)

    return {
        "stl": stl_path,
        "voxels": int(brain_mask.sum()),
        "directorio": salida_dir,
    }


if __name__ == "__main__":
    print("NEUROHUB - Módulo de Datos")
    print("=" * 50)
    print("\nDatasets disponibles:")
    for ds in DATASETS:
        print(f"  [{ds['tipo']}] {ds['nombre']}")
    print("\nArchivos NIfTI locales:")
    for a in listar_archivos_nifti():
        print(f"  - {a['directorio']}/{a['archivo']}")
