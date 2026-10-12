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


def _frac_caras_a_eje(verts, faces):
    tri = np.asarray(verts, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    return float((np.abs(np.abs(n).max(axis=1)) > 0.999).mean())


def _aristas_no_manifiestas(faces):
    """Número de aristas que no aparecen exactamente dos veces."""
    from collections import Counter
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    cont = Counter(map(tuple, np.sort(e, axis=1).tolist()))
    return sum(1 for n in cont.values() if n != 2)

def test_geometria_sintetica():
    """Regresiones geométricas sobre cubos, esferas y barras conocidos.

    Estas pruebas existen por un error concreto: durante mucho tiempo se
    verificó el volumen con `Trimesh.volume`, y como la malla de marching_cubes
    no es cerrada (~700 aristas no manifiestas de ~959.000) esa cifra depende de
    dónde esté la malla. El cerebro daba 1384.7 cm3 en el origen y 1299.5 cm3
    desplazado 500 mm, así que la métrica de aceptación medía el desplazamiento
    del origen, no el volumen. Aquí se comprueba que el volumen del CAMPO no
    depende de la posición, que las normales apuntan hacia fuera y que el
    suavizado no deforma las formas.
    """
    import trimesh

    import calidad_mallas as cm

    print("\n[7] Regresiones geometricas (formas sinteticas)")

    # Cubo de 20x20x20 mm en rejilla de 1.0 mm, con margen alrededor para que el
    # recorte de +1 vóxel no toque la superficie.
    lado, sp, n = 20.0, (1.0, 1.0, 1.0), 60
    r = int(round(lado / 2))
    mascara = np.zeros((n, n, n), dtype=np.uint8)
    c = n // 2
    mascara[c - r:c + r, c - r:c + r, c - r:c + r] = 1
    ref_mm3 = float(mascara.sum()) * sp[0] * sp[1] * sp[2]

    perfil = {"sigma_mm": 0.0, "taubin_iter": 0, "objetivo_mm": 1.0}
    v0, f0, vol0 = cm.malla_alta_calidad(
        mascara, sp, perfil=perfil, verbose=False, devolver_volumen=True)
    check(len(f0) > 0, "el cubo produce caras")
    check(abs(vol0 / ref_mm3 - 1.0) < 0.01,
          f"volumen del cubo sin suavizar {vol0/ref_mm3:.4f}x el exacto (tol 1 %)")

    # Traslación pura: el mismo cubo 17 vóxeles más allá en x, con sitio de
    # sobra a ambos lados para que el recorte no recorte la superficie. El
    # volumen NO puede cambiar. Con `Trimesh.volume` esto fallaba, porque el
    # volumen con signo depende del origen en una malla con aristas abiertas.
    desplazada = np.zeros_like(mascara)
    desplazada[c - r:c + r, c - r:c + r, c + 17 - r:c + 17 + r] = 1
    v1, f1, vol1 = cm.malla_alta_calidad(
        desplazada, sp, perfil=perfil, verbose=False, devolver_volumen=True)
    check(abs(vol1 - vol0) < 1e-9,
          f"el volumen no cambia al desplazar 17 vóxeles en x "
          f"({vol0:.3f} -> {vol1:.3f} mm3)")
    ancho0 = v0.max(axis=0) - v0.min(axis=0)
    ancho1 = v1.max(axis=0) - v1.min(axis=0)
    check(np.allclose(ancho0, ancho1, atol=1e-6),
          f"la traslación no deforma la malla ({ancho0.round(3)} vs "
          f"{ancho1.round(3)} mm)")

    # Normales exteriores: la normal de cada cara debe apuntar en sentido
    # contrario al centroide del cubo.
    centro = v0.mean(axis=0)
    tri = v0[f0]
    n_ = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    fuera = np.einsum("ij,ij->i", n_, tri.mean(axis=1) - centro) > 0
    check(fuera.mean() > 0.99,
          f"las normales apuntan hacia fuera ({fuera.mean()*100:.1f} % de caras)")

    m = trimesh.Trimesh(vertices=np.asarray(v0, dtype=np.float64),
                        faces=np.asarray(f0, dtype=np.int64), process=False)
    check(m.volume > 0,
          f"el volumen con signo es positivo ({m.volume:.1f} mm3): bobinado correcto")

    ejes0 = _frac_caras_a_eje(v0, f0)
    check(ejes0 > 0.8,
          f"el cubo sin suavizar tiene casi todas las caras alineadas a eje "
          f"({ejes0*100:.1f} %): el cube-test es el ground truth del escalonado")

    # Suavizado: el cubo debe seguir siendo un cubo y conservar su volumen. Un
    # cubo suavizado conserva caras planas, y eso NO es escalonado: son las
    # caras reales del cubo. Lo que se comprueba es que las aristas se redondeen
    # y que el volumen aguante. El suelo de ~25 % de caras a eje medido en la
    # esfera es un artefacto de marching_cubes, asi que la comparacion es
    # relativa y no un umbral absoluto.
    vs, fs, vols = cm.malla_alta_calidad(
        mascara, sp, perfil=dict(perfil, sigma_mm=1.0),
        verbose=False, devolver_volumen=True)
    check(abs(vols / ref_mm3 - 1.0) < 0.04,
          f"sigma 1.0 mm conserva el volumen del cubo ({vols/ref_mm3:.4f}x, "
          "tol 4 %: el redondeo de aristas recorta algo)")
    ejess = _frac_caras_a_eje(vs, fs)
    check(ejess < ejes0,
          f"sigma 1.0 mm redondea las aristas del cubo y baja las caras a eje "
          f"({ejes0*100:.1f} % -> {ejess*100:.1f} %)")
    diag = vs.max(axis=0) - vs.min(axis=0)
    check(np.all(diag > lado * 0.9) and np.all(diag < lado * 1.15),
          f"el cubo suavizado conserva las dimensiones ({diag.round(2)} mm "
          f"frente a {lado} mm)")

    # Esfera: volumen exacto 4/3 pi r^3, para comprobar que el refinamiento no
    # deforma formas suaves.
    r_mm, res = 12.0, 96
    yy, xx, zz = np.mgrid[0:res, 0:res, 0:res]
    cc = (res - 1) / 2.0
    dist = np.sqrt((xx - cc) ** 2 + (yy - cc) ** 2 + (zz - cc) ** 2)
    esfera = (dist * sp[0] <= r_mm).astype(np.uint8)
    # El volumen se mide con el conteo de vóxeles, que a 1.0 mm tiene un error
    # de discretization de ~1-2 % en una esfera; por eso la tolerancia es 4 %
    # y no 2 %.
    exacta = 4.0 / 3.0 * np.pi * r_mm ** 3
    ve, fe, vole = cm.malla_alta_calidad(
        esfera, sp, perfil=perfil, verbose=False, devolver_volumen=True)
    check(abs(vole / exacta - 1.0) < 0.04,
          f"esfera de r=12 mm: volumen {vole/exacta:.4f}x el exacto 4/3*pi*r^3")

    # Una esfera Ideal NO deberia tener casi ninguna cara pegada a un eje, pero
    # se midio un suelo estable de ~24-25 % a TODOS los espaciados (0.1 a 1.0
    # mm, work/diag_forms2.py), constante al refinar. Es un artefacto de
    # marching_cubes en la superficie de una esfera, no una property de la esfera.
    # Por eso aqui se exige solo que quede por debajo de ese suelo.
    ejese = _frac_caras_a_eje(ve, fe)
    check(ejese < 0.35,
          f"la esfera no supera el suelo de caras a eje de marching_cubes "
          f"({ejese*100:.2f} %, suelo medido ~25 %)")

    # Estructuras finas: barras de 2x2 y 4x4 mm de seccion. Aqui hay dos efectos
    # distintos y ambos son reales.
    #
    # 1) Una barra de 2x2 mm con sigma 1.0 mm hace que el campo suavizado baje
    #    de 0.5 en todas partes: la superficie de nivel deja de existir y
    #    marching_cubes lanza "Surface level must be within volume data range"
    #    (medido, work/diag_forms.py). La guarda de calidad lo evita reduciendo
    #    el sigma, y la barra se conserva integra. Perderla seria peor que
    #    dejar algo de escalonado.
    #
    # 2) Una barra de 4x4 mm con sigma 1.0 mm NO desaparece, pero se adelgaza:
    #    el nivel 0.5 cae dentro de la estructura y el volumen medido baja a
    #    0.72x. No es un fallo del pipeline, es la consecuencia de que el sigma
    #    en milimetros no tenga en cuenta el grosor de lo que suaviza. Se
    #    comprueba como comportamiento conocido y acotado.
    for ancho, s_mm, minimo in ((2, 1.0, 0.95), (2, 2.0, 0.95), (4, 1.0, 0.65)):
        h = ancho // 2
        barra = np.zeros((n, n, n), dtype=np.uint8)
        barra[c - h:c + h, c - h:c + h, c - 15:c + 15] = 1
        ref_barra = float(barra.sum())
        vb, fb, volb = cm.malla_alta_calidad(
            barra, sp, perfil=dict(perfil, sigma_mm=s_mm),
            verbose=False, devolver_volumen=True)
        check(len(fb) > 0,
              f"barra {ancho}x{ancho}x30 mm con sigma {s_mm} mm: la malla "
              f"existe ({len(fb):,} caras)")
        ratio = volb / ref_barra
        check(ratio >= minimo,
              f"barra {ancho}x{ancho}x30 mm con sigma {s_mm} mm: volumen "
              f"{ratio:.3f}x, por encima del minimo {minimo:.2f}x")

    print(f"      aristas no manifiestas del cubo: {_aristas_no_manifiestas(f0)}")


def test_volumen_estructuras_reales():
    """El volumen del campo debe conservar el volumen de la máscara real."""
    import SimpleITK as sitk

    import calidad_mallas as cm

    print("\n[8] Volumen del campo sobre la segmentacion real")
    seg = os.path.join(RAIZ, "salidas", "segmentaciones_ai", "brain.nii.gz")
    if not os.path.exists(seg):
        print("      (sin segmentacion, se omite)")
        return
    img = sitk.ReadImage(seg)
    arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
    sp = tuple(float(v) for v in img.GetSpacing())

    _, _, vol = cm.malla_alta_calidad(arr, sp, perfil=cm.perfil_de("cerebro"),
                                      verbose=False, devolver_volumen=True)
    ref = float(arr.sum()) * float(np.prod(sp))
    check(abs(vol / ref - 1.0) < 0.02,
          f"el cerebro conserva su volumen: {vol/ref:.4f}x la mascara (tol 2 %)")


if __name__ == "__main__":
    _p = main()
    run_test_render(_p)
    test_geometria_sintetica()
    test_volumen_estructuras_reales()
    print("\n" + "=" * 62)
    print("RESULTADO:", "TODO CORRECTO" if not FALLOS else f"{len(FALLOS)} FALLOS")
    for _f in FALLOS:
        print("   -", _f)
    print("=" * 62)
    sys.exit(1 if FALLOS else 0)
