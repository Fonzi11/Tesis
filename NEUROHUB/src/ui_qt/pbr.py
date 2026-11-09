"""
Materiales PBR de las estructuras segmentadas.

La paleta es deliberadamente neutra y de baja especularidad: no intenta
colorear una MRI/CT como una radiografia sepia, sino separar estructuras sin
alterar la lectura espacial de la anatomia.
"""

PBR_COLORS = {
    "cerebro": dict(
        color_rgba=(0.54, 0.60, 0.67, 0.85),
        roughness=0.88, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.35,
        subsurface_color=(0.55, 0.64, 0.75, 1.0),
        display="#8A9AAF", label="Cerebro",
    ),
    "craneo": dict(
        color_rgba=(0.82, 0.86, 0.90, 1.0),
        roughness=0.92, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.08,
        subsurface_color=(0.82, 0.88, 0.95, 1.0),
        display="#D1DCE8", label="Cráneo",
    ),
    "tumor": dict(
        color_rgba=(0.86, 0.18, 0.10, 1.0),
        roughness=0.62, metallic=0.0,
        emission=(0.08, 0.00, 0.00, 1.0), subsurface=0.05,
        subsurface_color=(0.95, 0.25, 0.12, 1.0),
        display="#DB321F", label="Tumor",
    ),
    "aneurisma": dict(
        color_rgba=(1.00, 0.55, 0.00, 1.0),
        roughness=0.35, metallic=0.0,
        emission=(1.00, 0.35, 0.00, 1.0), subsurface=0.05,
        subsurface_color=(1.0, 0.6, 0.2, 1.0),
        display="#FF8C00", label="Aneurisma",
    ),
    "vasos": dict(
        color_rgba=(0.92, 0.12, 0.10, 1.0),
        roughness=0.42, metallic=0.0,
        emission=(0.12, 0.01, 0.00, 1.0), subsurface=0.12,
        subsurface_color=(1.0, 0.18, 0.12, 1.0),
        display="#E6352A", label="Sistema vascular",
    ),
    "arterias": dict(
        color_rgba=(0.95, 0.16, 0.10, 1.0),
        roughness=0.38, metallic=0.0,
        emission=(0.10, 0.00, 0.00, 1.0), subsurface=0.10,
        subsurface_color=(1.0, 0.20, 0.12, 1.0),
        display="#F04432", label="Arterias",
    ),
    "venas": dict(
        color_rgba=(0.14, 0.35, 0.92, 1.0),
        roughness=0.44, metallic=0.0,
        emission=(0.00, 0.01, 0.12, 1.0), subsurface=0.10,
        subsurface_color=(0.20, 0.45, 1.0, 1.0),
        display="#3974E8", label="Venas",
    ),
    "fs_cortex": dict(color_rgba=(0.32, 0.82, 0.45, 0.45),
                      roughness=0.72, display="#52D173", label="Corteza FS"),
    "fs_white_matter": dict(color_rgba=(0.35, 0.62, 0.95, 0.32),
                            roughness=0.82, display="#599EF2",
                            label="Sustancia blanca FS"),
    "fs_cerebellum": dict(color_rgba=(0.95, 0.72, 0.12, 0.88),
                          roughness=0.68, display="#F2B81F", label="Cerebelo FS"),
    "fs_brainstem": dict(color_rgba=(0.95, 0.30, 0.18, 0.92),
                         roughness=0.62, display="#F24D2E", label="Tronco FS"),
    "fs_thalamus": dict(color_rgba=(0.77, 0.26, 0.88, 0.92),
                        roughness=0.62, display="#C442E0", label="Tálamo FS"),
    "fs_basal_ganglia": dict(color_rgba=(0.12, 0.75, 0.88, 0.92),
                             roughness=0.62, display="#20BFDF",
                             label="Ganglios basales FS"),
    "fs_hippocampus": dict(color_rgba=(0.95, 0.28, 0.62, 0.92),
                           roughness=0.62, display="#F2479E",
                           label="Hipocampo FS"),
    "fs_ventricles": dict(color_rgba=(0.96, 0.96, 0.96, 0.55),
                          roughness=0.5, display="#F5F5F5",
                          label="Ventrículos FS"),
}

# Alias de claves: nombres alternativos de archivo que el visor puede
# encontrar (skull.stl, brain.stl...) se mapean a su estructura canonica.
PBR_ALIASES = {
    "skull": "craneo",
    "brain": "cerebro",
    "cranium": "craneo",
    "aneurisma_candidatos": "aneurisma",
    "venas_arterias": "vasos",
    "vessels": "vasos",
    "vessel": "vasos",
    "artery": "arterias",
    "arteries": "arterias",
    "veins": "venas",
    "vein": "venas",
}


def resolve_pbr(key):
    """Devuelve la entrada de PBR_COLORS que corresponde a `key`.

    Aplica PBR_ALIASES para que los nombres reales de archivo (skull.stl,
    arterias.stl, ...) hereden el material de su estructura canonica.
    """
    if not key:
        return {}
    k = key.lower()
    if k in PBR_COLORS:
        return PBR_COLORS[k]
    canon = PBR_ALIASES.get(k)
    if canon:
        return PBR_COLORS.get(canon, {})
    # Ultimo recurso: coincidencia por subcadena ("Cerebro_Completo", ...).
    for name, meta in PBR_COLORS.items():
        if name in k:
            return meta
    return {}


def label_de(key):
    """Nombre legible de una estructura, con mayuscula inicial."""
    meta = resolve_pbr(key)
    if meta.get("label"):
        return meta["label"]
    return (key or "modelo").replace("_", " ").title()


def color_de(key, por_defecto="#8B8B8B"):
    """Color hexadecimal para la muestra del panel de capas."""
    meta = resolve_pbr(key)
    if meta.get("display"):
        return meta["display"]
    if meta.get("color_rgba"):
        r, g, b = meta["color_rgba"][:3]
        return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))
    return por_defecto
