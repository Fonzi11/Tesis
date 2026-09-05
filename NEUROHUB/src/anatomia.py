"""
NEUROHUB - Panel de Anatomía Interactivo con Turtle
====================================================
Dibuja diagrama del cerebro con estructuras tumor/aneurisma.
Controles: flechas ←→ o A/D para navegar, ESC para salir.
"""

import os
import sys
import math

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

BG = "#0a0a0e"
GRID = "#1a1a24"
BRAIN = "#1e1e2e"
BRAIN_EDGE = "#8ab4f8"
TUMOR = "#c828dc"
ANEURYSM = "#ff8c00"
VESSEL = "#c83232"
TEXT_C = "#f4f4f6"
TEXT_DIM = "#8a8a96"

class AnatomiaTurtle:
    """Panel educativo del cerebro usando turtle."""

    def __init__(self):
        self.t = None
        self.selected = 0
        self.buttons = []
        self.structuras = [
            ("Cerebro", "Órgano principal del SNC. Dividido en hemisferios. "
             "Segmentable con TotalSegmentator."),
            ("Tumor", "Masa anormal de tejido. Detectado con MRI T1ce/T2/FLAIR. "
             "Clasificación BraTS: ET=4, ED=2, NCR=1."),
            ("Aneurisma", "Dilatación anormal de vaso. Riesgo de ruptura. "
             "Detectado en CTA con análisis de curvatura."),
            ("Vasos", "Red vascular cerebral. Arterias y venas. "
             "Segmentables por umbral CTA/MRA."),
            ("Cráneo", "Estructura ósea protectora. Segmentable por "
             "umbral HU en CT."),
        ]

    def draw(self):
        """Dibuja el diagrama interactivo."""
        try:
            import turtle
        except ImportError:
            print("turtle no disponible en este entorno")
            return

        self.t = turtle.Turtle()
        screen = turtle.Screen()
        screen.bgcolor(BG)
        screen.title("NEUROHUB - Anatomía Cerebral Interactiva")
        screen.setup(1100, 800)
        screen.tracer(0)

        self._draw_background()
        self._draw_brain_diagram()
        self._draw_legend()
        self._draw_info_panel()

        screen.tracer(1)
        screen.listen()
        screen.onkey(self._prev, "Left")
        screen.onkey(self._next, "Right")
        screen.onkey(self._prev, "a")
        screen.onkey(self._next, "d")
        screen.onkey(screen.bye, "Escape")

        turtle.done()

    # ---------------------------------------------------------------
    def _prev(self):
        self.selected = (self.selected - 1) % len(self.structuras)
        if self.t is not None:
            self._draw_info_panel()

    def _next(self):
        self.selected = (self.selected + 1) % len(self.structuras)
        if self.t is not None:
            self._draw_info_panel()

    # ---------------------------------------------------------------
    def _draw_background(self):
        t = self.t
        t.penup()
        t.goto(0, 0)
        t.color(GRID)
        t.pensize(0.5)
        for x in range(-500, 501, 40):
            t.penup()
            t.goto(x, -350)
            t.pendown()
            t.goto(x, 350)
        for y in range(-350, 351, 40):
            t.penup()
            t.goto(-500, y)
            t.pendown()
            t.goto(500, y)

    # ---------------------------------------------------------------
    def _draw_brain_diagram(self):
        t = self.t
        t.penup()
        t.color(BRAIN_EDGE)
        t.pensize(4)
        # Dibujar elipse del cerebro
        t.goto(240, 0)
        t.pendown()
        for i in range(72):
            angle = i * 5 * math.pi / 180
            x = 240 * math.cos(angle)
            y = 150 * math.sin(angle)
            t.goto(x, y)
        t.penup()

        # Hemisferio derecho (sombra)
        t.color("#2d2d3f")
        t.pensize(1)
        t.goto(240, 0)
        t.pendown()
        for i in range(72):
            angle = i * 5 * math.pi / 180
            x = 240 * math.cos(angle) * 0.85
            y = 150 * math.sin(angle) * 0.85
            t.goto(x, y)
        t.penup()

        # Sulcos principales
        t.color("#3a3a4a")
        t.pensize(2)
        t.goto(-10, 150)
        t.pendown()
        t.goto(-10, -150)
        t.penup()

    # ---------------------------------------------------------------
    def _draw_vessels(self):
        t = self.t
        t.color(VESSEL)
        t.pensize(2.5)
        t.penup()
        t.goto(0, 120)
        t.pendown()
        t.goto(0, -90)
        t.goto(85, 40)
        t.penup()
        t.goto(0, 70)
        t.pendown()
        t.goto(-85, 40)
        t.penup()

    def _draw_pulsing_dot(self, x, y, radius, color, label):
        t = self.t
        t.penup()
        t.goto(x, y)
        t.color(color)
        t.pensize(2)
        t.dot(radius * 2, color)
        # Anillo
        t.penup()
        t.goto(x + radius, y)
        t.pendown()
        t.circle(radius, 360)
        t.penup()
        t.goto(x + radius + 10, y + 8)
        t.color(TEXT_C)
        t.write(label, font=("Arial", 10, "bold"))

    def _draw_legend(self):
        t = self.t
        items = [
            ("TUMOR (Magenta)", TUMOR),
            ("ANEURISMA (Naranja)", ANEURYSM),
            ("VASOS (Rojo)", VESSEL),
            ("CEREBRO (Azul)", BRAIN_EDGE),
        ]
        y = -325
        t.penup()
        t.goto(-480, y)
        t.color(TEXT_DIM)
        t.write("LEYENDA:", font=("Arial", 12, "bold"))
        for name, color in items:
            y += 22
            t.goto(-480, y)
            t.dot(10, color)
            t.goto(-460, y + 5)
            t.color(TEXT_C)
            t.write(name, font=("Arial", 10))

    def _draw_info_panel(self):
        """Dibuja el panel de información de estructura seleccionada."""
        t = self.t
        # Limpiar panel
        t.penup()
        t.goto(150, -170)
        t.color(BG)
        t.pensize(2)
        t.pendown()
        t.goto(500, -170)
        t.goto(500, -270)
        t.goto(150, -270)
        t.goto(150, -170)
        t.penup()

        struct = self.structuras[self.selected]
        t.goto(165, -190)
        t.color(BRAIN_EDGE)
        t.write(f"► {struct[0].upper()}", font=("Arial", 12, "bold"))
        t.goto(170, -215)
        t.color(TEXT_C)
        t.write(struct[1][:75], font=("Arial", 9))

    # ---------------------------------------------------------------
    def launch(self):
        """Método de compatibilidad."""
        self.draw()


def launch_anatomia():
    """Lanza el panel de anatomía."""
    a = AnatomiaTurtle()
    a.draw()
    return a


if __name__ == "__main__":
    launch_anatomia()

