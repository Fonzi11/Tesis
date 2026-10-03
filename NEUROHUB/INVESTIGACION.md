# 📚 Investigación de Recursos para NEUROHUB

## Datasets Públicos para Identificación de Tumores Cerebrales

### BraTS 2020/2021/2023 (Brain Tumor Segmentation)
- **Formato**: NIfTI (.nii.gz)
- **Modalidades**: T1, T1ce (contraste), T2, T2-FLAIR
- **Anotaciones** (máscaras `_seg.nii.gz`):
  - Label 1: **NCR/NET** (Necrosis y tumor no realzado)
  - Label 2: **ED** (Edema peritumoral)
  - Label 4: **ET** (Tumor realzado con gadolinio)
- **Acceso**: Registración en CBICA UPenn. Muestra libre en HuggingFace
  `rocky93/BraTS_segmentation`
- **Uso en NEUROHUB**: ya descargadas 12 muestras en `data/nifti/braTS_sample/`

### TCIA (The Cancer Imaging Archive)
- **Formato**: DICOM
- **Colecciones clave**: TCIA-GBM, TCIA-LGG (gliomas con segmentación experta)
- **Acceso**: Libre en cancerimagingarchive.net
- **URL**: https://www.cancerimagingarchive.net/

### ADAM Challenge (Aneurysm Detection And segMentation)
- **Formato**: NIfTI
- **Anotaciones**: máscaras de aneurismas, bounding boxes
- **Tipo**: Detección y segmentación de aneurismas intracraneales
- **Acceso**: https://adam.isi.uu.nl/

## Complemento con Neuroradiología

### Protocolo de identificación de tumores
1. Adquisición MRI multimodal (T1, T1ce, T2, FLAIR)
2. Registrado al mismo template anatómico
3. Interpolación isotrópica 1mm³
4. Segmentación: ET (realzado), ED (edema), NCR (necrosis)
5. Evaluación: Dice Similarity vs. máscaras expertas

### Detección de aneurismas
1. Adquisición CTA/MRA con contraste (tag DICOM 0018|0010: ContrastBolusAgent)
2. Segmentación de vasculatura (umbral HU, TotalSegmentator)
3. Esqueletización del árbol vascular
4. Análisis de ratio dilatación local / basal
5. Análisis de curvatura y proximidad a bifurcaciones
6. Síntesis: score compuesto + filtro volumen mínimo

## Neuronavegación

### Formatos compatibles
| Sistema | Formatos aceptados |
|---------|-------------------|
| Medtronic StealthStation | DICOM, STL |
| BrainLab | DICOM, STL, NRRD |
| 3D Slicer (open source) | NIfTI, DICOM, STL, PLY |

### Flujo de trabajo recomendado
1. Cargar NIfTI/DICOM en NEUROHUB
2. Segmentar tumor/aneurisma (BRATS o heurística)
3. Exportar STL (funciones `exportar_para_neuronavegacion`)
4. Importar en 3D Slicer → fusionar con volumen → exportar al sistema de neuronavegación

### Protocolo OpenIGTLink
- Protocolo abierto para comunicación en tiempo real en quirófano
- Compatible con 3D Slicer, robots quirúrgicos y sistemas de tracking

## Pipeline de Segmentación Implementado en NEUROHUB

```
Input (DICOM/NIfTI)
  → Preprocesamiento (SimpleITK, normalización intensidad)
  → Segmentación:
      - MRI multimodal → BRATS SegResNet (4 canales)
      - MRI/CT unimodal → Heurística por percentiles
      - Vasculatura → TotalSegmentator / umbral CTA
  → Identificación:
      - Tumor: ET=4 (magenta), ED=2, NCR=1
      - Aneurisma: score de dilatación/curvatura (naranja)
  → Visualización:
      - pygame: Visor 3D (rotación, zoom, slices)
      - turtle: Anatomía educativa interactiva
      - tkinter: Hub de control dark theme
  → Exportación:
      - STL (+NIfTI) para neuronavegación
      - Volumen de estructura reportado en cm³
```

## Notas de Implementación

- **BraTS 2020**: El modelo MONAI `brats_mri_segmentation` (v0.4.4) pesa
  ~33MB y se descarga automáticamente de MONAI Model Zoo (en `NEUROHUB/`)
- **TotalSegmentator**: Segmenta >100 estructuras anatómicas, incluyendo
  cerebro, cráneo, vasos (en NEUROHUB)
- **Los archivos de ejemplo**: 12 pacientes BraTS2021 con 4 modalidades
  cada uno están en `data/nifti/braTS_sample/`

## Referencias
1. Menze et al., "The Multimodal Brain Tumor Image Segmentation Benchmark (BRATS)", IEEE TMI 34(10), 2015.
2. Bakas et al., "Advancing The Cancer Genome Atlas glioma MRI collections", Nat. Sci. Data, 2017.
3. [BraTS Challenge](https://www.braintumorsegmentation.org/)
4. [TCIA](https://www.cancerimagingarchive.net/)
5. [ADAM Challenge](https://adam.isi.uu.nl/)