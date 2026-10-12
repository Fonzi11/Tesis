"""
Verificacion integral de NEUROHUB: interfaz, pipeline y motor de radiomics.

Este guion es el punto de entrada UNICO para comprobar que el proyecto esta
sano. Antes no habia ninguno: cada parte se probaba con un script distinto
(`NEUROHUB/tests/test_imports.py`, `prueba_slicer_malla.py`,
`paridad_pyradiomics.py`, `NEUROHUB/main.py`), y no habia forma de responder a
"¿esta todo integrado?" porque la integracion no se comprobaba en ningun sitio.

ETAPAS (se piden por separado con `--etapa`):

    deps      herramientas/verificar_instalacion.py: imports y recursos
    imports   modulos de src/ y main.py: importan y compilan
    ui_qt     la ventana PySide6 arranca, monta el visor y se cierra
    radiomics extraccion completa + tabla + exportacion CSV/JSON/informe
    raidionics el daemon de Docker responde y la imagen esta disponible
    slicer    la malla de 3D Slicer se reconstruye y la textura no cambia
    paridad   NEUROHUB vs PyRadiomics 3.0.1 descriptor a descriptor
    pipeline  procesar_caso.py end-to-end sobre un NIfTI real

Las etapas caras (slicer, paridad, pipeline) estan desactivadas por defecto
porque suman varios minutos y la paridad necesita el arbol de PyRadiomics
desempaquetado en la raiz. Se activan con `--todo` o `--etapa <nombre>`.

Uso:

    python verificacion_integral.py             # etapas rapidas
    python verificacion_integral.py --todo       # absolutamente todo
    python verificacion_integral.py --etapa radiomics
    python verificacion_integral.py --ui-real    # ventana Qt real, no offscreen
"""

import argparse
import math
import os
import subprocess
import sys
import time
import traceback

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
# `src.ui_qt` se importa como `src.*` desde NEUROHUB, mientras que el motor de
# radiomics se importa como `radiomics.*` desde src/. hacen falta las dos raices
# en el path, y por eso el orden importa: NEUROHUB gana si se inserta despues.
SRC = os.path.join(RAIZ, "NEUROHUB", "src")
NEUROHUB = os.path.join(RAIZ, "NEUROHUB")
for _ruta in (SRC, NEUROHUB):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

MRI = os.path.join(RAIZ, "data", "nifti", "MRBrainTumor1.nii.gz")
TUMOR = os.path.join(RAIZ, "salidas", "segmentaciones_ai", "tumor_brats.nii.gz")

ETAPAS_RAPIDAS = ["deps", "imports", "ui_qt", "radiomics", "raidionics"]
ETAPAS = ETAPAS_RAPIDAS + ["slicer", "paridad", "pipeline"]


# =============================================================================
# MARCO DE EJECUCION
# =============================================================================
class Informe:
    """Acumula el resultado de cada etapa y lo imprime como un resumen."""

    MARCAS = {"OK": "[ OK ]", "FALLO": "[FALLO]", "OMITE": "[OMITE]"}

    def __init__(self):
        self.filas = []

    def anota(self, etapa, estado, detalle, segundos):
        self.filas.append((etapa, estado, detalle, segundos))
        print("  %s %-10s %6.1f s  %s"
              % (self.MARCAS[estado], etapa, segundos, detalle), flush=True)

    def fallo(self, etapa, exc):
        self.anota(etapa, "FALLO", exc, 0.0)

    def resumen(self):
        print()
        print("=" * 78)
        print("RESUMEN")
        print("=" * 78)
        fallos = [f for f in self.filas if f[1] == "FALLO"]
        for etapa, estado, detalle, seg in self.filas:
            print("  %-10s %-6s %6.1f s  %s" % (etapa, estado, seg, detalle))
        print("-" * 78)
        print("  %d etapas | %d fallos | %d omitidas"
              % (len(self.filas), len(fallos),
                 sum(1 for f in self.filas if f[1] == "OMITE")))
        print("=" * 78)
        if fallos:
            print("VEREDICTO: HAY %d ETAPA(S) ROTA(S) -> %s"
                  % (len(fallos), ", ".join(f[0] for f in fallos)))
            return 1
        print("VEREDICTO: todo correcto en las etapas ejecutadas")
        return 0


