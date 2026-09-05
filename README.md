# 🧠 Proyecto Tesis

Segmentación y modelado 3D de neuroimágenes para diagnóstico asistido por IA.

## 📦 Contenido

- **`NEUROHUB/`** — Plataforma principal (tkinter + pygame + turtle):
  - Visualización de DICOM/NIfTI
  - Segmentación completa (máscara de tumor, cráneo, cerebro, vasculatura)
  - Fac-export único: `salidas/fbx/neurohub_completo.fbx` (6 materiales)
  - Visor 3D pygame con ventana adaptativa y resolución auto-ajustable
  - Panel educativo interactivo (turtle)
- **`ATLAS/`** — Aplicación de segmentación avanzada (customtkinter, legado):
  - Procesamiento de imágenes médicas DICOM / NIfTI
  - Segmentación automática con TotalSegmentator, BRATS 2020
  - Sus modelos 3D se guardan en `archivo/modelos_3d/`
- **`docs/`** — Documentación (arquitectura, cambios, guías) + scripts de demo
- **`herramientas/`** — Utilidades (preview, FBX único, validación, verificación)
- **`archivo/`** — Material histórico / residual (modelos antiguos, debug)

## 🚀 Inicio rápido

### NEUROHUB (plataforma principal)
```bash
cd NEUROHUB
python launcher.py
```

### ATLAS (segmentación avanzada, legado)
```bash
cd ATLAS
python launcher.py
```

## 📁 Estructura

```
Tesis/
├── README.md                 # Este índice
├── NEUROHUB/                 # Plataforma principal
│   ├── main.py              # Hub principal (tkinter/customtkinter)
│   ├── launcher.py          # Verifica dependencias y lanza
│   ├── build_exe.py         # Genera ejecutable con PyInstaller
│   ├── tests/               # Scripts de verificación
│   └── src/
│       ├── data_manager.py  # Gestión datasets (BraTS, TCIA, ADAM)
│       ├── viewer3d.py      # Visor 3D interactivo (pygame)
│       └── anatomia.py      # Anatomía educativa (turtle)
├── ATLAS/                    # Segmentación avanzada (legado)
├── data/                     # Datos médicos (no versionados)
│   ├── dicom/
│   └── nifti/               # incluye muestras BraTS2021
├── salidas/                  # Resultados (mallas STL, FBX único, preview, neuronavegación)
├── modelos_preentrenados/    # Pesos de IA
├── docs/                     # Documentación del proyecto
│   └── scripts/              # Demos de layout / arquitectura
├── herramientas/             # Utilidades de desarrollo
└── archivo/                  # Modelos y material histórico (no versionado)
```

## 🎯 Pipeline

```
Input (DICOM/NIfTI)
  → Preprocesamiento (SimpleITK)
  → Segmentación (BRATS/TotalSegmentator/Heurística)
  → Identificación (tumor con ET/ED/NCR, aneurisma con vasculatura)
  → Visualización 3D (pygame) + 2D (slices)
  → Exportación (STL + FBX único para Unity + NIfTI para neuronavegación)
```

## 🔧 Dependencias

```bash
pip install -r NEUROHUB/requirements.txt
pip install -r ATLAS/requirements.txt
```

## 📄 Licencia

Proyecto de tesis académica. Los datos de `data/` son públicos (BraTS, TCIA).