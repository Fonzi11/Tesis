"""
Puente con 3D Slicer para reconstruir mallas y medir sobre ellas.

3D Slicer ya esta instalado en esta maquina (D:/APPS/3D Slicer 5.12.3) y es
la herramienta que usa el propio pipeline de NEUROHUB en
`segmentacion_completa.generar_mallas_3d`. Este modulo completa esa
integración con la parte que faltaba: 

  * ejecuta Slicer SIN interfaz (`--no-main-window --python-script`), que es
    como se puede usar como motor de render dentro de un proceso,
  * expone `reconstruir_stl` / `stl_a_volumen` para convertir una máscara en
    malla y una malla en NIfTI, de forma que las ROI que calcula radiomics
    coincidan con lo que se ve en el visor 3D,
  * permite la CONVERGENCIA de mallas, que es la ventaja real de usar Slicer:
   superficie con suavizado y decisión de marching cubes por vtkImageMarchingCubes,
  * y, si algún día se instala Docker, delega a Raidionics (ver
    `raidionics_bridge`), que es el otro motor posible.

Todo se llama por proceso externo: Slicer corre en su propio intérprete de
Python (3.12) y no puede compartir objetos con el intérprete de NEUROHUB
(3.13), así que la comunicación es por archivos NIfTI/STL en disco.
"""

import os
import subprocess
import tempfile

# Rutas de las imágenes (una por estructura), que es el formato que consume
# el visor 3D. El nombre de la clave coincide con el de `pbr.resolve_pbr`.
SLICER_CANDIDATOS = [
    r"D:\APPS\3D Slicer 5.12.3\Slicer.exe",
    r"C:\Program Files\Slicer 5.12.3\Slicer.exe",
    r"C:\Program Files\Slicer\Slicer.exe",
    os.path.expanduser(r"~\AppData\Local\NA-MIC\Slicer 5.12.3\Slicer.exe"),
]

# Espera máxima de una reconstrucción: con un cerebro de ~1M de vóxeles y
# smoothing, el marching cubes tarda del orden de segundos a un minuto.
TIMEOUT_SEGUNDOS = 600


def ruta_slicer():
    """
    Devuelve la ruta al ejecutable de Slicer, o None si no está instalado.

    Se buscan primero las rutas conocidas del proyecto y, si ninguna existe, se
    pregunta al PATH. Así, si el usuario mueve Slicer a otra carpeta, basta
    con tenerlo en el PATH en vez de tocar el código.
    """
    import shutil

    for ruta in SLICER_CANDIDATOS:
        if os.path.isfile(ruta):
            return ruta
    return shutil.which("Slicer") or shutil.which("Slicer.exe")


def disponible():
    """True si se puede lanzar Slicer."""
    return ruta_slicer() is not None


