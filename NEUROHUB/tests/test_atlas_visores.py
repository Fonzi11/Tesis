"""
Pruebas de los visores de ATLAS: orientación radiológica del 2D, contornos
anatómicos, clases de lesión y catálogo de casos.
"""

import os
import sys

import numpy as np
import pytest
import SimpleITK as sitk

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "src"))

import volumen_2d as v2d  # noqa: E402


def _imagen_lps(arr_xyz_lps, ruta, orientacion=None):
    """Escribe un volumen definido en LPS (índices x, y, z) y, si se pide,
    lo reescribe con otra orientación de adquisición (p. ej. sagital PIR)."""
    img = sitk.GetImageFromArray(np.transpose(arr_xyz_lps, (2, 1, 0)).copy())
    img.SetSpacing((1.0, 1.0, 1.0))
    if orientacion:
        img = sitk.DICOMOrient(img, orientacion)
    sitk.WriteImage(img, ruta)
    return ruta


@pytest.fixture
def cabeza(tmp_path):
    """Volumen 40x50x30 (x=L, y=P, z=S) con marcadores en lados conocidos."""
    a = np.zeros((40, 50, 30), np.float32)
    a[:, :, :] = 10.0
    a[30:38, 20:30, 10:20] = 100.0   # marcador en el lado IZQUIERDO (x alto)
    a[15:25, 2:8, 10:20] = 60.0      # marcador ANTERIOR (y bajo)
    a[15:25, 20:30, 25:29] = 80.0    # marcador SUPERIOR (z alto)
    m = np.zeros(a.shape, np.uint8)
    m[30:38, 20:30, 10:20] = 1
    return a, m, tmp_path


@pytest.mark.parametrize("orientacion", [None, "PIR", "RAS"])
def test_planos_en_convencion_radiologica(cabeza, orientacion):
    """Sea cual sea la orientación de adquisición, en pantalla: axial con
    anterior arriba y la izquierda del paciente a la derecha; coronal y
    sagital con superior arriba."""
    a, _m, tmp = cabeza
    ruta = _imagen_lps(a, str(tmp / "vol.nii.gz"), orientacion)
    v = v2d.Volumen2D(ruta)
    z_med = v.n_cortes("axial") // 2

    axial = v.corte_volumen("axial", v.n_cortes("axial") - 1 - 15)  # z LPS = 15
    filas, cols = np.nonzero(axial == 100.0)
    assert cols.mean() > axial.shape[1] / 2, "la izquierda del paciente debe verse a la derecha"
    filas, _ = np.nonzero(axial == 60.0)
    assert filas.mean() < axial.shape[0] / 3, "lo anterior debe verse arriba"

    coronal = v.corte_volumen("coronal", 25)
    filas, _ = np.nonzero(coronal == 80.0)
    assert filas.mean() < coronal.shape[0] / 4, "lo superior debe verse arriba (coronal)"
    sagital = v.corte_volumen("sagital", 20)
    filas, _ = np.nonzero(sagital == 80.0)
    assert filas.mean() < sagital.shape[0] / 4, "lo superior debe verse arriba (sagital)"
    filas, cols = np.nonzero(sagital == 60.0)
    assert cols.mean() < sagital.shape[1] / 3, "lo anterior debe verse a la izquierda (sagital)"
    assert z_med >= 0


@pytest.mark.parametrize("orientacion", ["PIR", "RAS"])
def test_mascara_guardada_vuelve_a_la_orientacion_original(cabeza, orientacion):
    a, m, tmp = cabeza
    vol = _imagen_lps(a, str(tmp / "vol.nii.gz"), orientacion)
    msk = _imagen_lps(m.astype(np.float32), str(tmp / "msk.nii.gz"), orientacion)
    v = v2d.Volumen2D(vol, msk)
    assert v.vóxeles_tumor() == int(m.sum())
    salida = str(tmp / "guardada.nii.gz")
    v.guardar_mascara(salida)
    original = sitk.ReadImage(msk)
    guardada = sitk.ReadImage(salida)
    assert guardada.GetDirection() == pytest.approx(original.GetDirection())
    assert guardada.GetOrigin() == pytest.approx(original.GetOrigin())
    assert np.array_equal(sitk.GetArrayFromImage(guardada) > 0,
                          sitk.GetArrayFromImage(original) > 0)


