# 🧠 NEUROHUB

Plataforma unificada para la identificación de **tumores** y **aneurismas**
en imágenes médicas (DICOM/NIfTI), con segmentación completa de estructuras
cerebrales, generación de mallas 3D y exportación FBX para Unity.

> **Carpeta única del proyecto.** Integra lo que antes eran dos aplicaciones
> separadas (`ATLAS/` y `NEUROHUB/`). La interfaz principal es la de ATLAS
> (visor 3D VTK embebido con capas, opacidad, supersampling) y los módulos de
> datos, mallas, pipeline, tests y el visor GPU de PyVista vienen de NEUROHUB.

### 🚀 Inicio Rápido

La interfaz actual es **PySide6/Qt** y vive en `src/ui_qt`:

```bash
cd /d D:\Tesis\NEUROHUB
D:\Tesis\.venv\Scripts\python.exe -m pip install -r requirements.txt
D:\Tesis\.venv\Scripts\python.exe launcher.py doctor
D:\Tesis\.venv\Scripts\python.exe launcher.py ui
```

> **Interfaz legacy.** `main.py` (tkinter + pygame) se conserva como
> referencia histórica y ya **no** es el punto de entrada. Sus dependencias
> (`customtkinter`, `pygame`) son opcionales.

## 📦 Dependencias

```bash
pip install -r requirements.txt
```

### Comandos oficiales

Ejecuta siempre estos comandos desde `D:\Tesis\NEUROHUB` usando el Python del
entorno `.venv`. `launcher.py` es el punto de entrada único:

```bat
cd /d D:\Tesis\NEUROHUB
D:\Tesis\.venv\Scripts\python.exe launcher.py doctor
D:\Tesis\.venv\Scripts\python.exe launcher.py ui
D:\Tesis\.venv\Scripts\python.exe launcher.py verificar --etapa deps --etapa imports
```

En la interfaz, dentro de **Estudio**, usa **Carpeta DICOM...** para
seleccionar la carpeta completa del estudio. La búsqueda incluye subcarpetas,
por lo que no es necesario seleccionar los archivos `.dcm` uno por uno.
También acepta estudios exportados como uno o varios `.zip` con archivos
DICOM dentro de `DICOM/`; los ZIP ilegibles se omiten si existe otro archivo
válido y se selecciona automáticamente la serie con más cortes (normalmente
la adquisición volumétrica principal).
**Archivo NIfTI...** queda disponible para cargar un volumen `.nii`/`.nii.gz`
o un DICOM individual.

Para procesar DICOM de pacientes y generar el modelo 3D:

```bat
cd /d D:\Tesis\NEUROHUB
D:\Tesis\.venv\Scripts\python.exe herramientas\extraer_pacientes.py --listar
D:\Tesis\.venv\Scripts\python.exe herramientas\convertir_paciente.py 890923
D:\Tesis\.venv\Scripts\python.exe procesar_caso.py D:\Tesis\data\nifti\pacientes\890923.nii.gz
```

El último comando genera máscaras, mallas y renders bajo `D:\Tesis\salidas`.
Para casos grandes puedes añadir `--rapido`; para la máxima resolución no lo
añadas. `launcher.py doctor` informa si Docker/Raidionics está disponible, pero
Docker no es necesario para el visor ni para el pipeline principal.

## 🖥️ Tecnologías

| Tecnología | Rol |
|-----------|-----|
| **PySide6 / Qt** | Interfaz principal (ventana, paneles, visor 2D) |
| **VTK / PyVista** | Render 3D con OpenGL y supersampling |
| **SimpleITK** | Procesamiento NIfTI/DICOM + carga de series |
| **trimesh / scikit-image** | Mallas STL (marching cubes) |
| **numpy / scipy** | Cálculo numérico y mapeo de voxeles |
| **TotalSegmentator** | Segmentación de estructuras anatómicas |
| **BraTS (SegResNet)** | Segmentación de tumores cerebrales |
| **ONNX Runtime + DirectML** | Backend AMD para modelos ONNX exportados y validados |
| **PyInstaller** | Generación de ejecutable standalone |

