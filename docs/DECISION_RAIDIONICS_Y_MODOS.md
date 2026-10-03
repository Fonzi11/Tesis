# Decisiones de arquitectura: Raidionics, modos de análisis y vasos en RM

> **Estado:** vigente · **Ámbito:** `NEUROHUB/`
>
> Este documento existe para que estas decisiones no dependan de la memoria de
> una conversación. Todo lo que aquí se afirma como "verificado" se comprobó
> ejecutando el contenedor o el código, no leyendo documentación.

---

## 1. Raidionics entra como motor externo en Docker

### Decisión

Raidionics se integra **como contenedor**, con la imagen
`dbouget/raidionics-rads:v1.3.2-py39-cpu`, fijado por versión.

### Por qué Docker y no la API de Raidionics

- El cliente oficial arrastra la API de Raidionics, que cambia entre versiones.
- El NIfTI en disco es un contrato estable y comparable descriptor a descriptor
  con el motor propio (`extract.py`).
- Se puede correr sin montar ningún servidor.

### Contrato real (verificado con una prueba de humo)

**Todos los puntos de este bloque son empíricos.** Los supuestos iniciales eran
falsos y se documentan aquí para que nadie los vuelva a asumir:

| Punto | Valor real | Supuesto descartado |
|---|---|---|
| Imagen | `dbouget/raidionics-rads` | ~~`raidionics/radiomics:latest`~~ (**no existe**) |
| Interfaz | `main.py -c <config.ini>` | ~~subcomando `suite`~~ (**no existe**) |
| Config | `.ini` con `configparser` | ~~JSON~~ |
| Pipeline | JSON aparte, vía `pipeline_filename` | — |
| Primer paso | `Model selection` | ~~`Segmentation`~~ |
| Modelos | Descarga aparte, 87 MB | ~~incluidos en la imagen~~ |
| Entrada | `<inputs>/<T0>/raw/*.nii.gz` + `mri_sequences.csv` | — |
| Salida | `<T0>/<vol>_annotation-<Clase>_<Modelo>.nii.gz` | ~~`data.json`~~ (**no se genera**) |
| Código de salida | Siempre 0, incluso al fallar | — |

Detalles finos que costó la mayor parte del diagnóstico:

1. **`caller=raidionics` en el `.ini` es lo que hace que se lea `raw/`.** Con
   cualquier otro valor, los volúmenes no se encuentran.
2. **`mri_sequences.csv` es obligatorio** para una segmentación. Sin él, el
   volumen se registra con `sequence=None` y el paso responde
   `No radiological volume for {... T1-CE ...}`.
3. **El nombre en el CSV va SIN extensión.** La búsqueda interna compara
   `basename(ruta).split('.')[0]`: `input0.nii.gz` no casa, `input0` sí.
4. **`Model selection` genera el paso `Segmentation`.** Escribir
   `Segmentation` directamente hace que el pipeline "se ejecute" en 0.01 s y no
   escriba ninguna máscara, **sin dar ningún error**.
