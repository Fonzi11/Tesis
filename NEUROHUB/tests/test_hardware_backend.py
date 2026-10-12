"""Pruebas del contrato de selección de backend de inferencia."""

import importlib
import os
import sys

import pytest


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE_DIR, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _backend():
    return importlib.import_module("hardware_backend")


def test_cpu_es_un_fallback_disponible():
    backends = {b.name: b for b in _backend().detect_inference_backends()}
    assert backends["cpu"].available is True
    assert backends["cpu"].provider == "CPUExecutionProvider"


def test_directml_selecciona_cpu_como_fallback(monkeypatch):
    module = _backend()
    monkeypatch.setattr(
        module,
        "detect_inference_backends",
        lambda: (
            module.InferenceBackend(
                "amd-directml", "DmlExecutionProvider",
                "AMD Radeon / DirectML", True, "test",
            ),
            module.InferenceBackend(
                "cuda", None, "NVIDIA CUDA", False, "test"
            ),
            module.InferenceBackend(
                "cpu", "CPUExecutionProvider", "CPU", True, "test"
            ),
        ),
    )
    assert module.preferred_onnx_providers() == [
        "DmlExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_directml_forzado_falla_si_no_esta_disponible(monkeypatch):
    module = _backend()
    monkeypatch.setenv("NEUROHUB_ONNX_PROVIDER", "directml")
    monkeypatch.setattr(
        module,
        "detect_inference_backends",
        lambda: (
            module.InferenceBackend(
                "amd-directml", None, "AMD Radeon / DirectML", False, "ausente"
            ),
            module.InferenceBackend("cuda", None, "NVIDIA CUDA", False, "ausente"),
            module.InferenceBackend(
                "cpu", "CPUExecutionProvider", "CPU", True, "test"
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="DmlExecutionProvider"):
        module.preferred_onnx_providers()
