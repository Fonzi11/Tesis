"""Regresiones para estudios DICOM entregados dentro de ZIPs."""

import importlib
import os
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

dicom = importlib.import_module("01_procesamiento_dicom")


def test_busqueda_dicom_elige_la_serie_con_mas_cortes(tmp_path, monkeypatch):
    """Los localizadores cortos no deben ganar a la serie volumétrica."""
    root = tmp_path / "estudio"
    (root / "localizador").mkdir(parents=True)
    (root / "volumen").mkdir()

    class FakeReader:
        def GetGDCMSeriesIDs(self, directory):
            name = os.path.basename(directory)
            return {"localizador": ["short"], "volumen": ["main"]}.get(
                name, []
            )

        def GetGDCMSeriesFileNames(self, directory, series_id):
            count = {"short": 2, "main": 4}[series_id]
            return [os.path.join(directory, f"{index}.dcm")
                    for index in range(count)]

    monkeypatch.setattr(dicom.sitk, "ImageSeriesReader", FakeReader)
    series_dir, series_id, names = dicom._find_first_dicom_series(str(root))

    assert os.path.basename(series_dir) == "volumen"
    assert series_id == "main"
    assert len(names) == 4


def test_zip_corrupto_se_omite_y_no_permite_traversal(tmp_path):
    """Un ZIP truncado no aborta la extracción ni escribe fuera del temporal."""
    source = tmp_path / "estudio"
    source.mkdir()
    (source / "corrupto.zip").write_bytes(b"not-a-zip")

    valid = source / "valido.zip"
    with zipfile.ZipFile(valid, "w") as handle:
        handle.writestr("../escape.dcm", b"should-not-be-extracted")
        handle.writestr("documentos/not_dicom.txt", b"ignored")

    extracted, count = dicom._extraer_zips_dicom(str(source))

    assert extracted is None
    assert count == 0
    assert not (tmp_path / "escape.dcm").exists()


def test_conversion_por_lotes_convierte_todas_las_series(tmp_path, monkeypatch):
    root = tmp_path / "estudio"
    (root / "serie_a").mkdir(parents=True)
    (root / "serie_b").mkdir()

    class FakeImage:
        pass

    class FakeReader:
        def __init__(self):
            self.names = None

        def GetGDCMSeriesIDs(self, directory):
            return {"serie_a": ["a"], "serie_b": ["b"]}.get(
                os.path.basename(directory), [])

        def GetGDCMSeriesFileNames(self, directory, series_id):
            return [os.path.join(directory, series_id + ".dcm")]

        def SetFileNames(self, names):
            self.names = names

        def Execute(self):
            return FakeImage()

    escritos = []
    monkeypatch.setattr(dicom.sitk, "ImageSeriesReader", FakeReader)
    monkeypatch.setattr(
        dicom.sitk, "WriteImage",
        lambda image, path: escritos.append(path))

    resultados = dicom.dicom_series_to_nifti(
        str(root), str(tmp_path / "nifti"))

    assert len(resultados) == 2
    assert all(path.endswith(".nii.gz") for path in resultados)
    assert escritos == resultados