5. **Las rutas del `.ini` deben ser las del contenedor.** Escribirlas con rutas
   del anfitrión (`C:\...`) hace que `main.py` imprima su mensaje de uso y salga
   con código 0. Además, en Windows `os.path.join` produce `\`, y una ruta de
   Linux con barras invertidas no existe: la ruta se concatena a mano.
6. **Raidionics clasifica el fichero por cardinalidad de valores.** Un volumen
   sintético de pocos niveles distintos se toma por una máscara y no por un
   volumen (`input_file_category_disambiguation`).

### El fallo silencioso

`main.py` captura las excepciones y las registra en el log, así que **el
contenedor devuelve 0 aunque el pipeline haya fallado por dentro**. Por eso
`ejecutar()` no se conforma con el `returncode`: exige que haya aparecido una
salida esperada y, si no, extrae las líneas `ERROR` del log.

### Alcance real de `raidionics-rads`

Hace **segmentación e informes clínicos**, no radiomics tipo PyRadiomics. Los
descriptores numéricos siguen viniendo del motor propio (`extract.py`);
Raidionics aporta segmentación de referencia y reporte estandarizado. Son
complementarios, no intercambiables.

### Verificación

```bash
python NEUROHUB/launcher.py raidionics estado
python NEUROHUB/launcher.py raidionics extraer <ruta_absoluta>.nii.gz --salida <salida>
```

Comprobado sobre `data/nifti/MRBrainTumor1.nii.gz` (256×256×112): máscara de
1 108 745 vóxeles, con tamaño y espaciado idénticos a los del original.

> Las rutas de los subcomandos se resuelven desde el directorio del launcher,
> no desde el directorio actual: hay que pasar rutas **absolutas**.

---

## 2. Aneurisma y tumor son modos EXCLUYENTES

### Decisión

Un caso se ejecuta en **un solo modo**: `aneurisma` **o** `tumor`. Nunca los
dos. Es una restricción del pipeline, no una preferencia de la interfaz.

### Por qué

No son "dos cosas más que se pueden pedir":

1. **Clínicamente inválido.** No se pueden diagnosticar aneurisma y tumor a la
   vez; son diagnósticos excluyentes por definición. Presentar ambos como
   hallazgos coexistentes es un error, no superabundancia de información.
2. **Técnicamente engañoso.** La detección de aneurismas (dilataciones focales
   sobre la máscara vascular) y la segmentación de tumor (masa en el parénquima)
   comparten volumen pero no hipótesis. Ejecutar ambas produce dos resultados
   que compiten, y el visor los muestra juntos como si fueran compatibles.

Antes de este cambio, el pipeline ejecutaba **los dos siempre**, sin que nada
lo impidiera.

### Cómo se garantiza

| Capa | Mecanismo |
|---|---|
| Interfaz | `QComboBox` con 3 opciones: el estado "los dos" es irrepresentable |
| API | `normalizar_modo()` valida y lanza `ValueError` si el valor no es válido |
| Worker | `PipelineWorker.__init__` valida: el error salta al construir, no a mitad |
| Ejecutor | `modo_exclusivo(a, t)` lanza si llegan los dos a True, en vez de elegir |
| Pipeline | Solo se ejecuta la rama del modo pedido |
| Persistencia | `_limpiar_mascara_del_modo_opuesto()` borra restos de una corrida anterior |
| Verificación | `verificar_exclusividad()` falla el caso si aparece la otra clase |

La validación vive en `pipeline_bridge`, no en el widget, para que **ningún**
llamador (interfaz, script o CLI) pueda saltársela.

La comprobación final (`verificar_exclusividad`) se ejecuta aunque el pipeline ya
esté limitado por construcción: es la red que detecta un cambio futuro en el
código que reintroduzca la ejecución de las dos.

### Cobertura

`NEUROHUB/tests/test_modos_y_raidionics.py::TestModosExcluyentes` — 7 pruebas,
incluida la que exige que `modo_exclusivo(True, True)` lance excepción.

---

## 3. Retiro de vasculatura y modo aneurisma inerte

### Decisión

La segmentación y separación automática de vasos (venas y arterias) se ha **retirado del pipeline**. Las funciones `generate_vessels_mask()`, `separar_arterias_venas()` y `_umbral_vasos_angiografia()` han sido eliminadas por falta de secuencias angiográficas dedicadas (MRA/CTA) en volúmenes MRI convencionales.

### Impacto en el Modo Aneurisma

El módulo de detección de aneurismas (`improve_aneurysm_detection`) requiere la máscara `vasos.nii.gz` como entrada. Al eliminarse la generación de vasculatura, el modo aneurisma permanece en la aplicación como **modo inerte de respaldo**:
- Si `vasos.nii.gz` no existe en el directorio de salida, la detección de aneurisma se omite de forma limpia con una advertencia en el log.
- Si el usuario importa previamente `vasos.nii.gz` (p. ej. desde 3D Slicer o angiografía externa), la detección de aneurisma se ejecuta normalmente.

---

## 4. Cómo verificar todo

```bash
# Suite de las tres correcciones (incluye la prueba real con Docker)
python -m pytest NEUROHUB/tests/test_modos_y_raidionics.py -v

# Prueba de humo real, aislada
python NEUROHUB/launcher.py raidionics extraer <abs>.nii.gz --salida <salida>
```

Sin Docker, la prueba de humo se omite y las otras 20 siguen ejecutándose.
Estado: **21 pruebas, todas en verde**, incluida la de humo real.

## 5. Límites conocidos

- La separación arteria/vena es una aproximación por intensidad (ver §3).
- `raidionics-rads` no calcula radiomics tipo PyRadiomics; los descriptores
  numéricos siguen viniendo del motor propio.
- Solo está verificado el modelo `MRI_Brain` con secuencia `T1-CE`. Otros modelos
  existen en las releases, pero no se han probado end-to-end; las constantes
  `MODELO_*` del puente están preparadas para cambiarlos.
- En Windows, `docker-credential-desktop.exe` debe estar en el `PATH`; si no, el
  `pull` falla con un error de credenciales que no parece relacionado.



