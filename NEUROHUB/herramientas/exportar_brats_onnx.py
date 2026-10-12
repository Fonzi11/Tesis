"""Exporta el bundle BraTS a ONNX para ejecutarlo con DirectML en AMD.

La exportación es deliberadamente fija al ROI oficial 240x240x160. El
pipeline usa ventanas deslizantes sobre el volumen clínico y valida que
ONNX Runtime exponga DirectML antes de usar la Radeon.
"""

from __future__ import annotations

import argparse
import os
import sys

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from hardware_backend import preferred_onnx_providers
from importlib import import_module


def export_model(output_path: str) -> str:
    brats = import_module("02_segmentacion_brats")
    bundle = os.path.join(
        ROOT, "modelos_preentrenados", "brats_mri_segmentation"
    )
    model, _ = brats.load_brats_model(bundle)
    if model is None:
        raise RuntimeError("No se pudo cargar el modelo BraTS para exportación")

    model = model.cpu().eval()
    dummy = torch.zeros((1, 4, 240, 240, 160), dtype=torch.float32)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        output_path,
        input_names=["image"],
        output_names=["pred"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )

    import onnx
    import onnxruntime as ort

    onnx.checker.check_model(onnx.load(output_path))
    session = ort.InferenceSession(
        output_path,
        providers=preferred_onnx_providers(),
    )
    print(f"[ONNX] Exportado y validado: {output_path}")
    print(f"[ONNX] Proveedores efectivos: {session.get_providers()}")
    session.run(["pred"], {"image": dummy.numpy()})
    print("[ONNX] Inferencia de prueba completada")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--salida",
        default=os.path.join(
            ROOT, "modelos_preentrenados",
            "brats_mri_segmentation", "models", "model.onnx",
        ),
    )
    args = parser.parse_args()
    export_model(args.salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