## 📁 Estructura

```
NEUROHUB/
├── launcher.py          # Punto de entrada único: UI, doctor y verificación
├── procesar_caso.py     # Pipeline completo de un caso
├── pipeline.py          # Orquestación del pipeline
├── render_caso.py       # Render y exportación de un caso
├── build_exe.py         # Genera ejecutable con PyInstaller
├── herramientas/        # Conversión, exportación y utilidades del proyecto
│   └── diagnostico/     # Verificación integral y diagnósticos opcionales
├── scripts/             # Comprobaciones de humo (pincel, mapeo, pintado real)
├── tests/               # Suite de tests (pytest)
└── src/
    ├── ui_qt/           # Aplicación Qt: ventana, paneles, visor 2D y visor 3D
    ├── volumen_2d.py    # Volumen NIfTI + máscara + pincel de delineado
    ├── data_manager.py  # Gestión datasets + carga NIfTI/DICOM
    ├── segmentacion_completa.py  # Segmentación completa + FBX Unity
    └── radiomics/       # Extracción de características radiómicas

salidas/
├── mallas/*.stl             # Mallas 3D (cerebro, cráneo, tumor, vasos)
├── fbx/neurohub_completo.fbx  # UN solo FBX combinado para Unity (con materiales)
├── segmentaciones_ai/*.nii.gz # Máscaras NIfTI por estructura
└── neuronavegacion/         # NIfTI por estructura para neuronavegación
```

`data/`, `modelos_preentrenados/` y `salidas/` permanecen en la raíz del
workspace (`D:\Tesis`) porque contienen datos clínicos, pesos grandes y
resultados generados. El código y las herramientas viven en esta carpeta
`NEUROHUB/`; no hay que duplicarlos ni ejecutar copias antiguas desde la raíz.

## 🖌️ Visor 2D y delineado de tumor

El visor 2D (`src/ui_qt/viewer_2d.py`) navega los tres planos (axial,
coronal y sagital) y permite **delinear el tumor a mano** sobre la imagen:

| Herramienta | Uso |
|-------------|-----|
| **Navegar** | Rueda = zoom · Ctrl+rueda = cambio de corte |
| **Pincel** | Arrastrar con el botón izquierdo para marcar tumor |
| **Borrar** | Arrastrar con el botón izquierdo para quitar tumor |

Atajos: `B` pincel · `E` borrar · `T` ir al corte con más tumor ·
`Ctrl+Z` deshacer.

El radio del pincel se expresa en **voxels del volumen**, no en píxeles de
pantalla, de modo que el tamaño del pincel es el mismo con cualquier nivel de
zoom. La máscara se puede **guardar como NIfTI** (`Guardar máscara`) sobre la
rejilla del volumen, o usar **Segmentar y crear 3D** para guardar la anotación,
reconstruir la superficie de alta calidad y actualizar inmediatamente el visor
3D. La aplicación muestra en la cabecera el backend real de inferencia:
`AMD` cuando DirectML está disponible y `CPU` cuando no lo está.

### Dónde busca el visor el volumen

Al abrir un caso, el visor busca la imagen del paciente entre las NIfTI de la
carpeta. Prioriza los nombres conocidos (`volumen_paciente.nii.gz`) y luego las
**modalidades BraTS** (`*_flair`, `*_t1ce`, `*_t2`, `*_t1`), FLAIR primero
porque es la que mejor muestra edema y tumor realzado. Las máscaras
(`*_seg`, `*_tumor_*`, `*_label`) nunca se toman como imagen de fondo.

La máscara que se superpone debe **compartir rejilla** con el volumen; si no,
se avisa por consola y el visor carga la imagen **sin máscara** para que el
delineado manual siga siendo posible.

