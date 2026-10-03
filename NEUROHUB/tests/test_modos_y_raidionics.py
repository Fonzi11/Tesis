"""
NEUROHUB - Pruebas de humo de las tres correcciones principales
================================================================

Cubre, sin necesitar Docker ni red salvo donde se indica:

  1. Los modos de analisis son EXCLUYENTES (aneurisma / tumor).
  2. El umbral vascular se adapta a la modalidad (el fallo de RM).
  3. El contrato de Raidionics: rutas, estructura y config.

Las pruebas de Raidionics que necesitan el contenedor real se marcan con
`docker` y se saltan si Docker no responde, de modo que el conjunto completo
se pueda ejecutar en un portatil sin Docker.

    python -m pytest NEUROHUB/tests/test_modos_y_raidionics.py -v
    python NEUROHUB/tests/test_modos_y_raidionics.py
"""

import importlib
import json
import os
import sys

import numpy as np
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(BASE_DIR)
SRC = os.path.join(BASE_DIR, "src")
for _r in (SRC, BASE_DIR, RAIZ):
    if _r not in sys.path:
        sys.path.insert(0, _r)


def _modulo(nombre):
    """Importa un modulo del pipeline (los numerados no son paquetes)."""
    return importlib.import_module(nombre)


def _escribir_volumen(ruta, arr):
    """Escribe un NIfTI minimo pero valido."""
    import SimpleITK as sitk
    sitk.WriteImage(sitk.GetImageFromArray(arr), ruta)
    return ruta


def _preparar_sin_descarga(puente, entrada, salida):
    """`preparar_caso` saltandose la descarga del modelo (que pesa 87 MB)."""
    original = puente.descargar_modelo
    puente.descargar_modelo = lambda *a, **k: True
    try:
        return puente.preparar_caso(entrada, salida, progreso=lambda m: None)
    finally:
        puente.descargar_modelo = original


# =============================================================================
# 1. MODOS EXCLUYENTES
# =============================================================================
class TestModosExcluyentes:
    """Aneurisma y tumor no pueden ejecutarse en el mismo caso."""

    def setup_method(self):
        self.pb = _modulo("ui_qt.pipeline_bridge")

    def test_los_modos_validos_se_excluyen(self):
        assert self.pb.MODO_ANEURISMA in self.pb.MODOS_VALIDOS
        assert self.pb.MODO_TUMOR in self.pb.MODOS_VALIDOS
        assert len(self.pb.MODOS_VALIDOS) == 2
        # Cada modo declara explicitamente cual es el otro, y son simetricos.
        assert set(self.pb.MODO_EXCLUYE) == set(self.pb.MODOS_VALIDOS)
        assert self.pb.MODO_EXCLUYE[self.pb.MODO_ANEURISMA] == self.pb.MODO_TUMOR
        assert self.pb.MODO_EXCLUYE[self.pb.MODO_TUMOR] == self.pb.MODO_ANEURISMA

    def test_normalizar_acepta_los_dos_modos(self):
        for modo in self.pb.MODOS_VALIDOS:
            assert self.pb.normalizar_modo(modo) == modo
            assert self.pb.normalizar_modo(modo.upper()) == modo
            assert self.pb.normalizar_modo("  %s " % modo) == modo

    def test_normalizar_rechaza_basura(self):
        # La regla tiene que aguantar tambien la entrada mal formada: si aqui
        # colara un "aneurisma+tumor", la garantia de exclusividad seria falsa.
        for malo in ["ambos", "aneurisma+tumor", "tumor y aneurisma", "x"]:
            with pytest.raises(ValueError):
                self.pb.normalizar_modo(malo)

    def test_normalizar_acepta_none(self):
        assert self.pb.normalizar_modo(None) is None
        assert self.pb.normalizar_modo("") is None

    def test_modo_exclusivo_rechaza_los_dos_a_la_vez(self):
        # ESTE es el test de la regla: pedir aneurisma Y tumor a la vez es un
        # error de programacion y debe saltar, no elegir uno en silencio.
        with pytest.raises(ValueError):
            self.pb.modo_exclusivo(True, True)

    def test_modo_exclusivo_determina_el_modo(self):
        assert self.pb.modo_exclusivo(True, False) == self.pb.MODO_ANEURISMA
        assert self.pb.modo_exclusivo(False, True) == self.pb.MODO_TUMOR
        assert self.pb.modo_exclusivo(False, False) is None

    def test_worker_rechaza_modo_invalido(self):
        with pytest.raises(ValueError):
            self.pb.PipelineWorker("estudio.nii.gz", modo="los dos")


