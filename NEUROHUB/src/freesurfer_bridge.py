"""Integracion opcional con FreeSurfer.

FreeSurfer no se distribuye como paquete pip y en Windows normalmente se
ejecuta dentro de WSL. Este modulo mantiene esa dependencia fuera del resto de
NEUROHUB y expone una interfaz segura para los comandos mas utiles:
``recon-all``, conversion NIfTI/MGH, estadisticas y mascaras de ``aseg``.
"""

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_SUJETO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_COMANDOS = (
    "recon-all",
    "mri_convert",
    "mris_convert",
    "mri_binarize",
    "asegstats2table",
    "aparcstats2table",
)


@dataclass(frozen=True)
class Instalacion:
    """Describe el backend detectado sin arrancar un procesamiento."""

    backend: str
    home: str | None
    recon_all: str | None
    wsl_distribution: str | None = None

    @property
    def disponible(self):
        return bool(self.recon_all)


def _buscar_nativo():
    home = os.environ.get("FREESURFER_HOME")
    candidatos = []
    if home:
        candidatos.append(os.path.join(home, "bin", "recon-all"))
        candidatos.append(os.path.join(home, "bin", "recon-all.exe"))
    encontrado = shutil.which("recon-all")
    if encontrado:
        candidatos.insert(0, encontrado)
    for candidato in candidatos:
        if os.path.isfile(candidato) or shutil.which(candidato):
            return Instalacion("native", home or os.path.dirname(
                os.path.dirname(candidato)), candidato)
    return None


