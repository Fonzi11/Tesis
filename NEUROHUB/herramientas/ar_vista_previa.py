"""Renderiza una lámina de control (4 vistas) de un caso de modelos AR."""
import json
import os
import sys

import pyvista as pv

VISTAS = (
    ("Anterior", (0, -1, 0), (0, 0, 1)),
    ("Lateral izquierda", (1, 0, 0), (0, 0, 1)),
    ("Superior", (0, 0, 1), (0, -1, 0)),
    ("Oblicua", (0.8, -0.9, 0.6), (0, 0, 1)),
)


def renderizar(carpeta, salida=None):
    with open(os.path.join(carpeta, "resumen.json"), encoding="utf-8") as fh:
        info = json.load(fh)
    pv.global_theme.background = "#101418"
    pl = pv.Plotter(shape=(2, 2), off_screen=True, window_size=(1800, 1500))
    for i, (titulo, direccion, arriba) in enumerate(VISTAS):
        pl.subplot(i // 2, i % 2)
        for e in info["estructuras"]:
            malla = pv.read(os.path.join(carpeta, e["stl"]))
            pl.add_mesh(malla, color=e["color"], opacity=e["opacidad"],
                        smooth_shading=True, specular=0.3)
        # Las STL están en LPS; la cámara se define en LPS (+X izq., +Y post.).
        pl.view_vector(direccion, viewup=arriba)
        pl.reset_camera()
        pl.camera.zoom(1.25)
        pl.add_text(titulo, font_size=12, color="white")
        # Sin depth peeling: con el controlador AMD en modo off-screen deja
        # la imagen en blanco.
    pl.subplot(0, 0)
    pl.add_text("\n\n%s" % info["caso"], font_size=10, color="#bbbbbb")
    salida = salida or os.path.join(carpeta, "%s_vista_previa.png" % info["caso"])
    pl.screenshot(salida)
    pl.close()
    return salida


if __name__ == "__main__":
    print(renderizar(sys.argv[1]))
