"""Prepara los artefactos de un estudio para la escena Unity MR de NEUROHUB."""

import argparse
import json
import os
import shutil
from datetime import datetime, timezone


ESTRUCTURAS = {
    "cerebro": {"color": [0.65, 0.67, 0.72, 1.0], "opacity": 0.28},
    "craneo": {"color": [0.90, 0.88, 0.82, 1.0], "opacity": 0.12},
    "tumor": {"color": [0.78, 0.15, 0.86, 1.0], "opacity": 0.92},
    "vasos": {"color": [0.92, 0.12, 0.10, 1.0], "opacity": 0.95},
    "arterias": {"color": [0.95, 0.16, 0.10, 1.0], "opacity": 0.95},
    "venas": {"color": [0.14, 0.35, 0.92, 1.0], "opacity": 0.95},
    "fs_cortex": {"color": [0.32, 0.82, 0.45, 1.0], "opacity": 0.45},
    "fs_white_matter": {"color": [0.35, 0.62, 0.95, 1.0], "opacity": 0.32},
    "fs_cerebellum": {"color": [0.95, 0.72, 0.12, 1.0], "opacity": 0.88},
    "fs_brainstem": {"color": [0.95, 0.30, 0.18, 1.0], "opacity": 0.92},
    "fs_thalamus": {"color": [0.77, 0.26, 0.88, 1.0], "opacity": 0.92},
    "fs_basal_ganglia": {"color": [0.12, 0.75, 0.88, 1.0], "opacity": 0.92},
    "fs_hippocampus": {"color": [0.95, 0.28, 0.62, 1.0], "opacity": 0.92},
    "fs_ventricles": {"color": [0.96, 0.96, 0.96, 1.0], "opacity": 0.55},
}


def preparar(estudio_dir, unity_dir):
    """Copia solo los FBX del estudio y genera un manifiesto determinista."""
    estudio_dir = os.path.abspath(estudio_dir)
    unity_dir = os.path.abspath(unity_dir)
    fbx_dir = os.path.join(estudio_dir, "fbx")
    study_id = os.path.basename(estudio_dir)
    if study_id.lower() == "resultado":
        study_id = os.path.basename(os.path.dirname(estudio_dir))
    destino = os.path.join(unity_dir, "Assets", "Resources", "Studies",
                           study_id)
    if not os.path.isdir(fbx_dir):
        raise FileNotFoundError("No existe la carpeta FBX: %s" % fbx_dir)

    os.makedirs(destino, exist_ok=True)
    modelos = []
    for nombre in sorted(os.listdir(fbx_dir)):
        if not nombre.lower().endswith(".fbx"):
            continue
        origen = os.path.join(fbx_dir, nombre)
        if not os.path.isfile(origen):
            continue
        clave = os.path.splitext(nombre)[0].lower()
        shutil.copy2(origen, os.path.join(destino, nombre))
        datos = dict(ESTRUCTURAS.get(clave, {
            "color": [0.7, 0.7, 0.7, 1.0], "opacity": 0.8,
        }))
        datos.update({"id": clave, "file": nombre})
        modelos.append(datos)

    if not modelos:
        raise RuntimeError("No hay FBX para exportar desde %s" % fbx_dir)

    manifiesto = {
        "schema": "neurohub-mr-study-v1",
        "studyId": study_id,
        "sourceDirectory": estudio_dir,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "models": modelos,
        "clinicalReviewRequired": True,
        "renderProfile": {
            "pipeline": "URP",
            "antiAliasing": 4,
            "gpuInstancing": True,
            "asyncLoad": True,
        },
    }
    with open(os.path.join(destino, "study_manifest.json"), "w",
              encoding="utf-8") as archivo:
        json.dump(manifiesto, archivo, indent=2, ensure_ascii=False)
    return manifiesto


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("estudio", help="Carpeta del estudio que contiene fbx/")
    parser.add_argument("--unity", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "unity", "NeuroHubMR"))
    args = parser.parse_args()
    resultado = preparar(args.estudio, args.unity)
    print("Unity MR preparado: %s (%d modelos)" %
          (resultado["studyId"], len(resultado["models"])))


if __name__ == "__main__":
    main()
