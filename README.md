# 🧠 Proyecto Tesis

Segmentación y modelado 3D de neuroimágenes para diagnóstico asistido por IA.

## 📦 Contenido

- **`ATLAS/`** — Aplicación principal con interfaz gráfica (customtkinter) para:
  - Procesamiento de imágenes médicas **DICOM / NIfTI**
  - Segmentación automática de estructuras cerebrales (TotalSegmentator, BRATS 2020)
  - Detección de tumores y aneurismas
  - Generación de modelos 3D imprimibles (STL) y exportables (FBX)
- **`Intentos/`** — Herramientas de desarrollo Blender para conversión STL → FBX con colores por vértice
- **`tools/`** — Utilidades auxiliares (p. ej., descarga de muestra BraTS2021)

## 🚀 Inicio rápido

```bash
cd ATLAS
pip install -r requirements.txt
python launcher.py
```

Para generar un ejecutable:

```bash
python build_exe.py   # genera ATLAS/dist/ATLAS.exe
```

## 📁 Estructura

```
Tesis/
├── ATLAS/                    # Aplicación principal
│   ├── main.py              # Interfaz gráfica
│   ├── launcher.py          # Lanzador con verificación de dependencias
│   ├── build_exe.py         # Script para generar ejecutable
│   ├── requirements.txt     # Dependencias
│   └── src/                 # Módulos del pipeline
│       ├── 01_procesamiento_dicom.py
│       ├── 02_segmentacion_brats.py
│       └── 03_integrar_brats.py
├── data/                     # Datos de entrada (no versionados)
│   ├── dicom/
│   └── nifti/
├── modelos_3d/               # Modelos 3D generados (no versionados)
├── modelos_preentrenados/    # Pesos de IA (no versionados)
├── salidas/                  # Resultados (no versionados)
├── Intentos/                 # Herramientas de desarrollo
└── tools/                    # Utilidades auxiliares
```

## 🛠️ Dependencias principales

- Python 3.10+
- PyTorch, MONAI, TotalSegmentator
- SimpleITK, trimesh, numpy, scipy, scikit-image
- customtkinter

> 📌 Los archivos médicos (`data/`), modelos 3D y pesos de IA se mantienen fuera
> del repositorio por su tamaño (varios GB). Consulta `tools/descargar_braTS_muestra.py`
> para descargar una muestra pública de datos BraTS.

## 📄 Licencia

Proyecto de tesis académica.