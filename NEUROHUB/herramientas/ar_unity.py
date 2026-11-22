"""Instala casos de modelos AR en el proyecto Unity NeuroHubMR.

    python ar_unity.py <carpeta_caso> [<carpeta_caso> ...]

Por cada caso genera con Blender un FBX por estructura (versión completa y
versión ligera) y escribe ``study_manifest.json`` con el esquema
``neurohub-mr-study-v1`` que lee ``NeuroHubStudyLoader``. Colores, opacidades,
grupos de capa y volúmenes vienen de ``resumen.json``. Al final actualiza
``Resources/Studies/studies_index.json`` con los casos instalados.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
UNITY = os.path.join(os.path.dirname(AQUI), "unity", "NeuroHubMR")

# Grupo de capa de cada estructura (orden de "pelado" en el visor).
GRUPOS = (
    ("craneo", "craneo"),
    ("corteza_", "corteza"),
    ("sustancia_blanca", "sustancia_blanca"),
    ("cerebelo", "cerebelo_tronco"),
    ("tronco_encefalico", "cerebelo_tronco"),
    ("ventriculos", "ventriculos"),
    ("arterias", "vasos"),
    ("tumor_", "lesion"),
    ("aneurisma", "lesion"),
)


def grupo_de(ident):
    for prefijo, grupo in GRUPOS:
        if ident.startswith(prefijo):
            return grupo
    return "profundas"  # tálamo, caudado, putamen, hipocampo...


def _blender():
    for ruta in sorted(glob.glob(r"D:\Program Files\Blender Foundation\Blender*\blender.exe")
                       + glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"),
                       reverse=True):
        return ruta
    encontrado = shutil.which("blender")
    if not encontrado:
        raise RuntimeError("No se encontró Blender para exportar FBX.")
    return encontrado


def _exportar_fbx(glb, destino):
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    r = subprocess.run([_blender(), "--background", "--factory-startup", "--python",
                        os.path.join(AQUI, "ar_fbx_blender.py"), "--", glb, destino],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Blender falló:\n" + r.stdout[-2000:] + r.stderr[-2000:])


def _instalar_variante(info, carpeta_caso, glb, study_id, unity_dir):
    fbx_dir = os.path.join(carpeta_caso, "fbx" if study_id == info["caso"] else "fbx_ligero")
    _exportar_fbx(os.path.join(carpeta_caso, glb), fbx_dir)
    destino = os.path.join(unity_dir, "Assets", "Resources", "Studies", study_id)
    if os.path.isdir(destino):
        # Solo se reemplazan los FBX y el manifiesto; los .meta de Unity se
        # conservan para no romper referencias.
        for f in glob.glob(os.path.join(destino, "*.fbx")):
            os.remove(f)
    os.makedirs(destino, exist_ok=True)
    modelos = []
    for e in info["estructuras"]:
        nombre = e["id"] + ".fbx"
        origen = os.path.join(fbx_dir, nombre)
        if not os.path.isfile(origen):
            raise FileNotFoundError(origen)
        shutil.copy2(origen, os.path.join(destino, nombre))
        modelos.append({"id": e["id"], "file": nombre, "name": e["nombre"],
                        "group": grupo_de(e["id"]),
                        "color": list(e["color"]) + [1.0],
                        "opacity": e["opacidad"],
                        "volumeCm3": e["volumen_cm3"],
                        "triangles": e["triangulos"]})
    if not any(m["group"] == "lesion" for m in modelos):
        raise RuntimeError("%s no tiene lesión (tumor o aneurisma)." % study_id)
    manifiesto = {
        "schema": "neurohub-mr-study-v1", "studyId": study_id,
        "caseId": info["caso"],
        "lesionType": "aneurisma" if any(m["id"] == "aneurisma" for m in modelos) else "tumor",
        "lod": "ligero" if study_id.endswith("_ligero") else "completo",
        "sourceDirectory": os.path.abspath(carpeta_caso),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "models": modelos, "clinicalReviewRequired": True,
        "renderProfile": {"pipeline": "URP", "antiAliasing": 4,
                          "gpuInstancing": True, "asyncLoad": True},
    }
    for ruta in (os.path.join(destino, "study_manifest.json"),
                 os.path.join(carpeta_caso, "study_manifest_%s.json" % manifiesto["lod"])):
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(manifiesto, fh, indent=2, ensure_ascii=False)
    return destino, len(modelos)


def instalar(carpeta_caso, unity_dir=UNITY):
    with open(os.path.join(carpeta_caso, "resumen.json"), encoding="utf-8") as fh:
        info = json.load(fh)
    caso = info["caso"]
    salida = [_instalar_variante(info, carpeta_caso, info["glb"], caso, unity_dir)]
    salida.append(_instalar_variante(info, carpeta_caso, info["glb_ligero"],
                                     caso + "_ligero", unity_dir))
    return caso, salida


def escribir_indice(casos, unity_dir=UNITY):
    ruta = os.path.join(unity_dir, "Assets", "Resources", "Studies", "studies_index.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"studies": list(casos),
                   "lightStudies": [c + "_ligero" for c in casos]}, fh, indent=2)
    return ruta


if __name__ == "__main__":
    casos = []
    for carpeta in sys.argv[1:]:
        caso, variantes = instalar(carpeta)
        casos.append(caso)
        for destino, n in variantes:
            print("Unity: %s (%d modelos)" % (destino, n))
    print("Índice:", escribir_indice(casos))
