"""
Puente con Raidionics en Docker, el otro motor de radiomics posible.

`slicer_bridge` reconstruye superficies con 3D Slicer; este hace lo propio
con la suite clinica de Raidionics (`raidionics-core`), que es la que produce
el informe por ROI tal y como lo leeria un radiologo. Es el motor de
referencia con el que contrastar el motor propio de `extract.py`.

COMO SE HABLA CON RAIDIONICS
----------------------------
Raidionics tiene un cliente oficial, pero este puente NO lo usa: se habla con
el contenedor por el mismo mecanismo de `slicer_bridge`, un proceso externo y
archivos NIfTI en disco. Las razones son practicas:

  * el cliente oficial arrastra la API de Raidionics, que cambia entre
    versiones, mientras que el NIfTI en disco es un contrato estable,
  * el contenedor se puede correr con `docker run` sin montar un servidor,
  * el motor propio ya usa NIfTI, asi que el resultado se puede comparar
    descriptor a descriptor sin conversion alguna.

REQUISITOS
----------
Docker Desktop debe estar INSTALADO y con el daemon EN MARCHA. En una maquina
sin virtualizacion habilitada (WSL2 lo necesita) `docker run` falla con un 500
del socket, y eso NO es un fallo de radiomics: por eso `disponible()` distingue
"no hay docker" de "docker no responde" en vez de asumir lo contrario.

CONTRATO REAL (verificado con una prueba de humo, no de documentacion)
----------------------------------------------------------------------
Todo lo de este bloque se comprobio ejecutando el contenedor, porque la
documentacion publica no lo describe y los supuestos iniciales eran FALSOS:

  * Imagen. NO existe `raidionics/radiomics`. Las imagenes oficiales viven en
    el namespace `dbouget`:
        - `dbouget/raidionics-rads`     -> segmentacion + informes neuro
        - `dbouget/raidionics-segmenter`-> solo segmentacion
        - `dbouget/raidionics-val`      -> validacion
    Aqui se usa `raidionics-rads`, que es la unica que trae el generador de
    informes clinicos. La etiqueta se fija a una version concreta para que el
    resultado sea reproducible.

  * Interfaz. NO hay subcomando `suite`. El entrypoint de la imagen es
        python3 /workspace/raidionics_rads_lib/main.py
    y su unica opcion es un fichero de configuracion:
        main.py -c <config.ini> [-v debug|info|warning|error]
    Anyadir `suite` o rutas de imagen a la llamada hace que el contenedor termine
    sin hacer nada, sin error visible: ese era el fallo silencioso del puente.

  * Configuracion. Es un INI (no JSON) escrito con `configparser`, con las
    secciones `Default`, `System` y `Runtime`. Los campos que importan son
    `input_folder`, `output_folder`, `model_folder` y `pipeline_filename`.

  * Pipeline. Es un JSON aparte, referenciado desde `pipeline_filename`, con
    pasos numerados. Un paso de segmentacion NECESITA un paso previo
    `Model selection` que declara el modelo: es el que genera el paso
    `Segmentation` real. Sin el, el pipeline "se ejecuta" en 0.01 s y no
    escribe ninguna mascara.

  * Modelos. La imagen NO los trae. Hay que descargarlos de las releases de
    `raidionics/Raidionics-models` y descomprimirlos en `model_folder`, con la
    forma `<model_folder>/<Modelo>/` conteniendo `pipeline.json`,
    `pre_processing.ini` y `<timestamp>/model.onnx`.

  * Estructura de paciente. EXIGIDA, y no en la documentacion:
        <input_folder>/mri_sequences.csv     (opcional pero necesario para
                                              fijar la secuencia; sin el, el
                                              paso dice "No radiological volume")
        <input_folder>/<T0|T1|...>/raw/*.nii.gz
    El subdirectorio `raw` solo se lee si `caller=raidionics` en la config.

  * Salida. NO se produce un `data.json`. Raidionics escribe, dentro de
    `output_folder`:
        <output_folder>/<T0>/<volumen>_annotation-<Clase>_<Modelo>.nii.gz
        <output_folder>/<T0>/<volumen>_label-<Clase>.nii.gz
        <output_folder>/reporting/<T0>/neuro_clinical_report.json
        <output_folder>/executed_pipeline.json
    `resumen_informe()` por eso busca informes de `reporting/`, no `data.json`.

  * Salida del proceso. `main.py` captura las excepciones y las registra, asi
    que el contenedor devuelve CODIGO 0 aunque el pipeline falle. Comprobar solo
    el `returncode` daria falsos positivos: hay que verificar que aparecio una
    salida esperada.
"""