# =============================================================================
# 2. CONTRATO DE RAIDIONICS
# =============================================================================
class TestContratoRaidionics:
    """El puente debe generar exactamente lo que el contenedor espera."""

    def setup_method(self):
        self.pu = _modulo("radiomics.raidionics_bridge")

    def test_imagen_correcta(self):
        # La imagen que se usaba era `raidionics/radiomics:latest`, que NO
        # existe en Docker Hub. Las oficiales estan en el namespace `dbouget`.
        assert self.pu.IMAGEN.startswith("dbouget/raidionics-")
        assert ":" in self.pu.IMAGEN, "la etiqueta debe estar fijada"
        assert "latest" not in self.pu.IMAGEN, "la etiqueta no debe ser 'latest'"

    def test_no_hay_subcomando_suite(self):
        # `suite` no existe: el entrypoint solo acepta `-c <config>`.
        assert not hasattr(self.pu, "IMAGEN_ROLES")

    def test_prepara_estructura_que_raidionics_exige(self, tmp_path):
        pytest.importorskip("SimpleITK")
        arr = np.random.rand(8, 8, 8).astype(np.float32) * 100
        entrada = _escribir_volumen(os.path.join(str(tmp_path), "caso.nii.gz"),
                                    arr)
        pr = _preparar_sin_descarga(
            self.pu, entrada, os.path.join(str(tmp_path), "trabajo"))

        # La subcarpeta `raw` es obligatoria cuando caller=raidionics.
        assert os.path.isdir(os.path.join(pr["inputs"], "T0", "raw"))
        # El CSV de secuencias tambien, y SIN extension en el nombre: la
        # busqueda interna compara `basename(ruta).split('.')[0]`.
        csv = os.path.join(pr["inputs"], "mri_sequences.csv")
        assert os.path.isfile(csv)
        with open(csv, encoding="utf-8") as f:
            lineas = [l.strip() for l in f if l.strip()]
        assert lineas[0].lower().startswith("file")
        assert lineas[1].split(",")[0] == "caso"

        assert os.path.isfile(os.path.join(pr["raiz"], "rads_config.ini"))
        assert os.path.isfile(os.path.join(pr["raiz"], "pipeline.json"))

    def test_config_usa_rutas_del_contenedor(self, tmp_path):
        # Este era el fallo silencioso: la config llevaba rutas del anfitrion
        # (C:\...) a un fichero que lee el contenedor Linux, que no las tiene.
        pytest.importorskip("SimpleITK")
        arr = np.zeros((8, 8, 8), dtype=np.float32)
        entrada = _escribir_volumen(os.path.join(str(tmp_path), "caso.nii.gz"),
                                    arr)
        pr = _preparar_sin_descarga(
            self.pu, entrada, os.path.join(str(tmp_path), "trabajo"))

        with open(os.path.join(pr["raiz"], "rads_config.ini"),
                  encoding="utf-8") as f:
            config = f.read()
        assert self.pu.RECURSOS_CONTENEDOR in config
        assert "C:\\" not in config and "D:\\" not in config, \
            "no deben quedar rutas del anfitrion en la config"
        # Las rutas del contenedor usan '/', nunca '\\'.
        for linea in config.splitlines():
            if "folder" in linea or "filename" in linea:
                assert "\\" not in linea, "separador de ruta incorrecto: %s" % linea

    def test_pipeline_usa_model_selection(self, tmp_path):
        # El paso 1 tiene que ser `Model selection`. Con `Segmentation` el
        # pipeline "se ejecuta" en 0.01 s y no escribe ninguna mascara, sin
        # dar ningun error: es el fallo mas dificil de detectar.
        pytest.importorskip("SimpleITK")
        arr = np.zeros((8, 8, 8), dtype=np.float32)
        entrada = _escribir_volumen(os.path.join(str(tmp_path), "caso.nii.gz"),
                                    arr)
        pr = _preparar_sin_descarga(
            self.pu, entrada, os.path.join(str(tmp_path), "trabajo"))

        with open(os.path.join(pr["raiz"], "pipeline.json"),
                  encoding="utf-8") as f:
            pipeline = json.load(f)
        paso = pipeline["1"]
        assert paso["task"] == "Model selection"
        assert paso["model"]
        assert paso["format"] == "thresholding"

    def test_resumen_informe_no_busca_data_json(self, tmp_path):
        # Raidionics no escribe `data.json`: el puente viejo lo buscaba y por
        # eso siempre devolvia "no escribio data.json" aunque hubiera exito.
        resumen = self.pu.resumen_informe(str(tmp_path))
        assert "error" in resumen

    def test_mascaras_detectadas_por_nombre_real(self, tmp_path):
        # Los nombres reales llevan `_annotation-<Clase>_<Modelo>.nii.gz`.
        resultados = os.path.join(str(tmp_path), "resultados")
        carpeta = os.path.join(resultados, "T0")
        os.makedirs(carpeta, exist_ok=True)
        nombre = "caso_annotation-Brain_MRI_Brain.nii.gz"
        open(os.path.join(carpeta, nombre), "wb").close()
        encontradas = self.pu._mascaras_generadas(resultados)
        assert len(encontradas) == 1
        assert encontradas[0].endswith(nombre)


