# DonoTranscode - installation : environnement Python + PySide6 + ffmpeg
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=== DonoTranscode : installation ===" -ForegroundColor Cyan

# 1. Python 3.11 a 3.13
function Find-Python {
    foreach ($v in "3.11", "3.12", "3.13") {
        try {
            & py "-$v" -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return @("py", "-$v") }
        } catch {}
    }
    try {
        $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -in @("3.11", "3.12", "3.13")) { return @("python") }
    } catch {}
    return $null
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $py = @(Find-Python)
    if ($py.Count -eq 0 -or -not $py[0]) {
        Write-Host "Python 3.11, 3.12 ou 3.13 est introuvable." -ForegroundColor Red
        Write-Host "Installe-le avec :  winget install Python.Python.3.11   puis relance install.bat"
        exit 1
    }
    $exe = $py[0]
    $pyArgs = @($py | Select-Object -Skip 1)
    Write-Host "[1/3] Creation de l'environnement Python ($($py -join ' '))..."
    & $exe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Echec de la creation de .venv" }
} else {
    Write-Host "[1/3] Environnement Python deja present."
}

# 2. Dependances
Write-Host "[2/3] Installation de PySide6..."
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Echec de l'installation des dependances" }

# 3. ffmpeg
New-Item -ItemType Directory -Force bin | Out-Null
if ((Test-Path "bin\ffmpeg.exe") -and (Test-Path "bin\ffprobe.exe")) {
    Write-Host "[3/3] ffmpeg deja present dans bin\."
} else {
    $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $zip = Join-Path $env:TEMP "dono_ffmpeg.zip"
    $dir = Join-Path $env:TEMP "dono_ffmpeg"
    Write-Host "[3/3] Telechargement de ffmpeg (~200 Mo, build BtbN GPL)..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    Expand-Archive -Path $zip -DestinationPath $dir
    $binDir = Get-ChildItem -Path $dir -Recurse -Directory -Filter bin | Select-Object -First 1
    Copy-Item (Join-Path $binDir.FullName "ffmpeg.exe") bin\
    Copy-Item (Join-Path $binDir.FullName "ffprobe.exe") bin\
    Remove-Item -Force $zip
    Remove-Item -Recurse -Force $dir
}

Write-Host ""
Write-Host "Installation terminee. Lance l'appli avec 'Lancer DonoTranscode.bat'." -ForegroundColor Green
