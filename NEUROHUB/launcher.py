
"""
NEUROHUB - Lanzador
===================

Punto de entrada UNICO del proyecto. Reune en un solo comando todo lo que
antes estaba repartido en scripts sueltos: la interfaz PySide6, el pipeline de
segmentacion, el motor de radiomics, el puente con Raidionics en Docker y la
verificacion integral.

    python launcher.py                      # interfaz grafica (por defecto)
    python launcher.py ui                   # interfaz grafica, explicito
    python launcher.py verificar            # etapas rapidas de diagnostico
    python launcher.py verificar --todo     # verificacion completa
    python launcher.py radiomics --help     # extraccion sobre un NIfTI
    python launcher.py raidionics estado    # si Docker puede correr Raidionics
    python launcher.py doctor               # estado de TODO el entorno

Cada subcomando se puede pedir por separado, y todos comparten la misma
comprobacion de dependencias: instalar un paquete que hace falta para un modo
no debe ser condicion para usar los demas, asi que `doctor` informa y cada
modo instala solo lo suyo.
"""

import argparse
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
PADRE = os.path.dirname(RAIZ)

# Las dependencias de la app unificada: visor 3D VTK + pipeline de segmentacion.
DEPENDENCIAS = {
    "customtkinter": "customtkinter",
    "vtk": "vtk",
    "pyvista": "pyvista",
    "pygame": "pygame",
    "SimpleITK": "SimpleITK",
    "nibabel": "nibabel",
    "numpy": "numpy",
    "scipy": "scipy",
    "skimage": "scikit-image",
    "trimesh": "trimesh",
    "fast_simplification": "fast-simplification",
    "PIL": "pillow",
}
# Radiomics necesita poco mas, y va aparte para que una instalacion de la
# interfaz no arrastre el motor de rasgos si no se va a usar.
DEPENDENCIAS_RADIOMICS = {
    "pydicom": "pydicom",
}


def faltan(requeridas):
    """Lista de paquetes pip que no se pueden importar."""
    ausentes = []
    for modulo, pip in requeridas.items():
        try:
            __import__(modulo)
        except ImportError:
            ausentes.append(pip)
    return ausentes


def instalar(paquetes):
    """Instala paquetes, devolviendo False si alguno no se pudo instalar."""
    for p in paquetes:
        print("  -> instalando %s" % p, flush=True)
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", p])
        except subprocess.CalledProcessError:
            print("  !! no se pudo instalar %s" % p)
            return False
    return True


def asegurar(requeridas, etiqueta):
    """
    Deja las dependencias de `requeridas` listas. True si se puede continuar.

    No aborta el proceso si algo falla: el modo que se ha pedido puede no
    necesitar lo que falte (por ejemplo, `raidionics` funciona con Docker y
    sin ninguna de estas librerias), asi que devuelve el estado y deja que cada
    subcomando decida.
    """
    ausentes = faltan(requeridas)
    if not ausentes:
        return True
    print("Faltan dependencias de %s: %s" % (etiqueta, ", ".join(ausentes)))
    if not instalar(ausentes):
        print("Instalalas manualmente con: pip install -r requirements.txt")
        return False
    return True


def _preparar_rutas():
    """
    Deja el import de `src.*` funcionando y se posiciona en la raiz.

    `src.ui_qt` se importa como `src.*` desde NEUROHUB, mientras que el motor de
    radiomics se importa como `radiomics.*` desde src/. Hacen falta las dos
    raices en el path, y por eso el orden importa: NEUROHUB entra despues para
    ganar.
    """
    for ruta in (os.path.join(RAIZ, "src"), RAIZ):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)
    os.chdir(RAIZ)


