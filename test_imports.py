#!/usr/bin/env python
"""Test script para verificar que todas las importaciones funcionan."""

import sys
import os

# Agregar paths necesarios
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ATLAS"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ATLAS", "src"))

print("[TEST] Verificando importaciones...")

try:
    print("[✓] Importando customtkinter...", end=" ")
    import customtkinter as ctk
    print("OK")
except ImportError as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando SimpleITK...", end=" ")
    import SimpleITK as sitk
    print("OK")
except ImportError as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando PIL...", end=" ")
    from PIL import Image, ImageDraw
    print("OK")
except ImportError as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando numpy...", end=" ")
    import numpy as np
    print("OK")
except ImportError as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando 04_slices_2d...", end=" ")
    import importlib
    slices_module = importlib.import_module("04_slices_2d")
    print("OK")
except Exception as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando 03_integrar_brats...", end=" ")
    import importlib
    integrar = importlib.import_module("03_integrar_brats")
    print("OK")
except Exception as e:
    print(f"FALLO: {e}")

try:
    print("[✓] Importando main (primeras líneas)...", end=" ")
    # No hacer un import completo de main porque requiere la interfaz gráfica
    with open(os.path.join(os.path.dirname(__file__), "ATLAS", "main.py")) as f:
        code = f.read()
    compile(code, "main.py", "exec")
    print("OK (compilación exitosa)")
except Exception as e:
    print(f"FALLO: {e}")

print("\n[✓] Todas las verificaciones completadas")
