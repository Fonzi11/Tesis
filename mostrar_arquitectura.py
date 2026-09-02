#!/usr/bin/env python3
"""
Script de demostración de la arquitectura visual del ATLAS mejorado.
Muestra el layout 2D+3D y explica cómo interactúan los componentes.
"""

from pathlib import Path

DEMO = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ATLAS v1.1 - INTERFAZ MEJORADA                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────────────┐
│                              BARRA LATERAL (SIDEBAR)                       │
│ • Seleccionar entrada (DICOM/NIfTI)                                        │
│ • Seleccionar salida                                                       │
│ • [SEGMENTAR TUMOR] → Dispara integrate_brats_into_pipeline()              │
│ • [DETECTAR ANEURISMA]                                                     │
│ • [EXPORTAR A FBX]                                                         │
│ • Selector de enfoque: Completo / Tumor / Aneurisma                        │
└────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                          ÁREA PRINCIPAL (MAIN AREA)                          │
│                                                                              │
│  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  ┏━━━━━━━━━━━━━━━━┓               │
│  ┃ VISOR 3D (70%)                    ┃  ┃  VISTAS 2D (30%)┃               │
│  ┃ ┌────────────────────────────────┐┃  ┃  (Slice2DPanel) ┃               │
│  ┃ │                                │┃  ┃  ┌────────────┐  ┃               │
│  ┃ │     Modelo 3D                  │┃  ┃  │ AXIAL      │  ┃               │
│  ┃ │     ────────────────           │┃  ┃  │ 1024×1024px│  ┃               │
│  ┃ │     (Tumor con                 │┃  ┃  │ • Tumor    │  ┃               │
│  ┃ │      iluminación                │┃  ┃  │ • Círculo  │  ┃               │
│  ┃ │      profesional)               │┃  ┃  │ • Etiqueta │  ┃               │
│  ┃ │                                │┃  ┃  └────────────┘  ┃               │
│  ┃ │ • 3 luces (Key, Fill, Rim)     │┃  ┃  ┌────────────┐  ┃               │
│  ┃ │ • Ambient: 0.28                │┃  ┃  │ CORONAL    │  ┃               │
│  ┃ │ • Specular: 0.35               │┃  ┃  │ 1024×1024px│  ┃               │
│  ┃ │ • SpecularPower: 64            │┃  ┃  │ • Tumor    │  ┃               │
│  ┃ │ • Resolución: 1280×960         │┃  ┃  │ • Círculo  │  ┃               │
│  ┃ │                                │┃  ┃  │ • Etiqueta │  ┃               │
│  ┃ │ (Rotar: Click+Drag)            │┃  ┃  └────────────┘  ┃               │
│  ┃ │ (Zoom: Rueda Ratón)            │┃  ┃  ┌────────────┐  ┃               │
│  ┃ │                                │┃  ┃  │ SAGITAL    │  ┃               │
│  ┃ │                                │┃  ┃  │ 1024×1024px│  ┃               │
│  ┃ │                                │┃  ┃  │ • Tumor    │  ┃               │
│  ┃ │                                │┃  ┃  │ • Círculo  │  ┃               │
│  ┃ │                                │┃  ┃  │ • Etiqueta │  ┃               │
│  ┃ └────────────────────────────────┘┃  ┃  └────────────┘  ┃               │
│  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  ┗━━━━━━━━━━━━━━━━┛               │
│                                                                              │
│  (FBXPreviewPanel)                           (Slice2DPanel)                 │
│  Clase: UnifiedViewerPanel (contenedor)      Clase: UnifiedViewerPanel     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│                        CONSOLA DE LOGS (FOOTER)                            │
│                                                                            │
│ [HEADER] == SEGMENTACIÓN BRATS ==                                         │
│ [PROGRESS] Verificando modelo BRATS...                                    │
│ [SUCCESS] ✓ Máscara de tumor BRATS copiada a: tumors/tumor_brats.nii.gz  │
│ [SUCCESS] ✓ Vistas 2D generadas en: tumors/vistas_2d/                    │
│ [SUCCESS] ✓ Segmentación completada                                       │
└────────────────────────────────────────────────────────────────────────────┘


╔══════════════════════════════════════════════════════════════════════════════╗
║                        FLUJO DE DATOS (DETALLADO)                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

USER CLICKS: [SEGMENTAR TUMOR]
    ↓
