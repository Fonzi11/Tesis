"""
convert_stl_to_fbx.py

Blender headless script to convert STL (with per-vertex/triangle colors) to FBX preserving vertex colors.

Usage:
    blender --background --python convert_stl_to_fbx.py -- input.stl output.fbx [--uniform-color R G B] [--alpha A] [--force-parse] [-v]

Exit codes: 0 success, non-zero on error.

This script prefers Blender's STL importer but will fall back to a small pure-Python STL parser
that understands common binary-color-extended STLs (attribute word with 15-bit RGB) and a
simple ASCII-extended variant where vertex lines include R G B values after coordinates.

When run outside Blender ("bpy" unavailable) it prints a usage hint and exits non-zero.
"""

from __future__ import annotations
import sys
import os
import argparse
import struct
from typing import List, Tuple, Optional

# Try to import bpy. If not available, we'll exit with a helpful message.
try:
    import bpy
    BLENDER_AVAILABLE = True
except Exception:
    bpy = None  # type: ignore
    BLENDER_AVAILABLE = False


def parse_cli_args(argv: List[str]) -> argparse.Namespace:
    # In Blender, arguments after "--" are passed to the script.
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = argv[1:]

    p = argparse.ArgumentParser(description="Convert STL (with colors) to FBX or glTF preserving vertex colors.")
    p.add_argument("input", help="Input STL file path")
    p.add_argument("output", help="Output file path (FBX or glTF based on --export-format)")
    p.add_argument(
        "--export-format",
        choices=["fbx", "gltf"],
        default="fbx",
        help="Export format to write. Default: fbx. If gltf is selected, the script will attempt to use Blender's glTF exporter.",
    )
    p.add_argument(
        "--log-file",
        help="Optional path to write a detailed log of the conversion (appends).",
        default=None,
    )
    p.add_argument(
        "--uniform-color",
        nargs=3,
        metavar=("R", "G", "B"),
        type=float,
        help=(
            "Uniform color to apply if no colors found. Accepts three values in 0..1 or 0..255."
        ),
    )
    p.add_argument("--alpha", type=float, default=1.0, help="Alpha for uniform color (0..1). Default 1.0")
    p.add_argument(
        "--force-parse",
        action="store_true",
        help="Force using internal STL parser instead of Blender's importer (useful if importer drops colors).",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Verbose output")
    return p.parse_args(argv)


def exit_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# -----------------
# STL parsing code
# -----------------

# Types
Vec3 = Tuple[float, float, float]
Color = Tuple[float, float, float, float]  # RGBA in 0..1


def detect_stl_type(path: str) -> str:
    """Return 'binary' or 'ascii' by heuristics: file size check and header inspection."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        header = f.read(84)
        if len(header) < 84:
            return "ascii"
        # read triangle count from bytes 80..84
        try:
            tri_count = struct.unpack_from("<I", header, 80)[0]
            expected = 84 + tri_count * 50
            if expected == size:
                return "binary"
        except Exception:
            pass
        # fallback heuristics
        f.seek(0)
        start = f.read(256)
        if b"facet" in start.lower() or b"endsolid" in start.lower():
            return "ascii"
        # if there are null bytes it's probably binary
        if b"\x00" in start:
            return "binary"
        return "ascii"


def parse_binary_stl(path: str):
    """
    Parse a binary STL. Supports the common "attribute word encodes color" extension:
    attribute high bit (0x8000) set -> lower 15 bits are RRRRRGGGGGBBBBB (5 bits each).

    Returns (vertices, faces, colors_per_face) where colors_per_face is a list with either None
    or a tuple of 3 Color entries (one per corner). If attribute encodes a single color it is
    expanded to three equal corner colors.
    """
    verts: List[Vec3] = []
    vert_map = {}
    faces: List[Tuple[int, int, int]] = []
    colors: List[Optional[Tuple[Color, Color, Color]]] = []

    with open(path, "rb") as f:
        header = f.read(80)
        tri_data = f.read(4)
        if len(tri_data) < 4:
            raise ValueError("Not a valid binary STL (too small)")
        tri_count = struct.unpack("<I", tri_data)[0]

        for i in range(tri_count):
            # normal (3 floats) + 3 vertices (3*3 floats) + 2-byte attribute = 50 bytes
            data = f.read(50)
            if len(data) < 50:
                raise ValueError(f"Unexpected EOF while reading triangle {i}")
            vals = struct.unpack("<12fH", data)  # 12 floats then unsigned short
            # normals = vals[0:3]
            v1 = (vals[3], vals[4], vals[5])
            v2 = (vals[6], vals[7], vals[8])
            v3 = (vals[9], vals[10], vals[11])
            attr = vals[12]

            face_idx = []
            for v in (v1, v2, v3):
                # deduplicate vertices by coordinate with a small rounding tolerance
                key = (round(v[0], 6), round(v[1], 6), round(v[2], 6))
                if key in vert_map:
                    face_idx.append(vert_map[key])
                else:
                    vid = len(verts)
                    verts.append(v)
                    vert_map[key] = vid
                    face_idx.append(vid)
            faces.append((face_idx[0], face_idx[1], face_idx[2]))

            # color decoding for the common 15-bit color packing
            if attr & 0x8000:
                colorbits = attr & 0x7FFF
                r5 = (colorbits >> 10) & 0x1F
                g5 = (colorbits >> 5) & 0x1F
                b5 = colorbits & 0x1F
                r = r5 / 31.0
                g = g5 / 31.0
                b = b5 / 31.0
                c = (r, g, b, 1.0)
                colors.append((c, c, c))
            else:
                colors.append(None)

    return verts, faces, colors


def parse_ascii_stl(path: str):
    """
    Parse an ASCII STL. This parser looks for 'vertex' lines; if vertices include extra numeric
    tokens after the 3 coordinates, those will be interpreted as R G B (either 0..1 or 0..255).

    Returns the same structure as parse_binary_stl.
    """
    verts: List[Vec3] = []
    vert_map = {}
    faces: List[Tuple[int, int, int]] = []
    colors: List[Optional[Tuple[Color, Color, Color]]] = []

    def add_vertex(v: Vec3) -> int:
        key = (round(v[0], 6), round(v[1], 6), round(v[2], 6))
        if key in vert_map:
            return vert_map[key]
        idx = len(verts)
        verts.append(v)
        vert_map[key] = idx
        return idx

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        current_vertices: List[Vec3] = []
        current_colors: List[Optional[Color]] = []

        for raw in f:
            line = raw.strip()
            if not line:
                continue
            toks = line.split()
            if not toks:
                continue
            t0 = toks[0].lower()
            if t0 == "vertex":
                # tokens: vertex X Y Z [R G B]
                if len(toks) >= 4:
                    try:
                        x = float(toks[1]); y = float(toks[2]); z = float(toks[3])
                    except Exception:
                        continue
                    color = None
                    if len(toks) >= 7:
                        try:
                            r = float(toks[4]); g = float(toks[5]); b = float(toks[6])
                            # normalize if in 0..255
                            if r > 1.0 or g > 1.0 or b > 1.0:
                                r /= 255.0; g /= 255.0; b /= 255.0
                            color = (r, g, b, 1.0)
                        except Exception:
                            color = None
                    current_vertices.append((x, y, z))
                    current_colors.append(color)
            elif t0 == "endloop":
                if len(current_vertices) == 3:
                    idxs = [add_vertex(v) for v in current_vertices]
                    faces.append((idxs[0], idxs[1], idxs[2]))
                    if any(c is not None for c in current_colors):
                        # fill missing colors with the first available in this triangle
                        first = next((c for c in current_colors if c is not None), None)
                        corner_colors = tuple(c if c is not None else first for c in current_colors)
                        colors.append(corner_colors)
                    else:
                        colors.append(None)
                current_vertices = []
                current_colors = []

    return verts, faces, colors


# -----------------
# Blender helpers
# -----------------


def mesh_has_vertex_colors(mesh) -> bool:
    # Support old API (vertex_colors) and new API (color_attributes)
    if hasattr(mesh, "vertex_colors") and len(mesh.vertex_colors) > 0:
        return True
    if hasattr(mesh, "color_attributes"):
        # color_attributes exist in newer Blender; check any color attribute with CORNER/POINT domain
        for a in mesh.color_attributes:
            if getattr(a, "data", None) is not None:
                return True
    return False


def create_mesh_object(name: str, verts: List[Vec3], faces: List[Tuple[int, int, int]]):
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def add_vertex_colors(mesh, colors_per_face: List[Optional[Tuple[Color, Color, Color]]], uniform: Optional[Color] = None):
    """
    colors_per_face: list length == number of faces; each entry None or tuple of 3 Colors
    uniform: if provided, will be used if entry is None
    """
    # Ensure we have a color layer - support multiple Blender versions
    if hasattr(mesh, "vertex_colors"):
        # old-style API (per-loop)
        name = "Col"
        # remove existing layer if present
        if name in mesh.vertex_colors:
            vcol = mesh.vertex_colors[name]
        else:
            vcol = mesh.vertex_colors.new(name=name)
        data = vcol.data
        # iterate polygons and assign per-loop colors
        for poly_idx, poly in enumerate(mesh.polygons):
            face_colors = None
            if poly_idx < len(colors_per_face):
                face_colors = colors_per_face[poly_idx]
            for offset in range(poly.loop_total):
                loop_index = poly.loop_start + offset
                if face_colors is not None:
                    c = face_colors[offset]
                else:
                    c = uniform
                if c is None:
                    # fallback white
                    data[loop_index].color = (0.8, 0.8, 0.8, 1.0)
                else:
                    # data[loop_index].color expects a (r,g,b,a) sequence
                    data[loop_index].color = (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
    else:
        # new API: color_attributes
        name = "Col"
        if name in mesh.color_attributes:
            attr = mesh.color_attributes[name]
        else:
            # domain CORNER gives per-loop color
            attr = mesh.color_attributes.new(name=name, type='FLOAT_COLOR', domain='CORNER')
        data = attr.data
        for poly_idx, poly in enumerate(mesh.polygons):
            face_colors = None
            if poly_idx < len(colors_per_face):
                face_colors = colors_per_face[poly_idx]
            for offset in range(poly.loop_total):
                loop_index = poly.loop_start + offset
                if face_colors is not None:
                    c = face_colors[offset]
                else:
                    c = uniform
                if c is None:
                    data[loop_index].color = (0.8, 0.8, 0.8, 1.0)
                else:
                    data[loop_index].color = (float(c[0]), float(c[1]), float(c[2]), float(c[3]))


def try_import_with_blender_importer(path: str) -> List[bpy.types.Object]:
    """Attempt to import using Blender's import_mesh.stl operator and return new objects created.
    If it fails or doesn't create objects, return an empty list.
    """
    pre_objs = set(bpy.context.scene.objects[:])
    try:
        # The import operator is usually available as import_mesh.stl
        bpy.ops.import_mesh.stl(filepath=path)
    except Exception as e:
        print(f"Blender STL importer failed: {e}")
        return []
    post_objs = [o for o in bpy.context.scene.objects if o not in pre_objs]
    return post_objs


def export_selected_to_fbx(output_path: str, verbose: int = 0) -> None:
    # Ensure selection and active object are set; caller should have selected the objects to export
    # Build exporter kwargs and enable vertex color export if available
    kwargs = {
        "filepath": output_path,
        "use_selection": True,
        "object_types": {"MESH"},
        "global_scale": 1.0,
        "apply_unit_scale": True,
        "axis_forward": '-Z',
        "axis_up": 'Y',
    }

    # detect supported properties of the FBX exporter and enable any vertex-color flag
    try:
        prop_names = [p.identifier for p in bpy.ops.export_scene.fbx.bl_rna.properties if getattr(p, 'identifier', None)]
    except Exception:
        prop_names = []
    color_keys = ["use_vertex_colors", "use_colors", "use_vertex_color"]
    for k in color_keys:
        if k in prop_names:
            kwargs[k] = True
            break

    if verbose:
        print("FBX exporter kwargs:", kwargs)

    try:
        bpy.ops.export_scene.fbx(**kwargs)
    except Exception as e:
        exit_error(f"FBX export failed: {e}")


# -----------------
# Main flow
# -----------------

def main():
    args = parse_cli_args(sys.argv)

    inp = os.path.abspath(args.input)
    outp = os.path.abspath(args.output)

    # Setup optional simple logging helper
    log_fp = None
    def log(msg: str):
        print(msg)
        if args.log_file:
            nonlocal log_fp
            if log_fp is None:
                try:
                    log_fp = open(args.log_file, 'a', encoding='utf-8')
                except Exception:
                    log_fp = None
            if log_fp is not None:
                try:
                    log_fp.write(msg + "\n")
                    log_fp.flush()
                except Exception:
                    pass

    if not os.path.isfile(inp):
        exit_error(f"Input file not found: {inp}")

    # If not running inside Blender, fail with helpful instructions
    if not BLENDER_AVAILABLE:
        exit_error(
            "This script must be run inside Blender's Python environment.\nExample: blender --background --python convert_stl_to_fbx.py -- input.stl output.fbx"
        )

    try:
        # Basic scene cleanup so we export only the converted object(s)
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False, confirm=False)

        # Try Blender's importer first unless the user forced parsing
        created_objects: List[bpy.types.Object] = []
        colors_present = False

        if not args.force_parse:
            try:
                created_objects = try_import_with_blender_importer(inp)
                # check if any created mesh has vertex colors
                for o in created_objects:
                    if hasattr(o, 'data') and o.data is not None:
                        if mesh_has_vertex_colors(o.data):
                            colors_present = True
                            break
            except Exception as e:
                log(f"Warning: Blender importer attempt raised: {e}")

        if not created_objects or not colors_present:
            # Fall back to internal parser
            stl_type = detect_stl_type(inp)
            if args.verbose:
                log(f"Detected STL type: {stl_type}")
            if stl_type == 'binary':
                verts, faces, colors = parse_binary_stl(inp)
            else:
                verts, faces, colors = parse_ascii_stl(inp)

            if args.verbose:
                log(f"Parsed {len(verts)} verts, {len(faces)} faces. Colors present: {any(c is not None for c in colors)}")

            # Create object from parsed data
            obj = create_mesh_object(os.path.splitext(os.path.basename(inp))[0], verts, faces)
            # Add vertex colors if present or if uniform color requested
            if any(c is not None for c in colors):
                add_vertex_colors(obj.data, colors)
                colors_present = True
            else:
                if args.uniform_color:
                    rc = args.uniform_color
                    # normalize 0..255 -> 0..1 if needed
                    if any(v > 1.0 for v in rc):
                        rc = [v / 255.0 for v in rc]
                    uniform = (float(rc[0]), float(rc[1]), float(rc[2]), float(args.alpha))
                    add_vertex_colors(obj.data, [None] * len(faces), uniform=uniform)
                    colors_present = True
                else:
                    # no colors found and none requested: leave mesh without colors
                    colors_present = False
            created_objects = [obj]

        # Select objects to export
        for o in bpy.context.scene.objects:
            # default: deselect everything then select created_objects
            o.select_set(False)
        for o in created_objects:
            o.select_set(True)
            bpy.context.view_layer.objects.active = o

        # Ensure output directory exists
        out_dir = os.path.dirname(outp)
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                exit_error(f"Unable to create output directory {out_dir}: {e}")

        # Export with requested format
        fmt = (args.export_format or 'fbx').lower()
        if fmt == 'fbx':
            if args.verbose:
                log(f"Exporting FBX to: {outp}")
            export_selected_to_fbx(outp, args.verbose)
        elif fmt == 'gltf':
            if args.verbose:
                log(f"Exporting glTF to: {outp}")
            # build kwargs for glTF exporter
            kwargs = {
                'filepath': outp,
                'export_selected': True,
                'export_apply': True,
            }
            # try to enable vertex colors if exporter supports that option
            try:
                prop_names = [p.identifier for p in bpy.ops.export_scene.gltf.bl_rna.properties if getattr(p, 'identifier', None)]
            except Exception:
                prop_names = []
            if 'export_colors' in prop_names:
                kwargs['export_colors'] = True
            try:
                bpy.ops.export_scene.gltf(**kwargs)
            except Exception as e:
                exit_error(f"glTF export failed: {e}")
        else:
            exit_error(f"Unknown export format: {fmt}")

        # Verify output
        if os.path.isfile(outp):
            print(f"Exported {fmt.upper()} to: {outp}")
            if log_fp is not None:
                log_fp.close()
            sys.exit(0)
        else:
            exit_error(f"Export reported success but file not found: {outp}")

    except SystemExit:
        # allow explicit sys.exit to propagate
        if log_fp is not None:
            log_fp.close()
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        if args.log_file:
            try:
                with open(args.log_file, 'a', encoding='utf-8') as f:
                    f.write('UNHANDLED EXCEPTION:\n')
                    f.write(tb + '\n')
            except Exception:
                pass
        exit_error(f"Unhandled exception during conversion: {e}\nSee log for details.", code=99)


if __name__ == '__main__':
    main()
