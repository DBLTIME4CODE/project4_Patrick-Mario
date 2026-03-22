# Creates/updates local venv and installs all dependencies.
param()

$ErrorActionPreference = "Stop"

function Test-PythonCommand {
    param([string]$CommandName)

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        return $false
    }

    try {
        & $CommandName --version | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if (-not (Test-Path ".venv")) {
    # uv-installed Python (known location on this machine)
    $uvPython = "$env:APPDATA\uv\python\cpython-3.14.3-windows-x86_64-none\python.exe"

    if (Test-Path $uvPython) {
        & $uvPython -m venv .venv
    }
    elseif (Test-PythonCommand -CommandName "py") {
        py -m venv .venv
    }
    elseif (Test-PythonCommand -CommandName "python") {
        python -m venv .venv
    }
    else {
        throw "No Python interpreter found. Install Python or add it to PATH."
    }
}

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Expected virtual environment interpreter not found at $venvPython"
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython -m pip install -r requirements-dev.txt

Write-Host "Environment bootstrapped."
