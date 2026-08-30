"""
=====================================================================
 PROYECTO ATLAS - Lanzador
=====================================================================
"""

import os
import sys
import subprocess
import importlib.util

def check_dependencies():
    """Verifica que las dependencias necesarias estén instaladas."""
    required = {
        "customtkinter": "customtkinter",
        "SimpleITK": "SimpleITK",
        "numpy": "numpy",
        "trimesh": "trimesh",
        "scipy": "scipy",
        "skimage": "skimage",
        "torch": "torch",
        "monai": "monai",
        "nibabel": "nibabel",
        "pyvista": "pyvista",
        "fast_simplification": "fast_simplification",
        "totalsegmentator": "totalsegmentator",
    }

    missing = []
    for module_name, package_name in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)

    return missing

def install_dependencies(missing):
    """Instala las dependencias faltantes."""
    print("=" * 60)
    print("INSTALANDO DEPENDENCIAS FALTANTES")
    print("=" * 60)
    for pkg in missing:
        print(f"Instalando {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    print("Dependencias instaladas correctamente.")

def main():
    """Punto de entrada principal."""
    print("=" * 60)
    print("  PROYECTO ATLAS - Lanzador")
    print("=" * 60)

    # Verificar dependencias
    missing = check_dependencies()
    if missing:
        print(f"\nFaltan {len(missing)} dependencias: {', '.join(missing)}")
        response = input("¿Desea instalarlas ahora? (s/n): ").strip().lower()
        if response in ('s', 'si', 'sí', 'y', 'yes'):
            install_dependencies(missing)
        else:
            print("No se pueden continuar sin las dependencias necesarias.")
            input("Presione Enter para salir...")
            sys.exit(1)

    # Ejecutar la aplicación
    main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Importar y ejecutar la aplicación
    import main
    main.main()

if __name__ == "__main__":
    main()