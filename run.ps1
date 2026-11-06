<#
  One command to install, build and start d2bg on Windows:   .\run.cmd   (or .\run.ps1)

  - Python 3.12 and the app's packages come from uv (it downloads Python if needed).
  - The browser UI is built with Node the first time, and again whenever web/ changes.
  - Then the app starts on http://127.0.0.1:4242 and opens your browser.

  Extra arguments go to `d2bg serve`, for example:  .\run.cmd --demo juggernaut   or   .\run.cmd --lan
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Already running? Open it instead of starting a second copy: the second could not take the port.
if (-not ($args -contains "--port")) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:4242/health" | Out-Null
        Write-Host "d2bg уже запущен. Открываю http://127.0.0.1:4242/ (окно с первым запуском не закрывайте)." -ForegroundColor Green
        Start-Process "http://127.0.0.1:4242/"
        exit 0
    }
    catch { }
}

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Не найдено: $cmd. $hint" -ForegroundColor Red
        exit 1
    }
}

Need "uv" "Установите:  winget install astral-sh.uv   (потом откройте новый терминал)"

Write-Host "Проверяю пакеты Python (первый запуск займёт около минуты)..."
uv sync --quiet --inexact
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $PSScriptRoot "src\d2bg\static\index.html"
$newestSource = Get-ChildItem -Path "web\src", "web\index.html", "web\package.json" -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$needBuild = -not (Test-Path $dist) -or ($newestSource.LastWriteTime -gt (Get-Item $dist).LastWriteTime)

if ($needBuild) {
    Need "npm" "Установите Node.js 20 или новее с https://nodejs.org (нужно один раз, чтобы собрать интерфейс)"
    Push-Location web
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "Устанавливаю пакеты интерфейса..."
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Write-Host "Собираю интерфейс..."
        npm run build --silent
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Приложение работает, пока открыто это окно. Остановить: Ctrl+C."
uv run d2bg serve @args
exit $LASTEXITCODE
