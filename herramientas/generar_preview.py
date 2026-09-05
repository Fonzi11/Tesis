"""
NEUROHUB - Generador de Preview 3D (headless)
============================================
Renderiza las mallas STL (cerebro, cráneo, tumor, arterias, venas, vasos)
a una imagen PNG de vista previa usando matplotlib con shading por normales.

Uso:
    python herramientas/generar_preview.py [--out salidas/preview_3d.png]
"""
import os
import sys
import argparse
import numpy as np

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import trimesh

# Estructura -> color RGB (0-1)
COLORES = {
    "cerebro":   (0.65, 0.67, 0.72),   # gris cerebral
    "craneo":    (0.92, 0.88, 0.80),   # hueso
    "tumor":     (0.78, 0.15, 0.86),   # magenta
    "arterias":  (0.88, 0.12, 0.12),   # rojo
    "venas":     (0.10, 0.22, 0.78),   # azul
    "vasos":     (0.82, 0.35, 0.10),   # naranja
}
ORDEN = ["cerebro", "craneo", "tumor", "arterias", "venas", "vasos"]

LUZ = np.array([0.45, -0.35, 0.82])
LUZ = LUZ / np.linalg.norm(LUZ)


def cargar_mesh(ruta):
    m = trimesh.load(ruta)
    if isinstance(m, trimesh.Scene):
        m = m.dump(concatenate=True)
    return m


def nombre_a_color(nombre_stl):
    """Mapea nombre de archivo a color configurado."""
    base = os.path.splitext(os.path.basename(nombre_stl))[0]
    for k, c in COLORES.items():
        if k in base or base in k:
            return c
    return (0.7, 0.7, 0.7)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mallas", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "salidas", "mallas"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "salidas", "preview_3d.png"))
    ap.add_argument("--elev", type=float, default=22.0)
    ap.add_argument("--azim", type=float, default=-58.0)
    ap.add_argument("--dpi", type=int, default=240)
    args = ap.parse_args()

    mallas_dir = os.path.normpath(args.mallas)
    if not os.path.isdir(mallas_dir):
        print(f"[PREVIEW] [!] Directorio de mallas no existe: {mallas_dir}")
        sys.exit(1)

    stls = sorted(
        f for f in os.listdir(mallas_dir)
        if f.lower().endswith(".stl")
    )
    if not stls:
        print("[PREVIEW] [!] No hay archivos STL")
        sys.exit(1)

    fig = plt.figure(figsize=(13, 10))
    ax = fig.add_subplot(111, projection="3d")
    # Dibujar en el ORDEN en que se añaden las colecciones (painter's order),
    # no reordenar por profundidad: si no, mplot3d repinta el cráneo ENCIMA
    # del tumor (tiene más profundidad media) y el interior nunca se ve.
    ax.computed_zorder = False
    fig.patch.set_facecolor("#0c0c12")
    ax.set_facecolor("#0c0c12")

    # Recolecta todas las geometrías para calcular el centro de la escena
    centros = []
    meshes_cargadas = []
    for f in stls:
        try:
            m = cargar_mesh(os.path.join(mallas_dir, f))
            if m is None or len(m.vertices) == 0:
                continue
            meshes_cargadas.append((f, m))
            centros.append((m.vertices.min(axis=0) + m.vertices.max(axis=0)) / 2.0)
        except Exception as e:
            print(f"[PREVIEW] [!] No se pudo cargar {f}: {e}")

    if not meshes_cargadas:
        print("[PREVIEW] [!] No se cargó ninguna malla")
        sys.exit(1)

    centro = np.mean(centros, axis=0)
    # Tamaño de la escena para el límite de ejes
    mins = np.min([m.vertices.min(axis=0) for _, m in meshes_cargadas], axis=0)
    maxs = np.max([m.vertices.max(axis=0) for _, m in meshes_cargadas], axis=0)
    escena = (maxs - mins).max()

    # Prioridad de dibujo: estructuras sólidas primero, vasos/tumor encima
    # y con transparencia en craneo/cerebro para que el tumor (que vive DENTRO
    # del cráneo) sea visible en la preview. Sin esto, el render se ve como una
    # cabeza gris opaca sin ninguna estructura interna.
    def prioridad(nombre):
        n = nombre.lower()
        if "craneo" in n:
            return 0
        if "cerebro" in n:
            return 1
        if "tumor" in n:
            return 3
        if "vaso" in n:
            return 4
        return 2
    dibujar = sorted(meshes_cargadas, key=lambda fm: prioridad(fm[0]))

    _ALPHA = {
        "craneo": 0.06,    # cascarón casi transparente (jaula de alambre)
        "cerebro": 0.10,   # muy transparente
        "tumor": 1.0,
        "vasos": 1.0,
        "venas": 1.0,
        "arterias": 1.0,
    }

    for f, m in dibujar:
        color = nombre_a_color(f)
        verts = m.vertices
        tris = m.faces
        normales = np.cross(
            verts[tris[:, 1]] - verts[tris[:, 0]],
            verts[tris[:, 2]] - verts[tris[:, 0]],
        )
        nrm = np.linalg.norm(normales, axis=1, keepdims=True)
        normales = normales / (nrm + 1e-12)
        diff = np.clip(normales @ LUZ, 0.12, 1.15)
        # Suavizado: cuarta potencia para dar cuerpo
        diff = 0.35 + 0.85 * (diff ** 1.6)
        cara_colores = [tuple(np.clip(np.array(color) * d, 0, 1)) for d in diff]

        nombre_stl = os.path.splitext(os.path.basename(f))[0].lower()
        alpha = next((_ALPHA[k] for k in _ALPHA if k in nombre_stl), 0.9)

        if alpha < 0.5:
            # Estructura envolvente (cráneo/cerebro): caras casi invisibles +
            # aristas del color de la estructura para que el interior se vea.
            edge = tuple(np.clip(np.array(color) * 0.55, 0, 1))
            pc = Poly3DCollection(
                verts[tris], facecolors=cara_colores,
                edgecolors=edge, linewidths=0.18,
                alpha=alpha,
            )
        else:
            pc = Poly3DCollection(
                verts[tris], facecolors=cara_colores,
                edgecolors=(0.05, 0.05, 0.07), linewidths=0.12,
                alpha=alpha,
            )
        ax.add_collection3d(pc)
        print(f"[PREVIEW] [OK] {f}: {len(m.vertices):,} verts, {len(m.faces):,} faces")

    # Escena ajustada
    escena_2 = escena * 0.55
    ax.set_xlim(centro[0] - escena_2, centro[0] + escena_2)
    ax.set_ylim(centro[1] - escena_2, centro[1] + escena_2)
    ax.set_zlim(centro[2] - escena_2, centro[2] + escena_2)

    ax.view_init(elev=args.elev, azim=args.azim)
    ax.set_box_aspect((1.1, 1.1, 0.9))
    ax.axis("off")

    # Título
    ax.set_title("NEUROHUB — Segmentación Completa\n"
                 "Cerebro · Cráneo · Arterias · Venas · Vasos · Tumor",
                 fontsize=13, color="#c8c8d0", pad=8)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=args.dpi, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"\n[PREVIEW] [OK] Guardado: {args.out} ({os.path.getsize(args.out):,} bytes)")


if __name__ == "__main__":
    main()