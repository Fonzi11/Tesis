# ATLAS MR

Escena de realidad mixta para revisar los modelos 3D reconstruidos por
ATLAS. Usa Unity 2022.3 LTS, URP, OpenXR y XR Hands. La misma escena
funciona como visor de escritorio y como aplicación OpenXR para Meta Quest 3,
HoloLens 2, Pico y otros visores compatibles, siempre que el runtime exponga
seguimiento de manos (`XR_EXT_hand_tracking`). No usa ningún SDK propietario.

## Flujo

1. Generar los modelos con `NEUROHUB/herramientas/modelos_ar_freesurfer.py`.
2. Instalar los estudios en Unity (FBX por estructura + manifiesto + índice):

   ```bat
   D:\Tesis\.venv\Scripts\python.exe NEUROHUB\herramientas\ar_unity.py ^
     salidas\modelos_ar_freesurfer\tumor_02 salidas\modelos_ar_freesurfer\aneurisma_05 ...
   ```

3. Configurar el proyecto (importación, OpenXR y escena) sin abrir el Editor:

   ```bat
   "D:\Unity\editor\2022.3.40f1\Editor\Unity.exe" -batchmode -nographics ^
     -projectPath D:\Tesis\NEUROHUB\unity\NeuroHubMR -executeMethod NeuroHubBatch.Setup
   ```

   También desde el Editor: `ATLAS > MR > Configurar OpenXR` y
   `ATLAS > MR > Build Study Scene`.
4. Compilar: `NeuroHubBatch.BuildAndroid` (`Builds/Android/ATLAS_MR.apk`,
   Quest/Pico, paquete `com.atlas.mr`) o `NeuroHubBatch.BuildWindows`
   (`Builds/Windows/ATLAS_MR.exe`: PC VR, Quest Link, HoloLens remoting).

Las clases C# conservan el prefijo `NeuroHub` (y la carpeta del proyecto su
nombre) para no invalidar las referencias de la escena; el producto, los menús
y los mensajes se llaman ATLAS.

Cada estudio vive en `Assets/Resources/Studies/<estudio>/` con su
`study_manifest.json` (color, opacidad, grupo de capa y volumen por
estructura). `studies_index.json` lista los cinco casos y sus versiones
`_ligero`. Los estudios anteriores se movieron a `EstudiosArchivados/` para
que no entren en el build.

## OpenXR

`NeuroHubXRSetup` deja asignado el loader OpenXR en Windows y Android, render
*single pass instanced* y estas características:

- Manos: `HandTracking` (XR Hands), `MetaHandTrackingAim`,
  `HandInteractionProfile` (Khronos), `HandCommonPosesInteraction`,
  `PalmPoseInteraction`, `MicrosoftHandInteraction` (HoloLens 2).
- Controladores: Khronos Simple, Oculus Touch, Meta Quest Touch Pro.
- Android: `MetaQuestFeature`; IL2CPP ARM64, API mínima 29, Vulkan/GLES3.

La cámara limpia con negro transparente: en visores ópticos se ve el mundo
real y en Quest sirve de base para passthrough.

El render usa `Assets/Settings/NeuroHubURP.asset` (MSAA 4×, sin HDR ni
sombras), que `NeuroHubRenderSetup` crea y asigna en Graphics y en todos los
niveles de calidad (también desde `ATLAS > MR > Configurar URP`). Sin ese
asset los materiales URP de los modelos se dibujan en magenta; la prueba
`Render_URPActivoSinShadersDeError` lo detecta.

Sin visor activo (Editor sin runtime OpenXR, PC sin gafas),
`NeuroHubDesktopView` desactiva el seguimiento de la cabeza y coloca la cámara
frente al estudio.

## Demostración en el Editor

`ATLAS > MR > Reproducir demostración (gestos simulados)` abre la escena,
entra en Play y recorre los cinco estudios repitiendo despacio los gestos con
manos simuladas (esfera azul = izquierda, naranja = derecha; crece al hacer
pinza) y rótulos con el estudio, la lesión, los triángulos y los FPS. Espacio
pausa el recorrido; el teclado sigue funcionando. Desde la línea de comandos:

```bat
Unity.exe -projectPath D:\Tesis\NEUROHUB\unity\NeuroHubMR ^
  -executeMethod NeuroHubDemoMenu.OpenAndPlay -atlas-demo ^
  -atlas-capturas SimulationResults\capturas
```

`-atlas-capturas` guarda una imagen por paso en la primera vuelta.

## Gestos

| Gesto | Acción |
|---|---|
| Pinza con una mano y mover | Trasladar y rotar (agarre 6DoF) |
| Pinza con las dos manos | Escalar (distancia), rotar y trasladar |
| Toque rápido mano izquierda | Pelar la capa más externa (cráneo → corteza → sustancia blanca → …); la lesión nunca se oculta |
| Toque rápido mano derecha | Despiece animado alrededor de la lesión |
| Pinza breve con ambas manos | Restablecer posición, capas y despiece |

En escritorio: flechas/arrastre = rotar, WASD/QE = trasladar, +/- o rueda =
escala, L = pelar, U = mostrar todo, X = despiece, N = siguiente estudio,
R = restablecer.

## Simulaciones

Pruebas PlayMode en `Assets/Tests/PlayMode` (sin visor):

```bat
Unity.exe -batchmode -projectPath ... -executeMethod NeuroHubBatch.PrepareSimulation
Unity.exe -batchmode -projectPath ... -runTests -testPlatform PlayMode ^
  -testResults SimulationResults\resultados_pruebas.xml
Unity.exe -batchmode -projectPath ... -executeMethod NeuroHubBatch.FinishSimulation
```

`PrepareSimulation` activa el Mock Runtime oficial de OpenXR y
`FinishSimulation` lo desactiva para usar visores reales. Las métricas quedan en
`SimulationResults/simulacion_resultados.json`.

La revisión clínica sigue siendo humana: esta escena es un visor y no
establece diagnósticos.
