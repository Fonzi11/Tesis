"""
Volumen 2D interactivo: windowing, overlay y delineado manual.

Este modulo es la BASE del visor 2D y NO depende de Qt, para que se pueda
probar de forma aislada (`tests/test_volumen_2d.py`) y para que la misma
logica sirva tanto a la pantalla como a la exportacion de PNG.

Que resuelve
------------
1. Contraste. La version anterior normalizaba CADA corte por separado con los
   percentiles 0.5/99.5 de ese corte. En un volumen de RM el fondo (aire) es
   cero y ocupa la mayor parte de la imagen, asi que el percentil alto caia
   sobre el ruido del fondo y el parenquima salia aplastado en una franja
   gris. Aqui la ventana se calcula una sola vez sobre el VOLUMEN COMPLETO y,
   cuando el fondo domina, se excluye del calculo: la ventana la fijan los
   percentiles del TEJIDO, no los del aire.

2. Realce local. Un windowing global da contraste, pero las estructuras finas
   (cortex, edema) siguen apagadas. Se anade CLAHE por corte
   (`skimage.exposure.equalize_adapthist`), que redistribuye el rango sin
   mover los niveles globales, mas un realce de borde (unsharp) suave.

3. Overlay. El tumor se dibuja con relleno verde translucido y borde opaco,
   mezclado sobre la imagen ("alpha blending"), de modo que el tejido se ve a
   traves del relleno. El verde es el color de convencion para anotacion
   manual y no colisiona con el gris del tejido, que es lo unico que hay que
   leer en una RM.

4. Delineado manual. `pintar` / `borrar` escriben sobre la mascara 3D en la
   MISMA rejilla que el volumen, con deshacer por corte, y `guardar_mascara`
   la escribe como NIfTI con `CopyInformation` del volumen: lo que se delinea
   en pantalla es exactamente lo que despues se convierte en malla 3D.
"""

import os

import numpy as np
from scipy import ndimage

# Eje del array numpy (z, y, x) que se corta en cada orientacion clinica.
EJES = {
    "axial": 0,     # corte por z (el habitual)
    "coronal": 1,   # corte por y
    "sagital": 2,   # corte por x
}

NOMBRES_EJE = {0: "Axial", 1: "Coronal", 2: "Sagital"}

# Overlay del tumor: verde clinico. RGB float 0..255.
COLOR_TUMOR_RGB = (0, 230, 110)
ALPHA_RELLENO = 0.35     # se mezcla con el tejido; el borde va a 1.0
GROSOR_BORDE = 1         # erosion para el borde, en vóxeles
HISTORIAL_MAX = 64       # pasos de deshacer
# Cortes cacheados de la capa base (imagen de gris, sin tumor). Con 1024 px
# cada una ocupa ~3 MB, asi que el tope es bajo a proposito: sirve para que al
# pintar no se repita el render del corte visible, no para prefetch.
CACHE_BASE_MAX = 6


def eje_indice(eje):
    """Normaliza 'axial'/'coronal'/'sagital' o 0/1/2 al indice del array."""
    if isinstance(eje, str):
        clave = eje.strip().lower()
        if clave not in EJES:
            raise ValueError(f"Eje desconocido: {eje!r}. Use {sorted(EJES)}")
        return EJES[clave]
    e = int(eje)
    if e not in (0, 1, 2):
        raise ValueError(f"Eje fuera de rango: {eje!r}. Use 0, 1 o 2.")
    return e


