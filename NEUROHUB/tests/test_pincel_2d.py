"""
Pruebas del delineado manual 2D: mapeo de coordenadas y fluidez del trazo.

Regresan sobre dos fallos reales que no se ven leyendo el codigo:

1. El factor de pixeles por voxel NO es el mismo en horizontal y en vertical
   en coronal y sagital (el corte se renderiza con aspecto fisico corregido).
   Con un unico factor, el pincel se descentraba: en un caso real marcaba el
   voxel 191 de un corte de 112 filas, es decir, fuera del volumen, y no
   pintaba nada.
2. Al pintar, la imagen de gris del corte no cambia. Si se vuelve a renderizar
   entera en cada movimiento del raton, el trazo va a ~16 fps; con la cache de
   la capa base, a ~50.
"""
import os
import sys
import time

import numpy as np
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src import volumen_2d as v2d          # noqa: E402


def _volumen():
    """Volumen anisotropo: 30x40x50 con z a 2 mm.

    Es el caso que reproduce el descentrado: z son 30 vóxeles contra 50 de x,
    asi que los dos factores de px/voxel tienen que salir distintos.
    """
    vol = np.zeros((30, 40, 50), dtype=np.float32)
    vol[5:25, 5:35, 5:45] = 100.0
    v = v2d.Volumen2D(volumen=vol, spacing=(1.0, 1.0, 2.0))
    v.calcular_window()
    return v


@pytest.fixture
def anisotropo():
    return _volumen()


class TestEscalaPorEje:
    def test_coronal_y_sagital_tienen_factores_distintos(self, anisotropo):
        """Si kX == kY el mapeo es correcto por casualidad, no por diseno."""
        for eje in ("coronal", "sagital"):
            kx, ky = anisotropo.escala_voxeles(eje, alto=512)
            assert kx != ky, (
                f"{eje}: se esperaba un factor distinto por eje (kX={kx}, "
                f"kY={ky}); si son iguales, el test no cubre el bug")

    def test_los_factores_coinciden_con_el_render_real(self, anisotropo):
        """Cada factor debe reconstruir el numero de vóxeles del corte."""
        for eje in ("axial", "coronal", "sagital"):
            e = v2d.eje_indice(eje)
            otros = [i for i in (0, 1, 2) if i != e]
            kx, ky = anisotropo.escala_voxeles(eje, alto=512)
            rgb, _info = anisotropo.render_corte(eje, 5, alto=512,
                                                 overlay=False)
            alto_px, ancho_px = rgb.shape[:2]
            assert abs(ancho_px / kx - anisotropo.volumen.shape[otros[1]]) < 1
            assert abs(alto_px / ky - anisotropo.volumen.shape[otros[0]]) < 1

    def test_px_por_voxel_es_el_menor_de_los_dos(self, anisotropo):
        """Se conserva para el cursor; no debe cambiar de comportamiento."""
        for eje in ("axial", "coronal", "sagital"):
            kx, ky = anisotropo.escala_voxeles(eje, alto=512)
            assert anisotropo.px_por_voxel(eje, alto=512) == pytest.approx(
                min(kx, ky))


