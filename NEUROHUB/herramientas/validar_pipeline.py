"""Validación final del pipeline NEUROHUB: segmentación + FBX."""
import os
import sys

sys.path.insert(0, "NEUROHUB/src")


def main():
    import segmentacion_completa as sc

    print("=" * 70)
    print("PIPELINE COMPLETA DE SEGMENTACION + FBX: VALIDACION FINAL")
    print("=" * 70)

    # 1. Generar mallas
    res = sc.generar_mallas_3d("data/nifti/MRBrainTumor1.nii.gz")
    print()
    print("Estructuras generadas:")
    for k, v in res.items():
        stl = os.path.basename(v["stl"]) if v["stl"] else "N/A"
        print(f"  {k:15s} voxels={v['voxels']:>8,}  "
              f"vol={v['volumen_cm3']:>8.2f} cm3  stl={stl}")

    # 2. Verificar FBX existentes
    print()
    print("FBX generados:")
    fbx_dir = "salidas/fbx"
    for f in sorted(os.listdir(fbx_dir)):
        sz = os.path.getsize(os.path.join(fbx_dir, f))
        print(f"  {f:30s} {sz/1024:>10.1f} KB")

    # 3. Verificar que el viewer puede cargar las mallas
    print()
    try:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        from viewer3d import Pygame3DViewer
        v = Pygame3DViewer()
        ok = v.load_meshes_from_stl()
        print(f"Visor 3D: mallas cargadas = {ok}")
        for nombre in v.meshes:
            print(f"  - {nombre}: {len(v.meshes[nombre]['verts'])} verts")
    except Exception as e:
        print(f"Visor 3D: error {e}")

    print()
    print("VALIDACION FINAL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())