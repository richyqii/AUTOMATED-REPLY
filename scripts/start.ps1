param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install dependencies first. See README.md.'
}
& $pythonPath -m app.manage check-meta
if ($LASTEXITCODE -ne 0) {
    Write-Output 'Meta sender check failed. Correct the test credentials and number in .env first.'
    exit 1
}
& $pythonPath -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --no-access-log
exit $LASTEXITCODE