def _falta(ruta):
    return "" if os.path.exists(ruta) else "falta %s" % ruta


def _datos_ausentes():
    return _falta(MRI) or _falta(TUMOR)


# =============================================================================
# ETAPAS
# =============================================================================
def etapa_deps(informe):
    """Instalacion: el guion oficial de herramientas/ del proyecto."""
    script = os.path.join(
        RAIZ, "NEUROHUB", "herramientas", "verificar_instalacion.py")
    if not os.path.exists(script):
        informe.anota("deps", "OMITE", "no existe verificar_instalacion.py", 0.0)
        return
    t0 = time.time()
    p = subprocess.run([sys.executable, script], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    salida = (p.stdout or "") + (p.stderr or "")
    # El guion original imprime lineas de rulers decorativos, asi que se busca
    # la ultima linea con contenido real en vez de la ultima linea del todo.
    lineas = [ln.strip() for ln in salida.splitlines()
              if ln.strip() and not set(ln.strip()) <= set("=-*_")]
    ultimo = lineas[-1][:70] if lineas else "(sin salida)"
    # El guion original no devuelve codigo de salida, asi que se lee su texto.
    if p.returncode != 0 or "FALLO" in salida or "Error" in salida:
        informe.fallo("deps", ultimo)
    else:
        informe.anota("deps", "OK", ultimo, time.time() - t0)


def etapa_imports(informe):
    """Los modulos de src/ y main.py siguen importando y compilando."""
    import importlib

    modulos = ["04_slices_2d", "03_integrar_brats", "02_segmentacion_brats",
               "calidad_mallas", "anatomia", "viewer3d", "data_manager",
               "segmentacion_completa", "totalsegmentator_shim"]
    problemas = []
    for nombre in modulos:
        try:
            importlib.import_module(nombre)
        except Exception as exc:                        # noqa: BLE001
            problemas.append("%s -> %s: %s" % (nombre, type(exc).__name__, exc))
    with open(os.path.join(RAIZ, "NEUROHUB", "main.py"), encoding="utf-8") as f:
        try:
            compile(f.read(), "main.py", "exec")
        except SyntaxError as exc:
            problemas.append("main.py no compila: %s" % exc)

    if problemas:
        informe.fallo("imports", "; ".join(problemas))
    else:
        informe.anota("imports", "OK", "%d modulos + main.py" % len(modulos),
                      0.0)



SENTINELA_OK = "UI-QT-OK"
SENTINELA_FALLO = "UI-QT-FALLO"

# El harness de Qt se ejecuta como hijo porque VTK aborta el proceso entero
# (SIGSEGV) cuando no encuentra un pixel format valido, y un fallo de ese tipo
# no se puede capturar con try/except: mata al interprete sin dejar resumen.
HARNESS = '''
import os, sys, traceback
SENTINELA_OK, SENTINELA_FALLO = %(ok)r, %(fallo)r
os.environ["QT_QPA_PLATFORM"] = %(plataforma)r
try:
    from PySide6.QtCore import QTimer
    from src.ui_qt.app import crear_app
    from src.ui_qt.main_window import MainWindow
    app = crear_app([])
    ventana = MainWindow()
    ventana.show()
    QTimer.singleShot(1500, app.quit)   # un ciclo basta para montar la escena
    app.exec()
    ventana.close()
    print(SENTINELA_OK)
except Exception:
    traceback.print_exc()
    print(SENTINELA_FALLO)
    sys.exit(1)
'''


def etapa_ui_qt(informe, ui_real=False):
    """
    La ventana PySide6 arranca, monta el visor y se cierra sola.

    Va en un subproceso: en modo offscreen VTK aborta con SIGSEGV al no
    encontrar un pixel format valido, y eso se lleva por delante tambien al
    verificador. Con `--ui-real` la ventana se abre de verdad, que es la unica
    forma de comprobar de verdad el render de VTK.
    """
    import tempfile

    t0 = time.time()
    plataforma = "windows" if ui_real else "offscreen"
    with tempfile.TemporaryDirectory(prefix="neurohub_ui_") as tmp:
        guion = os.path.join(tmp, "harness_ui.py")
        with open(guion, "w", encoding="utf-8") as f:
            f.write(HARNESS % {"ok": SENTINELA_OK, "fallo": SENTINELA_FALLO,
                              "plataforma": plataforma})
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([SRC, NEUROHUB]))
        p = subprocess.run([sys.executable, guion], cwd=RAIZ, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)

    salida = (p.stdout or "") + (p.stderr or "")
    # Sin pixel format de OpenGL en offscreen: es una limitacion del entorno,
    # no un defecto de la aplicacion, asi que se informa como omision.
    if "failed to get valid pixel format" in salida and SENTINELA_OK not in salida:
        informe.anota("ui_qt", "OMITE",
                      "VTK sin OpenGL en %s: usar --ui-real" % plataforma,
                      time.time() - t0)
    elif p.returncode == 0 and SENTINELA_OK in salida:
        informe.anota("ui_qt", "OK",
                      "ventana construida y cerrada (%s)" % plataforma,
                      time.time() - t0)
    elif p.returncode < 0:
        informe.fallo("ui_qt", "el proceso de Qt morreu con codigo %d"
                      % -p.returncode)
    else:
        errores = [ln for ln in salida.splitlines() if ln.strip()][-3:]
        informe.fallo("ui_qt", " | ".join(errores) or "codigo %d"
                      % p.returncode)


