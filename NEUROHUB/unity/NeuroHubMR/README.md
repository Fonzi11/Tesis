# NEUROHUB MR

Escena base de realidad mixta para revisar modelos DICOM reconstruidos por
NEUROHUB. Usa Unity 2022.3 LTS, URP, OpenXR, XR Interaction Toolkit y XR
Hands. La misma escena sirve como visor de escritorio y como aplicación
OpenXR para HoloLens 2, Quest 3/Pro y otros visores compatibles, siempre que
el proveedor exponga seguimiento de manos.

## Flujo

1. Generar las mallas del estudio y exportarlas a FBX desde NEUROHUB.
2. Ejecutar `python launcher.py unity <carpeta-del-estudio>`.
3. Abrir `unity/NeuroHubMR` en Unity Hub.
4. Importar los FBX en `Assets/Resources/Studies/<studyId>/` y usar
   el constructor `NEUROHUB > MR > Build Study Scene`.
5. Configurar el perfil OpenXR del dispositivo y asignar las acciones de mano
   a `NeuroHubGestureController`.

El manifiesto conserva el identificador de estudio y los colores/opacidades de
cada estructura. No mezcla modelos entre estudios.

## Gestos

- Arrastre de mano: rotación.
- Pinza/escala: zoom continuo limitado.
- Botón de UI: reiniciar transformación.

Para máxima velocidad se usa URP, materiales con GPU instancing, carga
asíncrona y el nivel de detalle generado por NEUROHUB. La revisión clínica
continúa siendo humana: esta escena es un visor y no declara diagnóstico.
