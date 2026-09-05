"""
NEUROHUB - Modelo ÚNICO combinado (1 solo archivo FBX) vía API de Blender
=========================================================================
Une las 6 mallas STL (cerebro, cráneo, tumor, arterias, venas, vasos) en
UN SOLO objeto y exporta UN SOLO archivo FBX con los colores de cada
estructura (materiales por cara) listo para Unity / Blender / web.

Uso:
    python herramientas/modelo_unico.py            # usa bpy del entorno
    blender --background --python herramientas/modelo_unico.py   # Blender externo

Salida:
    salidas/fbx/neurohub_completo.fbx        (objeto único 'NEUROHUB')
"""
import os
import sys

try:
    import bpy  # noqa
except ImportError:
    sys.exit("[MODELO] bpy no disponible. Usa: blender --background --python "
             "herramientas/modelo_unico.py  (Blender debe estar instalado)")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STL_DIR = os.path.join(BASE_DIR, "salidas", "mallas")
OUT_FBX = os.path.join(BASE_DIR, "salidas", "fbx", "neurohub_completo.fbx")

# Color (R,G,B) 0..1 por estructura (igual que en el visor y la preview)
COLORES = {
    "cerebro":  (0.65, 0.67, 0.72),
    "craneo":   (0.90, 0.88, 0.82),
    "tumor":    (0.78, 0.15, 0.86),
    "arterias": (0.85, 0.10, 0.10),
    "venas":    (0.10, 0.20, 0.75),
    "vasos":    (0.80, 0.20, 0.20),
}


def importar_stl(ruta):
    """Importa un STL con la API que ofrezca la versión de Blender."""
    ops = []
    try:
        ops.append(bpy.ops.wm.stl_import)
    except Exception:
        pass
    try:
        ops.append(bpy.ops.import_mesh.stl)
    except Exception:
        pass
    for op in ops:
        try:
            res = op(filepath=ruta)
            obj = bpy.context.active_object
            if obj is not None and res != {"CANCELLED"}:
                return obj
        except Exception as e:
            print(f"[MODELO] Import con {getattr(op, 'idname', None)} falló: {e}")
    raise RuntimeError(f"No se pudo importar {ruta} con ninguna API STL")


def exportar_fbx():
    """Exporta la selección a FBX, adaptándose a las opciones disponibles."""
    kwargs = {
        "filepath": OUT_FBX,
        "use_selection": True,
        "use_mesh_modifiers": True,
        "axis_forward": "-Z",
        "axis_up": "Y",
    }
    try:
        supported = {p.identifier
                     for p in bpy.ops.export_scene.fbx.get_rna_type().properties}
        kwargs = {k: v for k, v in kwargs.items() if k in supported}
    except Exception:
        pass
    bpy.ops.export_scene.fbx(**kwargs)
def main():
    os.makedirs(os.path.dirname(OUT_FBX), exist_ok=True)

    # Escena limpia
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False, confirm=False)

    stls = sorted(f for f in os.listdir(STL_DIR) if f.lower().endswith(".stl"))
    if not stls:
        sys.exit(f"[MODELO] No hay STLs en {STL_DIR}")

    objs = []
    for f in stls:
        nombre = os.path.splitext(f)[0]
        print(f"[MODELO] Importando {f} ...")
        obj = importar_stl(os.path.join(STL_DIR, f))
        obj.name = nombre

        color = COLORES.get(nombre, (0.7, 0.7, 0.7))
        mat = bpy.data.materials.new(f"mat_{nombre}")
        mat.use_nodes = True
        nodo = mat.node_tree.nodes.get("Principled BSDF")
        if nodo is not None:
            nodo.inputs["Base Color"].default_value = (
                color[0], color[1], color[2], 1.0)
        if obj.data.materials:
            obj.data.materials.clear()
        obj.data.materials.append(mat)
        objs.append(obj)
        print(f"  -> {nombre}: {len(obj.data.vertices):,} verts, "
              f"{len(obj.data.polygons):,} caras")

    # UN SOLO objeto
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = "NEUROHUB"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    print(f"[MODELO] Objeto único: '{joined.name}' con "
          f"{len(joined.data.polygons):,} caras y "
          f"{len(joined.data.materials)} materiales")

    # Exportar UN SOLO FBX
    exportar_fbx()
    if not os.path.isfile(OUT_FBX):
        sys.exit("[MODELO] La exportación a FBX no produjo archivo")
    print(f"[MODELO] OK -> {OUT_FBX} ({os.path.getsize(OUT_FBX):,} bytes)")


if __name__ == "__main__":
    main()