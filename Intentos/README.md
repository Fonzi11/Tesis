STL → FBX (with vertex colors)
================================

This repository provides a Blender-based tool to convert STL files (including common color-extended variants) into FBX files while preserving vertex/face colors.

También incluye una interfaz gráfica para exportar el STL como un FBX independiente por cada capa horizontal.

Files
-----
- convert_stl_to_fbx.py — Main script intended to be run inside Blender:
  blender --background --python convert_stl_to_fbx.py -- input.stl output.fbx
- example/generate_colored_stl.py — Helper that writes small example STL files (binary with color attribute and ASCII with per-vertex colors).
- verify.sh, verify.ps1 — Example verification scripts that run the conversion in headless Blender (if Blender is installed).
- stl_to_fbx_gui.py — Interfaz gráfica para seleccionar el STL, la altura de capa y la carpeta de salida.
- convert_stl_to_fbx_layers.py — Script de Blender usado por la interfaz para cortar y exportar las capas.

Interfaz por capas
------------------
Ejecuta:

  python stl_to_fbx_gui.py

Selecciona el STL de 3D Slicer, indica la altura en las mismas unidades del modelo y pulsa **Convertir a FBX**. Se crearán archivos como `modelo_capa_0001.fbx` en la carpeta elegida. Blender debe estar instalado; la interfaz lo busca en el PATH y en las carpetas habituales de Windows.

Key features
------------
- Uses Blender's Python API (bpy) and prefers Blender's built-in STL importer.
- If Blender's importer does not preserve colors (some versions drop color info), the script falls back to an internal parser:
  - Binary STL color extension: checks the 2-byte attribute word per triangle (0x8000 flag + 15-bit R/G/B packed as 5:5:5) — commonly used by some exporters.
  - ASCII extension heuristic: recognizes vertex lines with trailing R G B values (either 0..1 floats or 0..255 integers).
- Adds colors to a vertex-color layer (supports both older `mesh.vertex_colors` API and newer `mesh.color_attributes` API).
- Exports FBX with vertex colors enabled when the FBX exporter exposes a relevant option.
- CLI option to apply a uniform color if no colors are found: --uniform-color R G B (0..1 or 0..255), and --alpha for alpha.

Usage
-----
1) Install Blender
   - Windows: download from https://www.blender.org/download/ and either add blender.exe to your PATH or use the full path when calling.
   - macOS: install the .dmg or use Homebrew cask: brew install --cask blender
   - Linux: install via your package manager or download from blender.org. Ensure the `blender` binary is in PATH.

2) Generate an example STL (optional)
   python example\generate_colored_stl.py
   This writes example/colored_example_binary.stl and example/colored_example_ascii.stl

3) Convert with Blender (headless) — direct method
   blender --background --python convert_stl_to_fbx.py -- example/colored_example_binary.stl example/colored_example_binary.fbx

   Or apply a uniform color if the STL has no colors:
   blender --background --python convert_stl_to_fbx.py -- example/colored_example_ascii.stl example/out.fbx --uniform-color 255 128 0 --alpha 1.0

Supervised launcher (recommended if Blender crashes)
-----------------------------------------------
If Blender has been unstable in your environment (crashes, hangs), use the provided `blender_launcher.py` that runs Blender in a supervised subprocess, captures logs, retries on failure, and can attempt a glTF fallback if FBX export fails.

Example (Windows PowerShell):
  python blender_launcher.py --blender "C:\\Program Files\\Blender Foundation\\Blender\\blender.exe" --script convert_stl_to_fbx.py --input example\colored_example_binary.stl --output example\colored_example_binary.fbx --log-dir logs --retries 2 --timeout 60 --retry-delay 2 --fallback-gltf -- --force-parse

Example (Unix / macOS):
  python3 blender_launcher.py --blender /usr/bin/blender --script convert_stl_to_fbx.py --input example/colored_example_binary.stl --output example/colored_example_binary.fbx --log-dir logs --retries 2 --timeout 60 --retry-delay 2 --fallback-gltf -- --force-parse

The launcher writes per-run stdout/stderr logs into the `logs/` directory and returns a non-zero exit code when all attempts fail. See `verify.ps1` and `verify.sh` which call the launcher by default.

Notes on STL color variants and limitations
------------------------------------------
- Binary STL color extension (attribute word): Many exporters use the 2-byte attribute word to store color: a common scheme sets bit 15 (0x8000) and packs 5 bits per RGB channel into the lower 15 bits. This encodes a single color per triangle. The internal parser decodes this scheme and assigns the same color to the triangle's corners.

- ASCII variants: There is no official ASCII STL color standard. Some tools append R G B values to vertex lines ("vertex x y z R G B"). The parser recognizes this heuristically. If your ASCII STL encodes color in another way, the fallback parser may not detect it.

- Per-vertex vs per-face: STL is a triangle-only format and usually duplicates vertices per triangle; color information in many STL variants is per-face. If your input encodes per-face colors differently from per-vertex colors, the script will place colors on the mesh corners (Blender's loop/color attribute). The FBX exporter may convert or duplicate vertices as needed when exporting — the end FBX should contain vertex colors, but tools reading the FBX may interpret them as per-vertex or per-corner colors depending on the reader.

- If an STL truly has no color information, use --uniform-color to apply a fallback.

Alternatives
------------
If Blender is not suitable for your environment, consider:
- Autodesk FBX SDK (C++ / Python bindings) — more low-level, steeper learning curve.
- Assimp / pyassimp — can read/write many formats but may not round-trip STL color variants reliably.

Example verification
--------------------
- On Linux/macOS (bash):
  ./verify.sh

- On Windows (PowerShell):
  .\verify.ps1

Both scripts try to run Blender in headless mode to convert example STLs. If Blender is not installed, they print instructions.

Support
-------
If you hit issues with a particular STL file, please share the file (or a small anonymized sample) and indicate whether it's ASCII or binary.


