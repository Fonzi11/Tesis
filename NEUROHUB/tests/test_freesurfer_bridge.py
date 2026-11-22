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


def test_ejecutar_retransmite_salida_y_conserva_log(tmp_path):
    class ProcesoFalso:
        stdout = iter(("etapa 1\n", "etapa 2\n"))
        returncode = 0

        def wait(self):
            return self.returncode

    log_path = tmp_path / "recon-all.log"
    salida = []
    with patch.object(fs, "detectar", return_value=_instalacion_nativa()), \
            patch.object(fs.subprocess, "Popen", return_value=ProcesoFalso()):
        fs.ejecutar(["recon-all"], log_path=str(log_path),
                    output_callback=salida.append)

    assert salida == ["etapa 1", "etapa 2"]
    assert log_path.read_text(encoding="utf-8") == "etapa 1\netapa 2\n"


def test_synthseg_construye_comando(tmp_path):
    entrada = tmp_path / "entrada.nii.gz"
    entrada.write_bytes(b"nifti")
    salida = tmp_path / "salida.nii.gz"

    with patch.object(fs, "detectar", return_value=_instalacion_nativa()), \
            patch.object(fs, "ejecutar") as ejecutar:
        fs.synthseg(str(entrada), str(salida), robust=True,
                    parcellation=True, threads=2, cpu=True)

    args = ejecutar.call_args.args[0]
    assert args[:5] == ["mri_synthseg", "--i", str(entrada),
                        "--o", str(salida)]
    assert "--robust" in args
    assert "--parc" in args
    assert ["--threads", "2"] == args[args.index("--threads"):
                                    args.index("--threads") + 2]
    assert "--cpu" in args


def test_tumorsynth_rechaza_modo_desconocido(tmp_path):
    entrada = tmp_path / "entrada.nii.gz"
    entrada.write_bytes(b"nifti")
    with pytest.raises(ValueError):
        fs.tumorsynth(str(entrada), str(tmp_path / "salida.nii.gz"),
                      mode="otro")