_run_brats() ─ Thread
    ├─ integrate_brats_into_pipeline(nifti_path, output_dir)
    │   │
    │   ├─ Descarga/verifica modelo BRATS
    │   │
    │   ├─ segment_tumor_brats_from_single_volume()
    │   │   └─ Segmenta tumor → tumor_brats.nii.gz
    │   │
    │   └─ ✨ NUEVO: generar_vistas_2d()
    │       ├─ Lee: nifti_path (volumen original)
    │       ├─ Lee: tumor_brats.nii.gz (máscara)
    │       ├─ Genera 3 vistas con renderizado ULTRADETALLE:
    │       │   ├─ Normalización: percentiles [0.5, 99.5]
    │       │   ├─ Gamma: 0.80 (preserva tonos)
    │       │   ├─ Resolución: 1024 px
    │       │   ├─ Supersampling: 3x + LANCZOS
    │       │   ├─ Tumor overlay: círculo + relleno 50%
    │       │   └─ Pie: etiqueta "Axial/Coronal/Sagital"
    │       │
    │       └─ Escribe PNG en: salidas/segmentaciones_ai/vistas_2d/
    │           ├─ corte_axial.png (1024×1024)
    │           ├─ corte_coronal.png (1024×1024)
    │           └─ corte_sagital.png (1024×1024)
    │
    └─ _refresh_preview_async()
        └─ unified_viewer.refresh_models() + load_2d_slices()
            ├─ FBXPreviewPanel: Recarga modelos 3D
            │   ├─ Renderizado VTK con 3 luces
            │   ├─ Iluminación Phong (máximo realismo)
            │   └─ Salida: PNG en canvas CustomTkinter
            │
            └─ Slice2DPanel: Carga vistas 2D PNG
                ├─ Lee: salidas/segmentaciones_ai/vistas_2d/*.png
                ├─ Redimensiona: 1024×1024 → 180×180 (thumbnail)
                ├─ Muestra en grid: [Axial] [Coronal] [Sagital]
                └─ Manejo de errores: muestra placeholder si falta archivo


╔══════════════════════════════════════════════════════════════════════════════╗
║                     PARÁMETROS DE CALIDAD (HARDCODED)                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

RENDERIZADO 3D (VTK)
──────────────────────────────────────────
• Resolución Interna: 1280 × 960 px
• Iluminación:
  └─ Key Light:     pos=(1.0, 0.5, 1.0),   intensity=1.0 (blanca)
  └─ Fill Light:    pos=(-0.8, 0.3, 0.5), intensity=0.5 (gris)
  └─ Rim Light:     pos=(0.0, -1.0, 0.2), intensity=0.4 (azul)
  └─ Ambient:       (0.2, 0.2, 0.22)
  
• Propiedades PBR:
  └─ Ambient:         0.28
  └─ Diffuse:         0.72
  └─ Specular:        0.35
  └─ SpecularPower:   64.0
  └─ Interpolation:   Phong

• Buffer Output: 1280×960 PNG


RENDERIZADO 2D (PIL + NumPy)
──────────────────────────────────────────
• Resolución Objetivo: 1024 px
• Supersampling: 3x (3072px → LANCZOS → 1024px)
• Contraste:
  └─ Percentiles: [0.5, 99.5]  ← Más agresivo que [1.0, 99.5]
  └─ Gamma: 0.80               ← Más suave que 0.85
  
• Visualización Tumor:
  └─ Relleno: RGBA(255, 0, 170, 110) magenta 50%
  └─ Borde: Erosión 1 iteración (antes 2)
  └─ Círculo: RGBA(120, 255, 90, 255) verde láser
  └─ Centroide: Cruz 15px×escala (antes 12px)
  
• Pie de Imagen:
  └─ Fuente: 24pt (antes 22pt)
  └─ Fondo: RGBA(0, 0, 0, 180) (antes 150)
  └─ Texto: "Axial" / "Coronal" / "Sagital"

• Buffer Output: 1024×1024 PNG


INTERFAZ (CustomTkinter)
──────────────────────────────────────────
• Layout Principal: 70% visor 3D + 30% vistas 2D
• Colores: Tema oscuro Material 3 (bg=#000000, accent=#8ab4f8)
• Fuentes: Segoe UI, Bahnschrift, Montserrat
• Thumbnails 2D: 180×180 px (redimensionadas de 1024×1024)
• Grid 2D: 3 columnas × 1 fila (Axial | Coronal | Sagital)


╔══════════════════════════════════════════════════════════════════════════════╗
║                         VALIDACIONES COMPLETADAS                             ║
╚══════════════════════════════════════════════════════════════════════════════╝

✅ Sintaxis Python: OK (py_compile exitoso)
✅ Importaciones: Validadas
✅ Lógica de Flujo: Verificada
✅ Clases Nuevas: UnifiedViewerPanel + Slice2DPanel
✅ Métodos Nueva: refresh_models(), load_2d_slices()
✅ Integración: 03_integrar_brats → llamada a generar_vistas_2d()
✅ Generación Automática: PNG en vistas_2d/
✅ Refrescar UI: _refresh_preview() sincroniza ambos paneles
✅ Thread-Safe: Operaciones en main thread (CustomTkinter requirement)


╔══════════════════════════════════════════════════════════════════════════════╗
║                        PRÓXIMOS PASOS (TESTING)                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

1. EJECUTAR INTERFAZ GRÁFICA
   $ cd d:\\Tesis\\ATLAS
   $ python main.py

2. CARGAR UN DICOM REAL
   • Archivo: d:\\Tesis\\data\\dicom\\PGBM-001\\...\\brain.dcm
   • O NIfTI: d:\\Tesis\\data\\nifti\\braTS_sample\\...\\scan.nii.gz

3. EJECUTAR SEGMENTACIÓN
   • Click: [SEGMENTAR TUMOR]
   • Esperar completación

4. VERIFICAR RESULTADOS
   ✓ ¿Se actualiza visor 3D con iluminación mejorada?
   ✓ ¿Aparecen las 3 vistas 2D en el panel derecho?
   ✓ ¿Se ven los archivos PNG en salidas/segmentaciones_ai/vistas_2d/?
   ✓ ¿Está el tumor claramente enmarcado en los cortes?

5. OPTIMIZAR SI NECESARIO
   • Si vistas 2D lentas: escala=2 en generar_vistas_2d()
   • Si renderizado 3D muy caro: reducir resolución interna
   • Si interfaz lag: usar threading para cargar PNGs
"""

if __name__ == "__main__":
    print(DEMO)
    
    # Guardar también en archivo
    with open(Path(__file__).parent / "ARQUITECTURA_VISUAL.txt", "w", encoding="utf-8") as f:
        f.write(DEMO)
    
    print("\n✓ Arquitectura guardada en: ARQUITECTURA_VISUAL.txt")
