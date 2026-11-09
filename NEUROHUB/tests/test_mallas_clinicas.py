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
mesh_store = importlib.import_module("ui_qt.mesh_store")


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


def test_estructura_sintetica_no_requiere_mascara(monkeypatch, tmp_path):
    """Las capas ilustrativas no deben romper el fallback nativo de mallas."""
    monkeypatch.setattr(segmentacion, "SEG_AI_DIR", str(tmp_path))
    arr, img = segmentacion._cargar_estructura(
        "vasculatura_sintetica",
        segmentacion.ESTRUCTURAS["vasculatura_sintetica"],
    )
    assert arr is None
    assert img is None


def test_craneo_se_restringe_a_envoltura_cerebral():
    """Una extension conectada hacia cuello no debe entrar en el STL craneal."""
    cerebro = np.zeros((40, 50, 60), dtype=np.uint8)
    cerebro[20:36, 15:35, 20:40] = 1
    craneo = np.zeros_like(cerebro)
    craneo[2:36, 10:40, 15:45] = 1

    resultado = segmentacion._restringir_craneo_a_cerebro(
        craneo, cerebro, (1.0, 1.0, 1.0), margen_mm=3.0)

    assert resultado[20, 15, 20]
    assert not resultado[2, 20, 30]
    assert resultado.sum() < craneo.sum()


def test_malla_remuestrea_spacing_mas_fino_sin_alargar_ejes():
    """El spacing inferior al objetivo debe conservar las dimensiones fisicas."""
    mask = np.zeros((30, 30, 30), dtype=np.uint8)
    mask[8:22, 7:23, 6:24] = 1

    verts, _ = calidad.malla_alta_calidad(
        mask,
        (0.4, 0.4, 0.2),
        estructura="tumor",
        min_voxels=0,
        perfil={"sigma_mm": 0.0, "taubin_iter": 0},
    )

    extension = verts.max(axis=0) - verts.min(axis=0)
    assert extension[0] < 9.0
    assert extension[1] < 9.0
    assert extension[2] < 5.0


def test_resultados_de_estudios_distintos_no_comparten_rutas(tmp_path):
    """Cada estudio debe resolver sus máscaras y mallas en su propio árbol."""
    estudio_a = tmp_path / "estudio_a"
    estudio_b = tmp_path / "estudio_b"
    estudio_a.mkdir()
    estudio_b.mkdir()

    rutas_a = mesh_store.rutas_serie(str(estudio_a))
    rutas_b = mesh_store.rutas_serie(str(estudio_b))
    assert rutas_a["segmentaciones"] != rutas_b["segmentaciones"]
    assert rutas_a["mallas"] != rutas_b["mallas"]

    import SimpleITK as sitk
    mascara_a = np.zeros((8, 8, 8), dtype=np.uint8)
    mascara_b = np.zeros((8, 8, 8), dtype=np.uint8)
    mascara_a[1:3, 1:3, 1:3] = 1
    mascara_b[5:7, 5:7, 5:7] = 1
    os.makedirs(rutas_a["segmentaciones"])
    os.makedirs(rutas_b["segmentaciones"])
    sitk.WriteImage(
        sitk.GetImageFromArray(mascara_a),
        os.path.join(rutas_a["segmentaciones"], "brain.nii.gz"),
    )
    sitk.WriteImage(
        sitk.GetImageFromArray(mascara_b),
        os.path.join(rutas_b["segmentaciones"], "brain.nii.gz"),
    )

    arr_a, _ = segmentacion.cargar_mascara(
        "brain.nii.gz", rutas_a["segmentaciones"])
    arr_b, _ = segmentacion.cargar_mascara(
        "brain.nii.gz", rutas_b["segmentaciones"])
    assert not np.array_equal(arr_a, arr_b)


def test_malla_delineacion_pequena_conserva_superficie():
    """Una máscara que llena el recorte debe conservar un fondo exterior."""
    mask = np.zeros((12, 12, 12), dtype=np.uint8)
    mask[5:7, 5:7, 5:7] = 1

    verts, faces = calidad.malla_alta_calidad(
        mask,
        (0.4, 0.4, 0.4),
        estructura="tumor",
        min_voxels=0,
        perfil={"sigma_mm": 2.0, "taubin_iter": 0},
    )

    assert len(verts) > 0
    assert len(faces) > 0


def test_repara_solo_brechas_pequenas_del_craneo():
    """La reparación no debe completar una ausencia anatómica grande."""
    craneo = np.zeros((20, 30, 30), dtype=np.uint8)
    craneo[4:16, 5:25, 5] = 1
    craneo[4:16, 5:25, 7] = 1
    reparado = segmentacion._reparar_huecos_craneo(
        craneo, (1.0, 1.0, 1.0), max_gap_mm=2.0)
    assert reparado[:, :, 6].sum() > 0
    assert reparado[:, :, 15].sum() == 0


def test_repara_brecha_vascular_pequena_sin_inventar_puente_largo():
    """Los vasos deben conservar ramas separadas y cerrar solo cortes pequeños."""
    vasos = np.zeros((20, 30, 30), dtype=np.uint8)
    vasos[8:12, 5:12, 9:12] = 1
    vasos[8:12, 13:21, 9:12] = 1
    reparado = segmentacion._reparar_mascara_vascular(
        vasos, (1.0, 1.0, 1.0), max_gap_mm=1.0)
    assert reparado[9, 12, 10]
    assert not reparado[9, 22, 10]


def test_completa_huecos_cerrados_de_la_envoltura_craneal():
    """Los agujeros internos de la calota se cierran, sin rellenar el exterior."""
    craneo = np.ones((12, 18, 18), dtype=np.uint8)
    craneo[4:8, 7:11, 7:11] = 0
    craneo[:2, :, :] = 0
    reparado = segmentacion._completar_envoltura_craneal(
        craneo, (1.0, 1.0, 1.0), max_gap_mm=1.0)
    assert reparado[5, 8, 8]
    assert not reparado[0, 8, 8]


def test_completa_envoltura_craneal_descarta_residuo_desconectado():
    """La calota exportada debe quedar en un componente anatómico dominante."""
    craneo = np.zeros((20, 30, 30), dtype=np.uint8)
    craneo[4:16, 5:25, 5:25] = 1
    craneo[1:3, 1:3, 1:3] = 1
    reparado = segmentacion._completar_envoltura_craneal(
        craneo, (1.0, 1.0, 1.0), max_gap_mm=1.0)
    assert reparado[10, 15, 15]
    assert not reparado[1, 1, 1]


def test_carga_mascara_vascular_usa_el_primer_alias_disponible(monkeypatch, tmp_path):
    """El pipeline acepta nombres habituales sin generar vasos si faltan."""
    image = np.zeros((8, 8, 8), dtype=np.uint8)
    image[3:5, 3:5, 3:5] = 1
    path = tmp_path / "vessels.nii.gz"
    sitk = importlib.import_module("SimpleITK")
    sitk.WriteImage(sitk.GetImageFromArray(image), str(path))
    monkeypatch.setattr(segmentacion, "SEG_AI_DIR", str(tmp_path))

    arr, img = segmentacion._cargar_estructura(
        "vasos", segmentacion.ESTRUCTURAS["vasos"])
    assert arr is not None
    assert img is not None
    assert int(arr.sum()) == 8
