"""
=====================================================================
 Vista 2D de alta calidad con tumor encerrado en c�rculo
=====================================================================
Genera cortes 2D (axial, coronal y sagital) a m�xima calidad a partir
del volumen del paciente y de la m�scara de tumor segmentada (BRATS o
heur�stica), dibujando el tumor identificado encerrado en un c�rculo.

Consideraciones de alineaci�n:
  - La m�scara de tumor (tumor_brats.nii.gz) se genera con
    CopyInformation(reference_img) sobre el MISMO volumen de entrada,
    por lo que ambas comparten rejilla de v�xeles exacta. Podemos
    superponerlas sin remuestrear.
  - SimpleITK GetArrayFromImage -> shape (z, y, x):
      eje 0 => axial (corte por z)
      eje 1 => coronal (corte por y)
      eje 2 => sagital (corte por x)

Calidad m�xima del render:
  - Ventana/contraste por percentiles robustos (fotograf�a m�dica).
  - Correcci�n de aspecto f�sico usando el spacing del NIfTI.
  - Supersampling (escala > 1) + redimensi�n LANCZOS a la resoluci�n
    final, evitando aliasing y dejando los bordes del c�rculo n�tidos.
  - Gamma aplicada en el espacio lineal para no lavar los grises.
=====================================================================
"""

import os

import numpy as np
import SimpleITK as sitk
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------
# Constantes de estilo
# ---------------------------------------------------------------------
COLOR_TUMOR_FILL = (255, 0, 170, 110)      # magenta transl�cido (relleno)
COLOR_TUMOR_EDGE = (255, 80, 200, 255)     # borde interior
COLOR_CIRCULO = (120, 255, 90)             # verde l�ser (c�rculo externo)
COLOR_MARCA = (255, 255, 120)              # cruz sobre el centroide
COLOR_TEXTO = (255, 255, 255, 235)

# Grosor de la l�nea del c�rculo (en px de la imagen a resoluci�n de salida)
GROSOR_CIRCULO = 5
GROSOR_EDGE = 2


def _font_tamagno(tam):
    """Devuelve una fuente PIL TrueType (Segoe UI) o la fuente por defecto."""
    try:
        from PIL import ImageFont
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeui.ttf")
        if os.path.exists(path):
            return ImageFont.truetype(path, tam)
    except Exception:
        pass
    try:
        from PIL import ImageFont
        return ImageFont.load_default()
    except Exception:
        return None
def _normalizar_slice(slice2d):
    """Normaliza una rebanada a uint8 con ventana por percentiles robustos.

    Usa percentiles P0.5/P99.5 sobre los vóxeles para fijar el contraste
    médico correcto (CT en HU o MRI relativo). Aplica gamma para preservar
    detalle en sombras. Devuelve un array uint8 0-255.
    """
    arr = np.asarray(slice2d, dtype=np.float32)
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)

    # Percentiles más agresivos para mejor contraste (ultradetalle)
    lo, hi = np.percentile(valid, [0.5, 99.5])
    if hi - lo < 1e-6:
        hi = lo + 1e-6

    img = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    # Gamma más suave para preservar tonos intermedios (ultradetalle)
    img = np.power(img, 0.80)
    return (img * 255.0).astype(np.uint8)


def _slice_mas_tumor(mask3d, eje):
    """Devuelve (indice, area) del corte con m�s v�xeles de tumor en el eje dado."""
    otros = tuple(e for e in (0, 1, 2) if e != eje)
    area = (mask3d > 0).sum(axis=otros)
    if area.max() <= 0:
        return mask3d.shape[eje] // 2, 0
    idx = int(np.argmax(area))
    return idx, int(area[idx])


def _aspecto(slice2d, eje, spacing):
    """Calcula la anchura y altura f�sicas del corte (espaciado correcto)."""
    h, w = slice2d.shape
    sz, sy, sx = spacing
    if eje == 0:   # axial   -> ejes x, y
        sp_w, sp_h = sx, sy
    elif eje == 1: # coronal -> ejes x, z
        sp_w, sp_h = sx, sz
    else:          # sagital -> ejes y, z
        sp_w, sp_h = sy, sz
    if sp_h > 3.5 * sp_w:
        sp_h = 3.5 * sp_w
    return w * sp_w, h * sp_h


