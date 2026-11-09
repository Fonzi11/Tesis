"""Reconstruccion de labelmaps con 3D Slicer en modo sin interfaz.

El proceso principal comunica las rutas mediante variables de entorno para no
depender de como Slicer serializa los argumentos de ``--python-script``.
"""

import os
import sys


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name}")
    return value


def _load_labelmap(slicer, path):
    loaded = slicer.util.loadLabelVolume(path, returnNode=True)
    if isinstance(loaded, tuple):
        ok, node = loaded
    else:
        ok, node = bool(loaded), loaded
    if not ok or node is None:
        raise RuntimeError(f"No se pudo cargar la máscara {path}")
    return node


def _export_one(slicer, logic, mask_path, output_path):
    import vtk

    labelmap = _load_labelmap(slicer, mask_path)
    segmentation = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLSegmentationNode",
        os.path.basename(mask_path),
    )
    logic.ImportLabelmapToSegmentationNode(labelmap, segmentation)
    segmentation.CreateClosedSurfaceRepresentation()
    segment_ids = vtk.vtkStringArray()
    segmentation.GetSegmentation().GetSegmentIDs(segment_ids)
    if segment_ids.GetNumberOfValues() == 0:
        raise RuntimeError(f"La máscara no contiene etiquetas: {mask_path}")
    segment_id = segment_ids.GetValue(0)
    polydata = vtk.vtkPolyData()
    segmentation.GetClosedSurfaceRepresentation(segment_id, polydata)
    if polydata.GetNumberOfPoints() == 0:
        raise RuntimeError(f"No se pudo crear superficie: {mask_path}")
    model = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLModelNode",
        os.path.basename(output_path),
    )
    model.SetAndObservePolyData(polydata)
    model.CreateDefaultDisplayNodes()
    if not model.GetPolyData() or model.GetPolyData().GetNumberOfPoints() == 0:
        raise RuntimeError(f"La máscara no produjo geometría: {mask_path}")
    if not slicer.util.saveNode(model, output_path):
        raise RuntimeError(f"No se pudo guardar la malla {output_path}")


def main():
    import slicer

    segmentations_dir = _require_env("NEUROHUB_SEGMENTATIONS_DIR")
    meshes_dir = _require_env("NEUROHUB_MESHES_DIR")
    os.makedirs(meshes_dir, exist_ok=True)
    logic = slicer.vtkSlicerSegmentationsModuleLogic()

    candidates = {
        "cerebro": ("brain.nii.gz",),
        "craneo": ("skull.nii.gz", "cranium.nii.gz"),
        "vasos": ("vessels.nii.gz", "vasos.nii.gz"),
        "arterias": ("arteries.nii.gz", "arterias.nii.gz"),
        "venas": ("veins.nii.gz", "venas.nii.gz"),
    }
    generated = 0
    for name, filenames in candidates.items():
        mask_path = next(
            (os.path.join(segmentations_dir, filename)
             for filename in filenames
             if os.path.isfile(os.path.join(segmentations_dir, filename))),
            None,
        )
        if not mask_path:
            continue
        output_path = os.path.join(meshes_dir, f"{name}.stl")
        _export_one(slicer, logic, mask_path, output_path)
        print(f"[SLICER] {name}: {output_path}", flush=True)
        generated += 1

    if generated == 0:
        raise RuntimeError(
            f"No se encontraron masks compatibles en {segmentations_dir}"
        )
    slicer.util.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[SLICER][ERROR] {exc}", file=sys.stderr, flush=True)
        try:
            import slicer
            slicer.util.exit(1)
        except Exception:
            raise