class Volumen2D:
    """Volumen + mascara alineados, con windowing y delineado manual.

    Atributos:
        volumen            float32 (z, y, x)
        mascara            uint8  (z, y, x), 1 = tumor
        spacing            (sx, sy, sz) en mm, tal cual reporta SimpleITK
        volumen_path       ruta del NIfTI de origen
        mascara_path       ruta de la mascara actual (si esta en disco)
        mascara_modificada True si el delineado tiene cambios sin guardar
    """

    def __init__(self, volumen_path=None, mascara_path=None, volumen=None,
                 mascara=None, spacing=(1.0, 1.0, 1.0)):
        self.volumen_path = None
        self.mascara_path = None
        self.volumen = None
        self.mascara = None
        self.spacing = tuple(float(v) for v in spacing[:3])
        self.mascara_modificada = False
        self._imagen_ref = None        # imagen SimpleITK del volumen
        self._lo, self._hi = 0.0, 1.0
        self._historial = []           # [(sectores, antes, despues)] LIFO
        # Cache de la imagen de gris por corte: ver `_render_base`. Se vacia
        # sola al superar CACHE_BASE_MAX, y de forma explicita cuando cambia
        # el volumen o la ventana.
        self._cache_base = {}

        if volumen is not None:
            self.volumen = np.asarray(volumen, dtype=np.float32)
            if mascara is not None:
                self.mascara = (np.asarray(mascara) > 0).astype(np.uint8)
        elif volumen_path and os.path.exists(volumen_path):
            self.cargar(volumen_path, mascara_path)

        if self.volumen is not None:
            if self.mascara is None:
                self.mascara = np.zeros(self.volumen.shape, dtype=np.uint8)
            if self.mascara.shape != self.volumen.shape:
                raise ValueError(
                    f"Volumen {self.volumen.shape} y mascara "
                    f"{self.mascara.shape} no comparten rejilla.")
            self.calcular_window()

    # ------------------------------------------------------------------
    @property
    def vacio(self):
        """True si no hay volumen cargado."""
        return self.volumen is None

    @property
    def forma(self):
        """(z, y, x) del volumen, o None si esta vacio."""
        return None if self.volumen is None else self.volumen.shape

    # ==================================================================
    # CARGA
    # ==================================================================
    def cargar(self, volumen_path, mascara_path=None):
        """Lee el volumen (y la mascara opcional) de disco."""
        import SimpleITK as sitk

        self.volumen_path = volumen_path
        img = sitk.ReadImage(volumen_path)
        self.volumen = sitk.GetArrayFromImage(img).astype(np.float32)
        self.spacing = tuple(float(v) for v in img.GetSpacing())
        self._imagen_ref = img

        self.mascara = np.zeros(self.volumen.shape, dtype=np.uint8)
        self.mascara_path = None
        self.mascara_modificada = False
        self._historial.clear()
        self.invalidar_cache()

        if mascara_path and os.path.exists(mascara_path):
            self.cargar_mascara(mascara_path)
        self.calcular_window()
        return self

    def cargar_mascara(self, mascara_path):
        """Carga una mascara NIfTI exigiendo que comparta la rejilla del volumen.

        No se re-muestrea a proposito: si la mascara no cuadra, superponerla
        daria un tumor desplazado, que en una presentacion clinica es peor que
        no dibujar tumor. Se falla de forma visible en lugar de adivinar.
        """
        import SimpleITK as sitk

        img = sitk.ReadImage(mascara_path)
        arr = (sitk.GetArrayFromImage(img) > 0).astype(np.uint8)
        if arr.shape != self.volumen.shape:
            raise ValueError(
                f"La mascara {os.path.basename(mascara_path)} tiene {arr.shape} "
                f"y el volumen {self.volumen.shape}. Deben compartir rejilla: "
                "reejecute el pipeline o alinee la mascara antes.")
        self.mascara = arr
        self.mascara_path = mascara_path
        self.mascara_modificada = False
        self._historial.clear()
        return self
