#!/usr/bin/env python3
"""
Script de verificación rápida del estado de ATLAS v1.1
Verifica sintaxis, archivos, y estructura del proyecto
"""

import os
import sys
from pathlib import Path

def check_file_exists(path, description=""):
    """Verifica si un archivo existe"""
    exists = os.path.exists(path)
    status = "✅" if exists else "❌"
    print(f"  {status} {path}")
    if description and not exists:
        print(f"     → {description}")
    return exists

def check_syntax(filepath):
    """Verifica sintaxis Python"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            compile(f.read(), filepath, 'exec')
        return True
    except Exception as e:
        print(f"     Syntax Error: {e}")
        return False

print("\n" + "="*80)
print("✅ VERIFICACIÓN DE ATLAS v1.1")
print("="*80)

base_path = Path("d:\\Tesis")
os.chdir(base_path)

# 1. Archivos principales
print("\n1️⃣  ARCHIVOS PRINCIPALES")
print("─" * 80)

atlas_files = [
    ("ATLAS/main.py", "Interfaz principal"),
    ("ATLAS/src/04_slices_2d.py", "Renderizado 2D"),
    ("ATLAS/src/03_integrar_brats.py", "Pipeline BRATS"),
    ("ATLAS/src/02_segmentacion_brats.py", "Segmentación BRATS"),
]

all_exist = True
for filepath, desc in atlas_files:
    exists = check_file_exists(filepath, desc)
    all_exist = all_exist and exists

# 2. Sintaxis Python
print("\n2️⃣  SINTAXIS PYTHON")
print("─" * 80)

all_valid = True
for filepath, _ in atlas_files[:3]:  # Verificar los 3 archivos modificados
    if os.path.exists(filepath):
        valid = check_syntax(filepath)
        status = "✅" if valid else "❌"
        print(f"  {status} {filepath}: Sintaxis {'válida' if valid else 'inválida'}")
        all_valid = all_valid and valid

# 3. Directorios de datos
print("\n3️⃣  DIRECTORIOS DE DATOS")
print("─" * 80)

data_dirs = [
    "data/dicom",
    "data/nifti",
    "modelos_3d",
    "salidas",
    "ATLAS/assets/fonts",
]

for dirpath in data_dirs:
    exists = check_file_exists(dirpath)

# 4. Archivos de documentación
print("\n4️⃣  DOCUMENTACIÓN GENERADA")
print("─" * 80)

doc_files = [
    "CAMBIOS_IMPLEMENTADOS.md",
    "ARQUITECTURA_VISUAL.txt",
    "mostrar_arquitectura.py",
    "RESUMEN_EJECUTIVO.txt",
]

for docfile in doc_files:
    check_file_exists(docfile)

# 5. Verificaciones adicionales
print("\n5️⃣  VERIFICACIONES ADICIONALES")
print("─" * 80)

# Verificar que UnifiedViewerPanel está en main.py
print("  Verificando clases nuevas...")
try:
    with open("ATLAS/main.py", 'r', encoding='utf-8') as f:
        content = f.read()
        has_unified = "class UnifiedViewerPanel" in content
        has_slice2d = "class Slice2DPanel" in content
        print(f"    {'✅' if has_unified else '❌'} UnifiedViewerPanel")
        print(f"    {'✅' if has_slice2d else '❌'} Slice2DPanel")
except Exception as e:
    print(f"    ❌ Error al leer main.py: {e}")

# Verificar que generar_vistas_2d está siendo llamado en 03_integrar_brats.py
print("  Verificando integración de vistas 2D...")
try:
    with open("ATLAS/src/03_integrar_brats.py", 'r', encoding='utf-8') as f:
        content = f.read()
        has_auto_gen = "generar_vistas_2d" in content
        print(f"    {'✅' if has_auto_gen else '❌'} Generación automática de vistas 2D")
except Exception as e:
    print(f"    ❌ Error al leer 03_integrar_brats.py: {e}")

# 6. Resumen
print("\n" + "="*80)
print("📊 RESUMEN")
print("="*80)

if all_exist and all_valid:
    print("\n✅ TODAS LAS VERIFICACIONES PASARON")
    print("\n Puedes ejecutar ATLAS con:")
    print("   $ cd d:\\Tesis\\ATLAS")
    print("   $ python main.py")
else:
    print("\n⚠️  ALGUNAS VERIFICACIONES FALLARON")
    print("\n Revisa los archivos marcados con ❌")

print("\n" + "="*80)
print("\n🚀 PRÓXIMOS PASOS:")
print("   1. Ejecuta: python main.py")
print("   2. Carga un archivo DICOM/NIfTI")
print("   3. Haz clic en 'SEGMENTAR TUMOR'")
print("   4. Verifica que se muestren las vistas 2D al lado del visor 3D")
print("\n" + "="*80 + "\n")
