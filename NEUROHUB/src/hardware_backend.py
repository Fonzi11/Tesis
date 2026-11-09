"""Detección honesta de backends de inferencia disponibles en Windows.

El render OpenGL/VTK y la inferencia de IA son recursos distintos. Este
módulo solo informa de un backend AMD cuando ONNX Runtime confirma
``DmlExecutionProvider``; no confunde la GPU gráfica con CUDA.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class InferenceBackend:
    name: str
    provider: str | None
    device: str
    available: bool
    reason: str


def _directml_runtime_check() -> tuple[bool, str]:
    """Comprueba que DirectML puede crear una sesión, no solo anunciarse."""
    try:
        import onnxruntime as ort
    except Exception as exc:
        return False, f"runtime ONNX no disponible: {exc}"

    if "DmlExecutionProvider" not in ort.get_available_providers():
        return False, "ONNX Runtime no expone DmlExecutionProvider"

    # La disponibilidad declarada por ORT no garantiza que el driver D3D12
    # pueda crear una sesión. El modelo identidad mantiene esta prueba barata.
    try:
        from onnx import TensorProto, helper

        graph = helper.make_graph(
            [
                helper.make_node("Identity", ["input"], ["output"]),
            ],
            "neurohub_directml_probe",
            [
                helper.make_tensor_value_info(
                    "input", TensorProto.FLOAT, [1, 1],
                ),
            ],
            [
                helper.make_tensor_value_info(
                    "output", TensorProto.FLOAT, [1, 1],
                ),
            ],
        )
        model = helper.make_model(
            graph,
            opset_imports=[helper.make_opsetid("", 17)],
            ir_version=8,
        )
        session = ort.InferenceSession(
            model.SerializeToString(),
            providers=["DmlExecutionProvider"],
        )
        if "DmlExecutionProvider" not in session.get_providers():
            return False, f"proveedor efectivo: {session.get_providers()}"
    except Exception as exc:
        return False, f"no se pudo crear sesión DirectML: {exc}"
    return True, "sesión ONNX Runtime creada con DmlExecutionProvider"


def detect_inference_backends() -> tuple[InferenceBackend, ...]:
    """Devuelve los backends instalados, en orden de preferencia."""
    backends: list[InferenceBackend] = []

    directml_available, directml_reason = _directml_runtime_check()

    if directml_available:
        backends.append(
            InferenceBackend(
                name="amd-directml",
                provider="DmlExecutionProvider",
                device="AMD Radeon / DirectML",
                available=True,
                reason=directml_reason,
            )
        )
    else:
        backends.append(
            InferenceBackend(
                name="amd-directml",
                provider=None,
                device="AMD Radeon / DirectML",
                available=False,
                reason=directml_reason,
            )
        )

    # En esta instalación AMD no se consulta CUDA por defecto: PyTorch
    # inicializa el driver NVIDIA al hacerlo y genera avisos engañosos.
    cuda_requested = os.environ.get("NEUROHUB_ENABLE_CUDA") == "1"
    if cuda_requested:
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    else:
        cuda_available = False
    backends.append(
        InferenceBackend(
            name="cuda",
            provider="CUDAExecutionProvider" if cuda_available else None,
            device="NVIDIA CUDA",
            available=cuda_available,
            reason="PyTorch confirma CUDA" if cuda_available else "CUDA no disponible",
        )
    )
    backends.append(
        InferenceBackend(
            name="cpu",
            provider="CPUExecutionProvider",
            device="CPU",
            available=True,
            reason="fallback universal",
        )
    )
    return tuple(backends)


def preferred_onnx_providers() -> list[str]:
    """Selecciona DirectML y deja CPU como fallback explícito."""
    forced = os.environ.get("NEUROHUB_ONNX_PROVIDER", "").strip().lower()
    providers = {b.name: b for b in detect_inference_backends()}
    if forced == "cpu":
        return ["CPUExecutionProvider"]
    if forced in ("amd", "directml") and providers["amd-directml"].available:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    if forced in ("amd", "directml"):
        raise RuntimeError(
            "NEUROHUB_ONNX_PROVIDER=directml fue solicitado, pero "
            "DmlExecutionProvider no está disponible."
        )
    if providers["amd-directml"].available:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def describe_backends() -> str:
    """Texto breve para logs y diagnósticos."""
    return "; ".join(
        f"{backend.name}={'sí' if backend.available else 'no'} ({backend.reason})"
        for backend in detect_inference_backends()
    )