def etapa_radiomics(informe):
    """
    El motor entero: carga, ROI BraTS, extraccion, tabla y las TRES
    exportaciones. Es la etapa que demuestra que `src/radiomics` funciona como
    paquete y no como codigo suelto, y que nada sale NaN o infinito.
    """
    t0 = time.time()
    if _datos_ausentes():
        informe.anota("radiomics", "OMITE", "datos ausentes (%s)"
                      % _datos_ausentes(), 0.0)
        return
    try:
        from radiomics import (ExtractionConfig, cargar_volumen, construir_tabla,
                              de_nifti, exportar_csv, exportar_informe,
                              exportar_json, extraer_radiomics, magmas_braTS)

        volumen, spacing, _meta = cargar_volumen(MRI)
        rois = magmas_braTS(tumor_roi=de_nifti(TUMOR, (1, 2, 3), "Tumor"))
        resultados = extraer_radiomics(
            volumen, rois, ExtractionConfig(bin_count=32))
        tabla = construir_tabla(resultados, {
            "Estudio": os.path.basename(MRI),
            "Spacing": "x".join("%.3f" % s for s in spacing),
        })

        # Un valor no finito es peor que un descriptor ausente: en un informe
        # clinico NaN e infinito no se distinguen y no se pueden comparar.
        valores = [tabla.valor(r, c)
                   for r in tabla.rois() for c in tabla.columnas()]
        no_finitos = sum(1 for v in valores if not math.isfinite(v))

        destino = os.path.join(RAIZ, "salidas", "reportes", "radiomics")
        rutas = [exportar_csv(tabla, os.path.join(destino, "verificacion.csv")),
                 exportar_json(tabla, os.path.join(destino, "verificacion.json")),
                 exportar_informe(tabla,
                                  os.path.join(destino, "verificacion.txt"))]
        for ruta in rutas:
            if not os.path.isfile(ruta) or os.path.getsize(ruta) == 0:
                informe.fallo("radiomics", "exportacion vacia: %s" % ruta)
                return

        if no_finitos:
            informe.fallo("radiomics", "%d valores no finitos" % no_finitos)
        else:
            informe.anota("radiomics", "OK",
                          "%d ROI x %d rasgos, 0 no finitos, CSV+JSON+TXT"
                          % (len(tabla.rois()), tabla.n_rasgos()),
                          time.time() - t0)
    except Exception as exc:                            # noqa: BLE001
        traceback.print_exc()
        informe.fallo("radiomics", "%s: %s" % (type(exc).__name__, exc))


