"""
Regresion del fallo "dibujar y borrar no funciona" en la vista 2D.

Los tests de `test_pincel_2d.py` ya cubren el algoritmo de pincel sobre
`Volumen2D`. Aqui se cubre la CAPA DE ARRIBA, que es donde estaba el fallo: el
visor 2D solo habilita Pincel y Borrar si hay un volumen cargado, y ese volumen
se buscaba por una lista corta de nombres fijos que NO incluia los nombres
reales de los casos BraTS (`<id>_flair.nii.gz`, ...). Con un caso de verdad
`buscar_volumen` devolvia None, el visor caia al modo visor-de-PNG y los botones
de delineado quedaban desactivados: no habia nada que pulsar.

Se cubre tambien la eleccion de mascara: si la mascara no comparte rejilla con
el volumen, `Volumen2D.cargar_mascara` levanta ValueError a proposito y el visor
se queda vacio, con lo que tampoco se puede pintar a mano.
"""
import os
import sys

import numpy as np
import pytest
import SimpleITK as sitk

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.ui_qt import mesh_store                       # noqa: E402


def _nifti(ruta, shape=(8, 10, 12), valor=1):
    """Escribe una NIfTI pequena y devuelve la ruta."""
    arr = np.full(shape, valor, dtype=np.uint8)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    sitk.WriteImage(img, ruta)
    return ruta


class TestBusquedaDeVolumen:
    def test_reconoce_un_caso_brats_real(self, tmp_path):
        """El fallo original: una carpeta con las 4 modalidades + la mascara."""
        d = tmp_path / "BraTS2021_00042"
        d.mkdir()
        for suf in ("t1", "t1ce", "t2", "flair"):
            _nifti(str(d / f"BraTS2021_00042_{suf}.nii.gz"))
        _nifti(str(d / "BraTS2021_00042_seg.nii.gz"))

        v = mesh_store.buscar_volumen(str(d))
        assert v is not None, (
            "un caso BraTS con sus 4 modalidades debe considerarse un volumen")
        # FLAIR es la modalidad con la que se delinea el tumor.
        assert v.endswith("_flair.nii.gz")

    def test_nunca_devuelve_una_mascara(self, tmp_path):
        """Tomar la mascara como imagen daria tejido totalmente tumor."""
        d = tmp_path / "caso"
        d.mkdir()
        _nifti(str(d / "caso_seg.nii.gz"))
        _nifti(str(d / "tumor_manual.nii.gz"))
        _nifti(str(d / "brain.nii.gz"))

        assert mesh_store.buscar_volumen(str(d)) is None

    def test_prefiere_el_nombre_conocido(self, tmp_path):
        """Si esta `volumen_paciente`, gana al resto."""
        d = tmp_path / "caso"
        d.mkdir()
        _nifti(str(d / "otro_flair.nii.gz"))
        _nifti(str(d / "volumen_paciente.nii.gz"))
        assert mesh_store.buscar_volumen(str(d)).endswith("volumen_paciente.nii.gz")

    def test_una_modalidad_suelta_tambien_sirve(self, tmp_path):
        d = tmp_path / "caso"
        d.mkdir()
        _nifti(str(d / "paciente_t1.nii.gz"))
        assert mesh_store.buscar_volumen(str(d)).endswith("paciente_t1.nii.gz")

    def test_sin_nada_devuelve_none(self, tmp_path):
        """Sigue siendo None cuando de verdad no hay imagen."""
        d = tmp_path / "vacio"
        d.mkdir()
        assert mesh_store.buscar_volumen(str(d)) is None
        assert mesh_store.buscar_volumen(str(tmp_path / "no_existe")) is None


class TestMascaraCompatible:
    def test_elige_la_mascara_de_la_misma_rejilla(self, tmp_path):
        d = tmp_path / "caso"
        d.mkdir()
        vol = _nifti(str(d / "volumen_paciente.nii.gz"), shape=(8, 10, 12))
        buena = _nifti(str(d / "tumor_manual.nii.gz"), shape=(8, 10, 12))
        # Otra rejilla, de otro caso: es la que se encontraba antes.
        mala = _nifti(str(d / "tumor_brats.nii.gz"), shape=(16, 20, 24))

        assert mesh_store.buscar_mascara_compatible([mala, buena], vol) == buena

    def test_devuelve_none_si_ninguna_encaja(self, tmp_path):
        """Que no haya máscara valida NO debe impedir pintar a mano."""
        d = tmp_path / "caso"
        d.mkdir()
        vol = _nifti(str(d / "volumen_paciente.nii.gz"), shape=(8, 10, 12))
        mala = _nifti(str(d / "tumor_brats.nii.gz"), shape=(16, 20, 24))

        assert mesh_store.buscar_mascara_compatible([mala], vol) is None

    def test_una_mascara_incompatible_no_tumba_el_volumen(self, tmp_path):
        """Regresion del fallo: la excepcion dejaba el visor sin pincel.

        Se construye el `Volumen2D` como lo hace la ventana, pasando solo la
        máscara compatible. Antes se pasaba la primera existente y el visor
        acababa vacio, sin herramientas de delineado.
        """
        from src import volumen_2d as v2d

        d = tmp_path / "caso"
        d.mkdir()
        vol = _nifti(str(d / "volumen_paciente.nii.gz"), shape=(8, 10, 12),
                     valor=100)
        _nifti(str(d / "tumor_brats.nii.gz"), shape=(16, 20, 24))

        candidatas = mesh_store.listar_mascaras_tumor(str(d))
        mascara = mesh_store.buscar_mascara_compatible(candidatas, vol)
        v = v2d.Volumen2D(vol, mascara)

        assert not v.vacio
        assert v.mascara.shape == v.volumen.shape
        # Y por tanto el pincel y el borrador pueden trabajar sobre el.
        n = v.pintar_tramo_2d("axial", 4, (4.0, 4.0), (6.0, 6.0), radio=1)
        assert n > 0
