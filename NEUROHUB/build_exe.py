"""
NEUROHUB - Script de Build
==========================
Genera un ejecutable con PyInstaller.
"""
import os
import sys
import subprocess

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(base, "main.py")
    icon = os.path.join(base, "assets", "icon.ico") if os.path.exists(
        os.path.join(base, "assets", "icon.ico")) else None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "NEUROHUB",
        "--add-data", f"{os.path.join(base, 'src')};src",
        "--hidden-import", "customtkinter",
        "--hidden-import", "SimpleITK",
        "--hidden-import", "numpy",
        "--hidden-import", "pygame",
        "--hidden-import", "nibabel",
        "--hidden-import", "scipy",
        "--hidden-import", "skimage",
        "--hidden-import", "trimesh",
        "--hidden-import", "PIL",
        main_script,
    ]
    if icon:
        cmd.insert(6, f"--icon={icon}")

    print("NEUROHUB - Generando ejecutable...")
    print(f"  {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=base)
    if result.returncode == 0:
        exe = os.path.join(base, "dist", "NEUROHUB.exe")
        try:
            print(f"\n[OK] Ejecutable generado: {exe}")
        except UnicodeEncodeError:
            print("\n[OK] Ejecutable generado (UTF-8 no soportado en esta consola)")
    else:
        try:
            print(f"\n[ERROR] Error (código {result.returncode})")
        except UnicodeEncodeError:
            print(f"\n[ERROR] Error (código {result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    main()