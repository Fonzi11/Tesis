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
}

# Alias de claves: nombres alternativos de archivo que el visor puede
# encontrar (skull.stl, brain.stl...) se mapean a su estructura canonica.
PBR_ALIASES = {
    "skull": "craneo",
    "brain": "cerebro",
    "cranium": "craneo",
    "aneurisma_candidatos": "aneurisma",
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