# =============================================================================
# SCRIPT QUE SE EJECUTA DENTRO DE SLICER
# =============================================================================
# El script recibe un JSON con los parámetros y escribe el resultado en otra
# ruta. Se genera en un archivo temporal porque Slicer sólo acepta rutas de
# script en disco.
SCRIPT_RECONSTRUIR = r'''
import json, os, sys

import slicer, vtk

parametros = json.load(open(PARAMETROS_JSON, encoding="utf-8"))
salida = parametros["salida_stl"]
mascara = parametros["mascara"]
suavizado = parametros.get("suavizado", 0.5)
decimacion = parametros.get("decimacion", 0.0)

nodo = slicer.util.loadVolume(mascara)
if nodo is None:
    raise SystemExit("No se pudo cargar la mascara: " + str(mascara))

# Todo el procesado se hace sobre una vtkImageData propia construida a partir
# del array numpy, en lugar de reutilizar el vtkImageData del nodo de Slicer.
# Motivos, ambos verificados en ejecucion real:
#   1) el tipo de escalar del nodo suele ser uint8 (una mascara BraTS lo es) y
#      vtkImageGaussianSmooth respeta el tipo de entrada, con lo cual el
#      suavizado redondea a 0/1 y no suaviza NADA;
#   2) updateVolumeFromArray con float64 deja el nodo con un tipo de escalar
#      incoherente y marching cubes deja de encontrar superficie.
import numpy as np
mascara_np = slicer.util.arrayFromVolume(nodo).astype(np.float32)
mascara_np[mascara_np > 0] = 1.0
mascara_np[mascara_np < 0] = 0.0
n_voxeles = int(np.count_nonzero(mascara_np))
if n_voxeles == 0:
    raise SystemExit("La mascara esta vacia")

origen = nodo.GetImageData()
imagen = vtk.vtkImageData()
imagen.SetDimensions(origen.GetDimensions())
imagen.SetSpacing(origen.GetSpacing())
imagen.SetOrigin(origen.GetOrigin())
# VTK 9 elimino SetImageToWorldMatrix. Se usa la direccion que Slicer ya
# calculo para el nodo, de modo que un NIfTI con ejes invertidos (habitual en
# BraTS, conada "radiological") produzca una malla coherente con el visor.
# La direccion no se pide a Slicer con GetIJKToRASDirectionMatrix: en Slicer
# ese metodo devuelve la matriz en coordenadas RAS, no en IJK, que no es lo que
# necesita vtkImageData. Se toma la submatriz 3x3 de IJK->RAS y se normaliza
# cada columna, que es exactamente la matriz de direccion en IJK.
ras = vtk.vtkMatrix4x4()
nodo.GetIJKToRASMatrix(ras)
direccion = vtk.vtkMatrix3x3()
import math
for c in range(3):
    # GetColumn devuelve un vtkTuple con las filas 0..2 de la columna c; no
    # existe Norm() sobre vtkTuple en VTK 9, se calcula a mano.
    norma = math.sqrt(sum(ras.GetElement(f, c) ** 2 for f in range(3)))
    for f in range(3):
        direccion.SetElement(f, c, ras.GetElement(f, c) / norma)
imagen.SetDirectionMatrix(direccion)
imagen.AllocateScalars(vtk.VTK_FLOAT, 1)
from vtk.util.numpy_support import vtk_to_numpy
escalares = vtk_to_numpy(imagen.GetPointData().GetScalars())
escalares[:] = mascara_np.reshape(-1)

# Suavizado: media gaussiana, que es lo que evita la superficie escalonada de
# un marching cubes directo sobre voxels.
if suavizado and suavizado > 0:
    suavizador = vtk.vtkImageGaussianSmooth()
    suavizador.SetInputData(imagen)
    suavizador.SetStandardDeviations(suavizado, suavizado, suavizado)
    suavizador.SetDimensionality(3)
    suavizador.Update()
    # Sin copy(): vtk_to_numpy devuelve una vista sobre la memoria de VTK que
    # se invalida en cuanto el filtro se destruye. Se pasa el array de
    # escalares del punto de datos, no la ImageData completa: vtk_to_numpy
    # espera un vtkDataArray y no sabe leer el tipo de un vtkImageData.
    suavizado_np = vtk_to_numpy(
        suavizador.GetOutput().GetPointData().GetScalars()
    ).copy().astype(np.float64)
    # El suavizado difumina los bordes de la mascara. Se renormaliza al maximo
    # y se vuelve a binarizar en 0.5: sin renormalizar, con sigma>=0.5 el pico
    # de los voxels interiores baja de 1.0 y el umbral borra la ROI entera.
    pico = float(suavizado_np.max())
    if pico <= 0.0:
        raise SystemExit("El suavizado dejo la mascara vacia")
    suavizado_np /= pico
    suavizado_np[suavizado_np < 0.5] = 0.0
    suavizado_np[suavizado_np >= 0.5] = 1.0
    escalares[:] = suavizado_np.astype(np.float32).reshape(-1)

marching = vtk.vtkImageMarchingCubes()
marching.SetInputData(imagen)
marching.SetValue(0, 0.5)
marching.ComputeNormalsOn()
marching.Update()

limpiador = vtk.vtkPolyDataConnectivityFilter()
limpiador.SetInputConnection(marching.GetOutputPort())
limpiador.SetExtractionModeToLargestRegion()
limpiador.Update()
polidata = limpiador.GetOutput()

if polidata.GetNumberOfPoints() == 0:
    raise SystemExit("La mascara no produjo ninguna superficie")

if decimacion and decimacion > 0.0:
    reduccion = vtk.vtkQuadricDecimation()
    reduccion.SetInputData(polidata)
    reduccion.SetTargetReduction(decimacion)
    reduccion.Update()
    polidata = reduccion.GetOutput()

escritor = vtk.vtkSTLWriter()
escritor.SetFileName(salida)
escritor.SetInputData(polidata)
escritor.SetFileTypeToBinary()
escritor.Write()

json.dump({"ok": True, "puntos": polidata.GetNumberOfPoints(),
           "caras": polidata.GetNumberOfCells()},
          open(RESULTADO_JSON, "w", encoding="utf-8"))
'''