# ==================================================================
    # WINDOWING Y REALCE
    # ==================================================================
    def calcular_window(self, percentiles=(0.5, 99.5), solo_tejido=True):
        """Fija la ventana global (lo, hi) a partir del VOLUMEN completo.

        `solo_tejido` descarta los voxels a cero cuando el fondo ocupa una
        parte sustancial del volumen. En RM el aire es 0 y es la mayoria de
        los voxels: si contara, el percentil 99.5 caeria sobre el ruido del
        fondo y todo el tejido apareceria en el tercio oscuro de la escala
        (que es exactamente lo que pasaba antes).

        Se calcula una vez y no por corte: con ventana por corte, dos cortes
        consecutivos del mismo paciente salen con distinta luminosidad y el
        tumor "cambia de aspecto" al avanzar de rebanada.
        """
        if self.volumen is None:
            self._lo, self._hi = 0.0, 1.0
            return self._lo, self._hi

        validos = self.volumen[np.isfinite(self.volumen)]
        if validos.size == 0:
            self._lo, self._hi = 0.0, 1.0
            return self._lo, self._hi

        if solo_tejido:
            no_cero = validos[np.abs(validos) > 1e-6]
            if no_cero.size >= 0.3 * validos.size and no_cero.size > 256:
                validos = no_cero

        lo, hi = np.percentile(validos, percentiles)
        if hi - lo < 1e-6:
            hi = lo + 1e-6
        self._lo, self._hi = float(lo), float(hi)
        # La ventana cambia el aspecto de todas las imagenes: la cache de la
        # capa base guarda pixeles YA normalizados, que quedarian obsoletos.
        self.invalidar_cache()
        return self._lo, self._hi

    def ventana(self):
        """(lo, hi) de la ventana actual, en unidades del volumen."""
        return self._lo, self._hi

    def _normalizar(self, arr):
        """Aplica la ventana global. Devuelve float 0..1."""
        x = (np.asarray(arr, dtype=np.float32) - self._lo) / (self._hi - self._lo)
        return np.clip(x, 0.0, 1.0)

    @staticmethod
    def _clahe(gris, kernel=48, clip=0.012):
        """CLAHE por corte; si skimage no esta, devuelve la imagen tal cual."""
        try:
            from skimage import exposure
            k = max(8, int(kernel) | 1)          # skimage exige kernel impar
            return exposure.equalize_adapthist(
                np.clip(gris, 0.0, 1.0), kernel_size=k, clip_limit=float(clip))
        except Exception:
            return gris

    @staticmethod
    def _realzar_bordes(gris, sigma=0.8, peso=0.35):
        """Unsharp mask: suma la version desenfocada para remarcar el relieve."""
        if peso <= 0:
            return gris
        suave = ndimage.gaussian_filter(gris, sigma=max(0.3, float(sigma)))
        return np.clip(gris + peso * (gris - suave), 0.0, 1.0)

    # ------------------------------------------------------------------
    def corte_volumen(self, eje, indice):
        """Rebanada del volumen en el eje indicado."""
        e = eje_indice(eje)
        return np.take(self.volumen, self._acotar(e, indice), axis=e)

    def corte_mascara(self, eje, indice):
        """Rebanada booleana de la mascara en el mismo eje."""
        e = eje_indice(eje)
        return np.take(self.mascara, self._acotar(e, indice), axis=e) > 0

    def _acotar(self, e, indice):
        return max(0, min(int(indice), self.volumen.shape[e] - 1))

    def n_cortes(self, eje):
        """Numero de cortes disponibles en ese eje."""
        return int(self.volumen.shape[eje_indice(eje)])

    def indice_mas_tumor(self, eje):
        """Indice del corte con mas tumor en ese eje (el central si no hay)."""
        e = eje_indice(eje)
        otros = tuple(i for i in (0, 1, 2) if i != e)
        area = self.mascara.sum(axis=otros)
        if area.max() <= 0:
            return int(self.volumen.shape[e] // 2)
        return int(np.argmax(area))

    def _aspecto_mm(self, e):
        """(ancho_mm, alto_mm) del corte para el eje del array `e`."""
        sx, sy, sz = self.spacing[:3]
        if e == 0:        # axial: ancho = x, alto = y
            return sx, sy
        if e == 1:        # coronal: ancho = x, alto = z
            return sx, sz
        return sy, sz    # sagital: ancho = y, alto = z

    # ==================================================================
    # RENDER DE UN CORTE
    # ==================================================================
    def render_corte(self, eje, indice, alto=512, clahe=True, unsharp=True,
                     gamma=0.85, overlay=True, grosor_borde=GROSOR_BORDE):
        """Devuelve `(rgb_uint8, info)` del corte con el tumor encima.

        El resultado ya tiene el aspecto fisico corregido por el espaciado y
        la resolucion `alto`: estirar un voxel anisotropico a un cuadrado
        falsearia la forma de la lesion.

        info trae 'eje', 'indice', 'n_cortes' y 'area_tumor_px', que es lo que
        la barra de estado muestra mientras se navega.
        """
        e = eje_indice(eje)
        mask = self.corte_mascara(e, indice) if overlay else None
        rgb = self._render_base(e, indice, alto, clahe, unsharp, gamma)
        if mask is not None and mask.any():
            # `rgb` viene de la cache con forma (h, w, 3) y `_reescalar` pide
            # (w, h): hay que desempaquetar en ese orden, no pasar el shape.
            alto_px, ancho_px = rgb.shape[:2]
            mask = self._reescalar(mask.astype(np.uint8), ancho_px, alto_px,
                                   orden=0) > 0
            rgb = self._superponer(rgb, mask, grosor_borde)

        info = {
            "eje": eje if isinstance(eje, str) else NOMBRES_EJE[e].lower(),
            "indice": int(self._acotar(e, indice)),
            "n_cortes": int(self.volumen.shape[e]),
            "area_tumor_px": int(mask.sum()) if mask is not None else 0,
        }
        return rgb.clip(0, 255).astype(np.uint8), info

    def _render_base(self, e, indice, alto, clahe, unsharp, gamma):
        """Render SIN tumor, cacheado por corte.

        Es la parte cara: normalizar, CLAHE, realce y re-muestreo son ~50 ms en
        un corte de 1024 px. Al pintar, la imagen de gris del corte NO cambia:
        solo la mascara. Sin esta cache, cada movimiento del raton repetiria
        esos 50 ms y el delineado seiria a 10 fps; con ella solo se rehace el
        overlay, que es ~8 ms, y el trazo va a ritmo de pantalla.

        La clave incluye la ventana y los parametros de realce, porque
        cambiarlos debe invalidar la cache y no servir la imagen anterior.
        """
        clave = (e, self._acotar(e, indice), int(alto), bool(clahe),
                 bool(unsharp), round(float(gamma), 3), self._lo, self._hi)
        cached = self._cache_base.get(clave)
        if cached is not None:
            return cached

        plano = self.corte_volumen(e, indice)
        gris = self._normalizar(plano)
        if clahe:
            gris = self._clahe(gris)
        if unsharp:
            gris = self._realzar_bordes(gris)
        gris = np.power(np.clip(gris, 0.0, 1.0), gamma)
        w, h = self._tamano_objetivo(e, alto)
        rgb = np.dstack([self._reescalar(gris, w, h, orden=1) * 255.0] * 3)

        self._cache_base[clave] = rgb
        # Solo unos pocos cortes: al pintar, la cache se vacia sola hacia el
        # corte siguiente sin llegar a unos miles de imagenes de 3 MB.
        if len(self._cache_base) > CACHE_BASE_MAX:
            self._cache_base.clear()
        return rgb

    def invalidar_cache(self):
        """Vacia la cache de la capa base (tras cambiar volumen o ventana)."""
        self._cache_base.clear()

    def _tamano_objetivo(self, e, alto):
        """(ancho, alto) en pixeles respetando el aspecto fisico del corte."""
        ancho_mm, alto_mm = self._aspecto_mm(e)
        alto = max(1, int(alto))
        if ancho_mm >= alto_mm:
            return alto, max(1, int(round(alto * alto_mm / ancho_mm)))
        return max(1, int(round(alto * ancho_mm / alto_mm))), alto

    @staticmethod
    def _reescalar(gris, w, h, orden=1):
        """Re-muestreo bilineal (o del vecino mas cercano) al tamano pedido."""
        h0, w0 = gris.shape
        if (h0, w0) == (h, w):
            return gris
        return ndimage.zoom(gris.astype(np.float32),
                            (h / h0, w / w0), order=orden,
                            mode="nearest")

    def escala_voxeles(self, eje, alto=1024):
        """(kX, kY) pixeles de render por voxel, uno por direccion del corte.

        Son DISTINTOS en coronal y sagital, y por eso no basta un unico numero:
        el array es (z, y, x) con z de 112 vóxeles y 1024 px de alto, mientras
        que x son 256 vóxeles en 686 px de ancho. K vale 9.14 en vertical y
        2.68 en horizontal, un factor 3.4 entre ambos ejes.

        Devolver un unicofactor (el menor, como haria un `min`) es lo que
        desplazaba el pincel en coronal y sagital: la coordenada vertical se
        dividia por 2.68 en vez de por 9.14, el trazo caia 3.4 veces mas abajo
        de donde se veia y a veces fuera del volumen, donde ya no pintaba nada.
        """
        e = eje_indice(eje)
        otros = [i for i in (0, 1, 2) if i != e]
        ancho_px, alto_px = self._tamano_objetivo(e, alto)
        return (ancho_px / max(1, self.volumen.shape[otros[1]]),
                alto_px / max(1, self.volumen.shape[otros[0]]))

    def px_por_voxel(self, eje, alto=1024):
        """Pixeles de render por voxel, para el eje indicado.

        Es el MENOR de los dos factores, y se conserva porque sirve para el
        circulo del cursor (un radio unico, conservador). Para traducir
        coordenadas hay que usar `escala_voxeles`, que separa los dos ejes.

        Se calcula sobre el render que realmente se produce (`_tamano_objetivo`
        respeta el aspecto fisico), asi que no puede desviarse de la imagen
        que el usuario ve.
        """
        kx, ky = self.escala_voxeles(eje, alto)
        return min(kx, ky)

    def factor_zoom(self, eje, alto=1024):
        """Alias de `px_por_voxel` con nombre explicito para el cursor."""
        return self.px_por_voxel(eje, alto)

    def _superponer(self, rgb, mask, grosor_borde=GROSOR_BORDE):
        """Mezcla el overlay: relleno translucido dentro, borde opaco.

        El alfa es 0 FUERA de la mascara. Esto parece obvio pero es el error
        que hacia aparecer la imagen entera verde: con alfa constante en toda
        la imagen, el fondo (negro) se teñia de verde y la RM dejaba de leerse
        como imagen de gris, que es lo unico que hay que mirar.

        OJO con el rendimiento: esto se llama en CADA movimiento del raton, y
        mezclar los tres canales de toda la imagen en float costs ~46 ms, que
        es la mitad del tiempo de fotograma. Solo se tocan los pixeles que
        están dentro de la mascara, que en un corte con tumor son unos miles.
        """
        if not mask.any():
            return rgb
        # COPIA OBLIGATORIA: `rgb` puede venir de la cache de `_render_base`, y
        # pintar el tumor encima de la imagen en cache la contaminaria de forma
        # permanente (la segunda vez el tumor saldria doble de intenso y no se
        # podria borrar). Se copia solo la imagen, que es una sola operacion
        # de memoria, no un bucle por pixel.
        rgb = np.array(rgb, dtype=np.float32, copy=True)
        color = np.asarray(COLOR_TUMOR_RGB, dtype=np.float32)
        # El borde se calcula ya a resolucion de render (no en vóxeles): es
        # donde el usuario ve el contorno, y asi el trazo del pincel se ve con
        # un grosor constante sea cual sea el eje.
        if grosor_borde > 0:
            borde = mask & ~ndimage.binary_erosion(
                mask, iterations=int(grosor_borde))
        else:
            borde = np.zeros_like(mask)
        alfa = np.where(borde, 1.0, np.where(mask, ALPHA_RELLENO, 0.0))

        # indexed_assign solo sobre `dentro`: fuera de la tumoracion el pixel
        # se deja intacto. `rgb` es float64 porque `np.power` devuelve float64
        # y el dstack con 255.0 lo arrastra.
        dentro = alfa > 0.0
        idx = np.flatnonzero(dentro.ravel())
        if idx.size == 0:
            return rgb
        canales = rgb.reshape(-1, rgb.shape[-1])
        a = alfa.ravel()[idx].astype(np.float32)[:, None]
        canales[idx] = canales[idx] * (1.0 - a) + color * a
        return rgb

    @staticmethod
    def _reescalar_rgb(rgb, w, h):
        """Re-escala una imagen RGB uint8 (h, w, 3) al tamano pedido.

        OJO: se re-escala cada canal por separado y NO se vuelve a multiplicar
        por 255. Reutilizar `_reescalar` (que espera 0..1) sobre un array ya
        escalado saturaba la imagen a blanco: es exactamente lo que salia al
        anadir el pie de texto.
        """
        h0, w0 = rgb.shape[:2]
        if (h0, w0) == (h, w):
            return rgb
        canales = [ndimage.zoom(rgb[:, :, c].astype(np.float32),
                                (h / h0, w / w0), order=1, mode="nearest")
                   for c in range(3)]
        return np.clip(np.dstack(canales), 0, 255).astype(np.uint8)

    def render_texto(self, rgb, texto, alto_total=None, alto_banda_frac=0.09):
        """Anade una banda de texto al pie sin tocar el contenido de la imagen.

        - `rgb` es una COPIA de los pixeles: el delineado se mide sobre lo que
          se ve, asi que la banda nunca se superpone a la imagen.
        - Si se pasa `alto_total`, la imagen se encoge lo justo para que
          imagen + banda midan exactamente ese alto. Asi el PNG exportado
          respeta el lienzo pedido (1024 px) en vez de crecer con el pie.
        """
        from PIL import Image, ImageDraw

        h, w = rgb.shape[:2]
        banda = max(16, int(h * alto_banda_frac))
        if alto_total is not None and int(alto_total) > banda:
            destino_h = int(alto_total) - banda
            if destino_h != h:
                w = max(1, int(round(w * destino_h / h)))
                rgb = self._reescalar_rgb(rgb, w, destino_h)
                h = destino_h

        img = Image.fromarray(rgb, mode="RGB")
        lienzo = Image.new("RGB", (w, h + banda), (0, 0, 0))
        lienzo.paste(img, (0, 0))
        draw = ImageDraw.Draw(lienzo)
        fuente = self._fuente(max(11, banda // 2))
        if fuente is not None:
            draw.text((8, h + max(1, banda // 4)), texto, font=fuente,
                      fill=(235, 235, 235))
        return np.asarray(lienzo, dtype=np.uint8)

    @staticmethod
    def _fuente(tam):
        """Fuente TrueType del sistema, o None si no se encuentra."""
        try:
            from PIL import ImageFont
            ruta = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                "Fonts", "segoeui.ttf")
            if os.path.exists(ruta):
                return ImageFont.truetype(ruta, int(tam))
            return ImageFont.load_default()
        except Exception:
            return None

    # ==================================================================
    # DELINEADO MANUAL
    # ==================================================================
    def pintar(self, eje, indice, x, y, radio=3, valor=1):
        """Pinta (valor=1) o borra (valor=0) un disco en el corte indicado.

        `x` e `y` son indices de VOXEL del corte, no de pantalla: el mapeo los
        hace el widget, que es quien conoce la escala del zoom. Fuera del
        volumen no se pinta nada, de modo que arrastrar el raton por el borde
        no deja manchas en ningun corte.

        Devuelve cuantos voxels han cambiado de estado.
        """
        antes = self.corte_mascara(eje, indice).copy()
        self.pintar_en_mascara(eje, indice, x, y, radio, valor)
        despues = self.corte_mascara(eje, indice)
        if np.array_equal(antes, despues):
            return 0
        self.mascara_modificada = True
        self._historial.append(
            (self._sectores(eje, indice), antes, despues.copy()))
        del self._historial[:-HISTORIAL_MAX]
        return int((despues & ~antes).sum() if valor
                   else (antes & ~despues).sum())

    def pintar_en_mascara(self, eje, indice, x, y, radio, valor):
        """Escribe un disco en la mascara, in-place, sin historial."""
        e = eje_indice(eje)
        otros = [i for i in (0, 1, 2) if i != e]
        alto, ancho = self.mascara.shape[otros[0]], self.mascara.shape[otros[1]]
        radio = max(1, int(radio))
        y0, y1 = max(0, int(y) - radio), min(alto, int(y) + radio + 1)
        x0, x1 = max(0, int(x) - radio), min(ancho, int(x) + radio + 1)
        if y0 >= y1 or x0 >= x1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disco = ((yy - int(y)) ** 2 + (xx - int(x)) ** 2) <= radio ** 2
        sectores = [slice(None)] * 3
        sectores[e] = self._acotar(e, indice)
        sectores[otros[0]] = slice(y0, y1)
        sectores[otros[1]] = slice(x0, x1)
        self.mascara[tuple(sectores)][disco] = int(valor)

    def pintar_tramo(self, eje, indice, x0, y0, x1, y1, radio=3, valor=1):
        """Pinta un SEGMENTO de (x0,y0) a (x1,y1), rellenando el hueco.

        Sin esto, un movimiento rapido del raton genera eventos `mouseMove`
        tan separados que entre dos muestras el pincel deja un hueco en la
        mascara: el delineateado sale punteado. Se recorre el segmento con
        pasos de ~medio voxel, que es la resolucion a la que realmente se
        resuelve el disco.

        Devuelve el numero de voxels que han cambiado de estado.
        """
        x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
        largo = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if largo < 1e-6:
            return self.pintar(eje, indice, x0, y0, radio, valor)
        pasos = max(1, int(largo / 0.5) + 1)
        total = 0
        for i in range(pasos + 1):
            t = i / pasos
            total += self.pintar(eje, indice, x0 + (x1 - x0) * t,
                                 y0 + (y1 - y0) * t, radio, valor)
        return total

    def pintar_tramo_2d(self, eje, indice, p0, p1, kx=None, ky=None,
                        radio=3, valor=1):
        """Pinta un SEGMENTO de (x0,y0) a (x1,y1) rellenando el hueco.

        Tres decisiones, todas visibles al delinear a mano:

        - Sin interpolacion, un movimiento rapido del raton genera eventos
          `mouseMove` tan separados que entre dos muestras el pincel deja un
          hueco: el delineateado sale punteado. Se recorre el segmento en
          pasos de ~medio voxel, la resolucion a la que se resuelve el brush.
        - El pincel es un CIRCULO en vóxeles, no en pixeles. El corte se
          renderiza con aspecto fisico corregido, asi que en coronal un voxel
          vertical ocupa 9.14 px y uno horizontal 2.68 px: un circulo de
          3 vóxeles se ve aplastado en pantalla, y el cursor lo dibuja como
          la elipse que realmente es. La mascara, en cambio, se mantiene
          isotropa a proposito.
        - No se deforma el disco para compensar `kx/ky`. Hacerlo deja el
          pincel en 1 solo voxel de alto (medido: 221 vóxeles para una linea
          de 200 en coronal), un pelo que no sirve ni para cerrar el
          contorno ni para que el STL salga con pared. El radio se mide en
          vóxeles, que es la unidad en la que se guarda y se volumetriza.

        `kx`, `ky` se aceptan por compatibilidad con la firma anterior, pero
        ya NO deforman el pincel: ver la nota de isotropia de arriba. Devuelve
        los voxels que han cambiado.
        """
        antes = self.corte_mascara(eje, indice).copy()
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
        largo = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        pasos = 1 if largo < 1e-6 else max(1, int(largo / 0.5))

        for i in range(pasos + 1):
            t = i / pasos if pasos else 0.0
            self._pincel_elipse(eje, indice, x0 + (x1 - x0) * t,
                                y0 + (y1 - y0) * t, radio, radio, valor)
        despues = self.corte_mascara(eje, indice)
        if np.array_equal(antes, despues):
            return 0
        self.mascara_modificada = True
        # Un solo paso de deshacer por trazo completo, no uno por muestra del
        # raton: deshuchar evento a evento haria falta pulsar Ctrl+Z cientos de
        # veces para corregir un solo contorno.
        self._historial.append(
            (self._sectores(eje, indice), antes, despues.copy()))
        del self._historial[:-HISTORIAL_MAX]
        return int((despues & ~antes).sum() if valor
                   else (antes & ~despues).sum())

    def _pincel_elipse(self, eje, indice, x, y, rx, ry, valor):
        """Escribe una elipse en la mascara, in-place, sin historial."""
        e = eje_indice(eje)
        otros = [i for i in (0, 1, 2) if i != e]
        alto, ancho = self.mascara.shape[otros[0]], self.mascara.shape[otros[1]]
        rx, ry = float(rx), float(ry)
        y0, y1 = max(0, int(y - ry)), min(alto, int(y + ry) + 1)
        x0, x1 = max(0, int(x - rx)), min(ancho, int(x + rx) + 1)
        if y0 >= y1 or x0 >= x1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        elipse = (((yy - y) / ry) ** 2 + ((xx - x) / rx) ** 2) <= 1.0
        sectores = [slice(None)] * 3
        sectores[e] = self._acotar(e, indice)
        sectores[otros[0]] = slice(y0, y1)
        sectores[otros[1]] = slice(x0, x1)
        self.mascara[tuple(sectores)][elipse] = int(valor)

    def _sectores(self, eje, indice):
        """Sectores que seleccionan el corte completo dentro del array 3D."""
        e = eje_indice(eje)
        otros = [i for i in (0, 1, 2) if i != e]
        sectores = [slice(None)] * 3
        sectores[e] = self._acotar(e, indice)
        sectores[otros[0]] = slice(0, self.mascara.shape[otros[0]])
        sectores[otros[1]] = slice(0, self.mascara.shape[otros[1]])
        return tuple(sectores)

    # ------------------------------------------------------------------
    def deshacer(self):
        """Revierte la ultima accion de delineado. True si habia algo que deshacer."""
        if not self._historial:
            return False
        sectores, antes, _despues = self._historial.pop()
        self.mascara[sectores] = antes.astype(np.uint8)
        self.mascara_modificada = True
        return True

    def limpiar_mascara(self):
        """Vacia la mascara dejando UN paso de deshacer con el estado previo."""
        if not self.mascara.any():
            return False
        estado = self.mascara.copy()
        self.mascara[:] = 0
        # Un solo sector que abarque todo: deshacer restaura la mascara entera
        # sin depender de que corte se estaba editando.
        self._historial = [(tuple(slice(None) for _ in range(3)),
                            estado, np.zeros_like(estado))]
        self.mascara_modificada = True
        return True

    # ------------------------------------------------------------------
    def vóxeles_tumor(self):
        """Numero de voxels marcados como tumor."""
        return int((self.mascara > 0).sum())

    def volumen_mm3_tumor(self):
        """Volumen del tumor en mm3, con el espaciado real del volumen."""
        return float(self.vóxeles_tumor() * np.prod(self.spacing[:3]))

    def volumen_cm3_tumor(self):
        return self.volumen_mm3_tumor() / 1000.0

    # ==================================================================
    # PERSISTENCIA
    # ==================================================================
    def guardar_mascara(self, ruta, formato="NIfTI"):
        """Guarda la mascara. Devuelve la ruta, o None si `ruta` es vacia.

        NIfTI es el formato que leen `segmentacion_completa` y `calidad_mallas`.
        Se escribe con `CopyInformation` del volumen, de modo que la malla 3D
        que se genere salga en la MISMA rejilla que se delineo en pantalla: si
        aqui se perdiera la alineacion, el 3D y el 2D mostrarian el tumor en
        sitios distintos, que es el fallo mas grave de esta pantalla.
        """
        if not ruta:
            return None
        formato = (formato or "NIfTI").upper()

        if formato == "NIFTI":
            import SimpleITK as sitk
            img = sitk.GetImageFromArray(self.mascara.astype(np.uint8))
            if self._imagen_ref is not None:
                img.CopyInformation(self._imagen_ref)
            else:
                # Sin imagen de referencia se invierte el spacing, porque el
                # array es (z, y, x) y SimpleITK lo describe como (x, y, z).
                img.SetSpacing(tuple(float(s) for s in self.spacing[::-1]))
            directorio = os.path.dirname(os.path.abspath(ruta))
            if directorio:
                os.makedirs(directorio, exist_ok=True)
            sitk.WriteImage(img, ruta)
            self.mascara_path = ruta
            self.mascara_modificada = False
            self._historial.clear()
            return ruta

        if formato == "PNG":
            # Mapa de bits por corte axial. NO es entrada del pipeline: sirve
            # para revisar el delineado a ojo o compartirlo como imagen.
            from PIL import Image
            os.makedirs(ruta, exist_ok=True)
            for i in range(self.mascara.shape[0]):
                Image.fromarray((self.mascara[i] * 255).astype(np.uint8),
                                mode="L").save(
                    os.path.join(ruta, f"mascara_{i:04d}.png"))
            return ruta

        raise ValueError(f"Formato de mascara no soportado: {formato}")