import configparser
import json
import os
import shutil
import subprocess
import tempfile

# Suite clinica de Raidionics. La etiqueta se fija para que el informe sea
# reproducible: `latest` cambiaria los valores entre dos ejecuciones.
IMAGEN = os.environ.get("NEUROHUB_RAIDIONICS_IMAGE",
                        "dbouget/raidionics-rads:v1.3.2-py39-cpu")

# Modelos que se descargan aparte, desde las releases de Raidionics-models.
# El sufijo de release se fija igual que la imagen: los modelos estan versionados
# junto al software y mezclarlos produce fallos de preprocesado silenciosos.
RELEASE_MODELOS = "v1.3.0-rc"
BASE_MODELOS = ("https://github.com/raidionics/Raidionics-models/releases/"
                "download/%s/" % RELEASE_MODELOS)

# Modelo por defecto: segmentacion de cerebro en RM, la unica combinacion
# verificada end-to-end con una prueba de humo real.
MODELO_CEREBRO = "MRI_Brain"
MODELO_CEREBRO_ZIP = "Raidionics-MRI_Brain-v13.zip"
MODELO_TUMOR = "MRI_TumorCore"
MODELO_TUMOR_ZIP = "Raidionics-MRI_TumorCore-v13.zip"

# Secuencia de RM que espera el modelo de cerebro. Se puede cambiar, pero
# entonces el modelo debe ser el entrenado para esa secuencia.
SECUENCIA_POR_DEFECTO = os.environ.get("NEUROHUB_RAIDIONICS_SEQUENCE", "T1-CE")

# Dentro del contenedor. El workspace es fijo en la imagen.
RAIZ_CONTENEDOR = "/workspace/raidionics_rads_lib"
CONFIG_CONTENEDOR = "/workspace/neurohub/rads_config.ini"
PIPELINE_CONTENEDOR = "/workspace/neurohub/pipeline.json"
RECURSOS_CONTENEDOR = "/workspace/neurohub/recursos"
# Espera maxima: la inferencia de un craneo completo tarda del orden de minutos
# en CPU, y mas si la imagen tiene que descargarse la primera vez.
TIMEOUT_SEGUNDOS = 1800
# Margen para la comprobacion de salud del daemon. El proxy de Docker Desktop
# reintenta antes de rendirse y `docker info` puede tardar casi un minuto en
# devolver el 500 cuando la virtualizacion esta desactivada.
TIMEOUT_INFO = 90

# Sentinel para "todavia no se ha preguntado", distinto de None ("va bien").
_SIN_PREGUNTAR = object()
_CACHE_DOCKER = _SIN_PREGUNTAR




def ruta_docker():
    """Ruta al ejecutable de docker, o None si no esta en el PATH."""
    import shutil
    return shutil.which("docker") or shutil.which("docker.exe")


def _consultar_docker():
    """
    Estado del daemon. None si funciona, o un texto con el motivo del fallo.

    Devolver el MOTIVO y no un booleano es lo que permite que `diagnostico()`
    diga que falta sin repetir la llamada, que contra el proxy de Docker
    Desktop tarda casi un minuto.

    El resultado se cachea: cuando el daemon esta parado, `docker info` tarda
    ~45 s en rendirse, y llamarlo una vez por cada pregunta haria que un simple
    `doctor` tardase varios minutos. El estado del daemon no cambia de un
    segundo a otro, asi que una sola comprobacion por proceso es suficiente; si
    se encendera Docker con el programa en marcha, `refrescar_docker()` lo
    vuelve a preguntar.
    """
    global _CACHE_DOCKER
    if _CACHE_DOCKER is not _SIN_PREGUNTAR:
        return _CACHE_DOCKER
    _CACHE_DOCKER = _preguntar_docker()
    return _CACHE_DOCKER


def refrescar_docker():
    """Olvida el resultado cacheado, para volver a preguntar al daemon."""
    global _CACHE_DOCKER
    _CACHE_DOCKER = _SIN_PREGUNTAR


