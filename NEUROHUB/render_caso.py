"""
NEUROHUB - Render headless de un caso
===================================
Genera vistas PNG de las mallas STL usando exactamente los ajustes que ya
valida el visor, para que la consola y la aplicacion muestren lo mismo.

Ajustes, y por que cada uno
---------------------------
  - MSAA 8x: antialiasing por multisample. Sin el, los bordes de la malla
    salen escalonados.
  - Depth peeling (8 peels): necesario para ordenar correctamente el craneo
    transparente sobre el cerebro. Sin el, las superficies transparentes se
    resuelven en el orden de dibujo y el resultado es incorrecto.
  - FXAA DESACTIVADO: combinado con depth peeling produce frames en blanco.
    Se documenta en tests/diag_render.py, que aisla exactamente esa combinacion.
  - Supersampling 2x + reduccion LANCZOS: renderiza al doble y reduce, lo que
    elimina el aliasing residual que deja el MSAA.
  - vtkLightKit con key light rasante y lateral: dibuja el relieve. Sin luz
    rasante una superficie suave se ve plana y no se aprecia el detalle fino.

Por que las luces NO se colocan en coordenadas absolutas
-------------------------------------------------------
Las mallas viven en el espacio de indices del NIfTI (centradas cerca de
(-120, -120, -80) mm), asi que unas luces fijas como (1, 0.5, 1) caen
practicamente DENTRO de la cabeza y el sombreado depende de donde acabe la
camara, no de la anatomia. vtkLightKit construye el esquema relativo a la
camara, que es lo correcto.
"""

import os
import sys

import numpy as np
import trimesh
import vtk
from PIL import Image
from vtk.util.numpy_support import vtk_to_numpy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# (clave, color RGB, opacidad). Mismos criterios de color que el visor.
ESCENAS = [
    ("completo", [("cerebro", (0.83, 0.67, 0.62), 1.0),
                  ("craneo", (0.91, 0.88, 0.83), 0.30),
                  ("tumor", (0.75, 0.15, 0.43), 1.0),
                  ("arterias", (0.95, 0.18, 0.12), 1.0),
                  ("venas", (0.18, 0.42, 0.95), 1.0),
                  ("aneurisma", (1.0, 0.55, 0.05), 1.0)]),
    ("cerebro", [("cerebro", (0.83, 0.67, 0.62), 1.0)]),
    ("craneo", [("craneo", (0.91, 0.88, 0.83), 1.0)]),
    ("tumor", [("tumor", (0.75, 0.15, 0.43), 1.0)]),
]

VISTAS_COMPLETO = [(0, 0), (35, 12), (-50, 20), (80, -10)]
ANCHO, ALTO = 1000, 720


def _polydata(stl, cache):
    """Carga el STL con el mismo vectorizado que usa el visor."""
    if stl not in cache:
        import main as app
        m = trimesh.load(stl, force="mesh")
        cache[stl] = app.FBXPreviewPanel._mesh_to_polydata(
            None, m.vertices, m.faces)
    return cache[stl]


def _luces(ren):
    """Esquema de luz relativo a la camara, con key rasante y lateral."""
    # Solo se expone SetKeyLightIntensity; las demas intensidades se controlan
    # por sus ratios con la key.
    kit = vtk.vtkLightKit()
    kit.SetKeyLightIntensity(1.15)
    kit.SetKeyLightWarmth(0.55)
    kit.SetKeyToFillRatio(2.6)
    kit.SetKeyToHeadRatio(2.2)
    kit.SetKeyToBackRatio(3.2)
    kit.SetFillLightWarmth(0.35)
    kit.SetBackLightWarmth(0.45)
    kit.SetHeadLightWarmth(0.2)
    # La rasante se consigue con elevacion y azimut: SetKeyLightAngle toma un
    # vtkLight en esta sobrecarga, no un float.
    kit.SetKeyLightElevation(42.0)
    kit.SetKeyLightAzimuth(35.0)
    kit.AddLightsToRenderer(ren)


