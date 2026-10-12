"""
Puente entre la interfaz PySide6 y el pipeline de NEUROHUB.

Este modulo es el UNICO punto de contacto entre la capa de presentacion
(nuevos widgets) y la capa de procesamiento (modulos 01..04,
`segmentacion_completa`, `calidad_mallas`, `data_manager`). La interfaz
nunca importa `vtk`, `SimpleITK` ni `torch`: solo recibe cadenas de log,
progresos y rutas de archivos.

Los pasos replican exactamente el `_run_pipeline` de `main.py`, pero escriben
en los directorios canonicos de `segmentacion_completa`
(`salidas/segmentaciones_ai`, `salidas/mallas`, `salidas/fbx`) para que el
visor 3D existente encuentre los STL sin ninguna conversion.

Ejecucion: el trabajo pesado ocurre en un `QThread` (ver `ejecutar`), y los
resultados se devuelven como senales, de modo que la UI nunca se congela.
"""

import os
import sys
import traceback

from PySide6.QtCore import QObject, Signal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")

# Los modulos del pipeline (`01_procesamiento_dicom`, `03_integrar_brats`, ...)
# tienen nombres numerados y NO son paquetes, asi que no se pueden importar con
# `from src.01_... import ...`. `main.py` los carga metiendo `src` en sys.path y
# aqui se replica exactamente lo mismo; si no, el worker falla con
# "No module named '01_procesamiento_dicom'" aunque el archivo exista.
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

SALIDAS_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")
SEG_AI_DIR = os.path.join(SALIDAS_DIR, "segmentaciones_ai")
MALLAS_DIR = os.path.join(SALIDAS_DIR, "mallas")
FBX_DIR = os.path.join(SALIDAS_DIR, "fbx")
SLICES_DIR = os.path.join(SALIDAS_DIR, "slices_2d")

# Estructuras que el pipeline intenta generar, en el orden en que se dibujan
# en el visor (primero las envolventes, despues las internas).
ESTRUCTURAS_MALLAS = [
    ("cerebro", "brain.nii.gz", "Cerebro"),
    ("craneo", "skull.nii.gz", "Craneo"),
    ("tumor", "tumor_brats.nii.gz", "Tumor"),
    ("aneurisma", "aneurisma_v2.nii.gz", "Aneurisma"),
]

# ---------------------------------------------------------------------------
# MODO DE ANALISIS: ANEURISMA O TUMOR, NUNCA LOS DOS
# ---------------------------------------------------------------------------
# Por que existe esta restriction
# ------------------------------
# Los dos modos no son "dos cosas mas que se pueden pedir": son dos
# hipotesis clinicas DISTINTAS, con criterios opuestos. El pipeline
# anterior hacia las dos cosas a la vez para el mismo caso. Eso tiene dos
# consecuencias malas:
#
#   1. Clinicamente invalido. No se pueden diagnosticar "aneurisma" y "tumor"
#      a la vez: son diagnosticos excluyentes por definicion. Presentar ambos
#      como si fueran hallazgos coexistentes es un error, no una
#      superabundancia de informacion.
#   2. Tecnicamente misleading. La deteccion de aneurismas (que mide
#      dilataciones focales sobre la mascara vascular) y la segmentacion de
#      tumor (que busca una masa en el parenquima) comparten volumen pero no
#      hipotesis: ejecutar las dos sobre el mismo caso produce dos resultados
#      que compiten entre si, y el visor los muestra juntos como si fueran
#      compatibles.
#
# Por eso el modo es EXCLUYENTE por diseno, no por conveniencia: se declara
# cual de los dos se quiere y el pipeline ejecuta ese, y solo ese.
MODO_ANEURISMA = "aneurisma"
MODO_TUMOR = "tumor"
MODOS_VALIDOS = (MODO_ANEURISMA, MODO_TUMOR)

# Estructura que corresponde a cada modo. Se usa para (a) decidir que se
# ejecuta, (b) decidir que se dibuja, y (c) comprobar que no se ha colado la
# otra. La clave es la mascara que produce cada rama.
MODO_ESTRUCTURA = {MODO_ANEURISMA: "aneurisma", MODO_TUMOR: "tumor"}
# Estructura que cada modo PROHIBE encontrar en el caso.
MODO_EXCLUYE = {MODO_ANEURISMA: "tumor", MODO_TUMOR: "aneurisma"}


