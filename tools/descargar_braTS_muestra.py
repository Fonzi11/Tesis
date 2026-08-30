# -*- coding: utf-8 -*-
"""Descarga una muestra de NIfTI de tumores cerebrales (BraTS2021, datos abiertos
de Hugging Face, sin autenticación) para validar el pipeline de ATLAS.

Cada paciente incluye las 4 modalidades BraTS (flair, t1ce, t2, t1) y su máscara
de segmentación (`_seg.nii.gz`), lo que permite verificar segmentación y 3D.

Uso:
    python descargar_braTS_muestra.py --pacientes 12
    python descargar_braTS_muestra.py --pacientes 12 --mods flair t2 seg
"""
# =============================================================================
import argparse
import json
import os
import sys
import urllib.request

HF_REPO = "rocky93/BraTS_segmentation"
API_TREE = f"https://huggingface.co/api/datasets/{HF_REPO}/tree/main"
BASE_RAW = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"
MODS = ("flair", "t1ce", "t2", "t1", "seg")
_SALIDA_DEF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "nifti", "braTS_sample")


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


def list_pacientes():
    tree = _http_json(API_TREE)
    return sorted(n["path"] for n in tree
                  if n["type"] == "directory" and n["path"].startswith("BraTS2021_"))


def descargar(pacientes, mods, salida):
    os.makedirs(salida, exist_ok=True)
    total = 0
    for pid in pacientes:
        dest = os.path.join(salida, pid)
        os.makedirs(dest, exist_ok=True)
        for mod in mods:
            fname = f"{pid}_{mod}.nii.gz"
            out = os.path.join(dest, fname)
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                continue
            url = f"{BASE_RAW}/{pid}/{fname}"
            print(f"-> {url}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as f:
                f.write(resp.read())
            total += 1
        print(f"OK {pid}", flush=True)
    return len(pacientes), total


def main():
    ap = argparse.ArgumentParser(description="Descarga muestra BraTS2021 para ATLAS")
    ap.add_argument("--pacientes", type=int, default=10, help="Cantidad de pacientes")
    ap.add_argument("--mods", nargs="+", default=list(MODS),
                    help="Modalidades: flair t1ce t2 t1 seg")
    ap.add_argument("--salida", default=_SALIDA_DEF)
    args = ap.parse_args()

    pacientes = list_pacientes()
    if not pacientes:
        print("ERROR: no se pudo obtener la lista de pacientes.", file=sys.stderr)
        return 1
    sel = pacientes[:args.pacientes]
    n, total = descargar(sel, args.mods, args.salida)
    print(f"DESCARGA_OK pacientes={n} archivos={total}")
    print(f"SALIDA={args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())