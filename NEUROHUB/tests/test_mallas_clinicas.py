"""Regresiones geométricas para evitar superficies escalonadas o desplazadas."""

import importlib
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

calidad = importlib.import_module("calidad_mallas")
segmentacion = importlib.import_module("segmentacion_completa")


def test_malla_isotropica_conserva_el_origen_en_milimetros():
    """El recorte de una máscara no puede mover la anatomía por usar 0.6 mm."""
    mask = np.zeros((20, 20, 20), dtype=np.uint8)
    mask[8:12, 7:13, 6:14] = 1

    verts, faces = calidad.malla_alta_calidad(
        mask,
        (1.0, 1.0, 2.0),
        estructura="tumor",
        min_voxels=0,
    )

    assert len(verts) > 0
    assert len(faces) > 0
    assert float(verts[:, 0].min()) >= 5.0
    assert float(verts[:, 1].min()) >= 6.0
    assert float(verts[:, 2].min()) >= 14.0


def test_tumor_no_se_genera_sin_delineacion_manual(monkeypatch, tmp_path):
    """La segmentación automática no debe producir un tumor renderizable."""
    monkeypatch.setattr(segmentacion, "SEG_AI_DIR", str(tmp_path))
    arr, img = segmentacion._cargar_estructura(
        "tumor", segmentacion.ESTRUCTURAS["tumor"]
    )
    assert arr is None
    assert img is None
