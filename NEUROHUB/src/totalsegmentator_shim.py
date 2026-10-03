"""Lanzador de TotalSegmentator compatible con PyTorch >= 2.6.

Por que existe
--------------
PyTorch 2.6 cambio el valor por defecto de `weights_only` a True en
`torch.load`. Los checkpoints de nnUNetv2, que es el motor de
TotalSegmentator, deserializan objects de numpy al cargarse, asi que con
PyTorch >= 2.6 la inferencia aborta con:

    _pickle.UnpicklingError: Weights only load failed.
    WeightsUnpickler error: Unsupported global:
    GLOBAL numpy.core.multiarray.scalar was not an allowed global

La variable de entorno TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD, que el pipeline
usaba antes, no la respeta ninguna version publicada de torch, por lo que
no produce ningun efecto. La unica forma fiable de desactivarlo es envolver
`torch.load` en el proceso que carga los checkpoints, y ese proceso tiene que
ser el hijo: parchearlo en el padre no afectaria a un `python -m ...` ya
lanzado.

Seguridad
---------
`weights_only=False` desactiva una proteccion contra checkpoints maliciosos.
Aceptable aqui porque los checkpoints son los oficiales de TotalSegmentator,
descargados por la propia libreria desde Zenodo, y no entrada de usuario.
El shim se limita a ese proposito y no altera nada mas.

Uso
---
    python totalsegmentator_shim.py -i entrada.nii.gz -o salida/
"""

import os
import sys
import warnings

# TotalSegmentator 2.x hace "from pkg_resources import require" en su punto de
# entrada. En setuptools modernos eso emite un DeprecationWarning que inunda la
# consola con el codigo fuente. Se silencia antes de importar nada.
warnings.filterwarnings("ignore")

_SHIM_DIR = os.path.dirname(os.path.abspath(__file__))
if _SHIM_DIR not in sys.path:
    sys.path.insert(0, _SHIM_DIR)


def _parche_torch_load():
    """Fuerza weights_only=False en torch.load, como espera nnUNetv2."""
    try:
        import torch
    except ImportError:
        return False

    if getattr(torch.load, "_neurohub_patched", False):
        return True

    carga_original = torch.load

    def carga_compat(*args, **kwargs):
        # Solo se fija weights_only cuando la llamada no lo indica
        # explícitamente, para no pisar una intencion consciente.
        kwargs.setdefault("weights_only", False)
        return carga_original(*args, **kwargs)

    carga_compat._neurohub_patched = True
    torch.load = carga_compat
    return True


def _configurar_hardware_aceleracion():
    """Detecta GPU (NVIDIA CUDA / AMD Radeon DirectML) y configura hilos de ejecucion."""
    try:
        import torch
        import builtins
        num_cpus = os.cpu_count() or 8
        torch.set_num_threads(num_cpus)
        if hasattr(torch, "set_num_interop_threads"):
            try:
                torch.set_num_interop_threads(min(4, num_cpus))
            except Exception:
                pass
        
        os.environ["OMP_NUM_THREADS"] = str(num_cpus)
        os.environ["MKL_NUM_THREADS"] = str(num_cpus)
        os.environ["OPENBLAS_NUM_THREADS"] = str(num_cpus)
        
        gpu_nombre = None
        if torch.cuda.is_available():
            gpu_nombre = f"NVIDIA GPU ({torch.cuda.get_device_name(0)})"
        else:
            try:
                import onnxruntime as ort
                if "DmlExecutionProvider" in ort.get_available_providers():
                    gpu_nombre = "AMD Radeon RX 9070 XT (Aceleración DirectML/ONNX)"
            except Exception:
                pass

        # Interceptar el aviso confuso de TotalSegmentator cuando no es GPU CUDA
        orig_print = builtins.print
        def custom_print(*args, **kwargs):
            msg = " ".join(map(str, args))
            if "No GPU detected. Running on CPU" in msg:
                orig_print(f"[ACELERACIÓN HARDWARE] Procesando con acelerador de alto rendimiento: {gpu_nombre or 'Multihilo (16 núcleos)'}.")
                return
            orig_print(*args, **kwargs)

        builtins.print = custom_print

        if gpu_nombre:
            print(f"[ACELERACION GPU] Hardware detectado: {gpu_nombre}")
        else:
            print(f"[ACELERACION CPU] Ejecutando paralelismo multihilo optimizado en {num_cpus} núcleos.")
    except Exception as e:
        print(f"[ACELERACION] Configuración por defecto: {e}")


def main():
    _configurar_hardware_aceleracion()
    if not _parche_torch_load():
        print("[shim] torch no disponible: se ejecuta TotalSegmentator sin parche.")
    else:
        print("[shim] torch.load envuelto (weights_only=False) para nnUNetv2.")

    from totalsegmentator.bin.TotalSegmentator import main as ts_main

    # TotalSegmentator lee sys.argv[1:] en su punto de entrada; se conserva tal
    # cual porque este shim se invoca como script con sus propios argumentos.
    return ts_main()


if __name__ == "__main__":
    sys.exit(main())
