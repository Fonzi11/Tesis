# 🧠 NEUROHUB — Proyecto Tesis

Segmentación y modelado 3D de neuroimágenes para diagnóstico asistido por IA.

> **Proyecto unificado.** Antes existían dos carpetas paralelas (`ATLAS/` y
> `NEUROHUB/`) que se pisaban: dos interfaces, dos visores 3D y dos lanzadores
> para el mismo trabajo. Ahora todo vive en **`NEUROHUB/`**. La carpeta `ATLAS/`
> se eliminó; su interfaz avanzada (visor VTK con capas, opacidad y
> supersampling) y sus módulos de pipeline se integraron aquí.

## 📦 Contenido

- **`NEUROHUB/`** — Plataforma única (**PySide6/Qt** + VTK + PyVista):
  - Ventana principal Qt con paneles de entrada, segmentación y exportación
  - **Visor 2D** con navegación por los tres planos y **delineado manual de
    tumor** con pincel y borrador sobre la imagen NIfTI
  - **Visor 3D VTK** embebido: mallas de máxima resolución, capas
    superpuestas, opacidad por estructura, antialiasing MSAA, supersampling 2×
  - Visor 3D GPU (PyVista)
  - Pipeline de segmentación (TotalSegmentator, BRATS 2020, heurística morfológica)
  - Reconstrucción de superficies uniforme (`calidad_mallas.py`)
  - Radiomics: motor propio (sin Docker) y motor externo Raidionics
  - Exportación STL, FBX y NIfTI para neuronavegación
  - Interfaz legacy (`main.py`, tkinter + pygame) conservada como referencia
- **`docs/`** — Documentación (arquitectura, cambios, guías) + scripts de demo
- **`herramientas/`** — Utilidades (preview, FBX único, validación, verificación)
- **`archivo/`** — Material histórico / residual (modelos antiguos, debug)

## 🚀 Inicio rápido

Un único punto de entrada para todo. Desde `NEUROHUB/`:

```bash
pip install -r requirements.txt     # la interfaz es PySide6/Qt

python launcher.py                  # interfaz gráfica (equivalente a `ui`)
python launcher.py doctor           # estado de Python, dependencias y motores
python launcher.py ui               # ventana principal, explícito

python -m src.ui_qt.app             # la misma ventana Qt, sin el launcher
```

### Motor de radiomics

```bash
# Motor propio: funciona sin Docker, solo con SimpleITK/numpy/scipy
python launcher.py radiomics  ../data/nifti/MRBrainTumor1.nii.gz \
                             ../salidas/segmentaciones_ai/tumor_brats.nii.gz \
                             --salida ../salidas/informe

# Motor externo Raidionics, dentro de Docker
python launcher.py raidionics estado                     # ¿se puede usar?
python launcher.py raidionics extraer <estudio.nii.gz>    # ejecuta el motor
```

> 📄 **Antes de tocar Raidionics, lee
> [`docs/DECISION_RAIDIONICS_Y_MODOS.md`](docs/DECISION_RAIDIONICS_Y_MODOS.md).**
> Documenta el contrato **real** de la imagen (que no es el que asume la
> documentación pública), los modos excluyentes aneurisma/tumor, y la causa por
> la que los vasos no aparecían en RM.

Raidionics necesita el daemon de Docker en marcha. `raidionics estado` distingue
las tres causas reales de fallo (no está docker, el daemon está apagado, o el
daemon devuelve error) e indica la causa concreta. **El motor propio no depende
de Docker** y sigue funcionando en cualquier caso.

Usa la imagen `dbouget/raidionics-rads`, fijada por versión: hace segmentación e
informes clínicos, **no** radiomics tipo PyRadiomics. Los descriptores numéricos
siguen viniendo del motor propio. La primera vez se descarga el modelo (87 MB).

> ⚠️ Las rutas de estos subcomandos se resuelven desde el directorio del
> launcher, no desde el actual: usa rutas **absolutas**.

> ⚠️ En Windows, Docker Desktop necesita la virtualización por hardware. Si
> `raidionics estado` dice que el daemon no puede arrancar, comprueba que
> «Plataforma de máquina virtual» esté habilitada en *Activar o desactivar
> características de Windows* y reinicia. Sin eso, Docker devuelve un 500 por
> el socket y ningún motor en Docker puede funcionar.

## 🩺 Modos de análisis: aneurisma **o** tumor

Un caso se ejecuta en **un solo modo**. Aneurisma y tumor son diagnósticos
excluyentes por definición, así que el pipeline **no los ejecuta juntos**, y la
interfaz no permite siquiera representar ese estado. Si se piden los dos a la vez,
el error salta al construir el worker, no a mitad del cálculo.

```bash
python -m pytest NEUROHUB/tests/test_modos_y_raidionics.py -v   # 21 pruebas
```

## ✅ Verificación integral

El mismo launcher da acceso al verificador, que comprueba interfaz, pipeline,
radiomics y motores externos:

```bash
python launcher.py verificar              # etapas rápidas
python launcher.py verificar --todo       # añade slicer, paridad y pipeline
python launcher.py verificar --etapa radiomics raidionics
python launcher.py verificar --ui-real    # abre la ventana Qt de verdad
```