def normalizar_modo(modo):
    """
    Valida y normaliza el modo pedido. Lanza ValueError si no es valido.

    Se valida aqui y no en la UI para que ningun llamador (interfaz, script o
    linea de comandos) pueda saltarse la restriccion: es la unica puerta.
    """
    if modo is None:
        return None
    limpio = str(modo).strip().lower()
    if limpio == "":
        return None
    if limpio not in MODOS_VALIDOS:
        raise ValueError(
            "Modo de analisis '%s' no valido. Solo se admite uno de: %s. "
            "Aneurisma y tumor son modos EXCLUYENTES: no se pueden ejecutar "
            "los dos en el mismo caso." % (modo, ", ".join(MODOS_VALIDOS)))
    return limpio


def modo_exclusivo(aneurisma, tumor):
    """
    Devuelve el unico modo que hay que ejecutar, deducido de lo que se pide.

    Acepta los dos parametros por comodidad, pero si los dos son True es un
    error de programacion, no un caso valido: se lanza excepcion en vez de
    elegir uno en silencio. Un despliegue accidental de "ejecuta las dos" debe
    fallar de forma visible, no producir un caso con dos diagnosticos.
    """
    a = bool(aneurisma)
    t = bool(tumor)
    if a and t:
        raise ValueError(
            "Se han pedido aneurisma Y tumor a la vez. Los modos son "
            "excluyentes por diseno (ver la nota de MODOS_VALIDOS).")
    if a:
        return MODO_ANEURISMA
    if t:
        return MODO_TUMOR
    return None


PASOS_TOTAL = 6


