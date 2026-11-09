"""Pruebas del adaptador FreeSurfer sin requerir FreeSurfer instalado."""

import os
import sys
from unittest.mock import patch

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import freesurfer_bridge as fs


def _instalacion_nativa():
    return fs.Instalacion("native", r"C:\FreeSurfer", "recon-all")


def test_sujeto_rechaza_traversal():
    with pytest.raises(ValueError):
        fs.recon_all("entrada.nii.gz", "..\\otro", "subjects")


def test_recon_all_construye_comando_y_licencia(tmp_path):
    entrada = tmp_path / "entrada.nii.gz"
    entrada.write_bytes(b"nifti")
    licencia = tmp_path / "license.txt"
    licencia.write_text("license", encoding="utf-8")
    subjects = tmp_path / "subjects"

    with patch.object(fs, "detectar", return_value=_instalacion_nativa()), \
            patch.object(fs, "ejecutar") as ejecutar:
        fs.recon_all(str(entrada), "caso01", str(subjects),
                     license_path=str(licencia))

    args = ejecutar.call_args.args[0]
    assert args[:1] == ["recon-all"]
    assert args[1:4] == ["-i", str(entrada), "-s"]
    assert args[-1] == "-all"
    assert ejecutar.call_args.kwargs["env_extra"]["SUBJECTS_DIR"] == \
        os.path.abspath(str(subjects))
    assert ejecutar.call_args.kwargs["env_extra"]["FS_LICENSE"] == \
        os.path.abspath(str(licencia))


def test_diagnostico_no_disponible():
    instalacion = fs.Instalacion("none", None, None)
    with patch.object(fs, "detectar", return_value=instalacion):
        mensaje = fs.diagnostico()
    assert "no está" in mensaje

