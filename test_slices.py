#!/usr/bin/env python3
"""Test de carga de imágenes 2D."""
import os
import sys

# Agregar ATLAS al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ATLAS'))

from PIL import Image

slice_dir = os.path.join(os.path.dirname(__file__), "salidas", "segmentaciones_ai", "vistas_2d")

print(f"[TEST] slice_dir: {slice_dir}")
print(f"[TEST] Existe: {os.path.exists(slice_dir)}")
print()

for name in ["axial", "coronal", "sagital"]:
    path = os.path.join(slice_dir, f"corte_{name}.png")
    print(f"[TEST] {name}:")
    print(f"       Ruta: {path}")
    print(f"       Existe: {os.path.exists(path)}")
    
    if os.path.exists(path):
        try:
            img = Image.open(path)
            print(f"       ✓ Abierta: {img.size} {img.mode}")
            
            # Test de thumbnail
            img_thumb = img.copy()
            img_thumb.thumbnail((320, 320), Image.Resampling.LANCZOS)
            print(f"       ✓ Thumbnail: {img_thumb.size}")
            
        except Exception as e:
            print(f"       ✗ Error: {e}")
    print()