class PipelineWorker(QObject):
    """Ejecuta el pipeline en segundo plano y emite su avance.

    Vive en un `QThread`. No debe tocar ningun widget: solo senales.
    """

    # (mensaje, nivel) con nivel en INFO/SUCCESS/WARNING/ERROR/HEADER
    log = Signal(str, str)
    # fraccion 0..1 del avance global
    progress = Signal(float)
    # indice de paso (1-based) y su titulo
    step = Signal(int, str)
    # (ok, mensaje) al terminar
    finished = Signal(bool, str)

    def __init__(self, input_path, output_dir=None, generar_slices=True,
                 modo=None):
        """
        `modo` es el modo de analisis: `aneurisma`, `tumor`, o None (ninguno).

        Si se pasan los dos a la vez el constructor falla, en vez de elegir uno.
        Es deliberado: el error tiene que saltar al construir el worker, no a
        mitad del pipeline, cuando ya se ha hecho trabajo de mas.
        """
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir or SEG_AI_DIR
        self.generar_slices = generar_slices
        # Se valida aqui, en la puerta de entrada, para que ningun llamador
        # pueda saltarse la regla de exclusividad.
        self.modo = normalizar_modo(modo)
        self._cancelado = False

    @property
    def hace_aneurisma(self):
        """True si este caso se ejecuta en modo aneurisma."""
        return self.modo == MODO_ANEURISMA

    @property
    def hace_tumor(self):
        """True si este caso se ejecuta en modo tumor."""
        return self.modo == MODO_TUMOR

    # ------------------------------------------------------------------
    def cancelar(self):
        """Solicita la detencion: se comprueba entre pasos."""
        self._cancelado = True

    def _info(self, msg, nivel="INFO"):
        self.log.emit(msg, nivel)

    # ------------------------------------------------------------------
    def run(self):
        """Punto de entrada del hilo. Envolve todo en un try/except."""
        try:
            ok = self._ejecutar_pipeline()
        except Exception as e:  # pragma: no cover - defensivo
            self._info(f"Error inesperado en el pipeline: {e}", "ERROR")
            self._info(traceback.format_exc(), "ERROR")
            ok = False
            mensaje = str(e)
        else:
            mensaje = ("Pipeline completado" if ok
                       else "Pipeline detenido antes de terminar")
        self.progress.emit(1.0)
        self.finished.emit(ok, mensaje)

    def _asegurar_volumen_en_salidas(self, nifti_path):
        """Copia la imagen del paciente a `salidas/volumen_paciente.nii.gz`.

        Se omite si ya esta, si el origen es el mismo fichero o si la copia
        existente es al menos tan reciente como la original: en ese caso ya
        hay una copia valida y reescribirla solo gastaria I/O.
        """
        destino = os.path.join(SALIDAS_DIR, "volumen_paciente.nii.gz")
        try:
            if os.path.exists(destino):
                if (os.path.normcase(os.path.abspath(destino))
                        == os.path.normcase(os.path.abspath(nifti_path))):
                    return
                if os.path.getmtime(destino) >= os.path.getmtime(nifti_path):
                    return
            import shutil
            shutil.copy2(nifti_path, destino)
            self._info(f"Volumen del paciente copiado a {destino}", "INFO")
        except Exception as e:                               # noqa: BLE001
            # No es critico: el pipeline sigue, y el visor 2D cae al modo
            # visor-de-PNG, que es lo que pasaba siempre.
            self._info(f"No se pudo copiar el volumen a las salidas: {e}",
                       "WARNING")

    # ------------------------------------------------------------------
    def _ejecutar_pipeline(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(MALLAS_DIR, exist_ok=True)
        os.makedirs(FBX_DIR, exist_ok=True)

        import importlib
        pipeline_01 = importlib.import_module("01_procesamiento_dicom")
        pipeline_03 = importlib.import_module("03_integrar_brats")

        self._info("=" * 60, "HEADER")
        self._info("INICIANDO PIPELINE COMPLETO", "HEADER")
        self._info("=" * 60, "HEADER")

        # ---------------- Paso 1: resolver volumen de entrada ------------
        self.step.emit(1, "Resolviendo volumen de entrada")
        self._info("[1/6] Resolviendo volumen de entrada...", "PROGRESS")
        self.progress.emit(0.1)
        nifti_path = pipeline_01.resolve_input_volume(
            self.input_path,
            os.path.join(self.output_dir, "volumen_paciente.nii.gz"),
        )
        if not nifti_path or not os.path.exists(nifti_path):
            self._info(f"No se pudo obtener un volumen NIfTI de: {self.input_path}",
                       "ERROR")
            return False
        self._info(f"Volumen: {nifti_path}", "SUCCESS")
        # Se copia la imagen del paciente al directorio de salida. Sin esto,
        # `salidas/segmentaciones_ai` solo contiene etiquetas (una por
        # estructura) y el visor 2D se queda SIN NINGUN volumen real que
        # mostrar: al buscar una imagen, la unica NIfTI que encaja con el
        # patron BraTS `*_t1.nii.gz` es `vertebrae_T1.nii.gz`, una mascara de
        # vertebra. El panel se llenaba de gris con un tumor verde encima y
        # parecia no mostrar la imagen. Es el volumen que se esta segmentando,
        # asi que copiarlo no engorda nada y deja el caso completo.
        self._asegurar_volumen_en_salidas(nifti_path)

        # ---------------- Paso 2: segmentacion AI -------------------------
        if self._cancelado:
            return False
        self.step.emit(2, "Segmentacion AI (TotalSegmentator)")
        self._info("[2/6] Ejecutando segmentacion AI (TotalSegmentator)...", "PROGRESS")
        self.progress.emit(0.3)
        pipeline_01.run_ai_segmentation(nifti_path, self.output_dir, fast_mode=True)
        self._info("Segmentacion AI completada", "SUCCESS")

        # ---------------- Paso 3: modo de analisis (excluyente) -----------
        # Los dos diagnosticos (tumor / aneurisma) son excluyentes: solo se
        # ejecuta el modo pedido. Ver la nota de MODOS_VALIDOS mas arriba.
        if self._cancelado:
            return False
        brain_path = os.path.join(self.output_dir, "brain.nii.gz")
        tumor_path = os.path.join(self.output_dir, "tumor_brats.nii.gz")
        aneurisma_path = os.path.join(self.output_dir, "aneurisma_v2.nii.gz")

        # Una mascara de la OTRA modalidad que venga de una corrida anterior
        # contaminaria el visor: se borra antes de empezar, para que el caso
        # que se muestra sea exactamente el que se ha ejecutado.
        self._limpiar_mascara_del_modo_opuesto()

        if self.hace_tumor:
            self.step.emit(3, "Segmentacion de tumor (BraTS)")
            self._info("[3/4] Modo TUMOR: ejecutando segmentacion de tumor...",
                       "PROGRESS")
            self.progress.emit(0.55)
            pipeline_03.integrate_brats_into_pipeline(nifti_path, self.output_dir)
            if not self._mascara_tiene_voxeles(tumor_path):
                # Respaldo morfologico: mismo criterio que aplica `main.py`.
                self._info("BraTS no produjo una mascara valida: se aplica el "
                           "metodo morfologico de respaldo", "WARNING")
                if os.path.exists(brain_path):
                    try:
                        pipeline_01.generate_tumor_mask(
                            nifti_path, brain_path,
                            os.path.join(self.output_dir,
                                         "tumor_heuristica.nii.gz"))
                    except Exception as e:
                        self._info(f"El respaldo morfologico fallo: {e}",
                                   "WARNING")
            self._info("Segmentacion de tumor completada", "SUCCESS")
        elif self.hace_aneurisma:
            self.step.emit(3, "Deteccion de aneurismas")
            self._info("[3/4] Modo ANEURISMA: no se busca tumor (modos "
                       "excluyentes)", "INFO")
            # NOTA: la deteccion de aneurisma requiere vasos.nii.gz, que ya
            # no se genera en el pipeline (vasculatura eliminada). El modo
            # aneurisma solo funcionara si vasos.nii.gz existe previamente
            # (p.ej. importado de 3D Slicer). Esto es intencionado: el codigo
            # de aneurisma se conserva inerte por decision de diseno.
            vasos_path = os.path.join(self.output_dir, "vasos.nii.gz")
            self.progress.emit(0.7)
            if os.path.exists(vasos_path):
                pipeline_03.improve_aneurysm_detection(
                    nifti_path, vasos_path, aneurisma_path)
                self._info("Deteccion de aneurisma completada", "SUCCESS")
            else:
                self._info("Sin mascara de vasos (vasos.nii.gz): se omite la "
                           "deteccion de aneurismas. La vasculatura ya no se "
                           "genera en el pipeline; importe vasos.nii.gz de "
                           "una fuente externa si necesita este modo.",
                           "WARNING")
        else:
            self.step.emit(3, "Sin modo de analisis")
            self._info("No se ha indicado modo de analisis: se omiten tumor y "
                       "aneurisma. Se procesa solo la anatomia.",
                       "WARNING")

        # ---------------- Paso 4: mallas 3D y vistas 2D ------------------
        if self._cancelado:
            return False
        self.step.emit(4, "Generando modelos 3D")
        self._info("[4/4] Generando modelos 3D...", "PROGRESS")
        self.progress.emit(0.85)
        self._generar_mallas()

        if self.generar_slices:
            self._generar_vistas_2d(nifti_path)

        # Comprobacion de la regla de exclusividad antes de dar el caso por
        # bueno. Si aqui hubiera resultado de las dos modalidades, el caso se
        # marca como fallido: es preferible parar que entregar un caso con dos
        # diagnosticos incompatibles.
        if not self.verificar_exclusividad()[0]:
            return False

        self.progress.emit(0.97)
        self._info("=" * 60, "HEADER")
        self._info("PIPELINE COMPLETADO", "HEADER")
        self._info("=" * 60, "HEADER")
        return True

    # ------------------------------------------------------------------
    def _limpiar_mascara_del_modo_opuesto(self):
        """
        Borra las mascaras de la modalidad que NO se va a ejecutar.

        Sin esto, un caso ejecutado en modo tumor despues de uno ejecutado en
        modo aneurisma (o al reejecutar el mismo caso cambiando de modo)
        acumularia las dos mascaras en `output_dir`, y el visor las dibujaria
        juntas: volveria a aparecer exactamente la situation que los modos
        excluyentes pretenden evitar.

        Solo se borran mascaras, nunca imagenes del paciente: es una limpieza
        de resultados, no de entrada.
        """
        if self.modo is None:
            return
        prohibido = MODO_EXCLUYE[self.modo]
        rutas = {
            MODO_ANEURISMA: [os.path.join(self.output_dir, "aneurisma_v2.nii.gz"),
                              os.path.join(self.output_dir, "aneurisma.nii.gz")],
            MODO_TUMOR: [os.path.join(self.output_dir, "tumor_brats.nii.gz"),
                         os.path.join(self.output_dir, "tumor_heuristica.nii.gz"),
                         os.path.join(self.output_dir, "tumor_heur.nii.gz")],
        }[prohibido]
        for ruta in rutas:
            if os.path.exists(ruta):
                try:
                    os.remove(ruta)
                    self._info("Se descarta la mascara de '%s' de una corrida "
                               "anterior: incompatible con el modo %s"
                               % (prohibido, self.modo), "INFO")
                except OSError as e:
                    self._info(f"No se pudo borrar {os.path.basename(ruta)}: {e}",
                               "WARNING")

    # ------------------------------------------------------------------
    def verificar_exclusividad(self):
        """
        Comprobacion final: en el caso ejecutado no puede haber resultado de
        las dos modalidades.

        Se ejecuta aunque el pipeline se haya limitado por construccion, porque
        es la unica red que detecta un cambio futuro en el codigo que
        reintroduzca la ejecucion de las dos. Devuelve `(ok, detalle)`.
        """
        if self.modo is None:
            return True, "sin modo de analisis: no aplica"
        prohibido = MODO_EXCLUYE[self.modo]
        rutas = {
            MODO_ANEURISMA: [os.path.join(self.output_dir, "aneurisma_v2.nii.gz"),
                              os.path.join(self.output_dir, "aneurisma.nii.gz")],
            MODO_TUMOR: [os.path.join(self.output_dir, "tumor_brats.nii.gz"),
                         os.path.join(self.output_dir, "tumor_heuristica.nii.gz"),
                         os.path.join(self.output_dir, "tumor_heur.nii.gz")],
        }[prohibido]
        encontradas = [r for r in rutas if self._mascara_tiene_voxeles(r)]
        if encontradas:
            detalle = ("Modo %s, pero tambien hay resultado de '%s': %s"
                       % (self.modo, prohibido,
                          ", ".join(os.path.basename(r) for r in encontradas)))
            self._info(detalle, "ERROR")
            return False, detalle
        return True, "modo %s respetado" % self.modo

    # ------------------------------------------------------------------
    def _mascara_tiene_voxeles(self, path):
        """True si la mascara NIfTI existe y no esta vacia."""
        if not path or not os.path.exists(path):
            return False
        try:
            import SimpleITK as sitk
            arr = sitk.GetArrayFromImage(sitk.ReadImage(path))
            return bool((arr > 0).any())
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _generar_mallas(self):
        """Convierte cada mascara disponible en su STL de maxima resolucion.

        Se delega en `segmentacion_completa.generar_mallas_3d`, que ya aplica
        Taubin + control de calidad (`calidad_mallas`), de modo que aqui no se
        reimplementa nada.
        """
        try:
            import segmentacion_completa as sc
        except Exception as e:
            self._info(f"No se pudo importar segmentacion_completa: {e}", "ERROR")
            return

        try:
            resultados = sc.generar_mallas_3d(salida_dir=MALLAS_DIR)
        except Exception as e:
            self._info(f"Error generando mallas: {e}", "ERROR")
            self._info(traceback.format_exc(), "ERROR")
            return

        if not resultados:
            self._info("No se generaron mallas (no hay mascaras validas)", "WARNING")
            return

        for nombre, info in sorted(resultados.items()):
            stl = info.get("stl", "")
            caras = info.get("faces")
            caras_txt = f"{len(caras):,} caras" if caras is not None else ""
            self._info(f"Modelo '{nombre}': {os.path.basename(stl)} {caras_txt}".strip(),
                       "SUCCESS")

    # ------------------------------------------------------------------
    def _generar_vistas_2d(self, nifti_path):
        """Renderiza los tres cortes con el tumor encerrado en un circulo."""
        mask = None
        for cand in ("tumor_brats.nii.gz", "tumor_heuristica.nii.gz",
                     "tumor_heur.nii.gz"):
            ruta = os.path.join(self.output_dir, cand)
            if self._mascara_tiene_voxeles(ruta):
                mask = ruta
                break
        if mask is None:
            self._info("Sin mascara de tumor: no se generan vistas 2D", "WARNING")
            return
        try:
            import importlib
            slices = importlib.import_module("04_slices_2d")
            os.makedirs(SLICES_DIR, exist_ok=True)
            slices.generar_vistas_2d(nifti_path, mask, SLICES_DIR)
            self._info(f"Vistas 2D generadas en {SLICES_DIR}", "SUCCESS")
        except Exception as e:
            self._info(f"No se pudieron generar las vistas 2D: {e}", "WARNING")


# =============================================================================
# MALLA 3D A PARTIR DE LA MÁSCARA DELINEADA A MANO
# =============================================================================
class MeshFromMaskWorker(QObject):
    """Convierte una máscara NIfTI delineada a mano en una malla STL.

    Es el worker del botón "Generar 3D" del visor 2D. Solo ref Surface
    reconstruction: no vuelve a ejecutar TotalSegmentator ni la segmentación de
    tumor, porque la máscara ya está hecha y rehacerla tiraría el trabajo del
    usuario.

    Importa `segmentacion_completa` y `calidad_mallas` (no VTK ni Qt), así que
    puede vivir en el hilo sin tocar la interfaz.
    """

    log = Signal(str, str)
    progress = Signal(float)
    finished = Signal(bool, str)
    # (ruta_stl) al terminar, para que la ventana refresque el visor 3D.
    malla_lista = Signal(str)

    def __init__(self, mascara_path, salida_dir=None, estructura="tumor"):
        super().__init__()
        self.mascara_path = mascara_path
        self.salida_dir = salida_dir or MALLAS_DIR
        self.estructura = estructura
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        try:
            ok, resumen = self._generar()
        except Exception as e:  # pragma: no cover - defensivo
            self.log.emit(f"Error generando la malla: {e}", "ERROR")
            self.log.emit(traceback.format_exc(), "ERROR")
            ok, resumen = False, str(e)
        self.progress.emit(1.0)
        self.finished.emit(ok, resumen)

    # ------------------------------------------------------------------
    def _generar(self):
        if not os.path.exists(self.mascara_path):
            return False, f"No existe la máscara: {self.mascara_path}"
        os.makedirs(self.salida_dir, exist_ok=True)

        self.log.emit("=" * 60, "HEADER")
        self.log.emit(f"Reconstruyendo la superficie de '{self.estructura}' "
                      f"desde la máscara manual", "HEADER")
        self.log.emit("=" * 60, "HEADER")

        import importlib
        try:
            calidad = importlib.import_module("calidad_mallas")
        except ImportError as e:
            return False, f"No se pudo importar calidad_mallas: {e}"

        import SimpleITK as sitk
        import numpy as np

        img = sitk.ReadImage(self.mascara_path)
        arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
        if arr.sum() == 0:
            return False, "La máscara está vacía: no hay nada que reconstruir."

        self.log.emit(f"Máscara: {int(arr.sum()):,} vóxeles, "
                      f"spacing {tuple(round(float(s), 3) for s in img.GetSpacing())}",
                      "INFO")
        self.progress.emit(0.2)

        # `malla_alta_calidad` aplica el refinamiento isótropo, el suavizado
        # gaussiano y Taubin: es el mismo camino que usa el pipeline para el
        # resto de estructuras, así que el tumor manual tiene el mismo acabado
        # que el cerebro y el cráneo.
        verts, faces = calidad.malla_alta_calidad(
            arr, img.GetSpacing(), estructura=self.estructura,
            min_voxels=20, verbose=True)
        self.progress.emit(0.7)

        if len(verts) == 0 or len(faces) == 0:
            return False, "La máscara no produjo geometría (¿escala demasiado fina?)"

        stl = os.path.join(self.salida_dir, f"{self.estructura}.stl")
        if not calidad.malla_a_stl(verts, faces, stl):
            return False, f"No se pudo escribir el STL: {stl}"

        self.log.emit(f"STL generado: {os.path.basename(stl)} "
                      f"({len(faces):,} caras)", "SUCCESS")
        self.log.emit(f"Volumen del tumor: {self._volumen_cm3(arr, img.GetSpacing())}",
                      "INFO")

        self.progress.emit(0.95)
        self.malla_lista.emit(stl)
        return True, f"{self.estructura}.stl generado ({len(faces):,} caras)"

    @staticmethod
    def _volumen_cm3(arr, spacing):
        """Volumen de la máscara en cm3, para el log."""
        import numpy as np
        mm3 = float(arr.sum()) * float(np.prod(spacing[:3]))
        return f"{mm3 / 1000.0:.2f} cm³"


# =============================================================================
# EXPORTACIÓN A FBX
# =============================================================================
# EXPORTACIÓN A FBX
# =============================================================================
class FbxExportWorker(QObject):
    """Convierte las mallas STL de un estudio en archivos FBX.

    Vive tambien en un `QThread`. Delega en
    `01_procesamiento_dicom.export_stl_to_single_fbx`, que ya aplica los
    materiales PBR; aqui solo se orquestan los archivos y se reporta el avance.

    Los parametros PBR se toman de `pbr.PBR_COLORS` filtrando por los nombres de
    argumento que acepta la funcion de exportacion, igual que hacia `_export_fbx`
    de `main.py`.
    """

    log = Signal(str, str)
    progress = Signal(float)
    finished = Signal(bool, str)     # (ok, resumen)

    # Argumentos que acepta export_stl_to_single_fbx.
    FBX_KW = ("color_rgba", "roughness", "metallic", "emission",
              "subsurface", "subsurface_color")

    def __init__(self, stl_dir=None, fbx_dir=None, estructuras=None):
        super().__init__()
        self.stl_dir = stl_dir or MALLAS_DIR
        self.fbx_dir = fbx_dir or FBX_DIR
        # Si se indica, solo se exportan esas estructuras (en ese orden).
        self.estructuras = list(estructuras) if estructuras else None
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        try:
            ok, resumen = self._exportar()
        except Exception as e:  # pragma: no cover - defensivo
            self.log.emit(f"Error exportando a FBX: {e}", "ERROR")
            self.log.emit(traceback.format_exc(), "ERROR")
            ok, resumen = False, str(e)
        self.progress.emit(1.0)
        self.finished.emit(ok, resumen)

    # ------------------------------------------------------------------
    def _stl_disponibles(self):
        """[(nombre, ruta)] de los STL a exportar, en orden estable."""
        if not os.path.isdir(self.stl_dir):
            return []
        archivos = [f for f in sorted(os.listdir(self.stl_dir))
                    if f.lower().endswith(".stl")]
        if self.estructuras:
            # Se respeta el orden pedido (capas visibles) y se ignoran las
            # estructuras que no tengan STL en disco.
            por_base = {os.path.splitext(f)[0].lower(): f for f in archivos}
            orden = []
            for key in self.estructuras:
                base = os.path.splitext(os.path.basename(str(key)))[0].lower()
                if base in por_base and por_base[base] not in orden:
                    orden.append(por_base[base])
            return [(f, os.path.join(self.stl_dir, f)) for f in orden]
        return [(f, os.path.join(self.stl_dir, f)) for f in archivos]

    def _params_de(self, nombre_stl):
        """Parametros PBR de una malla, por nombre de archivo."""
        from .pbr import PBR_COLORS, PBR_ALIASES

        base = os.path.splitext(nombre_stl)[0].lower()
        canon = PBR_ALIASES.get(base, base)
        meta = PBR_COLORS.get(canon) or PBR_COLORS.get(base)
        if not meta:
            return {}
        return {k: v for k, v in meta.items() if k in self.FBX_KW}

    # ------------------------------------------------------------------
    def _exportar(self):
        import importlib
        pipeline_01 = importlib.import_module("01_procesamiento_dicom")

        stls = self._stl_disponibles()
        if not stls:
            self.log.emit("No hay modelos STL para exportar.", "WARNING")
            return False, "No hay modelos STL para exportar"

        os.makedirs(self.fbx_dir, exist_ok=True)
        self.log.emit("=" * 60, "HEADER")
        self.log.emit(f"EXPORTACION A FBX ({len(stls)} mallas)", "HEADER")
        self.log.emit("=" * 60, "HEADER")

        exportadas = []
        for i, (nombre, ruta) in enumerate(stls):
            if self._cancelado:
                return False, f"Exportacion cancelada ({len(exportadas)} listas)"
            self.progress.emit(i / len(stls))
            self.log.emit(f"Exportando {nombre}...", "PROGRESS")

            fbx_path = os.path.join(
                self.fbx_dir, os.path.splitext(nombre)[0] + ".fbx")
            try:
                # FIDELIDAD CLINICA: se exporta la malla en su resolucion
                # NATIVA (sin decimar) para preservar el detalle anatomico.
                pipeline_01.export_stl_to_single_fbx(
                    ruta, fbx_path, **self._params_de(nombre))
            except Exception as e:
                self.log.emit(f"No se pudo exportar {nombre}: {e}", "ERROR")
                continue

            self.log.emit(f"FBX generado: {os.path.basename(fbx_path)}", "SUCCESS")
            exportadas.append(fbx_path)

        resumen = (f"{len(exportadas)} FBX exportados" if exportadas
                   else "No se genero ningun FBX")
        return bool(exportadas), resumen