# =============================================================================
# DOCTOR: estado de todo el entorno de una vez
# =============================================================================
def cmd_doctor(_args):
    """
    Informe del estado del entorno: Python, dependencias, motores externos.

    No instala nada. Su valor es separar de un vistazo lo que FALTA (y hay que
    instalarlo) de lo que esta APAGADO (y hay que encenderlo): instalar VTK no
    arregla un Docker Desktop parado, y confundirlos hace perder mucho tiempo.
    """
    import platform

    print("=" * 72)
    print("  NEUROHUB - estado del entorno")
    print("=" * 72)
    print("Python      : %s (%s)" % (platform.python_version(), sys.executable))
    print("Plataforma  : %s %s" % (platform.system(), platform.release()))
    print("Raiz        : %s" % RAIZ)

    print("\n-- Dependencias de la interfaz --")
    ausentes = faltan(DEPENDENCIAS)
    print("  %s" % ("todas presentes" if not ausentes
                  else "FALTAN: " + ", ".join(ausentes)))

    print("\n-- Dependencias de radiomics --")
    ausentes_rad = faltan(DEPENDENCIAS_RADIOMICS)
    print("  %s" % ("todas presentes" if not ausentes_rad
                  else "FALTAN: " + ", ".join(ausentes_rad)))

    print("\n-- Motores externos --")
    # Slicer: basta con que el ejecutable este, no hace falta arrancarlo.
    slicer = _buscar_slicer()
    print("  3D Slicer  : %s" % (slicer or "no encontrado"))

    # Raidionics: a diferencia de Slicer, aqui importa el DAEMON, no el binario.
    try:
        _preparar_rutas()
        from radiomics import raidionics_bridge
        docker = raidionics_bridge.ruta_docker()
        if docker is None:
            print("  Raidionics : docker no esta en el PATH")
        else:
            print("  Docker     : %s" % docker)
            problema = raidionics_bridge.diagnostico()
            if problema is None:
                print("  Raidionics : disponible")
            else:
                print("  Raidionics : NO disponible -> %s" % problema)
    except Exception as exc:                        # pragma: no cover
        print("  Raidionics : no se pudo comprobar (%s)" % exc)

    print("\n" + "=" * 72)
    return 0


def _buscar_slicer():
    """Ruta de Slicer si aparece en el PATH o en las rutas habituales."""
    import shutil
    encontrado = shutil.which("Slicer") or shutil.which("Slicer.exe")
    if encontrado:
        return encontrado
    for base in (r"C:\Program Files", r"D:\APPS"):
        carpeta = os.path.join(base, "3D Slicer 5.12.3", "Slicer.exe")
        if os.path.exists(carpeta):
            return carpeta
    return None


# =============================================================================
# RAIDIONICS: motor externo en Docker
# =============================================================================
def cmd_raidionics(args):
    """
    Estado y ejecucion de Raidionics dentro de Docker.

    `estado` responde si el motor se puede usar, que es la pregunta que se hace
    uno antes de diagnosticar cualquier otra cosa. `extraer` delega en el puente
    y deja el informe en disco.
    """
    _preparar_rutas()
    from radiomics import raidionics_bridge as puente

    if args.accion == "estado":
        docker = puente.ruta_docker()
        if docker is None:
            print("Docker no esta instalado o no esta en el PATH.")
            print(puente.diagnostico())
            return 1
        problema = puente.diagnostico()
        if problema is None:
            print("Raidionics disponible.")
            print("  docker    : %s" % docker)
            print("  imagen    : %s" % puente.IMAGEN)
            print("  descargada: %s" % ("si" if puente.imagen_presente()
                                       else "no (se bajara al primer uso)"))
            return 0
        print("Raidionics NO disponible.")
        print("  %s" % problema)
        print("\nEl motor propio de radiomics sigue funcionando sin Docker.")
        return 1

    # extraer
    if args.estudio is None:
        print("Falta el NIfTI de entrada. Uso: raidionics extraer <estudio.nii.gz>")
        return 2
    salida = args.salida or os.path.join(PADRE, "salidas", "raidionics")
    print("Ejecutando Raidionics sobre %s" % args.estudio)
    print("La primera vez se descarga el modelo: puede tardar bastante.")
    try:
        resumen = puente.extraer(args.estudio, salida,
                                 progreso=lambda m: print("  %s" % m))
    except RuntimeError as exc:
        # El puente ya traduce el fallo del contenedor a un mensaje util
        # (incluye las ultimas lineas de ERROR del log de Raidionics), que es
        # donde esta la causa real: `main.py` no propaga los codigos de error.
        print("Raidionics fallo:\n%s" % exc)
        return 1
    if resumen is None:
        print("No se pudo ejecutar: %s" % puente.diagnostico())
        return 1
    print("\nSegmentacion completada (modelo %s, secuencia %s)."
          % (resumen.get("modelo"), resumen.get("secuencia")))
    for mascara in resumen.get("mascaras", []):
        print("  mascara: %s" % mascara)
    for informe in resumen.get("informes", []):
        print("  informe: %s" % informe)
    if not resumen.get("informes"):
        print("  (sin informe clinico: este pipeline solo segmenta)")
    print("\nResultados en %s" % salida)