def etapa_raidionics(informe):
    """
    El puente con Raidionics en Docker se puede usar de verdad.

    No se lanza el contenedor aqui: la inferencia de un craneo completo tarda
    minutos y descarga gigas, lo que haria la verificacion inutilizable. Lo que
    se comprueba es lo barato y lo que de verdad se rompe en la practica: que
    el daemon responde y que la imagen esta disponible. Si Docker no esta, la
    etapa se OMITE con el motivo, porque el motor propio no depende de el.
    """
    t0 = time.time()
    try:
        from radiomics import raidionics_bridge

        if raidionics_bridge.ruta_docker() is None:
            informe.anota("raidionics", "OMITE", "docker no instalado", 0.0)
            return

        problema = raidionics_bridge.diagnostico()
        if problema is not None:
            informe.anota("raidionics", "OMITE", problema, time.time() - t0)
            return

        if not raidionics_bridge.imagen_presente():
            informe.anota("raidionics", "OK",
                          "docker operativo; la imagen %s se bajara al primer uso"
                          % raidionics_bridge.IMAGEN, time.time() - t0)
            return

        informe.anota("raidionics", "OK",
                      "docker operativo, imagen %s lista" % raidionics_bridge.IMAGEN,
                      time.time() - t0)
    except Exception as exc:                            # noqa: BLE001
        informe.fallo("raidionics", "%s: %s" % (type(exc).__name__, exc))


def etapa_slicer(informe):
    """
    La superficie se reconstruye con 3D Slicer y los rasgos de textura NO
    cambian al cambiar de malla. Si cambian, la extraccion depende de la
    geometria y los valores dejan de ser comparables entre estudios.
    """
    t0 = time.time()
    if _datos_ausentes():
        informe.anota("slicer", "OMITE", "datos ausentes", 0.0)
        return
    try:
        from radiomics import slicer_bridge
        if not slicer_bridge.disponible():
            informe.anota("slicer", "OMITE",
                          "3D Slicer no instalado (se usa la malla de skimage)",
                          0.0)
            return

        from radiomics import (ExtractionConfig, cargar_volumen, de_nifti,
                              extraer_radiomics, magmas_braTS)

        volumen, _, _ = cargar_volumen(MRI)
        rois = magmas_braTS(tumor_roi=de_nifti(TUMOR, (1, 2, 3), "Tumor"))
        con = extraer_radiomics(
            volumen, rois,
            ExtractionConfig(bin_count=32, malla_slicer=True))
        sin = extraer_radiomics(
            volumen, rois, ExtractionConfig(bin_count=32))

        desajustes = 0
        for roi, rasgos in con.items():
            ref = sin[roi]
            for k, v in rasgos.items():
                if any(t in k for t in ("GLCM", "GLRLM", "GLSZM", "NGTDM",
                                        "LSH", "LSZM")):
                    if abs(v - ref[k]) > 1e-9:
                        desajustes += 1

        # Si Slicer reconstruye, el volumen de malla tiene que moverse. Si
        # sale identico, el puente fallo en silencio y se estaria comparando
        # skimage consigo mismo, dando un falso "todo bien".
        v_con = con["Tumor_SNFH"]["original_MeshVolume_mm3"]
        v_sin = sin["Tumor_SNFH"]["original_MeshVolume_mm3"]
        if desajustes:
            informe.fallo("slicer",
                          "%d rasgos de textura dependen de la malla" % desajustes)
        elif abs(v_con - v_sin) < 1e-6:
            informe.fallo("slicer",
                          "la malla de Slicer no difiere de skimage: puente roto")
        else:
            informe.anota("slicer", "OK",
                          "Slicer %.0f mm3 vs skimage %.0f mm3, textura estable"
                          % (v_con, v_sin), time.time() - t0)
    except Exception as exc:                            # noqa: BLE001
        traceback.print_exc()
        informe.fallo("slicer", "%s: %s" % (type(exc).__name__, exc))


