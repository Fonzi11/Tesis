"""
Pruebas de generación y renderizado de vistas 2D (04_slices_2d.py)
"""
import os
import sys
import numpy as np
import pytest
import SimpleITK as sitk
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import importlib
slices_module = importlib.import_module("04_slices_2d")


def _crear_nifti_prueba(tmp_path):
    """Crea un volumen sintetico y una mascara de tumor alineada."""
    arr_vol = np.zeros((30, 40, 50), dtype=np.float32)
    # Parenquima cerebral sintetico
    arr_vol[5:25, 5:35, 5:45] = 100.0
    # Tumor sintetico
    arr_vol[12:18, 15:25, 20:30] = 250.0

    arr_mask = np.zeros((30, 40, 50), dtype=np.uint8)
    arr_mask[12:18, 15:25, 20:30] = 1

    img_vol = sitk.GetImageFromArray(arr_vol)
    img_vol.SetSpacing((1.0, 1.0, 2.0))

    img_mask = sitk.GetImageFromArray(arr_mask)
    img_mask.CopyInformation(img_vol)

    vol_path = os.path.join(tmp_path, "volumen.nii.gz")
    mask_path = os.path.join(tmp_path, "tumor.nii.gz")

    sitk.WriteImage(img_vol, vol_path)
    sitk.WriteImage(img_mask, mask_path)

    return vol_path, mask_path


class TestGenerarVistas2D:
    def test_generar_vistas_2d_crea_pngs_validos(self, tmp_path):
        vol_path, mask_path = _crear_nifti_prueba(str(tmp_path))
        out_dir = os.path.join(str(tmp_path), "vistas")

        resultado = slices_module.generar_vistas_2d(vol_path, mask_path, out_dir)

        assert "axial" in resultado
        assert "coronal" in resultado
        assert "sagital" in resultado

        for eje, ruta in resultado.items():
            assert os.path.exists(ruta)
            img = Image.open(ruta)
            assert img.mode in ("RGB", "RGBA")
            # El lado mayor del canvas debe ser de 1024px por resolucion objetivo
            assert max(img.size) == 1024

    def test_sin_circulo_verde(self, tmp_path):
        """Verifica que no queden pixeles verde laser de la elipse eliminada."""
        vol_path, mask_path = _crear_nifti_prueba(str(tmp_path))
        out_dir = os.path.join(str(tmp_path), "vistas")

        resultado = slices_module.generar_vistas_2d(vol_path, mask_path, out_dir)

        for eje, ruta in resultado.items():
            img = Image.open(ruta).convert("RGB")
            arr = np.array(img)
            # Verde laser antiguo (120, 255, 90) no debe existir
            verdes_laser = (arr[:, :, 0] == 120) & (arr[:, :, 1] == 255) & (arr[:, :, 2] == 90)
            assert not verdes_laser.any(), f"Se detectaron pixeles del circulo verde en {eje}"