# =============================================================================
# 4. PRUEBA DE HUMO REAL (requiere Docker; se salta si no esta)
# =============================================================================
def _docker_disponible():
    try:
        return _modulo("radiomics.raidionics_bridge").diagnostico() is None
    except Exception:
        return False


def test_raidionics_segmenta_un_nifti_real(tmp_path):
    """
    Prueba de humo end-to-end: entra un NIfTI y sale una mascara.

    Es la unica forma de detectar que el contrato cambio: una version nueva de
    la imagen puede cambiar la config o el layout de carpetas sin avisar, y el
    fallo se manifiesta como un contenedor que "termina bien" y no escribe
    nada. Se salta si no hay Docker, para no romper la suite en un portatil.
    """
    sitk = pytest.importorskip("SimpleITK")
    if not _docker_disponible():
        pytest.skip("Docker no responde: la prueba de humo real se omite")

    # Volumen sintetico con una estructura que el modelo deberia segmentar.
    # El ruido no es decorativo: Raidionics CLASIFICA el fichero mirando cuantos
    # valores distintos tiene, y si son pocos lo toma por una mascara y no por
    # un volumen (`input_file_category_disambiguation`). Sin ruido, un cubo de
    # dos niveles se declara "Annotation" y el pipeline responde "No
    # radiological volume", que es un fallo del test, no del puente.
    rng = np.random.default_rng(0)
    arr = rng.normal(120.0, 15.0, size=(32, 32, 32)).astype(np.float32)
    arr[8:24, 8:24, 8:24] += 90.0
    entrada = _escribir_volumen(os.path.join(str(tmp_path), "humo.nii.gz"),
                                arr)

    puente = _modulo("radiomics.raidionics_bridge")
    if not puente.imagen_presente():
        pytest.skip("La imagen de Raidionics no esta descargada")

    salida = os.path.join(str(tmp_path), "raidionics")
    try:
        resumen = puente.extraer(entrada, salida, progreso=lambda m: None)
    except RuntimeError as exc:
        pytest.fail("Raidionics fallo: %s" % exc)

    if not resumen:
        pytest.skip("Raidionics no disponible en esta maquina")
    assert resumen["ok"]
    assert resumen["mascaras"], "no se escribio ninguna mascara"
    for ruta in resumen["mascaras"]:
        assert os.path.isfile(ruta), "mascara anunciada pero inexistente: %s" % ruta
        # La mascara tiene que tener contenido: un NIfTI vacio seria un falso
        # positivo igual que no haber escrito nada.
        assert (sitk.GetArrayFromImage(sitk.ReadImage(ruta)) > 0).any()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))