def _render_uno(capas, mallas_dir, destino, cache, azimut, elevacion):
    """Renderiza una escena y escribe el PNG."""
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.055, 0.06, 0.075)
    ren.SetAmbient(0.25, 0.25, 0.27)
    _luces(ren)

    for clave, color, opacidad in capas:
        stl = os.path.join(mallas_dir, f"{clave}.stl")
        if not os.path.isfile(stl):
            continue
        mp = vtk.vtkPolyDataMapper()
        mp.SetInputData(_polydata(stl, cache))
        mp.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mp)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(opacidad)
        prop.SetInterpolationToPhong()
        prop.SetSpecular(0.35)
        prop.SetSpecularPower(28)
        prop.SetAmbient(0.18)
        prop.SetDiffuse(0.82)
        ren.AddActor(actor)

    win = vtk.vtkRenderWindow()
    win.AddRenderer(ren)
    win.SetOffScreenRendering(1)
    win.SetSize(ANCHO * 2, ALTO * 2)      # supersampling
    win.SetMultiSamples(8)                 # MSAA 8x
    ren.SetUseDepthPeeling(1)              # orden de transparencias
    ren.SetMaximumNumberOfPeels(8)
    ren.SetOcclusionRatio(0.1)
    # FXAA se deja desactivado a proposito (ver docstring del modulo).

    # Se rota la camara y DESPUES se reencuadra: fijar la posicion a mano
    # sobreescribiria la rotacion y todas las vistas saldrian iguales.
    ren.ResetCamera()
    win.Render()
    cam = ren.GetActiveCamera()
    cam.Azimuth(azimut)
    cam.Elevation(elevacion)
    cam.OrthogonalizeViewUp()
    ren.ResetCamera()
    win.Render()
    cam.Zoom(1.5)                         # ResetCamera deja margen de sobra
    ren.ResetCameraClippingRange()
    win.Render()

    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.SetInputBufferTypeToRGBA()
    w2i.ReadFrontBufferOff()
    w2i.Update()
    dims = w2i.GetOutput().GetDimensions()
    arr = vtk_to_numpy(w2i.GetOutput().GetPointData().GetScalars())
    arr = arr.reshape(dims[1], dims[0], -1)[:, :, :3].astype("uint8")
    img = Image.fromarray(np.ascontiguousarray(arr[::-1]))
    img = img.resize((ANCHO, ALTO), Image.LANCZOS)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino)
    colores = len(np.unique(np.asarray(img).reshape(-1, 3), axis=0))
    win.Finalize()
    return colores


def generar(mallas_dir, renders_dir):
    """Genera todas las vistas de un caso y devuelve la lista de PNG."""
    os.makedirs(renders_dir, exist_ok=True)
    cache, escritos = {}, []
    for nombre, capas in ESCENAS:
        if not any(os.path.isfile(os.path.join(mallas_dir, f"{c}.stl"))
                   for c, _, _ in capas):
            continue
        vistas = VISTAS_COMPLETO if nombre == "completo" else [(0, 0)]
        for i, (az, el) in enumerate(vistas):
            sufijo = "" if len(vistas) == 1 else f"_{i + 1}"
            destino = os.path.join(renders_dir, f"{nombre}{sufijo}.png")
            colores = _render_uno(capas, mallas_dir, destino, cache, az, el)
            if colores <= 1:
                # Un frame monocromo es un frame vacio: no se da por bueno.
                print(f"   [X] {os.path.basename(destino)}: frame vacio, se descarta")
                os.remove(destino)
                continue
            escritos.append(destino)
            print(f"   [OK] {os.path.basename(destino)}  "
                  f"({colores:,} colores unicos)")
    return escritos


if __name__ == "__main__":
    RAIZ = os.path.dirname(BASE_DIR)
    mallas = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "salidas", "mallas")
    salida = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RAIZ, "salidas", "renders")
    generar(mallas, salida)
