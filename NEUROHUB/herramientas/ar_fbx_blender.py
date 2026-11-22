"""Exporta cada estructura de un GLB AR a su propio FBX (ejecutar con Blender).

    blender --background --python ar_fbx_blender.py -- caso_AR.glb carpeta_fbx

Se parte del GLB para que el FBX herede exactamente la misma geometría,
posición y material (color + alfa) que el modelo glTF.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
glb, destino = args[0], args[1]
os.makedirs(destino, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
objetos = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for obj in objetos:
    for mat in obj.data.materials:
        if mat is not None:
            # Blender 4.2+: el modo de mezcla del material se conserva en FBX
            # como transparencia; Unity la reaplica desde el manifiesto.
            mat.surface_render_method = "BLENDED"
for obj in objetos:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    ruta = os.path.join(destino, obj.name + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=ruta, use_selection=True, object_types={"MESH"},
        apply_scale_options="FBX_SCALE_UNITS", bake_space_transform=True,
        axis_forward="-Z", axis_up="Y", mesh_smooth_type="FACE",
        add_leaf_bones=False)
    print("FBX", ruta)