def _preguntar_docker():
    if ruta_docker() is None:
        return ("docker no esta instalado o no esta en el PATH; el motor "
                "propio de radiomics sigue funcionando")
    try:
        p = subprocess.run([ruta_docker(), "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=TIMEOUT_INFO)
    except subprocess.TimeoutExpired:
        return "docker no responde: el daemon esta colgado"
    except (OSError, subprocess.SubprocessError) as exc:
        return "docker no se puede ejecutar: %s" % exc
    if p.returncode == 0 and (p.stdout or "").strip():
        return None                      # todo bien
    salida = ((p.stderr or "") + (p.stdout or "")).lower()
    if ("500" in salida or "hyper-v" in salida or "virtualizacion" in salida
            or "not running" in salida or "pipe" in salida):
        return ("el daemon de Docker esta apagado o no puede arrancar. En "
                "Windows casi siempre es la virtualizacion (WSL2 la "
                "necesita): activa 'Plataforma de maquina virtual' y "
                "reinicia. El motor propio de radiomics sigue funcionando")
    return "docker info fallo: %s" % ((p.stderr or "").strip()[:200] or "?")


def disponible():
    """
    True si se puede LLEGAR a ejecutar un contenedor.

    No basta con que el binario exista: Docker Desktop puede estar instalado y
    tener el daemon apagado, y en ese caso `docker run` falla. La comprobacion
    real es un `docker info`, con un margen holgado porque el proxy reintenta
    antes de rendirse; un timeout aqui significa daemon parado, no puente roto.
    """
    return _consultar_docker() is None


def diagnostico():
    """
    Explica por que Raidionics no se puede usar, para la consola y la UI.

    Distingue los fallos que se dan en la practica y que tienen causas muy
    distintas: no hay binario, el daemon esta apagado, o el daemon devuelve
    error (tipicamente por virtualizacion desactivada). None si todo va bien.
    """
    return _consultar_docker()




def _comando(extra_volumenes):
    """Argumentos comunes del `docker run`: montajes y nada de red."""
    cmd = [ruta_docker(), "run", "--rm"]
    for origen, destino in extra_volumenes:
        cmd += ["-v", "%s:%s" % (os.path.abspath(origen), destino)]
    return cmd


# ---------------------------------------------------------------------------
# MODELOS
# ---------------------------------------------------------------------------
def modelo_descargado(modelo, destino_modelos):
    """True si el modelo ya esta en disco, con su ONNX y su `pre_processing.ini`."""
    base = os.path.join(destino_modelos, modelo)
    return (os.path.isfile(os.path.join(base, "pipeline.json"))
            and os.path.isfile(os.path.join(base, "pre_processing.ini"))
            and os.path.isdir(os.path.join(base, "0")))


def descargar_modelo(modelo, zip_modelo, destino_modelos, progreso=None):
    """
    Baja el modelo de las releases oficiales y lo descomprime en `destino_modelos`.

    La imagen de Docker NO incluye los pesos: son cientos de MB que viven en
    `raidionics/Raidionics-models`. Sin este paso el pipeline arranca y no
    segmenta nada.

    Se descarga solo si no esta ya, y de forma atomica (a una carpeta temporal
    que se renombra al final) para no dejar un modelo a medias que la proxima
    ejecucion daria por bueno.
    """
    if modelo_descargado(modelo, destino_modelos):
        return True
    os.makedirs(destino_modelos, exist_ok=True)

    import io
    import urllib.request
    import zipfile

    url = BASE_MODELOS + zip_modelo
    if progreso:
        progreso("Descargando el modelo %s (solo la primera vez)..." % modelo)
    try:
        with urllib.request.urlopen(url, timeout=1800) as respuesta:
            datos = respuesta.read()
    except Exception as exc:
        raise RuntimeError("No se pudo descargar el modelo %s desde %s: %s"
                           % (modelo, url, exc))

    temporal = os.path.join(destino_modelos, "_tmp_%s" % modelo)
    if os.path.isdir(temporal):
        shutil.rmtree(temporal)
    os.makedirs(temporal, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(datos)) as archivo:
        archivo.extractall(temporal)

    origen = os.path.join(temporal, modelo)
    if not os.path.isdir(origen):
        raise RuntimeError("El zip de %s no contiene la carpeta %s/"
                           % (zip_modelo, modelo))
    destino = os.path.join(destino_modelos, modelo)
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    shutil.move(origen, destino)
    shutil.rmtree(temporal, ignore_errors=True)
    return modelo_descargado(modelo, destino_modelos)


def _escribir_config(destino, input_folder, output_folder, model_folder,
                     pipeline_filename, caller="raidionics"):
    """
    Escribe el `.ini` de configuracion que espera el entrypoint.

    Se escribe con `configparser` en vez de a mano porque es lo que lee la
    libreria. `caller=raidionics` es lo que hace que se lea el subdirectorio
    `raw/` de cada timestamp; con cualquier otro valor no se encontrarian los
    volumenes.
    """
    config = configparser.ConfigParser()
    config.add_section("Default")
    config.set("Default", "task", "neuro_diagnosis")
    config.set("Default", "caller", caller)

    config.add_section("System")
    config.set("System", "gpu_id", "-1")
    config.set("System", "acceleration", "cpu")
    config.set("System", "input_folder", input_folder)
    config.set("System", "output_folder", output_folder)
    config.set("System", "model_folder", model_folder)
    config.set("System", "pipeline_filename", pipeline_filename)

    config.add_section("Runtime")
    config.set("Runtime", "reconstruction_method", "thresholding")
    config.set("Runtime", "reconstruction_order", "resample_first")
    config.set("Runtime", "use_stripped_data", "False")

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as archivo:
        config.write(archivo)
    return destino


def _escribir_pipeline_segmentacion(destino, modelo, secuencia, timestamp=0):
    """
    Escribe el pipeline JSON de UNA segmentacion.

    El paso 1 es `Model selection`, NO `Segmentation`. Es un detalle que no
    aparece en la documentacion pero que lo cambia todo: `Model selection` es lo
    que genera el paso `Segmentation` real a partir del modelo. Si se escribe
    `Segmentation` directamente, el pipeline se ejecuta en ~0.01 s, anuncia
    "1 steps" y no produce ninguna mascara, sin dar ningun error.
    """
    pasos = {
        "1": {
            "task": "Model selection",
            "model": modelo,
            "timestamp": timestamp,
            "format": "thresholding",
            "description": "Model selection for %s" % modelo,
        }
    }
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="\n") as archivo:
        json.dump(pasos, archivo, indent=4, sort_keys=True)
    return destino


def _reescribir_rutas_a_contenedor(ruta_config, raiz_anfitrion):
    """
    Reescribe en la config las rutas del ANFITRION por las del CONTENEDOR.

    Este es el punto donde fallaba el puente: la config se creaba con rutas de
    Windows, y dentro del contenedor esas rutas no existen. El contenedor
    devolvia el mensaje de "falta el fichero de configuracion" y terminaba con
    codigo 0, sin escribir ninguna mascara.

    Se hace sobre el fichero ya escrito, en vez de construir el INI con las
    rutas ya correctas, para que el fichero que queda en disco sea exactamente
    el que lee el contenedor y se pueda inspeccionar sin docker.
    """
    import re

    with open(ruta_config, encoding="utf-8") as archivo:
        texto = archivo.read()

    def _sustituye(marca):
        ruta = marca.group(2).strip()
        if not ruta:
            return marca.group(0)
        try:
            relativo = os.path.relpath(ruta, raiz_anfitrion)
        except ValueError:          # distinta unidad: no se puede traducir
            return marca.group(0)
        if relativo.startswith(".."):
            return marca.group(0)
        destino = os.path.join(RECURSOS_CONTENEDOR, relativo)
        return "%s%s" % (marca.group(1), destino.replace("\\", "/"))

    for clave in ("input_folder", "output_folder", "model_folder",
                  "pipeline_filename"):
        patron = re.compile(r"^(\s*%s\s*=\s*)(\S.*)$" % clave,
                            re.IGNORECASE | re.MULTILINE)
        texto = patron.sub(_sustituye, texto)

    with open(ruta_config, "w", encoding="utf-8") as archivo:
        archivo.write(texto)
    return ruta_config


def preparar_caso(estudio, salida, modelo=MODELO_CEREBRO,
                  zip_modelo=MODELO_CEREBRO_ZIP,
                  secuencia=SECUENCIA_POR_DEFECTO, progreso=None):
    """
    Monta en `salida` toda la estructura que Raidionics espera.

    Estructura creada:

        <salida>/modelos/<Modelo>/...        pesos (descargados si faltan)
        <salida>/paciente/inputs/mri_sequences.csv
        <salida>/paciente/inputs/T0/raw/<volumen>.nii.gz
        <salida>/resultados/                  output_folder
        <salida>/rads_config.ini
        <salida>/pipeline.json

    El `raw/` y el `mri_sequences.csv` son obligatorios y no aparecen en la
    documentacion. Sin el CSV, Raidionics no sabe a que secuencia pertenece el
    volumen y el paso responde "No radiological volume for {... T1-CE ...}".
    El nombre del CSV va SIN extension: la busqueda interna compara
    `basename(ruta).split('.')[0]`, asi que `input0.nii.gz` no casa y `input0` si.
    """
    estudio = os.path.abspath(estudio)
    if not os.path.isfile(estudio):
        raise RuntimeError("No existe el volumen de entrada: %s" % estudio)

    raiz = os.path.abspath(salida)
    modelos = os.path.join(raiz, "modelos")
    inputs = os.path.join(raiz, "paciente", "inputs")
    t0 = os.path.join(inputs, "T0")
    resultados = os.path.join(raiz, "resultados")
    for carpeta in (modelos, t0, os.path.join(t0, "raw"), resultados):
        os.makedirs(carpeta, exist_ok=True)

    if progreso:
        progreso("Preparando el modelo %s..." % modelo)
    descargar_modelo(modelo, zip_modelo, modelos, progreso=progreso)

    base = os.path.basename(estudio)
    for sufijo in (".nii.gz", ".nii", ".gz"):
        if base.lower().endswith(sufijo):
            base = base[: -len(sufijo)]
            break
    destino_volumen = os.path.join(t0, "raw", base + ".nii.gz")
    shutil.copyfile(estudio, destino_volumen)

    with open(os.path.join(inputs, "mri_sequences.csv"), "w",
              encoding="utf-8", newline="") as archivo:
        archivo.write("File,MRI sequence\n%s,%s\n" % (base, secuencia))

    config = _escribir_config(
        os.path.join(raiz, "rads_config.ini"),
        input_folder=inputs,
        output_folder=resultados,
        model_folder=modelos,
        pipeline_filename=os.path.join(raiz, "pipeline.json"),
    )
    # La config se escribe con rutas del anfitrion (para poder leerla y
    # diagnosticarla sin docker) y se traduce aqui a rutas del contenedor, que
    # es como la lee el entrypoint.
    _reescribir_rutas_a_contenedor(config, raiz)
    _escribir_pipeline_segmentacion(os.path.join(raiz, "pipeline.json"),
                                    modelo=modelo, secuencia=secuencia)
    return {"raiz": raiz, "modelos": modelos, "inputs": inputs,
            "resultados": resultados, "volumen": destino_volumen,
            "modelo": modelo, "secuencia": secuencia}


def _mascaras_generadas(resultados):
    """Rutas de las mascaras NIfTI que Raidionics ha escrito."""
    encontradas = []
    for raiz, _dirs, archivos in os.walk(resultados):
        for nombre in archivos:
            if nombre.endswith(".nii.gz") and (
                    "_annotation-" in nombre or "_label-" in nombre):
                encontradas.append(os.path.join(raiz, nombre))
    return sorted(encontradas)


def _informes_generados(resultados):
    """Rutas de los informes clinicos JSON que Raidionics ha escrito."""
    encontrados = []
    for raiz, _dirs, archivos in os.walk(resultados):
        for nombre in archivos:
            bajo = nombre.lower()
            if bajo.endswith(".json") and ("report" in bajo or "data" in bajo):
                encontrados.append(os.path.join(raiz, nombre))
    return sorted(encontrados)


def imagen_presente():
    """True si la imagen ya esta descargada, para no hacer pull en cada llamada."""
    if ruta_docker() is None:
        return False
    try:
        p = subprocess.run([ruta_docker(), "image", "inspect", IMAGEN],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def ejecutar(preparado, timeout=None, verbose="info", progreso=None):
    """
    Lanza el contenedor sobre un caso ya preparado y devuelve un resumen.

    NO se conforma con el codigo de salida del contenedor. `main.py` captura
    las excepciones y las registra en el log, asi que devuelve 0 aunque el
    pipeline haya fallado por dentro. Un "returncode == 0" aqui no demuestra
    nada: la unica comprobacion fiable es que haya aparecido una salida
    esperada en `resultados`.
    """
    raiz = preparado["raiz"]
    cmd = _comando([(raiz, RECURSOS_CONTENEDOR)])
    # La imagen define ENTRYPOINT `python3 .../main.py`; hay que pasarle el
    # config como argumento, porque el entrypoint no acepta rutas por defecto.
    #
    # La ruta se concatena a mano y NO con `os.path.join`: en Windows esa funcion
    # devuelve `\\` como separador, y una ruta de Linux con barras invertidas no
    # existe dentro del contenedor. `main.py` responde entonces con el mensaje de
    # uso y sale con codigo 0, sin error visible.
    config_en_contenedor = "%s/rads_config.ini" % RECURSOS_CONTENEDOR.rstrip("/")
    cmd += [IMAGEN, "-c", config_en_contenedor, "-v", verbose]
    if progreso:
        progreso("Ejecutando Raidionics en Docker (imagen: %s)..." % IMAGEN)
    try:
        proceso = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=timeout or TIMEOUT_SEGUNDOS)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Raidionics supero el limite de %ds"
                           % (timeout or TIMEOUT_SEGUNDOS))
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("No se pudo lanzar docker: %s" % exc)

    log = (proceso.stderr or "") + (proceso.stdout or "")
    mascaras = _mascaras_generadas(preparado["resultados"])
    informes = _informes_generados(preparado["resultados"])

    if mascaras:
        return {"ok": True, "mascaras": mascaras, "informes": informes,
                "log": log, "returncode": proceso.returncode,
                "modelo": preparado.get("modelo"),
                "secuencia": preparado.get("secuencia")}

    # Sin salida: se busca el motivo real en el log, que es donde Raidionics
    # deja los errores aunque el contenedor devuelva 0.
    errores = [linea for linea in log.splitlines()
               if "error" in linea.lower()]
    detalle = ("\n".join(errores[-6:]) if errores
               else log.strip()[-500:] or "sin salida en el log")
    raise RuntimeError(
        "Raidionics no escribio ninguna mascara (el contenedor devolvio %d, "
        "pero el pipeline fallo por dentro).\n%s"
        % (proceso.returncode, detalle))


