"""
NEUROHUB - Lanzador
===================
Verifica dependencias y lanza la aplicación.
"""
import os
import sys
import subprocess


def check_and_install():
    required = {
        "customtkinter": "customtkinter",
        "pygame": "pygame",
        "SimpleITK": "SimpleITK",
        "nibabel": "nibabel",
        "numpy": "numpy",
        "scipy": "scipy",
        "skimage": "scikit-image",
        "trimesh": "trimesh",
        "PIL": "pillow",
    }
    missing = []
    for pkg, pip_name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print("Faltan dependencias. Instalando...")
        for p in missing:
            print(f"  -> {p}")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", p])
            except subprocess.CalledProcessError:
                print(f"  !! No se pudo instalar {p}")
                return False
    return True


def main():
    print("=" * 50)
    print("  NEUROHUB - Neuroimágenes Multiplataforma")
    print("=" * 50)

    if not check_and_install():
        print("Algunas dependencias no se instalaron.")
        print("Instale manualmente con: pip install -r requirements.txt")

    # Lanzar la app
    main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    sys.path.insert(0, os.path.dirname(main_path))
    os.chdir(os.path.dirname(main_path))

    try:
        import main
        app = main.App()
        app.run()
    except Exception as e:
        print(f"Error lanzando NEUROHUB: {e}")
        import traceback
        traceback.print_exc()
        input("\nPresione Enter para salir...")


if __name__ == "__main__":
    main()