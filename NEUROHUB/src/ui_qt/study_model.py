"""
Modelo de sesion: lo unico que la interfaz sabe del caso clinico.

Mantiene la lista de series cargadas (una por timestamp, como en Raidionics),
el estado de visibilidad de cada estructura 3D y los datos tabulares del
tumor. Es deliberadamente tonto (sin Qt, sin VTK): solo almacen y consulta,
de modo que se pueda probar de forma aislada con `tests/test_ui_qt.py`.
"""

import os


class Serie:
    """Una serie/estudio cargado en la sesion.

    En NEUROHUB cada "timestamp" de la interfaz equivale a un volumen de
    entrada (NIfTI o directorio DICOM). Se guardan los datos descriptivos que
    la interfaz muestra en la cabecera.
    """

    def __init__(self, uid, nombre, ruta, modality="MR", paciente="Paciente"):
        self.uid = uid
        self.nombre = nombre
        self.ruta = ruta
        self.modality = modality
        self.paciente = paciente
        # Estructuras 3D de esta serie: {clave: {"label","color","ruta","visible"}}
        self.capas = {}

    def add_capa(self, key, label, color, ruta, visible=True):
        """Registra una estructura 3D disponible para esta serie."""
        self.capas[key] = {
            "label": label,
            "color": color,
            "ruta": ruta,
            "visible": visible,
        }

    def set_visible(self, key, visible):
        if key in self.capas:
            self.capas[key]["visible"] = bool(visible)

    def claves_visibles(self):
        return [k for k, v in self.capas.items() if v["visible"]]

    def __repr__(self):
        return f"<Serie {self.nombre} ({len(self.capas)} capas)>"


class StudyModel:
    """Sesion completa: series + estructuras compartidas del visor."""

    def __init__(self):
        self.series = []            # [Serie]
        self.serie_activa = None    # Serie
        self.slices_2d = {}         # {eje: ruta_png}

    # ------------------------------------------------------------------
    def add_serie(self, serie):
        """Agrega una serie y la deja como activa."""
        self.series.append(serie)
        self.serie_activa = serie
        return serie

    def limpiar(self):
        self.series = []
        self.serie_activa = None
        self.slices_2d = {}

    def set_serie_activa(self, uid):
        for s in self.series:
            if s.uid == uid:
                self.serie_activa = s
                return s
        return None

    def total_capas_visibles(self):
        if not self.serie_activa:
            return 0
        return len(self.serie_activa.claves_visibles())

    def get_serie(self, uid):
        """Devuelve la serie con ese uid, o None."""
        for s in self.series:
            if s.uid == uid:
                return s
        return None

    def nombre_serie_activa(self):
        return self.serie_activa.nombre if self.serie_activa else "—"

    def descripcion(self):
        """Linea de estado para la cabecera."""
        if not self.serie_activa:
            return "Ningun estudio cargado"
        n = len(self.serie_activa.capas)
        vis = self.total_capas_visibles()
        return (f"{self.serie_activa.paciente} | {self.serie_activa.nombre} "
                f"({self.serie_activa.modality}) - {vis}/{n} estructuras visibles")

    def existe_volumen(self, ruta):
        return bool(ruta) and os.path.exists(ruta)

