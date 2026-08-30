# Verify script for Windows (PowerShell). Requires 'blender' in PATH.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exampleStl = Join-Path $scriptDir 'example\colored_example_binary.stl'
$outFbx = Join-Path $scriptDir 'example\colored_example_binary.fbx'

# Generate example STLs
Write-Output "Generating example STL files..."
python "$scriptDir\example\generate_colored_stl.py"

# If you have blender in PATH you can pass its path to the launcher; otherwise set $blenderPath manually
$blenderPath = (Get-Command blender -ErrorAction SilentlyContinue).Source
if (-not $blenderPath) {
    Write-Error "Blender not found in PATH. Set the path to blender.exe in the $blenderPath variable near the top of this script and rerun."
    exit 1
}

# Use launcher to supervise Blender runs
$launcher = Join-Path $scriptDir 'blender_launcher.py'
$logDir = Join-Path $scriptDir 'logs'
$extraArgs = "--force-parse"

# Run launcher
Write-Output "Running launcher..."
python $launcher --blender `"$blenderPath`" --script `"$scriptDir\convert_stl_to_fbx.py`" --input `"$exampleStl`" --output `"$outFbx`" --log-dir `"$logDir`" --retries 2 --timeout 60 --retry-delay 2 --fallback-gltf -- $extraArgs

if (Test-Path $outFbx) {
    Write-Output "Success: $outFbx created"
    exit 0
} else {
    Write-Error "Failed: $outFbx not created. Check logs in $logDir"
    exit 2
}