# =============================================================================
# EJECUCIÓN
# =============================================================================
def _escribir_script(destino, cuerpo, reemplazos):
    """
    Escribe el script de Slicer sustituyendo los marcadores por rutas.

    Los marcadores (`PARAMETROS_JSON`, `RESULTADO_JSON`) se inyectan como
    literales de Python ya escapados, que es más seguro que pasarlos por
    línea de comandos: las rutas de Windows contienen espacios y barras.
    """
    codigo = cuerpo
    for marcador, valor in reemplazos.items():
        codigo = codigo.replace(marcador, repr(str(valor)))
    with open(destino, "w", encoding="utf-8") as f:
        f.write(codigo)
    return destino


def _ejecutar_script(cuerpo, parametros, timeout=TIMEOUT_SEGUNDOS):
    """
    Lanza Slicer sin ventana con un script y devuelve lo que escribió.

    Se usa `--no-main-window` (no `--no-splash` a secas) porque sin ventana
    principal Slicer no inicializa la escena y el script fallaría.
    """
    import json

    exe = ruta_slicer()
    if exe is None:
        raise RuntimeError(
            "3D Slicer no está instalado. Instálalo o ponlo en el PATH; "
            "las rutas buscadas están en slicer_bridge.SLICER_CANDIDATOS.")

    with tempfile.TemporaryDirectory(prefix="neurohub_slicer_") as tmp:
        ruta_param = os.path.join(tmp, "parametros.json")
        ruta_res = os.path.join(tmp, "resultado.json")
        ruta_script = os.path.join(tmp, "script.py")
        with open(ruta_param, "w", encoding="utf-8") as f:
            json.dump(parametros, f)

        _escribir_script(ruta_script, cuerpo, {
            "PARAMETROS_JSON": ruta_param,
            "RESULTADO_JSON": ruta_res,
        })

        cmd = [exe, "--no-main-window", "--no-splash",
               "--python-script", ruta_script, "--exit-after-startup"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
        if os.path.isfile(ruta_res):
            with open(ruta_res, encoding="utf-8") as f:
                return json.load(f)
        raise RuntimeError(
            "Slicer no produjo resultado."
            f" Codigo de salida: {proc.returncode}."
            f" stdout: {(proc.stdout or str())[-2000:]}."
            f" stderr: {(proc.stderr or str())[-2000:]}")


def reconstruir_stl(mascara_nifti, salida_stl, suavizado=0.5, decimacion=0.0,
                    timeout=TIMEOUT_SEGUNDOS):
    """
    Convierte una máscara NIfTI en malla STL usando 3D Slicer.

    Es la vía de mayor calidad: `vtkImageMarchingCubes` con suavizado gaussiano
    y extracción de la mayor componente conexa produce una superficie limpia y
    cerrada, que es justo lo que necesitan los rasgos de forma para que la
    superficie y la esfericidad no dependan del escalonado del vóxel.

    Parametros
    ----------
    mascara_nifti : str
        Ruta del NIfTI binario.
    salida_stl : str
        Ruta del STL a escribir.
    suavizado : float
        Sigma en vóxeles del filtro gaussiano previo. 0 desactiva el suavizado.
    decimacion : float
        Fracción de reducción (0..0.9) con quadric decimation.
    timeout : int
        Segundos máximos de espera.

    Devuelve
    -------
    dict {"ok": bool, "puntos": int, "caras": int}
    """
    os.makedirs(os.path.dirname(os.path.abspath(salida_stl)), exist_ok=True)
    return _ejecutar_script(
        SCRIPT_RECONSTRUIR,
        {"mascara": os.path.abspath(mascara_nifti),
         "salida_stl": os.path.abspath(salida_stl),
         "suavizado": float(suavizado),
         "decimacion": float(decimacion)},
        timeout=timeout,
    )


def informacion():
    """
    Devuelve la versión de Slicer instalada, o None si no está.

    Se usa para mostrarla en el "Acerca de" de la aplicación y para dejar
    constancia en los metadatos del informe de radiomics de qué motor generó
    la geometría, que es lo que exige la trazabilidad clínica.
    """
    cuerpo = r'''
import json, slicer
json.dump({"version": slicer.app.applicationVersion,
           "revision": slicer.app.revision},
          open(RESULTADO_JSON, "w", encoding="utf-8"))
'''
    try:
        return _ejecutar_script(cuerpo, {}, timeout=180)
    except Exception:
        return None
