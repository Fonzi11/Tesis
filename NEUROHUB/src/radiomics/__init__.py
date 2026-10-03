"""
Motor de radiomics nativo de NEUROHUB (implementacion IBSI en NumPy/SciPy).

Por que NO PyRadiomics
---------------------
PyRadiomics solo publica ruedas para CPython 3.7-3.9 y el entorno de este
proyecto es Python 3.13, donde no compila (el `setup.py` importa numpy en la
fase de metadatos y falla). En lugar de depender de un binario imposible de
instalar, este paquete reimplementa las familias de rasgos siguiendo las
definiciones de la Image Biomarker Standardisation Initiative (IBSI):

    first_order  - intensidad (media, varianza, curtosis, ...)
    shape        - geometria 3D de la mascara (volumen, superficie, ...)
    glcm         - matriz de co-ocurrencia de niveles de gris
    glrlm        - matriz de longitud de series de gris
    glszm        - matriz de tamano de zonas de gris
    ngtdm        - matriz de dependencia de tono de gris
    lsh          - histogramas escalados
    lszm         - histogramas escalados de zona

Nomenclatura IBSI: los prefijos siguen el estandar (`original_`, `wavelet_`,
`log_sigma_`, `square_`, `exponential_`, `gradient_`, `lbp_`), y el nombre de
cada descriptor se escribe con el sufijo de la clase IBSI (`_Mean`,
`_Variance`, `_Coocurrence`...) para que un CSV exports sea intercambiable con
el de PyRadiomics y con el de Raidionics.

Los tres modulos de la capa superior son:

    extract      : calculo de rasgos sobre una imagen + mascara
    report       : tabla lista para interfaz + exportacion CSV/JSON
    slicer_bridge / raidionics_bridge : conectores opcionales
"""

from .masks import (                    # noqa: F401
    MaskLabelMap, estructura_mascara, rois_raidionics, magmas_braTS,
    de_nifti, UNIDADES_RANO,
)
from .features import (                 # noqa: F401
    RASGOS_PRIMERA_ORDEN, RASGOS_FORMA, RASGOS_TEXTURA, NOMBRES_CLASES,
)
from .extract import (                   # noqa: F401
    ExtractionConfig, extractor, extraer_radiomics, cargar_volumen,
    normalizar_intensidad,
)
from .report import (                    # noqa: F401
    RadiomicsTable, construir_tabla, exportar_csv, exportar_json,
    exportar_informe,
)
# Los puentes con motores externos son OPCIONALES a proposito: tanto Slicer
# como Docker pueden faltar en la maquina, e importar el paquete de radiomics
# no debe exigir ninguno de los dos. Por eso se exponen como submodulos a los
# que se llama de forma explicita, en vez de usarse en un `__init__` global.
from . import raidionics_bridge            # noqa: F401
from . import slicer_bridge               # noqa: F401

__version__ = "1.0.0"

__all__ = [
    "MaskLabelMap", "estructura_mascara", "rois_raidionics",
    "magmas_braTS", "de_nifti", "UNIDADES_RANO",
    "RASGOS_PRIMERA_ORDEN", "RASGOS_FORMA", "RASGOS_TEXTURA",
    "NOMBRES_CLASES",
    "ExtractionConfig", "extractor", "extraer_radiomics", "cargar_volumen",
    "normalizar_intensidad",
    "RadiomicsTable", "construir_tabla", "exportar_csv", "exportar_json",
    "exportar_informe", "raidionics_bridge", "slicer_bridge", "__version__",
]
