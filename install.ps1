<# install.ps1 — One-click setup for the CareerHub auto-apply tool #>
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$VenvDir = ".\.venv"
$PythonExe = "$env:APPDATA\uv\python\cpython-3.14.3-windows-x86_64-none\python.exe"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " CareerHub Auto-Apply — Setup" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# --- Python check ---
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at $PythonExe`nAdjust the path in this script or install via uv."
    exit 1
}
Write-Host "[1/5] Python found at $PythonExe" -ForegroundColor Green

# --- Create venv if needed ---
if (-not (Test-Path $VenvDir)) {
    Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Cyan
    & $PythonExe -m venv $VenvDir
}
else {
    Write-Host "[2/5] Virtual environment already exists" -ForegroundColor Green
}

# --- Activate venv ---
Write-Host "[3/5] Activating venv..." -ForegroundColor Cyan
& "$VenvDir\Scripts\Activate.ps1"

# --- Install packages ---
Write-Host "[4/5] Installing Python packages..." -ForegroundColor Cyan
pip install --upgrade pip | Out-Null
pip install playwright pyyaml python-dotenv
pip install -e .

# --- Install Playwright browsers ---
Write-Host "[5/5] Installing Playwright browsers (this downloads Chromium/Edge)..." -ForegroundColor Cyan
Write-Host "       This may take a minute on first run..." -ForegroundColor Yellow
playwright install chromium

Write-Host "`n========================================" -ForegroundColor Green
Write-Host " Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nTo use the tool, run these commands:`n" -ForegroundColor White
Write-Host "  # Activate the venv first (if not already active):" -ForegroundColor Gray
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  # Search for matching jobs:" -ForegroundColor Gray
Write-Host "  python -m myproject.apply_cli --search-only" -ForegroundColor Yellow
Write-Host ""
Write-Host "  # Apply to a specific job:" -ForegroundColor Gray
Write-Host '  python -m myproject.apply_cli --job-url "https://careerhub.microsoft.com/careerhub/explore/jobs/1970393556621720"' -ForegroundColor Yellow
Write-Host ""
Write-Host "  # Search + apply interactively:" -ForegroundColor Gray
Write-Host "  python -m myproject.apply_cli" -ForegroundColor Yellow
Write-Host ""
