"""
=====================================================================
 PROYECTO ATLAS - Script de Build para Ejecutable
=====================================================================
"""

import os
import sys
import subprocess

def main():
    """Genera el ejecutable único."""
    print("=" * 60)
    print("  PROYECTO ATLAS - Generando Ejecutable")
    print("=" * 60)

    # Verificar que PyInstaller esté instalado
    try:
        import PyInstaller
        print("✓ PyInstaller instalado")
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller instalado")

    # Directorio base
    base_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(base_dir, "main.py")

    # Comando de PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "ATLAS",
        "--icon", os.path.join(base_dir, "assets", "icon.ico") if os.path.exists(os.path.join(base_dir, "assets", "icon.ico")) else None,
        "--add-data", f"{os.path.join(base_dir, 'src')};src",
        "--hidden-import", "customtkinter",
        "--hidden-import", "SimpleITK",
        "--hidden-import", "numpy",
        "--hidden-import", "trimesh",
        "--hidden-import", "scipy",
        "--hidden-import", "skimage",
        "--hidden-import", "torch",
        "--hidden-import", "monai",
        "--hidden-import", "nibabel",
        "--hidden-import", "pyvista",
        "--hidden-import", "fast_simplification",
        "--hidden-import", "totalsegmentator",
        main_script,
    ]

    # Filtrar argumentos None
    cmd = [c for c in cmd if c is not None]

    print(f"\nEjecutando: {' '.join(cmd)}")
    print("Esto puede tomar varios minutos...\n")

    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        exe_path = os.path.join(base_dir, "dist", "ATLAS.exe")
        print(f"\n{'=' * 60}")
        print(f"✓ Ejecutable generado: {exe_path}")
        print(f"{'=' * 60}")
    else:
        print(f"\n✗ Error generando el ejecutable (código {result.returncode})")
        sys.exit(1)

if __name__ == "__main__":
    main()