# =============================================================================
# RADIOMICS: extraccion con el motor propio
# =============================================================================
def cmd_radiomics(args):
    """
    Extrae descriptores de un NIfTI y exporta el informe.

    Es el motor PROPIO, sin Docker: funciona siempre que estén SimpleITK,
    numpy y scipy. `raidionics` es el contraste externo, no un sustituto.

    `extraer_radiomics` NO acepta rutas sino el array ya cargado y un
    diccionario de ROI, asi que aqui se hace esa parte: `cargar_volumen` para
    la imagen y `de_nifti` + `estructura_mascara` para las ROI. Sin una
    mascara solo se puede calcular sobre el volumen entero.
    """
    _preparar_rutas()
    if not asegurar(DEPENDENCIAS_RADIOMICS, "radiomics"):
        return 1

    from radiomics import (cargar_volumen, de_nifti, magmas_braTS,
                           extraer_radiomics, construir_tabla, exportar_informe)

    if args.estudio is None:
        print("Falta la imagen. Uso: radiomics <estudio.nii.gz> [mascara.nii.gz]")
        return 2

    try:
        volumen, _spacing, _meta = cargar_volumen(args.estudio)
    except (OSError, FileNotFoundError) as exc:
        print("No se pudo leer la imagen %s: %s" % (args.estudio, exc))
        return 1
    print("Imagen: %s  (%d voxeles)" % (args.estudio, _meta["n_voxeles"]))

    if args.mascara:
        if not os.path.exists(args.mascara):
            print("No existe la mascara: %s" % args.mascara)
            return 1
        # BraTS codifica ET=1, NETC=2, SNFH=3. `magmas_braTS` es el traductor
        # que convierte cualquiera de esos casos (multietiqueta o binaria) a las
        # ROI de Raids-RADS, ya descartando las vacias, asi que devuelve el
        # diccionario final y no hace falta pasarle nada mas.
        tumor = de_nifti(args.mascara, (1, 2, 3), "tumor_brats")
        rois = magmas_braTS(tumor_roi=tumor)
        print("ROI detectadas: %s" % (", ".join(sorted(rois)) or "ninguna"))
    else:
        # Sin mascara no hay ROI: se calcula sobre todos los voxeles con valor,
        # que es un caso degenerado pero deja el comando utilizable.
        from radiomics.masks import de_array
        rois = {"volumen": de_array((volumen > 0).astype("uint8"),
                                    _spacing, 1, "volumen")}
        print("Sin mascara: se caracteriza el volumen completo.")

    if not rois:
        print("La mascara no contiene ninguna ROI con voxeles.")
        return 1

    print("Extrayendo descriptores...")
    resultados = extraer_radiomics(volumen, rois)
    total = sum(len(v) for v in resultados.values())
    print("ROI: %d, descriptores totales: %d" % (len(resultados), total))

    if args.salida:
        # `exportar_*` trabajan sobre una `RadiomicsTable`, no sobre el dict
        # que devuelve el extractor: hay que envolverlo primero.
        tabla = construir_tabla(resultados, {
            "imagen": os.path.basename(args.estudio),
            "mascara": os.path.basename(args.mascara) if args.mascara else "-",
            "rois": len(resultados),
        })
        print("Informe: %s" % exportar_informe(tabla, args.salida))
    return 0


