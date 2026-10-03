"""
NEUROHUB - Interfaz grafica PySide6 (capa de presentacion).

Este paquete implementa la ventana principal, los paneles de capas, el
visor central 2D/3D y la consola de progreso siguiendo el flujo de trabajo de
Raidionics, pero TODA la computacion sigue delegandose en los modulos ya
existentes de `src/` (DICOM, segmentacion, BraTS, control de calidad, mallas,
FBX). El unico punto de contacto es `pipeline_bridge.py`.

Modulos:
    software_config   paleta, tipografias y hoja QSS global
    widgets           grupo plegable, progreso circular, consola, tarjetas
    pbr               materiales PBR por estructura (extraidos de main.py)
    mesh_store        rutas canonicas y descubrimiento de mallas/cortes
    study_model       series, serie activa, capas y visibilidad
    panels            panel de estudio (series) y panel de capas
    viewer_2d         cortes ortogonales con zoom y desplazamiento
    viewer_3d         escena multi-modelo sobre VTK-Qt
    pipeline_bridge   workers de segmentacion y exportacion (QThread)
    main_window       ventana principal que coordina todo lo anterior
    app               punto de entrada (`python -m src.ui_qt.app`)
"""

__all__ = ["app", "main_window", "panels", "viewer_2d", "viewer_3d",
           "study_model", "mesh_store", "pbr", "pipeline_bridge",
           "software_config", "widgets"]
