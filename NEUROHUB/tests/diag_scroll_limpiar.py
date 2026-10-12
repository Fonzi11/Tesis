"""Reproduce: rueda no cambia de corte y 'Limpiar tumor' no responde."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BASE)
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QWheelEvent

from src.ui_qt.viewer_2d import Viewer2D
from src import volumen_2d as v2d

app = QApplication([])
v = Viewer2D()
v.resize(1200, 800)

vol = v2d.Volumen2D()
vol.cargar(os.path.join(REPO, "data", "nifti", "braTS_sample",
                         "BraTS2021_00000", "BraTS2021_00000_t1ce.nii.gz"))
vol.mascara[:, :, :] = 0
vol.mascara[30:40, 40:50, 40:50] = 1
v.set_volumen(vol)
v.set_eje("axial")
v.show()
app.processEvents()

print("=== RUEDA ===")
print("cortes axial :", v.n_cortes())
print("indice antes :", v.indice())
lienzo = v._paginators["axial"]
print("escala antes :", round(lienzo._escala, 4))

ev = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                 QPoint(0, 0), QPoint(0, 120),
                 Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
lienzo.wheelEvent(ev)
app.processEvents()
print("indice despues rueda lisa :", v.indice())
print("escala despues           :", round(lienzo._escala, 4))

ev2 = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                  QPoint(0, 0), QPoint(0, 120),
                  Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
v.wheelEvent(ev2)
app.processEvents()
print("indice despues rueda en barra :", v.indice())

# Ctrl+rueda sobre el LIENZO: la via de Slicer.
ev3 = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                  QPoint(0, 0), QPoint(0, 120),
                  Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
lienzo.wheelEvent(ev3)
app.processEvents()
print("indice despues Ctrl+rueda lienzo:", v.indice())

ev4 = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                  QPoint(0, 0), QPoint(0, -120),
                  Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
lienzo.wheelEvent(ev4)
app.processEvents()
print("indice despues Ctrl+rueda atras :", v.indice())

# Una sola "tiqueta" de rueda tactil suele venir con angleDelta 0 pero
# con scrollPhase/pixelDelta: es el caso que reporta un portatil.
# --- MODO SIN VOLUMEN (solo PNG): es lo que ve el usuario ahora ---
v2 = Viewer2D()
v2.resize(1200, 800)
png = {}
for eje in ("axial", "coronal", "sagital"):
    destino = os.path.join(REPO, "salidas", "slices_2d",
                           f"{eje}.png")
    if os.path.isfile(destino):
        png[eje] = destino
if not png:
    import glob
    for eje in ("axial", "coronal", "sagital"):
        cand = glob.glob(os.path.join(REPO, "salidas", "**", f"*{eje}*.png"),
                         recursive=True)
        if cand:
            png[eje] = cand[0]
print()
print("=== MODO PNG (sin volumen) ===")
print("png disponibles   :", {k: os.path.basename(p) for k, p in png.items()})
v2.set_cortes(png)
v2.show()
app.processEvents()
print("n_cortes          :", v2.n_cortes())
print("tiene_cortes      :", v2.tiene_cortes())
print("boton limpiar     : habilitado =", v2._btn_limpiar.isEnabled())
print("boton pincel      : habilitado =", v2._botones_brush['pintar'].isEnabled())
print("slider            : habilitado =", v2._slider.isEnabled())
l2 = v2._paginators["axial"]
esc_antes = l2._escala
ev = QWheelEvent(QPointF(600, 400), QPointF(600, 400),
                 QPoint(0, 0), QPoint(0, 120),
                 Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
l2.wheelEvent(ev)
app.processEvents()
print("Ctrl+rueda, indice:", v2.indice())
print("rueda lisa, escala :", round(esc_antes, 4), "->", round(l2._escala, 4))
print("=> SIN VOLUMEN la rueda solo hace zoom y no hay cortes:",
      v2.indice() == 0)

print()
print("=== LIMPIAR TUMOR ===")
vol.mascara[30:40, 40:50, 40:50] = 1
v.set_volumen(vol)
app.processEvents()
print("voxeles tumor antes :", vol.vóxeles_tumor())
b = v._btn_limpiar
print("boton habilitado   :", b.isEnabled())
print("boton visible      :", b.isVisible())
print("tamaño / geo       :", b.size(), b.geometry())

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt as _Qt
QTest.mouseClick(b, _Qt.LeftButton)
app.processEvents()
print("tras QTest.click   :", vol.vóxeles_tumor())
print("informacion        :", repr(v._lbl_info.text()))

# Clic en el centro del boton, como haria el usuario de verdad.
b.repaint()
c = b.rect().center()
QTest.mouseClick(b, _Qt.LeftButton, _Qt.NoModifier, c)
app.processEvents()
print("tras clic en centro:", vol.vóxeles_tumor())
print("informacion        :", repr(v._lbl_info.text()))

# Valores antes/despues del pixmap: si el corte se repinta.
# El tumor se pone EN EL CORTE VISIBLE: `indice_mas_tumor` deja el visor
# donde hay tumor, que es donde el usuario mira cuando pulsa "Limpiar".
v.set_indice(v.corte_actual())
app.processEvents()
eje_i = 0
z = v.indice()
vol.mascara[z, 40:50, 40:50] = 1
v._refrescar()
app.processEvents()
pm_antes = v.pixmap().toImage()
print("corte visible      :", z, " tumor en corte:", vol.vóxeles_tumor())
print("pixmap con tumor != vacio:", pm_antes != v._paginators["axial"].pixmap().toImage())

QTest.mouseClick(b, _Qt.LeftButton)
app.processEvents()
pm_despues = v.pixmap().toImage()
print("tras clic, pixmap cambia :", pm_antes != pm_despues)
print("voxeles tumor            :", vol.vóxeles_tumor())
print("informacion              :", repr(v._lbl_info.text()))
print("deshacer funciona        :", v.deshacer(), vol.vóxeles_tumor())

# Slider
print()
print("=== SLIDER ===")
print("slider habilitado  :", v._slider.isEnabled())
print("slider rango       :", v._slider.minimum(), v._slider.maximum())
v._slider.setValue(77)
app.processEvents()
print("indice tras slider :", v.indice())