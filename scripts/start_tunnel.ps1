$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$ngrokCommand = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokCommand) { throw 'Install the official ngrok app from Microsoft Store first.' }
try {
    $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 3 -UseBasicParsing
    if ($health.StatusCode -ne 200) { throw 'FastAPI health check failed.' }
} catch {
    throw 'Start the FastAPI server first using scripts/start.ps1, then retry.'
}
$ngrokArguments = @('http', '8000')
if (Test-Path -LiteralPath '.env') {
    $tokenLine = Get-Content -LiteralPath '.env' |
        Where-Object { $_ -match '^NGROK_AUTHTOKEN=' } |
        Select-Object -Last 1
    $token = if ($tokenLine) { $tokenLine.Substring('NGROK_AUTHTOKEN='.Length).Trim() } else { '' }
    if ($token -and -not $token.StartsWith('replace_')) {
        $env:NGROK_AUTHTOKEN = $token
        $ngrokArguments += @('--config', (Join-Path $PSScriptRoot 'ngrok.yml'))
    }
    Remove-Variable token
}
Write-Output 'Starting ngrok for local port 8000. Keep this terminal open.'
& $ngrokCommand.Source @ngrokArguments
exit $LASTEXITCODE
