"""
Tabla de radiomics y su exportación (CSV / JSON), al estilo de Raidionics.

Raidionics produce un CSV con una fila por ROI y una columna por descriptor, y
un JSON con los metadatos del estudio. Aquí se reproduce exactamente esa
estructura, de modo que el informe de NEUROHUB sea intercambiable con el de la
aplicación original:

    radiomics_<estudio>.csv    una fila por ROI, una columna por descriptor
    radiomics_<estudio>.json   metadatos + los mismos valores
    informe_<estudio>.txt      resumen legible en castellano (Raids-RADS)

El CSV se escribe con `;` como separador y `,` como decimal, que es lo que
espera Excel en configuración española.
"""

import csv
import json
import math
import os


class RadiomicsTable:
    """
    Tabla de rasgos: `{nombre_roi: {nombre_rasgo: valor}}`.

    Aporta las operaciones que necesita la interfaz: filtrar por clase de
    descriptor, quedarse con un subconjunto de ROI y formatear valores.
    """

    def __init__(self, resultados=None, metadatos=None):
        self.resultados = dict(resultados or {})
        self.metadatos = dict(metadatos or {})

    # ------------------------------------------------------------------
    def rois(self):
        return list(self.resultados.keys())

    def n_rasgos(self):
        """Nº de descriptores de la primera ROI."""
        for v in self.resultados.values():
            return len(v)
        return 0

    def columnas(self):
        """Nombres de todos los descriptores, en orden estable."""
        cols, vistas = [], set()
        for rasgos in self.resultados.values():
            for k in rasgos:
                if k not in vistas:
                    vistas.add(k)
                    cols.append(k)
        return cols

    def clase_de(self, nombre_rasgo):
        """
        Clase IBSI de un descriptor a partir de su nombre.

        `original_Mean` -> "Primera Orden"; `original_GLCM_Energy` -> "GLCM";
        `LSH_Median` -> "LSH"; `original_Sphericity` -> "Forma".

        Se resuelve con el registro de `features`, no adivinando por subcadena:
        adivinar fallaba con `original_SurfaceArea_mm2` (que sí es de forma) o
        con `original_GrayLevelVariance` (que es de primera orden y se
        parecería a un `GrayLevel*` de textura).
        """
        from .features import RASGOS_FORMA, RASGOS_TEXTURA

        partes = nombre_rasgo.split("_")
        # 1) ¿Es un descriptor de textura? Se busca el sufijo de clase.
        for clase, nombres in RASGOS_TEXTURA.items():
            for n in nombres:
                if nombre_rasgo.endswith("_" + n) and (
                        nombre_rasgo.startswith(clase + "_")
                        or f"_{clase}_" in nombre_rasgo):
                    return clase
        # 2) ¿Es de forma? Se comparan los descriptores del registro.
        for n in RASGOS_FORMA:
            if nombre_rasgo.endswith(n) or nombre_rasgo.endswith(n + "_mm3") \
                    or nombre_rasgo.endswith(n + "_mm2"):
                return "shape"
        # 3) En otro caso, primera orden.
        return "firstOrder"

    def por_clase(self):
        """{clase: [nombres_rasgo]} para agrupar la tabla en la interfaz."""
        out = {}
        for col in self.columnas():
            out.setdefault(self.clase_de(col), []).append(col)
        return out

    def valor(self, roi, rasgo, defecto=None):
        return self.resultados.get(roi, {}).get(rasgo, defecto)

    def __len__(self):
        return len(self.resultados)

    def __repr__(self):
        return (f"<RadiomicsTable {len(self.resultados)} ROI x "
                f"{self.n_rasgos()} rasgos>")


# =============================================================================
# CONSTRUCCIÓN
# =============================================================================
def construir_tabla(resultados, metadatos=None):
    """Envuelve un diccionario de resultados en un `RadiomicsTable`."""
    return RadiomicsTable(resultados, metadatos)


# =============================================================================
# EXPORTACIÓN
# =============================================================================
def exportar_csv(tabla, ruta, decimal=",", separador=";"):
    """
    Escribe la tabla como CSV (una fila por ROI).

    Se usa el separador y el decimal que Excel espera en español, de forma que
    el radiólogo pueda abrirlo y ver los números con coma.
    """
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    columnas = tabla.columnas()
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=separador)
        w.writerow(["ROI"] + columnas)
        for roi in tabla.rois():
            w.writerow([roi]
                       + [_formato(tabla.valor(roi, col), decimal)
                          for col in columnas])
    return ruta


def exportar_json(tabla, ruta):
    """Escribe metadatos + valores en JSON, como el `.json` de Raidionics."""
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    datos = {
        "metadatos": tabla.metadatos,
        "radiomics": {
            roi: {k: _limpio(v) for k, v in rasgos.items()}
            for roi, rasgos in tabla.resultados.items()
        },
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    return ruta


def exportar_informe(tabla, ruta, titulo="Informe de radiomics"):
    """
    Escribe un resumen legible con los descriptores clave de cada ROI.

    Es la versión en texto del informe de Raidionics: en lugar de volcar
    cientos de columnas, resume lo que el radiólogo lee de un vistazo
    (volumen, diámetros, esfericidad y los descriptores de textura
    principales).
    """
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    lineas = [titulo, "=" * len(titulo), ""]
    for clave, valor in (tabla.metadatos or {}).items():
        lineas.append(f"{clave}: {valor}")
    if tabla.metadatos:
        lineas.append("")

    for roi in tabla.rois():
        lineas.append(roi)
        lineas.append("-" * len(roi))
        for rasgo in RASGOS_INFORME:
            v = tabla.valor(roi, rasgo)
            if v is not None:
                lineas.append(f"  {rasgo:36s} {_formato(v, '.')}")
        lineas.append("")

    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    return ruta


# Descriptores que resumen una ROI en el informe legible. Los nombres deben
# coincidir EXACTAMENTE con los que compone `extract`: cada clase de textura
# antepone su propio sufijo (RunEntropy, ZoneEntropy, ...), no un "Entropy"
# genérico.
RASGOS_INFORME = [
    "original_MeshVolume_mm3",
    "original_VoxelVolume",
    "original_Maximum3DDiameter",
    "original_Elongation",
    "original_Sphericity",
    "original_SurfaceArea_mm2",
    "original_Mean",
    "original_StandardDeviation",
    "original_Median",
    "original_Entropy",
    "original_GLCM_Contrast",
    "original_GLCM_Entropy",
    "original_GLCM_Homogeneity",
    "original_GLRLM_RunEntropy",
    "original_GLRLM_ShortRunEmphasis",
    "original_GLSZM_ZoneEntropy",
    "original_GLSZM_LargeAreaEmphasis",
    "original_NGTDM_Busyness",
    "original_NGTDM_Complexity",
    "original_NGTDM_Strength",
]


def _formato(valor, decimal=","):
    """Formatea un valor para CSV/Informe; NaN se escribe como vacío."""
    if valor is None:
        return ""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if math.isnan(v):
        return ""
    if not math.isfinite(v):
        return ""
    if abs(v) >= 1e6 or (v != 0 and abs(v) < 1e-4):
        return ("%g" % v).replace(".", decimal)
    return ("%.6f" % v).rstrip("0").rstrip(".").replace(".", decimal)


def _limpio(valor):
    """NaN no es válido en JSON (el estándar lo prohíbe), se vuelve null."""
    if valor is None:
        return None
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return valor
    if not math.isfinite(v):
        return None
    return v

    return RadiomicsTable(resultados, metadatos)