## 🧩 Segmentación Completa

El pipeline genera **4 estructuras principales** a partir del volumen MRI:

| Estructura | Método | Color |
|-----------|--------|-------|
| Cerebro | TotalSegmentator (máscara brain) | Gris |
| Cráneo | TotalSegmentator (máscara skull) | Hueso |
| Tumor | BraTS FLAIR + segmentación IA | Magenta |
| Aneurisma | Detección morfológica sobre `vasos.nii.gz` (si existe previamente) | Naranja |

## 🧠 Segmentación de Tumor (BRATS multimodal + respaldo)

NEUROHUB usa el modelo **BRATS 2020 (SegResNet)** para la segmentación de
tumores con precisión clínica. El modelo requiere **4 modalidades MRI reales y
alineadas** (T1, T1ce, T2, FLAIR) para distinguir las subregiones:
NCR/NET (necrosis), ED (edema) y ET (tumor realzado).

### Auto-detección de pacientes BraTS
Al cargar **cualquier archivo NIfTI**, NEUROHUB escanea su directorio en busca
de las modalidades hermanas con la convención BraTS (`*_t1`, `*_t1ce`, `*_t2`,
`*_flair`). Si encuentra ≥3 reales, ejecuta BRATS completo automáticamente:

```
python
# Cargando una sola modalidad de un paciente completo...
data/nifti/braTS_sample/BraTS2021_00000/BraTS2021_00000_flair.nii.gz
# ...se detectan y usan las 4:
#   T1, T1CE, T2, FLAIR  →  inferencia BRATS (ET/ED/NCR)
```

También se resolvió el clasificador CT/MRI: el rango de intensidad de BraTS
(t1ce llega a ~12000) ya **no** se confunde con CT.

### Modalidad única (respaldo heurístico morfológico)
Si el archivo es **un solo volumen** (como `MRBrainTumor1.nii.gz`) o es un CT:
BRATS no puede alimentarse con 4 canales duplicados (el modelo destruiría el
contraste). En ese caso NEUROHUB aplica el **método morfológico heurístico**
real (`generate_tumor_mask`): núcleo sólido (percentil 95) + histeresis de
extensión (umbral permisivo con dilatación condicionada), produciendo una
máscara `tumor_heur.nii.gz` con volumen reportado en cm³.

### Backend AMD Radeon

La Radeon se detecta mediante `DmlExecutionProvider` de ONNX Runtime, no
mediante `torch.cuda` ni `nvidia-smi`. La aceleración de render VTK/OpenGL es
independiente de la inferencia. El visor 3D usa la GPU para dibujar la escena,
pero la reconstrucción geométrica (marching cubes, suavizado y escritura STL)
es un paso de CPU. TotalSegmentator/nnUNet no acepta DirectML en
su interfaz actual, por lo que el pipeline lo ejecuta en CPU y lo declara en
los logs; nunca se etiqueta como GPU para ocultar ese fallback. Los modelos
ONNX que se incorporen al proyecto pueden seleccionar DirectML automáticamente
y conservar `CPUExecutionProvider` como fallback. Para forzar el backend:

```text
NEUROHUB_ONNX_PROVIDER=directml
```

Si DirectML no está instalado, esta variable produce un error explícito en vez
de degradar silenciosamente a CPU. Las máscaras clínicas solo deben generarse
con un modelo validado para la modalidad y el modo solicitado.

Por defecto no se inicializa CUDA ni se consulta el driver NVIDIA. La variable
`NEUROHUB_ENABLE_CUDA=1` queda únicamente como compatibilidad explícita para
otra máquina; no forma parte de la ruta AMD de este proyecto.

### RM T1 con contraste: detección por forma (`generate_tumor_mask_t1`)

