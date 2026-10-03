"""Prueba headless del visor: resolución y escena multi-modelo.

Ejecuta el pipeline de render real de FBXPreviewPanel (sin ventana Tk) para
verificar que:
  1. Se descubren las mallas de salidas/mallas (craneo.stl, cerebro.stl).
  2. resolve_pbr asigna el material correcto a cada estructura.
  3. El presupuesto de caras por nivel es el esperado.
  4. La escena multi-modelo crea un actor por estructura y aplica opacidad.
  5. El render offscreen respeta la resolución de supersampling.
"""
import os
import sys
import time

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "NEUROHUB"))

import main as atlas  # noqa: E402


class _FakeLabel:
    def configure(self, **kw):
        pass


class _FakeSwatch:
    def configure(self, **kw):
        pass


def make_panel():
    """Crea un FBXPreviewPanel sin ventana real, solo con lo necesario."""
    p = atlas.FBXPreviewPanel.__new__(atlas.FBXPreviewPanel)
    p._status_cb = lambda msg, level="INFO": print(f"  [{level}] {msg}")

    p.fbx_dir = os.path.join(atlas.MODELOS_DIR, "fbx")
    p.stl_dir = atlas.MALLAS_DIR

    p._models = {}
    p._current_key = None
    p._actors = {}
    p._visible_keys = set()
    p._scene_key = None
    p._quality = "high"
    p._checkboxes = {}
    p._mesh_cache = {}

    p._ren = None
    p._ren_win = None
    p._img_tk = None
    p._img_label = None
    p._vtk_initialized = False
    p._placeholder_placed = False
    p._dragging = False

    p.key_label = _FakeLabel()
    p.swatch = _FakeSwatch()
    return p


FALLOS = []


def check(cond, msg):
    print(("  OK    " if cond else "  FALLO ") + "| " + msg)
    if not cond:
        FALLOS.append(msg)
    return bool(cond)


def main():
    panel = make_panel()

    print("\n[1] Descubrimiento de mallas")
    modelos = panel._scan_models()
    for k in sorted(modelos):
        print(f"      {k:<22} {modelos[k]['name']:<20} -> {modelos[k]['label']}")
    check("craneo" in modelos, "se encuentra craneo.stl")
    check("cerebro" in modelos, "se encuentra cerebro.stl")
    panel._models = modelos

    print("\n[2] Materiales por estructura (resolve_pbr)")
    for key in ("craneo", "cerebro", "skull", "brain"):
        meta = atlas.resolve_pbr(key)
        check(bool(meta), f"resolve_pbr({key!r}) devuelve material")
        if meta:
            print(f"      {key:<10} -> {meta['label']:<10} color={meta['display']}")

    print("\n[3] Presupuesto de caras por nivel")
    esperados = {
        ("craneo", "high"): 900000, ("cerebro", "high"): 700000,
        ("craneo", "medium"): 150000, ("cerebro", "medium"): 120000,
        ("cerebro_completo", "high"): 700000,
    }
    for (key, level), want in esperados.items():
        got = panel._quality_faces(key, level)
        check(got == want, f"{key}@{level} -> {got} caras (esperado {want})")

    print("\n[4] Resolucion real de las mallas fuente")
    import trimesh
    for key in ("craneo", "cerebro"):
        ruta = modelos[key]["stl"]
        m = trimesh.load(ruta, force="mesh")
        print(f"      {key:<10} {len(m.faces):>9,} caras  "
              f"{os.path.getsize(ruta)/1e6:>6.1f} MB  "
              f"-> presupuesto high = {panel._quality_faces(key, 'high'):,}")

    print("\n[5] Escena multi-modelo (craneo + cerebro)")
    panel._ensure_canvas()
    panel._current_key = "cerebro"
    panel._visible_keys = {"craneo", "cerebro"}

    t0 = time.monotonic()
    ordered = panel._sync_scene("high")
    print(f"      orden de dibujado: {ordered}  ({time.monotonic()-t0:.1f}s)")

    check(len(ordered) == 2, "la escena contiene 2 estructuras")
    n_actores = panel._ren.GetActors().GetNumberOfItems()
    check(n_actores == 2, f"el renderer tiene 2 actores (tiene {n_actores})")

    opac = {}
    for key in ordered:
        actor = panel._actors[key]["high"]["actor"]
        opac[key] = round(actor.GetProperty().GetOpacity(), 3)
        n = panel._actors[key]["high"]["pd"].GetNumberOfPolys()
        print(f"      {key:<10} opacidad={opac[key]:<6} celdas VTK={n:>9,}")
    check(opac.get("craneo", 1.0) < 1.0,
          "el craneo se vuelve transparente al haber cerebro dentro")
    check(opac.get("cerebro") == 1.0,
          "el cerebro queda opaco (nada visible en su interior)")
    return panel


def run_test_render(panel):
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    from PIL import Image

    print("\n[6] Render offscreen con supersampling")
    w, h = 900, 600
    panel._canvas_size = lambda: (w, h)
    factor = panel.SUPERSAMPLE_REPOSO
    rw, rh = int(w * factor), int(h * factor)
    panel._ren_win.SetSize(rw, rh)
    panel._ren.ResetCamera()
    panel._ren_win.Render()

    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(panel._ren_win)
    w2i.SetInputBufferTypeToRGBA()
    w2i.ReadFrontBufferOff()
    w2i.Update()
    dims = w2i.GetOutput().GetDimensions()
    print(f"      render interno: {dims[0]}x{dims[1]}  (lienzo {w}x{h}, factor {factor})")
    check(dims[0] == rw and dims[1] == rh, "el framebuffer respeta el supersampling")

    arr = vtk_to_numpy(w2i.GetOutput().GetPointData().GetScalars())
    arr = arr.reshape(dims[1], dims[0], -1)[:, :, :3].astype("uint8")
    img = Image.fromarray(np.ascontiguousarray(arr[::-1]))
    img = img.resize((w, h), Image.LANCZOS)

    colores = np.unique(np.asarray(img).reshape(-1, 3), axis=0)
    print(f"      colores distintos tras LANCZOS: {len(colores)}")
    check(len(colores) > 50, "el render contiene geometria visible")

    salida = os.path.join(RAIZ, "salidas", "test_render_alta_res.png")
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    img.save(salida)
    print(f"      imagen guardada: {salida}")


if __name__ == "__main__":
    _p = main()
    run_test_render(_p)
    print("\n" + "=" * 62)
    print("RESULTADO:", "TODO CORRECTO" if not FALLOS else f"{len(FALLOS)} FALLOS")
    for _f in FALLOS:
        print("   -", _f)
    print("=" * 62)
    sys.exit(1 if FALLOS else 0)
