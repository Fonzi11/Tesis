"""
Materiales PBR de las estructuras segmentadas.

Se extraen tal cual de `main.py` (PBR_COLORS / PBR_ALIASES / resolve_pbr) para
que el nuevo visor 3D pinte EXACTAMENTE igual que el anterior. Moverlos aqui
evita que el visor tenga que importar `main.py` (que construiria la app Tk al
importarse).
"""

PBR_COLORS = {
    "cerebro": dict(
        color_rgba=(0.76, 0.60, 0.58, 0.85),
        roughness=0.75, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.35,
        subsurface_color=(0.9, 0.45, 0.35, 1.0),
        display="#C99A91", label="Cerebro",
    ),
    "craneo": dict(
        color_rgba=(0.92, 0.88, 0.78, 1.0),
        roughness=0.85, metallic=0.0,
        emission=(0, 0, 0, 1), subsurface=0.08,
        subsurface_color=(1.0, 0.95, 0.80, 1.0),
        display="#EAE0C7", label="Cráneo",
    ),
    "tumor": dict(
        color_rgba=(0.40, 0.00, 0.90, 1.0),
        roughness=0.45, metallic=0.0,
        emission=(0.30, 0.00, 0.60, 1.0), subsurface=0.10,
        subsurface_color=(0.6, 0.1, 0.8, 1.0),
        display="#6600E6", label="Tumor",
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