def test_contornos_anatomicos_y_exclusion_de_la_lesion(tmp_path):
    a = np.full((40, 40, 20), 50.0, np.float32)
    lab = np.zeros(a.shape, np.float32)
    lab[5:35, 5:35, :] = 10          # tálamo: tiene color en la LUT
    m = np.zeros(a.shape, np.float32)
    m[15:25, 15:25, :] = 1
    vol = _imagen_lps(a, str(tmp_path / "v.nii.gz"))
    etq = _imagen_lps(lab, str(tmp_path / "l.nii.gz"))
    v = v2d.Volumen2D(vol, _imagen_lps(m, str(tmp_path / "m.nii.gz")))
    v.cargar_etiquetas(etq)
    sin, _ = v.render_corte("axial", 10, alto=200, clahe=False, unsharp=False, overlay=False)
    con, _ = v.render_corte("axial", 10, alto=200, clahe=False, unsharp=False,
                            overlay=False, anatomia=True)
    assert (np.abs(con.astype(int) - sin.astype(int)).sum(axis=-1) > 30).sum() > 100
    # Con la lesión visible, los contornos no se dibujan dentro de ella.
    v.etiquetas[:] = 0
    v.etiquetas[:, 18:22, 18:22] = 10           # estructura dentro de la lesión
    v.invalidar_cache()
    solo_lesion, _ = v.render_corte("axial", 10, alto=200, clahe=False, unsharp=False)
    lesion_y_anat, _ = v.render_corte("axial", 10, alto=200, clahe=False, unsharp=False,
                                      anatomia=True)
    assert np.array_equal(solo_lesion, lesion_y_anat)


def test_clases_brats_con_su_color(tmp_path):
    a = np.full((30, 30, 10), 40.0, np.float32)
    seg = np.zeros(a.shape, np.float32)
    seg[5:25, 5:25, :] = 2      # edema
    seg[10:20, 10:20, :] = 4    # realce
    seg[13:17, 13:17, :] = 1    # necrosis
    v = v2d.Volumen2D(_imagen_lps(a, str(tmp_path / "v.nii.gz")),
                      _imagen_lps(seg, str(tmp_path / "s.nii.gz")))
    assert v.clases_lesion is not None
    rgb, _ = v.render_corte("axial", 5, alto=300, clahe=False, unsharp=False)
    centro = rgb[150, 150].astype(int)
    assert centro[0] > 100 and centro[1] > 80 and centro[2] < 60, "necrosis: amarillo"
    realce = rgb[150, 110].astype(int)
    assert realce[0] > realce[1] + 40 and realce[0] > realce[2] + 40, "realce: rojo"


def test_catalogo_de_casos_atlas():
    from src.ui_qt import casos_atlas
    casos = casos_atlas.listar_casos()
    if not casos:
        pytest.skip("No hay casos ATLAS generados en esta máquina")
    for c in casos:
        assert c["lesion"] in ("tumor", "aneurisma"), c["id"]
        assert any(m["grupo"] == "lesion" for m in c["modelos"].values())
        for m in c["modelos"].values():
            assert os.path.isfile(m["stl"])
            assert 0.0 < m["opacity"] <= 1.0
    assert casos[0]["id"] in ("aneurisma_05", "tumor_02"), "los casos HUSI van primero"


def test_grupos_de_capas():
    from src.ui_qt.casos_atlas import grupo_de
    assert grupo_de("tumor_realce") == "lesion"
    assert grupo_de("aneurisma") == "lesion"
    assert grupo_de("corteza_frontal_izq") == "corteza"
    assert grupo_de("sustancia_blanca_der") == "sustancia_blanca"
    assert grupo_de("tronco_encefalico") == "cerebelo_tronco"
    assert grupo_de("arterias") == "vasos"
    assert grupo_de("craneo") == "craneo"
    assert grupo_de("talamo") == "profundas"
