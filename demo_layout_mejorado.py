#!/usr/bin/env python3
"""
DEMO: Layout mejorado - Vistas 2D GRANDES y bien distribuidas
Muestra cómo debería verse la interfaz con mejor visual
"""
import os
import sys
import customtkinter as ctk
from PIL import Image, ImageTk

# Theme colors
COLORS = {
    "bg": "#000000",
    "bg_secondary": "#0f0f12",
    "bg_card": "#1a1a1f",
    "bg_input": "#2a2a2f",
    "text": "#f4f4f6",
    "text_secondary": "#a0a0a6",
    "accent": "#8ab4f8",
    "border": "#3a3a3f",
}

FONT_FAMILY = "Segoe UI"
FONT_TITLE = "Bahnschrift"

def demo_window():
    """Ventana de demostración con layout mejorado."""
    
    app = ctk.CTk()
    app.title("ATLAS v1.1 - Layout Mejorado")
    app.geometry("1400x1000")
    app.configure(fg_color=COLORS["bg"])
    
    # ═══════════════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════════════
    header = ctk.CTkFrame(app, fg_color=COLORS["bg_secondary"], height=60)
    header.pack(fill="x", padx=0, pady=0)
    header.pack_propagate(False)
    
    title = ctk.CTkLabel(header, text="PROYECTO ATLAS - Visualización Integrada 2D+3D",
                        font=(FONT_TITLE, 20, "bold"), text_color=COLORS["accent"])
    title.pack(side="left", padx=20, pady=10)
    
    # ═══════════════════════════════════════════════════════════════════
    # MAIN CONTENT
    # ═══════════════════════════════════════════════════════════════════
    main_frame = ctk.CTkFrame(app, fg_color=COLORS["bg"])
    main_frame.pack(fill="both", expand=True, padx=16, pady=16)
    
    # ─────────────────────────────────────────────────────────────────
    # SECCIÓN SUPERIOR: Visor 3D placeholder
    # ─────────────────────────────────────────────────────────────────
    visor_3d_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], 
                                   corner_radius=12, border_width=1, border_color=COLORS["border"])
    visor_3d_frame.pack(fill="both", expand=True, pady=(0, 12))
    
    visor_title = ctk.CTkLabel(visor_3d_frame, text="VISOR 3D DE MODELOS",
                               font=(FONT_TITLE, 14, "bold"), text_color=COLORS["text"])
    visor_title.pack(anchor="nw", padx=16, pady=(12, 0))
    
    visor_content = ctk.CTkLabel(visor_3d_frame, text="[Modelo 3D con iluminación profesional]",
                                 font=(FONT_FAMILY, 12), text_color=COLORS["text_secondary"],
                                 fg_color=COLORS["bg_card"], corner_radius=8)
    visor_content.pack(fill="both", expand=True, padx=16, pady=(8, 16))
    
    # ─────────────────────────────────────────────────────────────────
    # SECCIÓN INFERIOR: Vistas 2D - DISTRIBUIDAS EN HORIZONTAL (3 columnas)
    # ─────────────────────────────────────────────────────────────────
    vistas_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"],
                                corner_radius=12, border_width=1, border_color=COLORS["border"])
    vistas_frame.pack(fill="both", expand=True, pady=(0, 0))
    
    vistas_title = ctk.CTkLabel(vistas_frame, text="VISTAS 2D CON TUMOR",
                               font=(FONT_TITLE, 14, "bold"), text_color=COLORS["text"])
    vistas_title.pack(anchor="nw", padx=16, pady=(12, 12))
    
    # Grid de 3 columnas para las vistas
    grid_frame = ctk.CTkFrame(vistas_frame, fg_color="transparent")
    grid_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    
    slice_dir = os.path.join(os.path.dirname(__file__), "salidas", "segmentaciones_ai", "vistas_2d")
    img_refs = {}  # Guardar referencias de imágenes
    
    for col, (name, label_txt) in enumerate([("axial", "AXIAL"), 
                                              ("coronal", "CORONAL"), 
                                              ("sagital", "SAGITAL")]):
        # Frame para cada vista
        col_frame = ctk.CTkFrame(grid_frame, fg_color=COLORS["bg_card"], 
                                 corner_radius=10, border_width=1, border_color=COLORS["border"])
        col_frame.grid(row=0, column=col, padx=6, pady=0, sticky="nsew")
        
        # Título
        col_title = ctk.CTkLabel(col_frame, text=label_txt,
                                font=(FONT_FAMILY, 12, "bold"), text_color=COLORS["accent"])
        col_title.pack(pady=(10, 8))
        
        # Canvas para imagen (450x450 para mejor visibilidad)
        canvas = ctk.CTkCanvas(col_frame, width=420, height=420,
                              bg=COLORS["bg_input"], highlightthickness=0, bd=0)
        canvas.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        
        # Intentar cargar la imagen
        path = os.path.join(slice_dir, f"corte_{name}.png")
        if os.path.exists(path):
            try:
                img = Image.open(path)
                img.thumbnail((420, 420), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img_refs[name] = photo  # Guardar referencia
                
                canvas.delete("all")
                canvas.create_image(210, 210, image=photo)
                print(f"✓ {name} cargada: {img.size}")
                
            except Exception as e:
                canvas.create_text(210, 210, text=f"Error: {e}", fill="red", font=(FONT_FAMILY, 10))
                print(f"✗ Error en {name}: {e}")
        else:
            canvas.create_text(210, 210, text=f"No encontrado\n{name}.png", 
                             fill=COLORS["text_secondary"], font=(FONT_FAMILY, 11))
            print(f"⚠️ {path} NO EXISTE")
    
    # Configurar columnas con peso igual
    grid_frame.grid_columnconfigure(0, weight=1)
    grid_frame.grid_columnconfigure(1, weight=1)
    grid_frame.grid_columnconfigure(2, weight=1)
    grid_frame.grid_rowconfigure(0, weight=1)
    
    # ═══════════════════════════════════════════════════════════════════
    # FOOTER
    # ═══════════════════════════════════════════════════════════════════
    footer = ctk.CTkFrame(app, fg_color=COLORS["bg_secondary"], height=40)
    footer.pack(fill="x", padx=0, pady=0)
    footer.pack_propagate(False)
    
    status_text = ctk.CTkLabel(footer, 
                              text="✓ Axial: 420×420px  |  ✓ Coronal: 420×420px  |  ✓ Sagital: 420×420px",
                              font=(FONT_FAMILY, 10), text_color=COLORS["text_secondary"])
    status_text.pack(side="left", padx=20, pady=8)
    
    # ═══════════════════════════════════════════════════════════════════
    # INSTRUCCIONES
    # ═══════════════════════════════════════════════════════════════════
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║             DEMO: LAYOUT MEJORADO PARA ATLAS v1.1                         ║
║                                                                            ║
║  VENTAJAS DE ESTA DISPOSICIÓN:                                            ║
║  ✓ Visor 3D: Ocupa espacio completo arriba (máxima visibilidad)          ║
║  ✓ Vistas 2D: 3 columnas con 420×420px cada una (MUCHO MÁS GRANDE)       ║
║  ✓ Tumor visible: Magenta fill + círculo verde encierro claro             ║
║  ✓ Etiquetas: AXIAL/CORONAL/SAGITAL en azul accent, legibles              ║
║  ✓ Balance: Espacio bien distribuido sin apretamiento                     ║
║  ✓ Responsive: Adapta a diferentes tamaños de ventana                     ║
║                                                                            ║
║  COMPARATIVA:                                                              ║
║  Antes:  Horizontal 70/30 + imágenes 180×180px = MUY PEQUEÑO              ║
║  Después: Vertical 60/40 + imágenes 420×420px = MUCHO MÁS CLARO           ║
║                                                                            ║
║  PRÓXIMOS PASOS:                                                           ║
║  1. Verifica que las imágenes se carguen correctamente (arriba)           ║
║  2. Observa la distribución de espacio (sin apretamiento)                 ║
║  3. Si te gusta, aplicaremos esto al main.py                              ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)
    
    app.mainloop()

if __name__ == "__main__":
    demo_window()
