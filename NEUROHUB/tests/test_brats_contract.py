"""Pruebas del contrato de entrada y salida del bundle BraTS."""

import importlib
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

brats = importlib.import_module("02_segmentacion_brats")


def test_postprocess_decodifica_tc_wt_et_como_subregiones_clinicas():
    """TC sin ET es NCR; WT fuera de TC es edema; ET conserva prioridad."""
    logits = np.full((1, 3, 1, 1, 4), -10.0, dtype=np.float32)
    # Voxel 0: ET, que también pertenece a TC y WT.
    logits[0, 0, 0, 0, 0] = 10.0
    logits[0, 1, 0, 0, 0] = 10.0
    logits[0, 2, 0, 0, 0] = 10.0
    # Voxel 1: TC sin ET => NCR.
    logits[0, 0, 0, 0, 1] = 10.0
    logits[0, 1, 0, 0, 1] = 10.0
    # Voxel 2: WT fuera de TC => edema.
    logits[0, 1, 0, 0, 2] = 10.0

    result = brats._postprocess_output(logits, (1, 1, 4))

    np.testing.assert_array_equal(
        result, np.array([[[4, 1, 2, 0]]], dtype=np.uint8)
    )


def test_segmentacion_brats_rechaza_modalidades_incompletas(tmp_path):
    """No se debe inferir BraTS rellenando canales ausentes."""
    import SimpleITK as sitk

    image = sitk.GetImageFromArray(np.ones((4, 4, 4), dtype=np.float32))
    paths = {}
    for name in ("t1ce", "t1", "t2"):
        path = tmp_path / f"caso_{name}.nii.gz"
        sitk.WriteImage(image, str(path))
        paths[name] = str(path)

    result = brats.segment_brats_tumor(
        paths["t1"], paths["t1ce"], paths["t2"], None,
        output_dir=str(tmp_path / "out"),
    )

    assert result is None