La heurística anterior **falla en T1ce** y se verificó sobre
`MRBrainTumor1.nii.gz` (T1ce, 256×256×112). Eligió el **seno occipital**
(4.5 cm³) en lugar de la lesión frontal (5.2 cm³), de brillo y tamaño
comparables. Hay tres motivos, todos comprobados sobre la imagen:

1. En T1ce lo más brillante también es la grasa subcutánea, la médula ósea y el
   contraste de los senos venosos. Al priorizar por volumen, gana el seno.
2. El tumor queda **fuera** de la máscara `brain` de TotalSegmentator: el
   modelo lo descarta por ser una masa anómala. Buscar solo dentro de `brain`
   no devuelve ningún candidato, así que hay que buscar en la **convexidad**
   rellena del cerebro.
3. Con umbral alto los vasos se fragmentan y el tumor queda como el único blob
   compacto por encima del volumen mínimo, lo que sí lo separa de un vaso
   tubular.

El criterio pasa a ser **compactibilidad**, no solo intensidad: un tumor tiene
sus tres ejes del mismo orden de magnitud; un vaso es tubular, con un eje que
domina a los otros dos. Se usa la **esfericidad de Wadell**
`Ψ = π^(1/3)·(6V)^(2/3)/A`, que vale 1 en una esfera y 0.806 en un cubo. El
núcleo verificado (1.27 cm³, ejes 16.8×15.9×19.7 mm) es la semilla de un
crecimiento regional **acotado a 6 mm**: sin esa cota el watershed inunda toda
la convexidad, porque el tejido cerebral también supera el umbral. Resultado:
5.5 cm³, con la masa completa y no solo su anillo brillante.

**Vasculatura y Detección de Aneurismas**: La segmentación automática de vasos
(venas y arterias) se ha retirado del pipeline por falta de secuencias de contraste
dedicadas (MRA/CTA) en resonancias magnéticas convencionales. La detección de aneurismas
permanece en el código como modo inerte y solo se activará si el usuario proporciona
previamente una máscara vascular externa (`vasos.nii.gz`).

## 🎮 Controles

### Visor 3D (legacy pygame)

> Estos atajos corresponden al visor pygame de `src/viewer3d.py`. La
> aplicación Qt (`src/ui_qt`) usa los controles de su propia barra de capas.
- **Arrastrar** → Rotación del modelo 3D
- **Rueda del mouse** → Zoom
- **C** → Mostrar/ocultar cerebro
- **K** → Mostrar/ocultar cráneo
- **T** → Mostrar/ocultar tumor
- **A** → Mostrar/ocultar arterias
- **V** → Mostrar/ocultar venas
- **N** → Mostrar/ocultar vasos
- **M** → Mostrar/ocultar slices MRI
- **1/2** → Modo malla / puntos
- **4** → Calidad/resolución del render (auto → 0.75x → 1x → 1.5x)
- **R** → Reset de vista
- **3** → Auto-rotación
- **ESC** → Salir

> **Resolución**: la ventana se abre a ~85 % del escritorio (mínimo 1280×800;
> variable `NEUROHUB_RES=ANCHOxALTO` para forzar tamaño). Las mallas se deciman
> finas al cargar (cráneo ~50k caras, cerebro/vasos ~32k) y en reposo el render
> usa supersampling **auto-ajustado (0.75x–1.5x)** según el rendimiento del
> equipo; durante el arrastre se usan mallas "lite" para mantener fluidez.

### Anatomía (turtle)
- **←/→** o **A/D** → Navegar estructuras
- **ESC** → Salir

## 🖼️ Carga de Datos

Soporta tres orígenes de entrada:

- **NIfTI** (.nii.gz / .nii): carga directa del volumen
- **DICOM** (.dcm): lee series completas con `ImageSeriesReader`
- **Directorio DICOM o ZIP DICOM**: detecta y carga automáticamente la serie
  con más cortes (incluye series con múltiples cortes y ZIPs exportados)

