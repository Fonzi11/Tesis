"""
Comprueba que el visor 2D encuentra la IMAGEN del paciente, no una etiqueta.

Regresion sobre un fallo real: `salidas/segmentaciones_ai` solo contiene
etiquetas (una por estructura). `vertebrae_T2.nii.gz` cumple el patron BraTS
`*_t2.nii.gz`, asi que se elegia como fondo del visor 2D y el panel se llenaba
con una mascara de vertebra en gris: "no se ven las imagenes".

    python tests/test_volumen_real.py
"""
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BASE)
sys.path.insert(0, BASE)

from src.ui_qt import mesh_store as ms  # noqa: E402

ETIQUETAS = ("vertebrae_T2.nii.gz", "tumor_brats.nii.gz", "brain.nii.gz")
IMAGEN = os.path.join(REPO, "data", "nifti", "braTS_sample",
                      "BraTS2021_00000", "BraTS2021_00000_t1ce.nii.gz")
IMAGEN_SEG = os.path.join(REPO, "data", "nifti", "braTS_sample",
                          "BraTS2021_00000", "BraTS2021_00000_seg.nii.gz")
ORIGEN_ETIQUETAS = os.path.join(REPO, "salidas", "segmentaciones_ai")


def _preparar():
    tmp = tempfile.mkdtemp()
    salidas = os.path.join(tmp, "salidas")
    seg = os.path.join(salidas, "segmentaciones_ai")
    os.makedirs(seg)
    for n in ETIQUETAS:
        origen = os.path.join(ORIGEN_ETIQUETAS, n)
        if os.path.isfile(origen):
            shutil.copy2(origen, os.path.join(seg, n))
    return tmp, salidas


def main():
    fallos = []

    def check(nombre, condicion):
        print(f"{'OK   ' if condicion else 'FALLO'} {nombre}")
        if not condicion:
            fallos.append(nombre)

    check("la imagen de prueba existe", os.path.isfile(IMAGEN))
    check("las etiquetas de prueba existen",
          all(os.path.isfile(os.path.join(ORIGEN_ETIQUETAS, n))
              for n in ETIQUETAS))

    tmp, salidas = _preparar()
    try:
        # 1. Sin imagen del paciente no se inventa ninguna.
        v = ms.buscar_volumen(salidas)
        check("sin volumen real no se elige una etiqueta", v is None)

        # 2. Una etiqueta no pasa el filtro por contenido.
        etiqueta = os.path.join(salidas, "segmentaciones_ai", "vertebrae_T2.nii.gz")
        check("vertebrae_T2 no se toma como imagen",
              not ms._parece_imagen(etiqueta))
        tumor = os.path.join(salidas, "segmentaciones_ai", "tumor_brats.nii.gz")
        check("tumor_brats no se toma como imagen", not ms._parece_imagen(tumor))

        # 3. Con la copia del volumen, se elige ESA y no una etiqueta.
        shutil.copy2(IMAGEN, os.path.join(salidas, "volumen_paciente.nii.gz"))
        v = ms.buscar_volumen(salidas)
        check("se elige la imagen del paciente",
              v is not None and os.path.basename(v) == "volumen_paciente.nii.gz")
        check("la imagen elegida es una imagen de verdad",
              v is not None and ms._parece_imagen(v))

        # 4. La mascara tumor encaja con ese volumen (modo pincel activo).
        #    La de `salidas` es de otro caso y no comparte rejilla, asi que no
        #    puede servir: se usa la segmentacion BraTS del MISMO caso que la
        #    imagen, que es lo que haria el pipeline recien ejecutado.
        seg = os.path.join(salidas, "segmentaciones_ai")
        shutil.copy2(IMAGEN_SEG, os.path.join(seg, "tumor_brats.nii.gz"))
        cands = ms.listar_mascaras_tumor(salidas)
        m = ms.buscar_mascara_compatible(cands, v) if v else None
        check("hay una mascara tumor compatible con el volumen",
              m is not None and os.path.basename(m) == "tumor_brats.nii.gz")

        # 5. Una mascara de OTRO caso no se cuela como mascara activa, pero
        #    tampoco rompe la carga: el visor sigue con la imagen sin tumor.
        check("una mascara incompatible se descarta sin error",
              all(not os.path.basename(r).startswith("vertebrae")
                  for r in cands))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(fallos)} fallo(s)")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())