# Runs formatting checks, static analysis, and tests.
param()

$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run ./scripts/bootstrap.ps1 first."
}

& $venvPython -m ruff check .
& $venvPython -m mypy src
& $venvPython -m pytest -q

Write-Host "All checks passed."
