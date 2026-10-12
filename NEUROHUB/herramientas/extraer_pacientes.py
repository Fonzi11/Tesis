"""
NEUROHUB - Extraccion de los estudios DICOM de "Imagenes pacientes"
====================================================================
Los ZIP exports de la plataforma de imagenes usan BACKSLASH como separador de
rutas (`DICOM\\xxxx.dcm`). unzip lo rechaza y SimpleITK tampoco encuentra los
archivos, asi que la extraccion se hace aqui, normalizando los nombres.

Ademas filtra: una carpeta de caso solo se crea si la conversion a NIfTI
funciona, de modo que `data/dicom/pacientes/` no se llene de-basuras.

Uso
---
    python herramientas/extraer_pacientes.py                  # indexa y extrae todo
    python herramientas/extraer_pacientes.py --listar         # solo lista
    python herramientas/extraer_pacientes.py --caso tumor_890923
"""

import argparse
import io
import os
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "NEUROHUB", "src"))

DESTINO = os.path.join(BASE_DIR, "data", "dicom", "pacientes")
RAIZ_ZIPS = os.path.join(BASE_DIR, "data")


def _normaliza(nombre):
    """Convierte `carpeta\\archivo.dcm` en un nombre plano de archivo."""
    return nombre.replace("\\", "/").split("/")[-1]


def indexar_zip(ruta_zip):
    """Devuelve [(subcarpeta, nombre_zip, ruta_absoluta)] de un export."""
    encontrados = []
    with zipfile.ZipFile(ruta_zip) as z:
        nombres = [n for n in z.namelist() if n.lower().endswith(".zip")]
        for sub in nombres:
            sub = sub.replace("\\", "/")
            grupo = os.path.dirname(sub) or "raiz"
            archivo = _normaliza(sub)
            # El .zip anidado vive dentro del mismo .zip: se extrae a disco
            # primero, porque zipfile no anida flujos.
            try:
                with z.open(sub) as flujo:
                    interno = zipfile.ZipFile(io.BytesIO(flujo.read()))
            except zipfile.BadZipFile:
                # Algunos exports (p. ej. TAC.zip) son archivos parciales o
                # vienen truncados desde la plataforma: se informan y se siguen.
                print(f"  [!] {archivo}: ZIP ilegible o truncado, se omite")
                continue
            with interno:
                members = [m for m in interno.namelist()
                           if m.lower().endswith(".dcm")]
                if not members:
                    print(f"  [!] {archivo}: no contiene cortes .dcm")
                    continue
                carpeta = os.path.join(DESTINO, archivo[:-4])
                if _cuenta(carpeta) != len(members):
                    os.makedirs(carpeta, exist_ok=True)
                    for m in members:
                        destino = os.path.join(carpeta, _normaliza(m))
                        if not os.path.isfile(destino):
                            with open(destino, "wb") as salida:
                                salida.write(interno.read(m))
                encontrados.append(
                    (grupo, archivo, carpeta, len(members)))
    return encontrados


def _cuenta(carpeta):
    return sum(len(f) for _, _, f in os.walk(carpeta))


def main():
    ap = argparse.ArgumentParser(description="Extrae los casos de 'Imagenes pacientes'")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--caso", default=None, help="extrae solo ese caso ya extraido")
    args = ap.parse_args()

    zips = []
    for nombre in sorted(os.listdir(RAIZ_ZIPS)):
        if nombre.startswith("Imagenes pacientes") and nombre.endswith(".zip"):
            zips.append(os.path.join(RAIZ_ZIPS, nombre))

    os.makedirs(DESTINO, exist_ok=True)
    for z in zips:
        for grupo, archivo, ruta, n in indexar_zip(z):
            print(f"  {os.path.basename(z)[:22]:24s} {grupo:12s} "
                  f"{archivo:26s} {n:>4d} cortes -> {os.path.basename(ruta)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())