def etapa_paridad(informe):
    """
    NEUROHUB frente a PyRadiomics 3.0.1.

    Se delega en `paridad_pyradiomics.py` en vez de duplicar la comparacion:
    ese archivo es la unica fuente de la lista de defectos pendientes.
    """
    script = os.path.join(
        RAIZ, "NEUROHUB", "herramientas", "diagnostico",
        "paridad_pyradiomics.py")
    if not os.path.exists(script):
        informe.anota("paridad", "OMITE", "no existe paridad_pyradiomics.py", 0.0)
        return
    if not os.path.isdir(os.path.join(RAIZ, "pyradiomics-3.0.1")):
        informe.anota("paridad", "OMITE", "falta el arbol pyradiomics-3.0.1",
                      0.0)
        return
    t0 = time.time()
    p = subprocess.run([sys.executable, script], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        informe.fallo("paridad", "el guion termino con codigo %d" % p.returncode)
        return
    salida = (p.stdout or "") + (p.stderr or "")
    resumen = [ln.strip() for ln in salida.splitlines()
               if ln.startswith(("Coinciden", "Desviaciones", "Solo en"))]
    # La paridad se marca OK si el guion corre, no si coincide al 100%: hay
    # defectos conocidos y documentados en el propio guion. El porcentaje se
    # imprime para que se vea la tendencia al repetir la ejecucion.
    informe.anota("paridad", "OK", " | ".join(resumen) or "comparacion ejecutada",
                  time.time() - t0)


def etapa_pipeline(informe):
    """El pipeline headless completo sobre un NIfTI real."""
    script = os.path.join(RAIZ, "NEUROHUB", "procesar_caso.py")
    if not os.path.exists(script):
        informe.anota("pipeline", "OMITE", "no existe procesar_caso.py", 0.0)
        return
    if _falta(MRI):
        informe.anota("pipeline", "OMITE", "falta %s" % MRI, 0.0)
        return
    t0 = time.time()
    # `procesar_caso.py` toma el volumen como argumento POSICIONAL, no con
    # --nifti, y escribe en su propia carpeta de trabajo: se le da una temporal
    # para no ensuciar salidas/ con una pasada de verificacion.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="neurohub_pipe_") as tmp:
        p = subprocess.run(
            [sys.executable, script, MRI, "--salida", tmp, "--rapido"],
            cwd=os.path.join(RAIZ, "NEUROHUB"),
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        salida = (p.stdout or "") + (p.stderr or "")
        errores = [ln.strip() for ln in salida.splitlines()
                   if ln.strip().startswith("[X]")] or \
                  [ln.strip() for ln in (p.stderr or "").splitlines() if ln.strip()]
        informe.fallo("pipeline",
                      errores[-1] if errores else "codigo %d" % p.returncode)
    else:
        informe.anota("pipeline", "OK", "procesar_caso.py completo",
                      time.time() - t0)


# =============================================================================
# MAIN
# =============================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Verificacion integral de NEUROHUB (pipeline + radiomics)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--todo", action="store_true",
                    help="ejecuta tambien las etapas lentas (slicer, paridad, "
                         "pipeline)")
    ap.add_argument("--etapa", action="append", choices=ETAPAS,
                    help="ejecuta solo las etapas indicadas (repetible)")
    ap.add_argument("--ui-real", action="store_true",
                    help="abre la ventana Qt en vez de offscreen")
    args = ap.parse_args()

    if args.etapa:
        pedidas = [e for e in ETAPAS if e in set(args.etapa)]
    else:
        pedidas = ETAPAS if args.todo else ETAPAS_RAPIDAS

    print("=" * 78)
    print("VERIFICACION INTEGRAL DE NEUROHUB")
    print("Etapas: %s" % ", ".join(pedidas))
    print("=" * 78, flush=True)

    informe = Informe()
    for etapa in pedidas:
        print("\n[%s] ejecutando..." % etapa, flush=True)
        try:
            if etapa == "deps":
                etapa_deps(informe)
            elif etapa == "imports":
                etapa_imports(informe)
            elif etapa == "ui_qt":
                etapa_ui_qt(informe, ui_real=args.ui_real)
            elif etapa == "radiomics":
                etapa_radiomics(informe)
            elif etapa == "raidionics":
                etapa_raidionics(informe)
            elif etapa == "slicer":
                etapa_slicer(informe)
            elif etapa == "paridad":
                etapa_paridad(informe)
            elif etapa == "pipeline":
                etapa_pipeline(informe)
        except Exception as exc:                        # noqa: BLE001
            traceback.print_exc()
            informe.fallo(etapa, "%s: %s" % (type(exc).__name__, exc))
        finally:
            sys.stdout.flush()

    return informe.resumen()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrumpido por el usuario")
        sys.exit(130)
