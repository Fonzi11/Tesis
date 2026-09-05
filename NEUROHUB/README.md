# 🧠 NEUROHUB

Plataforma multiplataforma para la identificación de **tumores** y **aneurismas**
en imágenes médicas (DICOM/NIfTI), con segmentación completa de estructuras
cerebrales, generación de mallas 3D y exportación FBX para Unity.

## 🚀 Inicio Rápido

```bash
cd NEUROHUB
python main.py
```

## 📦 Dependencias

```bash
pip install pygame pyinstaller customtkinter matplotlib
            SimpleITK nibabel numpy scipy scikit-image
            trimesh pillow
```

## 🖥️ Tecnologías

| Tecnología | Rol |
|-----------|-----|
| **tkinter/customtkinter** | GUI principal dark theme |
| **pygame** | Visor 3D interactivo (mallas reales STL) |
| **turtle** | Panel de anatomía cerebral educativa |
| **SimpleITK** | Procesamiento NIfTI/DICOM + carga de series |
| **trimesh** | Generación de mallas STL (marching cubes) |
| **scikit-image** | Extracción de superficies (marching cubes) |
| **matplotlib** | Preview 3D headless (shading por normales) |
| **Blender** | Exportación FBX con materiales PBR (opcional) |
| **TotalSegmentator** | Segmentación de 117 estructuras anatómicas |
| **BraTS** | Segmentación de tumores cerebrales (HuggingFace) |
| **PyInstaller** | Generación de ejecutable standalone |

## 📁 Estructura

```
NEUROHUB/
├── main.py              # Aplicación principal (tkinter hub)
├── build_exe.py         # Genera ejecutable con PyInstaller
├── tests/               # Scripts de verificación (imports, slices)
└── src/
    ├── __init__.py      # Módulo
    ├── data_manager.py  # Gestión datasets + carga NIfTI/DICOM
    ├── segmentacion_completa.py  # Segmentación completa + FBX Unity
    ├── viewer3d.py      # Visor 3D pygame (mallas STL reales)
    └── anatomia.py      # Anatomía interactiva con turtle

herramientas/            # (raíz del repo)
├── generar_preview.py   # Genera salidas/preview_3d.png headless (alta resolución)
├── modelo_unico.py      # Une las 6 mallas en un único FBX "NEUROHUB"
├── validar_pipeline.py  # Validación del pipeline completo
└── verificar_instalacion.py

salidas/
├── mallas/*.stl             # 6 mallas 3D (cerebro, cráneo, tumor, vasos, venas, arterias)
├── fbx/neurohub_completo.fbx  # UN solo FBX combinado para Unity (con materiales)
├── preview_3d.png           # Preview 3D renderizado headless
└── neuronavegacion/         # NIfTI por estructura para neuronavegación
```

## 🧩 Segmentación Completa

El pipeline genera **6 estructuras** a partir del volumen MRI:

| Estructura | Método | Color |
|-----------|--------|-------|
| Cerebro | TotalSegmentator (máscara brain) | Gris |
| Cráneo | TotalSegmentator (máscara skull) | Hueso |
| Tumor | BraTS FLAIR + segmentación IA | Magenta |
| Arterias | Separación heurística de vasos (pos. anterior) | Rojo |
| Venas | Separación heurística de vasos (resto) | Azul |
| Vasos completos | TotalSegmentator (combinación vascular) | Naranja |

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

**Separación arterias/venas**: dado que los datos son MRI sin contraste MRA/CTA,
se usa una heurística anatómica: componentes vasculares en posición anterior-media
y alta intensidad T1 → arterias; resto → venas, con ajuste de balance.

## 🎮 Controles

### Visor 3D (pygame)
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
- **Directorio DICOM**: detecta y carga la serie automáticamente
  (incluye series con múltiples cortes)

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

### Ejecutable standalone
```bash
python build_exe.py  # genera dist/NEUROHUB.exe (~434 MB)
```

## 📜 Licencia

Proyecto de tesis académica. Los datos médicos en `../data/` son de
dominio público (BraTS, TCIA) o de uso académico (ADAM).