# =============================================================================
# VERIFICAR: delega en verificacion_integral.py
# =============================================================================
def cmd_verificar(args):
    """Repasa las etapas de `verificacion_integral.py` sin duplicar su logica."""
    script = os.path.join(
        RAIZ, "herramientas", "diagnostico", "verificacion_integral.py")
    if not os.path.exists(script):
        print("No se encuentra %s" % script)
        return 1
    _preparar_rutas()
    comando = [sys.executable, script]
    if args.todo:
        comando.append("--todo")
    if args.ui_real:
        comando.append("--ui-real")
    if args.etapa:
        # En el verificador `--etapa` es `action="append"`, asi que cada
        # invocacion es una opcion con un solo valor: hay que aplanar la lista
        # de listas que produce `nargs="+"` y repetir la opcion por cada etapa.
        for grupo in args.etapa:
            for e in grupo:
                comando += ["--etapa", e]
    return subprocess.call(comando, cwd=PADRE)


# =============================================================================
# UI: ventana PySide6
# =============================================================================
def cmd_ui(_args):
    """
    Abre la ventana principal. VTK se importa DENTRO del subproceso de la app.

    No se importa aqui porque un fallo de VTK debe dejar abrir la ventana (el
    visor ya avisa en su lienzo), no tumbar el lanzador entero.
    """
    _preparar_rutas()
    if not asegurar(DEPENDENCIAS, "la interfaz"):
        print("Se intenta abrir igualmente; puede que falte alguna parte.")
    print("=" * 50)
    print("  NEUROHUB - Neuroimagenes multiplataforma")
    print("=" * 50)
    try:
        from src.ui_qt.app import main as abrir
    except ImportError as exc:
        print("No se pudo importar la interfaz: %s" % exc)
        import traceback
        traceback.print_exc()
        return 1
    return abrir()



    return 0



# =============================================================================
# CLI
# =============================================================================
def construir_parser():
    """
    Parser con un subcomando por funcionalidad.

    `ui` es el valor por defecto y por eso el primer argumento se interpreta a
    mano: si no es un subcomando conocido, se asume que el usuario quiere
    abrir la ventana, que es lo que hacia el launcher antiguo.
    """
    parser = argparse.ArgumentParser(
        prog="launcher.py",
        description="Punto de entrada unico de NEUROHUB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("ui", help="abre la ventana principal (por defecto)")
    sub.add_parser("doctor", help="estado de Python, dependencias y motores")

    p_rad = sub.add_parser("radiomics", help="extrae descriptores de un NIfTI")
    p_rad.add_argument("estudio", nargs="?", help="imagen NIfTI de entrada")
    p_rad.add_argument("mascara", nargs="?", help="mascara NIfTI, si hace falta")
    p_rad.add_argument("--salida", help="carpeta donde exportar el informe")

    p_rai = sub.add_parser("raidionics", help="motor externo en Docker")
    p_rai.add_argument("accion", choices=["estado", "extraer"],
                       help="'estado' diagnostica, 'extraer' ejecuta el motor")
    p_rai.add_argument("estudio", nargs="?", help="imagen NIfTI para 'extraer'")
    p_rai.add_argument("--salida", help="carpeta donde dejar el informe")

    p_ver = sub.add_parser("verificar", help="etapas de verificacion integral")
    p_ver.add_argument("--todo", action="store_true",
                       help="incluye las etapas caras (slicer, paridad, pipeline)")
    p_ver.add_argument("--ui-real", action="store_true",
                       help="abre la ventana Qt de verdad, no offscreen")
    p_ver.add_argument("--etapa", action="append", nargs="+",
                       metavar="ETAPA",
                       help="solo estas etapas (repetible: "
                            "--etapa deps --etapa radiomics)")

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    COMANDOS = {"ui", "doctor", "radiomics", "raidionics", "verificar"}
    # La ayuda tiene que verse completa y no caer en `ui`, que es el valor por
    # defecto: sin este caso, `launcher.py --help` abriria la ventana.
    if argv and argv[0] in ("-h", "--help", "help"):
        construir_parser().print_help()
        return 0
    # Sin subcomando, o con algo que no es un subcomando, se abre la interfaz.
    if not argv or argv[0] not in COMANDOS:
        argv = ["ui"] + argv

    args = construir_parser().parse_args(argv)
    return {
        "ui": cmd_ui,
        "doctor": cmd_doctor,
        "radiomics": cmd_radiomics,
        "raidionics": cmd_raidionics,
        "verificar": cmd_verificar,
    }[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