Función central: `data_manager.cargar_volumen(path)` — detecta el formato
y carga transparentemente (NIfTI, DICOM suelto, serie DICOM, directorio).

## 🧠 Datasets Compatibles

| Dataset | Tipo | Formato | Anotaciones |
|---------|------|---------|-------------|
| **BraTS 2021** | Tumores cerebrales | NIfTI | ET=4, ED=2, NCR=1 |
| **TCIA** | Oncología | DICOM | Segmentación experta |
| **ADAM** | Aneurismas | NIfTI | Máscaras binarias |

Descarga directa desde HuggingFace:
- `dm.descargar_braTS_muestra(num_pacientes=N)` — descarga pacientes BraTS2021

## 📤 Exportación

La plataforma exporta:

### FBX para Unity
Archivos individuales con materiales PBR (color por estructura):
- `salidas/fbx/cerebro.fbx` (3.8 MB)
- `salidas/fbx/craneo.fbx` (9.6 MB)
- `salidas/fbx/tumor.fbx` (2.2 MB)
- `salidas/fbx/arterias.fbx` (275 KB)
- `salidas/fbx/venas.fbx` (474 KB)
- `salidas/fbx/vasos.fbx` (4.0 MB)
- `salidas/fbx/neurohub_completo.fbx` (20.5 MB) — modelo combinado

### STL para neuronavegación/impresión 3D
- `salidas/mallas/*.stl` — mallas de máxima resolución (marching cubes)
- Compatible con Medtronic StealthStation, BrainLab, 3D Slicer

### Flujo Unity → gafas AR

El flujo completo de preparación, validación espacial, importación en Unity,
construcción de la escena de neuronavegación y despliegue a gafas AR está
documentado en
[`docs/FLUJO_NEURONAVEGACION_UNITY_AR.md`](../docs/FLUJO_NEURONAVEGACION_UNITY_AR.md).
Incluye:

- Diagrama Mermaid DICOM/NIfTI → NEUROHUB → Unity → dispositivo AR.
- Paquete recomendado con FBX, STL, máscaras y `manifest.json`.
- Controles de escala, orientación, registro, tracking y rendimiento.
- Separación explícita entre funcionalidades implementadas y pasos que deben
  completarse en Unity.
- Advertencias para no presentar vasos o aneurismas si no existe una máscara
  vascular real y validada.

El FBX es una salida de visualización; no sustituye la validación clínica ni
garantiza por sí mismo el registro del modelo con el paciente.

### Ejecutable standalone
```bash
python build_exe.py  # genera dist/NEUROHUB.exe (~434 MB)
```

## 🧪 Tests

```bash
cd NEUROHUB
python -m pytest tests/ -q
```

La suite cubre la carga de datos, la generación de vistas 2D, el algoritmo de
pincel (`test_pincel_2d.py`) y el flujo de delineado 2D
(`test_delineado_2d.py`).

Además hay **comprobaciones de humo** en `scripts/` que se ejecutan con
`python` directamente e imprimen medidas concretas:

| Script | Qué comprueba |
|--------|---------------|
| `check_brush.py` | Radio del pincel, deshacer y cache de la imagen de gris |
| `check_mapping.py` | Mapeo pantalla → voxel en los tres ejes y `paintEvent` |
| `check_pintado_real.py` | Pintado y borrado con **eventos de ratón reales** de Qt |

`check_pintado_real.py` es el que interesa si hay problemas de delineado:
manda `QMouseEvent` de verdad al lienzo (no llama al algoritmo directamente)
sobre datos sintéticos **y sobre un caso BraTS real**, y comprueba que la máscara
cambia. Es la prueba que destapó el fallo corregido en el que el visor se
quedaba sin herramientas de dibujo porque no encontraba el volumen del caso.

## 📜 Licencia

Proyecto de tesis académica. Los datos médicos en `../data/` son de
dominio público (BraTS, TCIA) o de uso académico (ADAM).