def _buscar_wsl():
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return None
    distro = os.environ.get("FREESURFER_WSL_DISTRO", "Ubuntu-22.04")
    comando = ["--", "bash", "-lc",
               "if [ -f /usr/local/freesurfer/7.4.1/SetUpFreeSurfer.sh ]; "
               "then export FREESURFER_HOME=/usr/local/freesurfer/7.4.1; "
               "source /usr/local/freesurfer/7.4.1/SetUpFreeSurfer.sh "
               ">/dev/null 2>&1; command -v recon-all; fi"]
    comando = ["--distribution", distro] + comando
    try:
        resultado = subprocess.run(
            [wsl] + comando, capture_output=True, text=True, timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    recon_all = resultado.stdout.strip().splitlines()
    if resultado.returncode or not recon_all or not recon_all[0].strip():
        return None
    home = os.path.dirname(os.path.dirname(recon_all[0].strip()))
    return Instalacion("wsl", home, recon_all[0].strip(), distro)


def detectar():
    """Devuelve la instalación disponible, priorizando nativa y luego WSL."""
    return _buscar_nativo() or _buscar_wsl() or Instalacion(
        "none", os.environ.get("FREESURFER_HOME"), None,
        os.environ.get("FREESURFER_WSL_DISTRO"),
    )


def diagnostico():
    """Devuelve ``None`` si FreeSurfer puede ejecutarse o un mensaje útil."""
    instalacion = detectar()
    if instalacion.disponible:
        return None
    if instalacion.backend == "none":
        return ("FreeSurfer no está en PATH ni en FREESURFER_HOME. "
                "En Windows instala FreeSurfer dentro de WSL y configura "
                "FREESURFER_WSL_DISTRO si tienes varias distribuciones.")
    return "Se encontró el backend %s, pero no recon-all." % instalacion.backend


def _validar_sujeto(subject):
    if not _SUJETO.fullmatch(subject or ""):
        raise ValueError(
            "El identificador del sujeto solo puede contener letras, números, "
            "punto, guion y guion bajo.")


def _ruta_absoluta(ruta, nombre):
    if not ruta:
        raise ValueError("Falta %s." % nombre)
    valor = os.path.abspath(os.fspath(ruta))
    return valor


def _wsl_path(ruta, instalacion):
    if os.name != "nt":
        return ruta
    valor = os.path.abspath(os.fspath(ruta))
    unidad, resto = os.path.splitdrive(valor)
    if not unidad:
        raise ValueError("La ruta Windows debe incluir una unidad: %s" % ruta)
    # La conversión directa evita que PowerShell/WSL eliminen las barras
    # invertidas al pasar argumentos a `wslpath`. Solo se usa para rutas de
    # unidades montadas de Windows; las rutas Linux de FreeSurfer se conservan.
    return "/mnt/%s/%s" % (
        unidad.rstrip(":").lower(),
        resto.lstrip("\\/").replace("\\", "/"),
    )


def _ruta_backend(ruta):
    """Convierte una ruta del anfitrión al formato del backend activo."""
    instalacion = detectar()
    if instalacion.backend == "wsl":
        return _wsl_path(ruta, instalacion)
    return ruta


def _comando(instalacion, args, env):
    if instalacion.backend == "native":
        return list(args), env
    if instalacion.backend != "wsl":
        raise RuntimeError(diagnostico())
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        raise RuntimeError("No se encontró wsl.exe.")
    # bash -lc se usa solo como adaptador de WSL; cada argumento se cita antes
    # de formar la orden para evitar interpretar rutas como código.
    exportaciones = []
    for clave in ("FREESURFER_HOME", "SUBJECTS_DIR", "FS_LICENSE"):
        if env.get(clave):
            exportaciones.append("export %s=%s" %
                                 (clave, shlex.quote(env[clave])))
    setup = ""
    if instalacion.backend == "wsl" and instalacion.home:
        setup = "export FREESURFER_HOME=%s; source %s/SetUpFreeSurfer.sh >/dev/null 2>&1; " % (
            shlex.quote(instalacion.home), shlex.quote(instalacion.home))
    orden = " ".join(exportaciones + [
        setup +
        "exec " + " ".join(shlex.quote(str(arg)) for arg in args)])
    comando = ["--", "bash", "-lc", orden]
    if instalacion.wsl_distribution:
        comando = ["--distribution", instalacion.wsl_distribution] + comando
    return [wsl] + comando, None


def ejecutar(args, log_path=None, env_extra=None, check=True):
    """Ejecuta un comando FreeSurfer y conserva stdout/stderr en un log."""
    instalacion = detectar()
    if not instalacion.disponible:
        raise RuntimeError(diagnostico())
    env = os.environ.copy()
    if instalacion.home:
        env["FREESURFER_HOME"] = instalacion.home
        env["PATH"] = os.path.join(instalacion.home, "bin") + os.pathsep + env.get(
            "PATH", "")
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    comando, comando_env = _comando(instalacion, args, env)
    if comando_env is None:
        comando_env = env
    log_handle = None
    try:
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "w", encoding="utf-8")
        resultado = subprocess.run(
            comando, cwd=None, env=comando_env, text=True,
            stdout=log_handle or subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False,
        )
    finally:
        if log_handle:
            log_handle.close()
    if check and resultado.returncode:
        detalle = " (log: %s)" % log_path if log_path else ""
        raise RuntimeError("FreeSurfer terminó con código %d%s." %
                           (resultado.returncode, detalle))
    return resultado


def recon_all(input_path, subject, subjects_dir, license_path=None,
              log_path=None, extra_args=None):
    """Ejecuta el pipeline anatómico completo de FreeSurfer."""
    _validar_sujeto(subject)
    entrada = _ruta_absoluta(input_path, "la imagen de entrada")
    if not os.path.isfile(entrada):
        raise FileNotFoundError(entrada)
    subjects = _ruta_absoluta(subjects_dir, "SUBJECTS_DIR")
    os.makedirs(subjects, exist_ok=True)
    if license_path and not os.path.isfile(license_path):
        raise FileNotFoundError(license_path)
    entrada_backend = _ruta_backend(entrada)
    subjects_backend = _ruta_backend(subjects)
    args = ["recon-all", "-i", entrada_backend, "-s", subject,
            "-sd", subjects_backend,
            "-all"]
    if extra_args:
        args.extend(extra_args)
    env = {"SUBJECTS_DIR": subjects_backend}
    if license_path:
        env["FS_LICENSE"] = _ruta_backend(os.path.abspath(license_path))
    return ejecutar(args, log_path=log_path, env_extra=env)