class TestTrazo:
    def test_el_trazo_no_deja_huecos(self, anisotropo):
        """Un solo evento de raton entre dos puntos muy separados.

        Sin interpolar, el delineado sale punteado: es el fallo que se ve al
        arrastrar rapido.
        """
        for eje in ("axial", "coronal", "sagital"):
            anisotropo.mascara[:] = 0
            n_col = anisotropo.corte_mascara(eje, 5).shape[1]
            anisotropo.pintar_tramo_2d(eje, 5, (2.0, 5.0),
                                       (float(n_col) - 3.0, 5.0), radio=2)
            corte = anisotropo.corte_mascara(eje, 5)
            por_fila = corte.sum(axis=1)
            filas = np.flatnonzero(por_fila)
            assert len(filas) > 0, f"{eje}: no se pinto nada"
            fila = filas[np.argmax(por_fila[filas])]
            cols = np.flatnonzero(corte[fila])
            assert (np.diff(cols) == 1).all(), (
                f"{eje}: el trazo sale punteado, hay "
                f"{int((np.diff(cols) > 1).sum())} huecos")

    def test_el_pincel_es_isotropico_en_voxeles(self, anisotropo):
        """Un circulo de N vóxeles, sea cual sea el eje del corte.

        Compensar la asimetria del render Here se media en un solo voxel de
        alto: un pelo que no sirve ni para cerrar el contorno ni para que el
        STL salga con pared.
        """
        radio = 3
        for eje in ("axial", "coronal", "sagital"):
            anisotropo.mascara[:] = 0
            anisotropo.pintar_tramo_2d(eje, 5, (20.0, 20.0), (20.0, 20.0),
                                       radio=radio)
            corte = anisotropo.corte_mascara(eje, 5)
            assert corte[20, 20], f"{eje}: el centro no se pinto"
            assert abs(corte.sum() - np.pi * radio ** 2) < np.pi * radio, (
                f"{eje}: area {corte.sum()} muy distinta de un disco de radio "
                f"{radio} (se deforma en algun eje)")

    def test_un_trazo_es_un_solo_paso_de_deshacer(self, anisotropo):
        """Deshacer evento a evento obligaria a pulsar Ctrl+Z cientos de veces."""
        anisotropo.mascara[:] = 0
        anisotropo._historial.clear()
        for i in range(5):
            anisotropo.pintar_tramo_2d("coronal", 5,
                                       (5.0, 10.0 + i), (35.0, 12.0 + i),
                                       radio=2)
        assert len(anisotropo._historial) == 5
        total = int(anisotropo.mascara.sum())
        assert anisotropo.deshacer()
        assert int(anisotropo.mascara.sum()) < total


class TestCacheCapaBase:
    def test_render_repetido_devuelve_la_misma_imagen(self, anisotropo):
        """La cache no puede alterar lo que se ve."""
        anisotropo.mascara[:] = 0
        a, _ = anisotropo.render_corte("coronal", 5, alto=512, overlay=True)
        b, _ = anisotropo.render_corte("coronal", 5, alto=512, overlay=True)
        assert np.array_equal(a, b)

    def test_la_cache_no_se_contamina_con_el_tumor(self, anisotropo):
        """Si el overlay se mezclara sobre la imagen cacheada, el tumor no se
        podria borrar: la segunda vez saldria mas intenso y la tercera mas."""
        anisotropo.mascara[:] = 0
        sin, _ = anisotropo.render_corte("coronal", 5, alto=512, overlay=True)
        anisotropo.pintar_tramo_2d("coronal", 5, (5.0, 10.0), (40.0, 10.0),
                                   radio=2)
        con, _ = anisotropo.render_corte("coronal", 5, alto=512, overlay=True)
        anisotropo.mascara[:] = 0
        tras_borrar, _ = anisotropo.render_corte("coronal", 5, alto=512,
                                                 overlay=True)
        assert not np.array_equal(sin, con), "el tumor no se ve"
        assert np.array_equal(sin, tras_borrar), (
            "el tumor se ha quedado pegado a la imagen de la cache")

    def test_cambiar_la_ventana_invalida_la_cache(self, anisotropo):
        anisotropo.render_corte("coronal", 5, alto=512)
        assert anisotropo._cache_base, "no se ha cacheado nada"
        anisotropo.calcular_window((1.0, 99.0))
        assert not anisotropo._cache_base, (
            "la cache sobrevive a un cambio de ventana: se servirian pixeles "
            "ya normalizados con la ventana anterior")


class TestFluidez:
    def test_el_render_cacheado_es_mas_barato(self, anisotropo):
        """Medicion del coste de un paso de raton.

        No se fija un umbral de fps, que fallaria en una maquina lenta: lo que
        se comprueba es que el segundo render es mucho mas barato que el
        primero, que es justo lo que aporta la cache. Si alguien la quita,
        este test lo dice.
        """
        anisotropo.mascara[:] = 0
        anisotropo._cache_base.clear()

        t0 = time.perf_counter()
        anisotropo.render_corte("coronal", 5, alto=1024, overlay=True)
        primer = time.perf_counter() - t0

        n = 5
        t0 = time.perf_counter()
        for _ in range(n):
            anisotropo.render_corte("coronal", 5, alto=1024, overlay=True)
        segundo = (time.perf_counter() - t0) / n

        assert segundo < primer / 2, (
            f"el render cacheado ({segundo * 1000:.1f} ms) no es claramente "
            f"mas barato que el primero ({primer * 1000:.1f} ms): la cache "
            f"de la capa base no esta funcionando")