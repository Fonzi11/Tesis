# 🧠 PROYECTO ATLAS

**Segmentación y Modelado 3D de Neuroimágenes**

## 📋 Descripción

ATLAS es una aplicación profesional con interfaz gráfica oscura para el procesamiento de imágenes médicas (DICOM/NIfTI), segmentación automática de estructuras cerebrales, detección de tumores y aneurismas, y generación de modelos 3D imprimibles (STL/FBX).

## 🚀 Inicio Rápido

### Opción 1: Ejecutar con Python

```bash
cd ATLAS
python launcher.py
```

### Opción 2: Generar Ejecutable

```bash
cd ATLAS
python build_exe.py
```

El ejecutable se generará en `ATLAS/dist/ATLAS.exe`

## 📁 Estructura del Proyecto

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
├── data/                     # Datos de entrada
│   ├── dicom/               # Archivos DICOM
│   └── nifti/               # Archivos NIfTI
├── modelos_3d/               # Modelos 3D generados
│   ├── stl/                 # Archivos STL
│   └── fbx/                 # Archivos FBX
├── modelos_preentrenados/    # Modelos de IA
├── salidas/                  # Resultados
│   ├── segmentaciones_ai/   # Máscaras de segmentación
│   └── reportes/            # Reportes
└── Intentos/                 # Archivos de desarrollo
```

## 🎯 Funcionalidades

- **Segmentación AI**: Segmentación automática de 104 estructuras anatómicas con TotalSegmentator
- **Detección de Tumores**: Segmentación de tumores cerebrales con modelo BRATS 2020
- **Detección de Aneurismas**: Análisis de curvatura y forma vascular
- **Modelado 3D**: Generación de mallas STL optimizadas
- **Exportación FBX**: Exportación con materiales PBR para Blender/Unity

## 🛠️ Dependencias

- Python 3.10+
- PyTorch
- MONAI
- TotalSegmentator
- SimpleITK
- trimesh
- customtkinter
- numpy, scipy, scikit-image

## 📄 Licencia

Proyecto de tesis académica.