def convertir(input_path, output_path, log_path=None, license_path=None):
    """Convierte entre formatos soportados por ``mri_convert``."""
    entrada = _ruta_absoluta(input_path, "la imagen de entrada")
    salida = _ruta_absoluta(output_path, "la imagen de salida")
    if not os.path.isfile(entrada):
        raise FileNotFoundError(entrada)
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    env = {}
    if license_path:
        if not os.path.isfile(license_path):
            raise FileNotFoundError(license_path)
        env["FS_LICENSE"] = _ruta_backend(os.path.abspath(license_path))
    return ejecutar(["mri_convert", _ruta_backend(entrada),
                     _ruta_backend(salida)], log_path=log_path,
                    env_extra=env)


def exportar_superficies(subjects_dir, subject, output_dir, log_path=None,
                         license_path=None):
    """Exporta las superficies corticales de FreeSurfer a STL para el visor 3D."""
    _validar_sujeto(subject)
    subjects = _ruta_absoluta(subjects_dir, "SUBJECTS_DIR")
    salida = _ruta_absoluta(output_dir, "la carpeta de salida")
    os.makedirs(salida, exist_ok=True)
    surf_dir = os.path.join(subjects, subject, "surf")
    env = {}
    if license_path:
        if not os.path.isfile(license_path):
            raise FileNotFoundError(license_path)
        env["FS_LICENSE"] = _ruta_backend(os.path.abspath(license_path))
    resultados = []
    for hemi in ("lh", "rh"):
        entrada = os.path.join(surf_dir, "%s.white" % hemi)
        destino = os.path.join(salida, "freesurfer_%s_white.stl" % hemi)
        if not os.path.isfile(entrada):
            raise FileNotFoundError("No existe la superficie: %s" % entrada)
        ejecutar(["mris_convert", _ruta_backend(entrada),
                  _ruta_backend(destino)], log_path=log_path, env_extra=env)
        resultados.append(destino)
    return resultados


def exportar_mascara(subjects_dir, subject, label, output_path, log_path=None):
    """Exporta una etiqueta de ``aseg.mgz`` como NIfTI binario."""
    _validar_sujeto(subject)
    subjects = _ruta_absoluta(subjects_dir, "SUBJECTS_DIR")
    salida = _ruta_absoluta(output_path, "la imagen de salida")
    aseg = os.path.join(subjects, subject, "mri", "aseg.mgz")
    if not os.path.isfile(aseg):
        raise FileNotFoundError("No existe el aseg procesado: %s" % aseg)
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    return ejecutar(["mri_binarize", "--i", _ruta_backend(aseg),
                     "--match", str(label), "--o", _ruta_backend(salida)],
                    log_path=log_path,
                    env_extra={"SUBJECTS_DIR": _ruta_backend(subjects)})


def exportar_estadisticas(subjects_dir, subject, output_dir, log_path=None):
    """Genera tablas de volumen de aseg y grosor/área cortical."""
    _validar_sujeto(subject)
    subjects = _ruta_absoluta(subjects_dir, "SUBJECTS_DIR")
    salida = _ruta_absoluta(output_dir, "la carpeta de salida")
    os.makedirs(salida, exist_ok=True)
    env = {"SUBJECTS_DIR": _ruta_backend(subjects)}
    resultados = []
    for nombre, comando, extra, archivo in (
        ("aseg", "asegstats2table", ["--meas", "volume"],
         os.path.join(salida, "%s_aseg.tsv" % subject)),
        ("aparc", "aparcstats2table", ["--hemi", "lh", "rh",
                                       "--meas", "thickness"],
         os.path.join(salida, "%s_aparc.tsv" % subject)),
    ):
        ejecutar([comando, "--subjects", subject] + extra +
                 ["--tablefile", _ruta_backend(archivo)], log_path=log_path,
                 env_extra=env)
        resultados.append(archivo)
    return resultados


def segmentar(input_path, subject, subjects_dir, output_path,
              license_path=None, log_path=None):
    """Ejecuta ``recon-all`` y exporta la segmentación anatómica de ``aseg``."""
    recon_all(input_path, subject, subjects_dir, license_path=license_path,
              log_path=log_path)
    subjects = _ruta_absoluta(subjects_dir, "SUBJECTS_DIR")
    aseg = os.path.join(subjects, subject, "mri", "aseg.mgz")
    return convertir(aseg, output_path, log_path=log_path)
