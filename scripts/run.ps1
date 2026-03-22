# Runs the app entrypoint.
param()

$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run ./scripts/bootstrap.ps1 first."
}

$env:PYTHONPATH = "src"
& $venvPython -m myproject.main