def extraer(estudio, salida, modelo=MODELO_CEREBRO,
            zip_modelo=MODELO_CEREBRO_ZIP, secuencia=SECUENCIA_POR_DEFECTO,
            timeout=None, progreso=None):
    """
    Lanza Raidionics sobre un NIfTI y devuelve un resumen con las mascaras.

    Atajo que encadena `preparar_caso` + `ejecutar`. Se mantiene la firma
    `(estudio, salida)` del puente anterior para no obligar a cambiar a los
    llamadores, pero ahora devuelve un diccionario con el detalle, en vez de
    asumir que existe un `data.json`.
    """
    if not disponible():
        return None
    preparado = preparar_caso(estudio, salida, modelo=modelo,
                              zip_modelo=zip_modelo, secuencia=secuencia,
                              progreso=progreso)
    return ejecutar(preparado, timeout=timeout, progreso=progreso)


def extraer_temporal(estudio, timeout=None, **opciones):
    """Atajo para pruebas: extrae en una carpeta temporal y devuelve el resumen."""
    tmp = tempfile.mkdtemp(prefix="neurohub_raidionics_")
    return extraer(estudio, tmp, timeout=timeout, **opciones) or tmp


def resumen_informe(carpeta):
    """
    Lee el informe clinico que deja Raidionics y lo devuelve como diccionario.

    A diferencia del puente anterior, NO busca un `data.json`: Raidionics no
    escribe ninguno. Busca los informes reales en `reporting/`, y si no hay
    ninguno devuelve las mascaras, para que al menos se vea que la
    segmentacion si llego a correr.
    """
    if not os.path.isdir(carpeta):
        return {"error": "La carpeta %s no existe" % carpeta}
    informes = _informes_generados(carpeta)
    if informes:
        with open(informes[0], encoding="utf-8") as f:
            return json.load(f)
    mascaras = _mascaras_generadas(carpeta)
    if mascaras:
        return {"segmentacion": "sin informe clinico",
                "mascaras": [os.path.basename(m) for m in mascaras]}
    return {"error": "Raidionics no escribio informe ni mascaras en %s" % carpeta}
