# Resumen de simulaciones ATLAS MR

Pruebas PlayMode (Unity 2022.3.40f1, `-runTests`): **31/31 superadas**, 0 fallidas. 
GPU de la estación: AMD Radeon RX 9070 XT.

## 1. Carga de estudios (lesión presente, escala real 1:1)

| Estudio | Lesión | Estructuras | Triángulos | Cerebro ancho×alto×largo (cm) | Lesión (cm) | Carga (s) |
|---|---|---:|---:|---|---|---:|
| tumor_02 | tumor | 31 | 703,567 | 14.3×10.7×14.7 | 7.2×6.7×8.9 | 0.073 |
| aneurisma_05 | aneurisma | 30 | 702,141 | 12.6×11.1×15.2 | 0.8×0.7×0.7 | 0.052 |
| brats_00000 | tumor | 30 | 701,514 | 13.3×12.1×16.9 | 4.5×4.8×7.6 | 0.053 |
| brats_00003 | tumor | 30 | 702,143 | 13.9×11.3×17.6 | 5.4×6.1×7.2 | 0.044 |
| brats_00006 | tumor | 30 | 702,559 | 12.9×11.9×17.4 | 7.4×6.9×7.2 | 0.043 |
| tumor_02_ligero | tumor | 31 | 185,740 | 14.3×10.7×14.7 | 7.2×6.7×8.9 | 0.040 |
| aneurisma_05_ligero | aneurisma | 30 | 181,840 | 12.6×11.2×15.2 | 0.8×0.7×0.7 | 0.035 |
| brats_00000_ligero | tumor | 30 | 180,574 | 13.3×12.1×16.9 | 4.5×4.8×7.6 | 0.036 |
| brats_00003_ligero | tumor | 30 | 181,769 | 13.9×11.3×17.6 | 5.4×6.1×7.2 | 0.039 |
| brats_00006_ligero | tumor | 30 | 181,152 | 12.9×11.9×17.4 | 7.4×6.9×7.2 | 0.039 |

## 2. Gestos con manos simuladas (RD5)

| Estudio | Traslación 10 cm (error mm) | Rotación 30° | Escala ×1,5 | Límite escala | Toque izq. oculta | Despiece (m) | Restablecer |
|---|---:|---:|---:|---|---|---:|---|
| tumor_02 | 0.000 | 30.00° | 1.500 | sí | craneo | 0.055 | sí |
| aneurisma_05 | 0.000 | 30.00° | 1.500 | sí | craneo | 0.055 | sí |
| brats_00000 | 0.000 | 30.00° | 1.500 | sí | corteza | 0.055 | sí |
| brats_00003 | 0.000 | 30.00° | 1.500 | sí | corteza | 0.055 | sí |
| brats_00006 | 0.000 | 30.00° | 1.500 | sí | corteza | 0.055 | sí |

## 3a. Render correcto (URP)

Cada estudio completo se renderiza con el pipeline del proyecto y se comprueba que todos los materiales usan shaders URP y que no aparece ningún píxel magenta (shader de error).

| Estudio | Pipeline | Píxeles del modelo (256²) | Píxeles magenta | Materiales no URP |
|---|---|---:|---:|---:|
| tumor_02 | NeuroHubURP | 10,836 | 0 | 0 |
| aneurisma_05 | NeuroHubURP | 9,402 | 0 | 0 |
| brats_00000 | NeuroHubURP | 6,796 | 0 | 0 |
| brats_00003 | NeuroHubURP | 6,878 | 0 | 0 |
| brats_00006 | NeuroHubURP | 6,547 | 0 | 0 |

Corrección del 22/11/2026: el proyecto no tenía asignado ningún pipeline URP, así que los modelos se dibujaban con el shader de error (magenta) y las cifras de rendimiento anteriores no medían el sombreado real. Ahora `NeuroHubRenderSetup` crea y asigna `Assets/Settings/NeuroHubURP.asset`, y las cifras de la sección 3 están medidas con el material translúcido real.

## 3. Rendimiento: render estéreo a resolución de Meta Quest 3 (RD4 ≥ 30 FPS)

Dos ojos de 2064×2208 px con MSAA 4×, modelo girando, tiempo CPU+GPU sincronizado por cuadro (120 cuadros).

| Estudio | Triángulos | ms medio | ms p95 | FPS medio | FPS p95 |
|---|---:|---:|---:|---:|---:|
| tumor_02 | 703,567 | 2.45 | 2.72 | 408 | 368 |
| aneurisma_05 | 702,141 | 2.63 | 2.89 | 380 | 346 |
| brats_00000 | 701,514 | 2.65 | 3.00 | 377 | 333 |
| brats_00003 | 702,143 | 2.76 | 3.17 | 362 | 315 |
| brats_00006 | 702,559 | 2.52 | 2.80 | 397 | 357 |
| tumor_02_ligero | 185,740 | 2.43 | 2.69 | 412 | 371 |
| aneurisma_05_ligero | 181,840 | 2.40 | 2.82 | 416 | 354 |
| brats_00000_ligero | 180,574 | 2.37 | 2.58 | 422 | 388 |
| brats_00003_ligero | 181,769 | 2.23 | 2.56 | 448 | 391 |
| brats_00006_ligero | 181,152 | 2.37 | 2.69 | 421 | 372 |

Estas cifras son de una GPU de escritorio (válidas para PC VR y Quest Link). Un visor autónomo tiene bastante menos potencia gráfica, así que el margen sobre 30 FPS debe confirmarse en el propio visor; para HoloLens 2 se recomiendan los estudios `_ligero` (~180 k triángulos).

## 4. OpenXR

**Editor (batchmode):** loader `OpenXRLoader`, runtime `Unity Mock Runtime` 0.0.2; la sesión llega a READY. En `-batchmode` el Editor no dibuja la vista de juego, por eso la pantalla XR se valida con el reproductor.

**Reproductor Windows (`ATLAS_MR.exe -atlas-simulacion`):** loader `OpenXRLoader`, runtime `Unity Mock Runtime`, pantalla XR activa: **sí** en 0.12 s, dispositivo `OpenXR Display`.

| Estudio | Lesión | Estructuras | Triángulos | Pelar capa | Despiece |
|---|---|---:|---:|---|---:|
| tumor_02 | tumor | 31 | 703,567 | sí | 1.00 |
| aneurisma_05 | aneurisma | 30 | 702,141 | sí | 1.00 |
| brats_00000 | tumor | 30 | 701,514 | sí | 1.00 |
| brats_00003 | tumor | 30 | 702,143 | sí | 1.00 |
| brats_00006 | tumor | 30 | 702,559 | sí | 1.00 |

El Mock Runtime usa gráficos nulos (`XR_UNITY_null_gfx`): no dibuja las texturas de los ojos, así que su tasa de cuadros no mide rendimiento gráfico (para eso está la sección 3). Tampoco implementa `XR_EXT_hand_tracking`; el seguimiento de manos real solo puede verificarse en un visor.

## Pendiente en visor físico

- FPS sostenidos en Quest 3 / HoloLens 2 con los estudios completos y ligeros (RD4).
- Gestos con manos reales (`XR_EXT_hand_tracking`) en dos visores OpenXR distintos (RD5).
- TRE del registro sobre el fantoma (RD2, RD3) y Dice frente a la referencia del neuronavegador (RD1).
