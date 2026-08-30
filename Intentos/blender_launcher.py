"""
blender_launcher.py

Runs Blender in a supervised way to execute the convert_stl_to_fbx.py script.
Features:
- Runs Blender with timeout and captures stdout/stderr to per-run log files.
- Retries a configurable number of times on crash or timeout.
- Optionally falls back to exporting glTF if FBX export keeps failing.
- Writes a summary exit code and prints helpful messages.

Usage (example):
  python blender_launcher.py --blender "C:\\Program Files\\Blender Foundation\\Blender\\blender.exe" \
      --script convert_stl_to_fbx.py -- input.stl output.fbx -- --uniform-color 255 0 0

Notes:
- Arguments after "--" are forwarded to the Blender script.
- This launcher is intended to be run in a normal Python environment (not inside Blender).
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import os
import shutil
import time
from datetime import datetime


def parse_args():
    p = argparse.ArgumentParser(description="Supervise a Blender headless run of convert_stl_to_fbx.py")
    p.add_argument("--blender", default=None, help="Path to Blender; if omitted, it is searched in PATH and common Windows folders")
    p.add_argument("--script", default="convert_stl_to_fbx.py", help="Path to the Blender-side script to run")
    p.add_argument("--input", default=None, help="Input STL path")
    p.add_argument("--output", default=None, help="Desired output path (FBX or glTF)")
    p.add_argument("--timeout", type=int, default=60, help="Timeout in seconds for each Blender run (default: 60)")
    p.add_argument("--retries", type=int, default=2, help="Number of retries on failure (default: 2)")
    p.add_argument("--retry-delay", type=float, default=2.0, help="Seconds to wait between retries")
    p.add_argument("--log-dir", default="logs", help="Directory to write run logs")
    p.add_argument("--fallback-gltf", action="store_true", help="If FBX fails, attempt glTF export as a fallback")
    p.add_argument("--force-parse", action="store_true", help="Add --force-parse to the Blender script args to use internal parser")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--", dest="forward", nargs=argparse.REMAINDER, help="Arguments forwarded to Blender script (placed after --) ")
    args = p.parse_args()
    if not args.blender and not args.input and not args.output:
        p.print_help()
        print("\nEjemplo rápido:")
        print("  python blender_launcher.py --input example\\colored_example_binary.stl --output example\\salida.fbx")
        print("\nPara exportar por capas usa directamente stl_to_fbx_gui.py.")
        p.exit(2)
    missing = [name for name, value in (("--input", args.input), ("--output", args.output)) if not value]
    if missing:
        p.error("faltan argumentos: " + ", ".join(missing))
    return args


def find_blender() -> str | None:
    found = shutil.which("blender") or shutil.which("blender.exe")
    if found:
        return found
    roots = [os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")]
    for root in roots:
        if not root:
            continue
        base = os.path.join(root, "Blender Foundation")
        if os.path.isdir(base):
            versions = sorted(os.listdir(base), reverse=True)
            for version in versions:
                candidate = os.path.join(base, version, "blender.exe")
                if os.path.isfile(candidate):
                    return candidate
    return None


def write_run_logs(log_dir: str, tag: str, stdout: bytes, stderr: bytes):
    os.makedirs(log_dir, exist_ok=True)
    t = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(log_dir, f"{tag}_{t}.out.txt")
    err_path = os.path.join(log_dir, f"{tag}_{t}.err.txt")
    with open(out_path, 'wb') as f:
        f.write(stdout)
    with open(err_path, 'wb') as f:
        f.write(stderr)
    return out_path, err_path


def run_once(blender_exe: str, script: str, input_path: str, output_path: str, extra_args: list[str], timeout: int, log_dir: str, attempt_idx: int, verbose: bool=False):
    cmd = [blender_exe, '--background', '--python', script, '--', input_path, output_path]
    if extra_args:
        cmd.extend(extra_args)
    if verbose:
        print('Running:', ' '.join(cmd))
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        out_path, err_path = write_run_logs(log_dir, f"run{attempt_idx}", proc.stdout, proc.stderr)
        return proc.returncode, out_path, err_path
    except subprocess.TimeoutExpired as te:
        # subprocess.run with timeout kills the process on Python >=3.3
        stdout = te.stdout or b''
        stderr = te.stderr or b''
        out_path, err_path = write_run_logs(log_dir, f"timeout{attempt_idx}", stdout, stderr)
        return 124, out_path, err_path
    except Exception as e:
        # unexpected error invoking blender
        write_run_logs(log_dir, f"error{attempt_idx}", b'', str(e).encode('utf-8'))
        return 125, None, None


def main():
    args = parse_args()
    blender_exe = args.blender or find_blender()
    if not blender_exe:
        print("No se encontró Blender. Instálalo o indica su ruta con --blender.", file=sys.stderr)
        sys.exit(2)
    script = args.script
    input_path = args.input
    output_path = args.output
    timeout = args.timeout
    retries = max(0, args.retries)
    retry_delay = args.retry_delay
    log_dir = args.log_dir
    fallback_gltf = args.fallback_gltf
    force_parse = args.force_parse
    forward = args.forward or []

    # Build extra args forwarded to the Blender script
    extra = []
    # include --force-parse if requested
    if force_parse:
        extra.append('--force-parse')
    # forward user-specified extra arguments (they may include flags starting with --)
    if forward:
        # forward may start with '--', remove leading if present
        if forward[0] == '--':
            forward = forward[1:]
        extra.extend(forward)

    attempt = 0
    last_err = None
    while attempt <= retries:
        attempt += 1
        rc, out_path, err_path = run_once(blender_exe, script, input_path, output_path, extra, timeout, log_dir, attempt, args.verbose)
        if rc == 0 and os.path.isfile(output_path):
            print(f"Conversion succeeded on attempt {attempt}; output: {output_path}")
            print(f"Stdout log: {out_path}; Stderr log: {err_path}")
            sys.exit(0)
        else:
            last_err = rc
            print(f"Attempt {attempt} failed (code {rc}). See logs: {out_path}, {err_path}")
            if attempt <= retries:
                print(f"Retrying after {retry_delay} seconds...")
                time.sleep(retry_delay)

    # All retries exhausted
    print(f"All attempts failed (last exit code {last_err}).")

    if fallback_gltf:
        # Try again but request glTF output
        print("Attempting fallback: glTF export")
        # replace output extension if needed
        root, _ = os.path.splitext(output_path)
        gltf_out = root + '.gltf'
        extra_gltf = [*extra, '--export-format', 'gltf']
        rc2, out_path2, err_path2 = run_once(blender_exe, script, input_path, gltf_out, extra_gltf, timeout, log_dir, attempt + 1, args.verbose)
        if rc2 == 0 and os.path.isfile(gltf_out):
            print(f"Fallback glTF succeeded: {gltf_out}")
            print(f"Stdout log: {out_path2}; Stderr log: {err_path2}")
            sys.exit(0)
        else:
            print(f"Fallback glTF failed (code {rc2}). See logs: {out_path2}, {err_path2}")
            sys.exit(3)

    # nothing worked
    sys.exit(2)


if __name__ == '__main__':
    main()
