"""Blender background script: split an STL into horizontal layers and export FBX files."""

from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import bpy  # type: ignore[import-not-found]
except ModuleNotFoundError as error:
    if error.name == "bpy":
        raise SystemExit(
            "Este script debe ejecutarse con Blender, no con Python normal. "
            "Usa: blender --background --python convert_stl_to_fbx_layers.py -- "
            "entrada.stl carpeta_salida --layer-height 1.0"
        ) from error
    raise


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Export an STL as one FBX per Z layer.")
    parser.add_argument("input")
    parser.add_argument("output_dir")
    parser.add_argument("--layer-height", type=float, required=True)
    return parser.parse_args(argv)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "modelo"


def export_object(obj, path: str):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    options = {"filepath": path, "use_selection": True, "object_types": {"MESH"}, "global_scale": 1.0, "apply_unit_scale": True, "axis_forward": "-Z", "axis_up": "Y"}
    try:
        supported = {prop.identifier for prop in bpy.ops.export_scene.fbx.bl_rna.properties}
        for color_option in ("use_vertex_colors", "use_colors", "use_vertex_color"):
            if color_option in supported:
                options[color_option] = True
                break
    except Exception:
        pass
    bpy.ops.export_scene.fbx(**options)


def bisect(obj, z: float, keep_above: bool):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.bisect(plane_co=(0.0, 0.0, z), plane_no=(0.0, 0.0, 1.0), clear_inner=keep_above, clear_outer=not keep_above, use_fill=True)
    bpy.ops.object.mode_set(mode="OBJECT")


def main():
    args = parse_args()
    if args.layer_height <= 0:
        raise ValueError("La altura de capa debe ser mayor que cero.")
    if not os.path.isfile(args.input):
        raise FileNotFoundError(args.input)
    os.makedirs(args.output_dir, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False, confirm=False)
    bpy.ops.import_mesh.stl(filepath=os.path.abspath(args.input))
    source_objects = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not source_objects:
        raise RuntimeError("Blender no pudo crear una malla a partir del STL.")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in source_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = source_objects[0]
    bpy.ops.object.join()
    source = bpy.context.object
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    min_z = min((source.matrix_world @ vertex.co).z for vertex in source.data.vertices)
    max_z = max((source.matrix_world @ vertex.co).z for vertex in source.data.vertices)
    layer_count = max(1, int((max_z - min_z) / args.layer_height + 0.999999))
    base_name = safe_name(os.path.splitext(os.path.basename(args.input))[0])

    for index in range(layer_count):
        lower = min_z + index * args.layer_height
        upper = min(max_z, lower + args.layer_height)
        layer = source.copy()
        layer.data = source.data.copy()
        bpy.context.collection.objects.link(layer)
        bisect(layer, lower, keep_above=True)
        bisect(layer, upper, keep_above=False)
        export_object(layer, os.path.join(args.output_dir, f"{base_name}_capa_{index + 1:04d}.fbx"))
        bpy.data.objects.remove(layer, do_unlink=True)
        print(f"LAYER {index + 1}/{layer_count}", flush=True)

    print(f"EXPORTED {layer_count}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)