"""Exporta todas las STL de un estudio a FBX usando Blender externo."""

import os
import sys


COLORS = {
    "cerebro": (0.65, 0.67, 0.72, 1.0),
    "craneo": (0.90, 0.88, 0.82, 1.0),
    "tumor": (0.78, 0.15, 0.86, 1.0),
    "vasos": (0.92, 0.12, 0.10, 1.0),
    "arterias": (0.95, 0.16, 0.10, 1.0),
    "venas": (0.14, 0.35, 0.92, 1.0),
}


def _args():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(values) < 2:
        raise SystemExit("Uso: blender --background --python blender_export.py -- STL_DIR FBX_DIR")
    return os.path.abspath(values[0]), os.path.abspath(values[1])


def _import_stl(bpy, path):
    if hasattr(bpy.ops.wm, "stl_import"):
        result = bpy.ops.wm.stl_import(filepath=path.replace("\\", "/"))
    else:
        result = bpy.ops.import_mesh.stl(filepath=path.replace("\\", "/"))
    if "CANCELLED" in result:
        raise RuntimeError(f"No se pudo importar {path}")
    selected = list(bpy.context.selected_objects)
    if not selected:
        raise RuntimeError(f"Blender no creo un objeto para {path}")
    return selected[-1]


def _material(bpy, name):
    color = COLORS.get(name.lower(), (0.7, 0.7, 0.7, 1.0))
    material = bpy.data.materials.new(f"NEUROHUB_{name}")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.48
    return material


def main():
    import bpy

    stl_dir, fbx_dir = _args()
    os.makedirs(fbx_dir, exist_ok=True)
    files = sorted(
        filename for filename in os.listdir(stl_dir)
        if filename.lower().endswith(".stl")
    )
    if not files:
        raise RuntimeError(f"No hay STL en {stl_dir}")

    exported = 0
    for filename in files:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(stl_dir, filename)
        name = os.path.splitext(filename)[0]
        obj = _import_stl(bpy, path)
        obj.name = name
        obj.data.materials.append(_material(bpy, name))
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.shade_smooth()
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        output = os.path.join(fbx_dir, f"{name}.fbx")
        bpy.ops.export_scene.fbx(
            filepath=output.replace("\\", "/"),
            use_selection=True,
            use_mesh_modifiers=True,
            axis_forward="-Z",
            axis_up="Y",
            add_leaf_bones=False,
        )
        if not os.path.isfile(output):
            raise RuntimeError(f"Blender no produjo {output}")
        print(f"[BLENDER] {name}: {output}", flush=True)
        exported += 1

    print(f"[BLENDER] Exportados {exported} FBX", flush=True)


if __name__ == "__main__":
    main()