def _componer_rebanada(slice_uint8, mask2d, eje, spacing, escala=2):
    """Compone la imagen final RGB con el tumor encerrado en un c�rculo.

    - slice_uint8 : rebanada normalizada (h, w) en uint8
    - mask2d      : m�scara de tumor (h, w) boolean
    - eje         : 0 axial, 1 coronal, 2 sagital
    - spacing     : (sz, sy, sx)
    - escala      : supersampling >1 para m�xima nitidez
    """
    # --- Aspecto f�sico y redimensi�n a alta resoluci�n ---
    ancho_fis, alto_fis = _aspecto(slice_uint8, eje, spacing)
    objetivo = 1024  # Mayor resolución para ultradetalle
    if ancho_fis >= alto_fis:
        tw = objetivo
        th = max(1, int(round(objetivo * alto_fis / ancho_fis)))
    else:
        th = objetivo
        tw = max(1, int(round(objetivo * ancho_fis / alto_fis)))

    base = Image.fromarray(slice_uint8, mode="L")
    # Supersampling: trabajamos a escala * resoluci�n para luego bajar con
    # LANCZOS. Esto produce un render m�s n�tido (m�ximo detalle).
    base = base.resize((tw * escala, th * escala), Image.LANCZOS)
    rgb = base.convert("RGB")
    draw = ImageDraw.Draw(rgb, "RGBA")

    if int(mask2d.sum()) > 0:
        fx = rgb.width / mask2d.shape[1]
        fy = rgb.height / mask2d.shape[0]

        # --- Relleno transl�cido del tumor (contorno suavizado) ---
        mask_img = Image.fromarray((mask2d.astype(np.uint8)) * 255, mode="L")
        mask_img = mask_img.resize((rgb.width, rgb.height), Image.LANCZOS)
        mask_rgba = np.array(mask_img)

        arr_rgb = np.asarray(rgb).copy()
        alfa = mask_rgba.astype(np.float32) / 255.0
        for c, color_c in enumerate(COLOR_TUMOR_FILL[:3]):
            arr_rgb[:, :, c] = (
                arr_rgb[:, :, c].astype(np.float32) * (1.0 - alfa * 0.45)
                + color_c * alfa * 0.45
            )
        rgb = Image.fromarray(arr_rgb.astype(np.uint8), "RGB")
        draw = ImageDraw.Draw(rgb, "RGBA")

        # --- Borde interior de la m�scara ---
        from scipy import ndimage
        eroded = ndimage.binary_erosion(mask2d, iterations=2)
        borde = mask2d & ~eroded
        if borde.any():
            ys, xs = np.where(borde)
            draw.point(
                list(zip((xs * fx).astype(int), (ys * fy).astype(int))),
                fill=COLOR_TUMOR_EDGE,
            )

        # --- C�rculo encerrando el tumor completo ---
        ys, xs = np.where(mask2d)
        cx = float(xs.mean()) * fx
        cy = float(ys.mean()) * fy
        rx = (float(xs.max() - xs.min()) * fx) / 2.0 + 18.0 * escala
        ry = (float(ys.max() - ys.min()) * fy) / 2.0 + 18.0 * escala
        # Para que el c�rculo quede circular (no el�ptico) por el aspect de
        # v�xel, ajustamos el radio menor a la escala de p�xel.
        rx = max(rx, ry)
        ry = max(rx, ry)
        bbox = (cx - rx, cy - ry, cx + rx, cy + ry)
        draw.ellipse(bbox, outline=COLOR_CIRCULO, width=GROSOR_CIRCULO * escala)

        # --- Cruz sobre el centroide ---
        r = 12 * escala
        draw.line((cx - r, cy, cx + r, cy), fill=COLOR_MARCA, width=max(2, escala))
        draw.line((cx, cy - r, cx, cy + r), fill=COLOR_MARCA, width=max(2, escala))

    # --- Reducci�n final a resoluci�n de pantalla (LANCZOS) ---
    if escala > 1:
        rgb = rgb.resize((tw, th), Image.LANCZOS)

    # --- Pie de imagen con informaci�n m�dica ---
    draw = ImageDraw.Draw(rgb, "RGBA")
    nombre = {0: "Axial", 1: "Coronal", 2: "Sagital"}.get(eje, "Corte")
    texto = f"{nombre}  |  Tumor"
    font = _font_tamagno(22)
    tw_txt = 0
    if font is not None:
        box = draw.textbbox((0, 0), texto, font=font)
        tw_txt = box[2] - box[0]
    draw.rectangle((0, rgb.height - 44, rgb.width, rgb.height), fill=(0, 0, 0, 150))
    if font is not None:
        draw.text(((rgb.width - tw_txt) // 2, rgb.height - 36),
                  texto, font=font, fill=COLOR_TEXTO)

    return rgb
def generar_vistas_2d(volumen_path, mascara_path, dir_salida,
                      escala=3, solo_ejes=None):
    """Genera los tres cortes 2D (axial, coronal, sagital) con el tumor
    encerrado en un c�rculo y los guarda como PNG.

    Args:
        volumen_path : NIfTI del volumen del paciente (misma rejilla que la m�scara).
        mascara_path : NIfTI de la m�scara de tumor (alineada con volumen_path).
        dir_salida   : directorio donde se guardan los PNG (se crea si falta).
        escala       : supersampling (2 = doble resoluci�n interna).
        solo_ejes    : lista opcional de ejes {0,1,2} para generar s�lo algunos.

    Returns:
        dict: {clave_orientacion: ruta_png} con las im�genes generadas.
        clave: "axial", "coronal", "sagital".
    """
    os.makedirs(dir_salida, exist_ok=True)

    if not os.path.exists(volumen_path):
        raise FileNotFoundError(f"Volumen no encontrado: {volumen_path}")
    if not os.path.exists(mascara_path):
        raise FileNotFoundError(f"M�scara de tumor no encontrada: {mascara_path}")

    vol_img = sitk.ReadImage(volumen_path)
    mask_img = sitk.ReadImage(mascara_path)

    vol_arr = sitk.GetArrayFromImage(vol_img).astype(np.float32)
    mask_arr = (sitk.GetArrayFromImage(mask_img) > 0).astype(np.uint8)

    if vol_arr.shape != mask_arr.shape:
        raise ValueError(
            f"Volumen {vol_arr.shape} y m�scara {mask_arr.shape} no comparten rejilla. "
            "Re-ejecute el pipeline para regenerar ambas."
        )

    sp = vol_img.GetSpacing()
    # SimpleITK devuelve spacing (x, y, z); para el array numpy (z, y, x)
    # usamos (sp[2], sp[1], sp[0]) -> (sz, sy, sx).
    spacing = (sp[2], sp[1], sp[0])

    if solo_ejes is None:
        solo_ejes = (0, 1, 2)

    nombres = {0: "axial", 1: "coronal", 2: "sagital"}
    salidas = {}
    for eje in solo_ejes:
        idx, _area = _slice_mas_tumor(mask_arr, eje)
        slice_vol = np.take(vol_arr, idx, axis=eje)
        slice_mask = np.take(mask_arr, idx, axis=eje) > 0
        norm = _normalizar_slice(slice_vol)
        img = _componer_rebanada(norm, slice_mask, eje, spacing, escala=escala)
        ruta = os.path.join(dir_salida, f"corte_{nombres[eje]}.png")
        img.save(ruta, format="PNG", optimize=True)
        salidas[nombres[eje]] = ruta

    return salidas


if __name__ == "__main__":
    import sys
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    salidas = os.path.join(os.path.dirname(base), "salidas", "segmentaciones_ai")
    vol = os.path.join(salidas, "volumen_paciente.nii.gz")
    masc = os.path.join(salidas, "tumor_brats.nii.gz")
    if not os.path.exists(vol):
        print(f"Volumen no disponible en {vol}; busque data/nifti o DICOM.")
        sys.exit(1)
    res = generar_vistas_2d(vol, masc, os.path.join(salidas, "vista_2d"))
    print("Generadas:", res)