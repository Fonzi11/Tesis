"""Aisla la causa del render en blanco del visor.

Usa EXACTAMENTE el mismo constructor de polydata y la misma carga de mallas que
FBXPreviewPanel, y luego renderiza con combinaciones de ajustes una a una:
  A  baseline (todo activado, como el visor)
  B  sin depth peeling
  C  sin MSAA
  D  sin FXAA
  E  sin depth peeling + sin MSAA
  F  sin depth peeling + sin MSAA + sin FXAA

VTK documenta que el depth peeling requiere multisampling desactivado; si A
sale vacio y B o C salen bien, ese es el conflicto.
"""
import os
import sys

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "NEUROHUB"))
import main as atlas  # noqa: E402

MALLAS = os.path.join(BASE, "salidas", "mallas")
W, H = 900, 600


def construir_actor(ren, ruta, color, opacidad, cache):
    """Carga un STL con el mismo vectorizado del visor y lo agrega al renderer."""
    import trimesh
    if ruta not in cache:
        m = trimesh.load(ruta, force="mesh")
        cache[ruta] = atlas.FBXPreviewPanel._mesh_to_polydata(
            None, m.vertices, m.faces)
    pd = cache[ruta]
    mp = vtk.vtkPolyDataMapper()
    mp.SetInputData(pd)
    mp.ScalarVisibilityOff()
    ac = vtk.vtkActor()
    ac.SetMapper(mp)
    ac.GetProperty().SetColor(*color)
    ac.GetProperty().SetOpacity(opacidad)
    ac.GetProperty().SetInterpolationToPhong()
    ac.SetVisibility(1)
    ren.AddActor(ac)
    return ac, pd


def nueva_ventana(ms, fxaa, peeling):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.047, 0.047, 0.055)
    ren.SetAmbient(0.2, 0.2, 0.22)
    for pos, inten, col in (((1, .5, 1), 1.0, (1, 1, 1)),
                            ((-.8, .3, .5), .5, (.9, .9, .95)),
                            ((0, -1, .2), .4, (.8, .85, .95))):
        l = vtk.vtkLight()
        l.SetPosition(*pos)
        l.SetIntensity(inten)
        l.SetColor(*col)
        ren.AddLight(l)
    win = vtk.vtkRenderWindow()
    win.AddRenderer(ren)
    win.SetOffScreenRendering(1)
    win.SetSize(W * 2, H * 2)
    win.SetMultiSamples(8 if ms else 0)
    if fxaa:
        ren.SetUseFXAA(1)
    if peeling:
        ren.SetUseDepthPeeling(1)
        ren.SetMaximumNumberOfPeels(8)
        ren.SetOcclusionRatio(0.1)
    return ren, win


def render(win, ren, destino):
    ren.ResetCamera()
    ren.GetActiveCamera().Zoom(1.15)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.SetInputBufferTypeToRGBA()
    w2i.ReadFrontBufferOff()
    w2i.Update()
    d = w2i.GetOutput().GetDimensions()
    a = vtk_to_numpy(w2i.GetOutput().GetPointData().GetScalars())
    a = a.reshape(d[1], d[0], -1)[:, :, :3].astype("uint8")
    img = Image.fromarray(np.ascontiguousarray(a[::-1]))
    img = img.resize((W, H), Image.LANCZOS)
    img.save(destino)
    return len(np.unique(np.asarray(img).reshape(-1, 3), axis=0)), img


def main():
    cache = {}
    craneo = os.path.join(MALLAS, "craneo.stl")
    cerebro = os.path.join(MALLAS, "cerebro.stl")
    out = os.path.join(BASE, "salidas", "diag")
    os.makedirs(out, exist_ok=True)

    casos = [
        ("A_baseline",              dict(ms=1, fxaa=1, peeling=1)),
        ("B_sin_peeling",           dict(ms=1, fxaa=1, peeling=0)),
        ("C_sin_msaa",              dict(ms=0, fxaa=1, peeling=1)),
        ("D_sin_fxaa",              dict(ms=1, fxaa=0, peeling=1)),
        ("E_sin_peeling_msaa",      dict(ms=0, fxaa=1, peeling=0)),
        ("F_sin_peeling_msaa_fxaa", dict(ms=0, fxaa=0, peeling=0)),
    ]
    print(f"{'caso':<26} {'colores':>8}  veredicto")
    print("-" * 58)
    for nombre, kw in casos:
        ren, win = nueva_ventana(**kw)
        construir_actor(ren, craneo, (0.92, 0.88, 0.80), 0.28, cache)
        construir_actor(ren, cerebro, (0.79, 0.60, 0.57), 1.0, cache)
        n, _ = render(win, ren, os.path.join(out, nombre + ".png"))
        print(f"{nombre:<26} {n:>8,}  {'OK' if n > 50 else 'VACIO'}")
        win.Finalize()
    print("-" * 58)
    print(f"imagenes en: {out}")


if __name__ == "__main__":
    main()
