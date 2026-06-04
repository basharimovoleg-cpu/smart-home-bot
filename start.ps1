$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

# Refresh PATH
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# Kill anything on port 8000
$portProc = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $portProc) {
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Write-Host "Killed process on port 8000 (PID $pid)"
}
Start-Sleep 1

# Kill old cloudflared
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1

Write-Host "Starting Cloudflare tunnel..." -ForegroundColor Cyan

# Start cloudflared and capture URL (output goes to stderr)
$cfProc = Start-Process -FilePath "cloudflared" -ArgumentList "tunnel","--url","http://127.0.0.1:8000" -NoNewWindow -PassThru -RedirectStandardError "$env:TEMP\cf-tunnel-err.log"

# Wait for tunnel URL from stderr
$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 2
    if (Test-Path "$env:TEMP\cf-tunnel-err.log") {
        $errContent = Get-Content "$env:TEMP\cf-tunnel-err.log" -Raw -ErrorAction SilentlyContinue
        if ($errContent -match 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com') {
            $tunnelUrl = $Matches[0]
            break
        }
    }
}

if (-not $tunnelUrl) {
    Write-Host "ERROR: Failed to get tunnel URL after 60s" -ForegroundColor Red
    Stop-Process -Id $cfProc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Tunnel URL: $tunnelUrl" -ForegroundColor Green

# Update .env
$envContent = Get-Content .env -Raw
$envContent = $envContent -replace '(?m)^BASE_URL=.*$', "BASE_URL=$tunnelUrl"
Set-Content .env -Value $envContent -NoNewline

Write-Host "Starting bot..." -ForegroundColor Cyan
python main.py
