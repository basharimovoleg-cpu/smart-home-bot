# watch.ps1 — Следит за статусом Sisyphus и играет звук при завершении
# Запуск: powershell -ExecutionPolicy Bypass -File watch.ps1 -Url "https://xxx.trycloudflare.com"

param(
    [Parameter(Mandatory=$true)]
    [string]$Url
)

$StatusUrl = "$Url/api/sisyphus-status"
$SoundPath = "$env:SystemRoot\Media\Windows Exclamation.wav"
if (-not (Test-Path $SoundPath)) {
    $SoundPath = "$env:SystemRoot\Media\chimes.wav"
}
$LastStatus = ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sisyphus Watcher запущен" -ForegroundColor Cyan
Write-Host "  Стучусь к: $StatusUrl" -ForegroundColor Gray
Write-Host "  Каждые 5 сек, жду 'done'" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    try {
        $resp = Invoke-RestMethod -Uri $StatusUrl -TimeoutSec 5 -ErrorAction Stop
        $status = $resp.status
        $message = $resp.message

        if ($status -ne $LastStatus) {
            $LastStatus = $status
            $color = switch ($status) {
                "idle"    { "Gray" }
                "working" { "Yellow" }
                "done"    { "Green" }
                default   { "White" }
            }
            $label = switch ($status) {
                "idle"    { "○ Ожидание задачи..." }
                "working" { "▶ Работаю..." }
                "done"    { "● ГОТОВО!" }
                default   { "? $status" }
            }
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $label" -ForegroundColor $color
            if ($message) { Write-Host "  └ $message" -ForegroundColor $color }
        }

        if ($status -eq "done") {
            # Звук
            if (Test-Path $SoundPath) {
                (New-Object Media.SoundPlayer $SoundPath).Play()
            } else {
                [System.Console]::Beep(800, 500)
                Start-Sleep -Millis 200
                [System.Console]::Beep(1000, 500)
            }

            # MessageBox
            $wshell = New-Object -ComObject Wscript.Shell
            $wshell.Popup(
                "$message`n`nСтукнуться в терминал: работа завершена.",
                0,
                "Sisyphus — Готово!",
                0x40 + 0x1000
            ) | Out-Null

            # Сброс статуса обратно в idle (через сервер)
            try {
                $null = Invoke-RestMethod -Uri "$Url/api/sisyphus-status/idle" -Method Post -TimeoutSec 3
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Статус сброшен в idle" -ForegroundColor Gray
                $LastStatus = "idle"
            } catch {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Не удалось сбросить статус: $_" -ForegroundColor Red
            }
        }
    } catch {
        if ($LastStatus -ne "error") {
            $LastStatus = "error"
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ✗ Сервер недоступен: $_" -ForegroundColor Red
            Write-Host "  Повтор через 10 сек..." -ForegroundColor DarkYellow
        }
        Start-Sleep -Seconds 10
        continue
    }

    Start-Sleep -Seconds 5
}