Etapas: `deps`, `imports`, `ui_qt`, `radiomics`, `raidionics`, `slicer`,
`paridad`, `pipeline`. Devuelve código de salida 0 si todo pasa, y lista las
etapas rotas si no. También se puede llamar directamente al script con
`python verificacion_integral.py` desde la raíz del repositorio.

`ui_qt` aparece como `OMITE` cuando VTK no encuentra un pixel format de
OpenGL válido en modo headless; en ese caso usa `--ui-real`.
`raidionics` aparece como `OMITE` con el motivo si el daemon de Docker no
responde, ya que el motor propio no depende de él.

## 📁 Estructura

```
Tesis/
├── README.md                 # Este índice
├── NEUROHUB/                 # Plataforma única
│   ├── main.py               # Interfaz legacy (customtkinter + pygame)
│   ├── launcher.py           # Punto de entrada único: ui, doctor, radiomics,
│   │                         #   raidionics y verificación
│   ├── procesar_caso.py      # Pipeline completo de un caso
│   ├── render_caso.py        # Render y exportación de un caso
│   ├── build_exe.py          # Genera ejecutable con PyInstaller
│   ├── pipeline.py           # Reconstrucción 3D headless (mallas + captura)
│   ├── scripts/              # Comprobaciones de humo (pincel, mapeo, pintado)
│   ├── tests/                # Suite de tests (pytest)
│   ├── assets/               # Fuentes empaquetadas
│   └── src/
│       ├── ui_qt/            # Aplicación Qt: ventana, paneles, visores 2D y 3D
│       ├── volumen_2d.py     # Volumen NIfTI + máscara + pincel de delineado
│       ├── 01_procesamiento_dicom.py  # Preprocesamiento + heurística
│       ├── 02_segmentacion_brats.py   # Segmentación BRATS
│       ├── 03_integrar_brats.py       # Integración y vistas 2D
│       ├── 04_slices_2d.py            # Render de slices
│       ├── data_manager.py            # Gestión datasets (BraTS, TCIA, ADAM)
│       ├── calidad_mallas.py          # Reconstrucción de superficies
│       ├── segmentacion_completa.py   # Segmentación + FBX Unity
│       ├── radiomics/                  # Motor de radiomics propio
│       ├── viewer3d.py                # Visor 3D legacy (pygame)
│       └── anatomia.py                # Anatomía educativa (turtle)
├── data/                     # Datos médicos (no versionados)
│   ├── dicom/
│   └── nifti/                # incluye muestras BraTS2021
├── salidas/                  # Resultados (mallas STL, FBX, preview, capturas)
│   └── mallas/               # Mallas STL de máxima resolución
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
  → Segmentación (BRATS / TotalSegmentator / heurística morfológica)
  → Identificación (tumor con ET/ED/NCR, aneurisma con vasculatura)
  → Reconstrucción 3D de calidad uniforme (calidad_mallas.py)
  → Visualización (VTK 2D/3D) y slices
  → Exportación (STL + FBX para Unity + NIfTI para neuronavegación)
```

## 🖼️ Renderizado

El visor 3D embebido renderiza con VTK en un framebuffer offscreen y lo
muestra en el widget Qt. Notas de implementación que importan al tocarlo:

- **MSAA sí, FXAA no.** Activar FXAA junto al multisampling produce un
  framebuffer completamente vacío (un solo color), medido en `_diag_render.py`.
  Los dos se anulan entre sí; el MSAA ya promedia muestras de verdad.
- **Depth peeling sí se usa**: es lo que ordena bien las superficies
  transparentes (cráneo semitransparente con el cerebro dentro).
- **Supersampling 2×**: se renderiza al doble y se reduce con LANCZOS.
- **Presupuestos de caras por estructura** (nivel `high`, para arrastre
  `medium`): cráneo 900k de 1.62M, cerebro 700k de 643k (entra completo).

## 🔧 Dependencias

```bash
pip install -r NEUROHUB/requirements.txt
```

Las dependencias de segmentación IA (torch, monai, TotalSegmentator) están
comentadas en `requirements.txt` porque solo hacen falta para el pipeline
completo, no para el visor ni la interfaz. Las de la interfaz legacy
(`customtkinter`, `pygame`) tampoco hacen falta si usas la app Qt.

## 🧪 Tests

```bash
cd NEUROHUB
python -m pytest tests/ -q
```

La suite cubre carga de datos, vistas 2D, el algoritmo de pincel
(`test_pincel_2d.py`) y el flujo de delineado en la vista 2D
(`test_delineado_2d.py`).

En `NEUROHUB/scripts/` hay además comprobaciones de humo que se ejecutan
directamente con `python` e imprimen medidas concretas: `check_brush.py`
(radio, deshacer y cache), `check_mapping.py` (mapeo pantalla → voxel) y
`check_pintado_real.py` (pintado y borrado con eventos de ratón reales de Qt,
tanto en datos sintéticos como en un caso BraTS real).

## 📄 Licencia

Proyecto de tesis académica. Los datos en `data/` son públicos (BraTS, TCIA).
