[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '1.0.0',
    [ValidateSet('tiny', 'base', 'small', 'medium', 'large-v3')][string]$Model = 'small',
    [string]$InnoSetupCompiler = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot 'build\windows'
$bundle = Join-Path $buildRoot 'CorTranscript'
$cache = Join-Path $projectRoot '.packaging-cache'
$output = Join-Path $projectRoot 'dist'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "La commande a échoué ($LASTEXITCODE) : $Program" }
}
function Get-Download {
    param([string]$Url, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Destination)) {
        $temporary = "$Destination.partial"
        Invoke-WebRequest -Uri $Url -OutFile $temporary -UseBasicParsing
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    }
}

if ($env:OS -ne 'Windows_NT') { throw 'La construction du .exe doit être effectuée sous Windows x64.' }
# Fail before downloading models if a prerequisite is missing.
$python = (& py -3.11 -c 'import sys; print(sys.executable)')
if ($LASTEXITCODE -ne 0) { throw 'Installe Python 3.11 x64 depuis python.org (avec le lanceur py).' }
Invoke-Checked $python @('-c', "import struct; assert struct.calcsize('P') == 8, 'Python x64 requis'")
if (-not $InnoSetupCompiler) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
    )
    $InnoSetupCompiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $InnoSetupCompiler -or -not (Test-Path -LiteralPath $InnoSetupCompiler)) {
    throw 'Installe Inno Setup 6 : https://jrsoftware.org/isdl.php'
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path $buildRoot, $cache, $output | Out-Null
if (Test-Path -LiteralPath $bundle) { Remove-Item -LiteralPath $bundle -Recurse -Force }
New-Item -ItemType Directory -Force -Path "$bundle\app", "$bundle\runtime", "$bundle\bin", "$bundle\licenses" | Out-Null

Write-Host '[1/7] Préparation de Python embarqué et des dépendances CPU.'
$pythonZip = Join-Path $cache 'python-3.11.9-embed-amd64.zip'
Get-Download 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' $pythonZip
Expand-Archive -LiteralPath $pythonZip -DestinationPath "$bundle\runtime" -Force
# All paths are relative to python311._pth, so a Desktop path with spaces or
# accents works and the runtime does not depend on the developer's environment.
@('python311.zip', '.', 'Lib\site-packages', '..\app', 'import site') |
    Set-Content -LiteralPath "$bundle\runtime\python311._pth" -Encoding ASCII
$buildVenv = Join-Path $buildRoot 'tools'
Invoke-Checked $python @('-m', 'venv', $buildVenv)
$buildPython = Join-Path $buildVenv 'Scripts\python.exe'
Invoke-Checked $buildPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'pyinstaller==6.16.0')
Invoke-Checked $buildPython @('-m', 'pip', 'install', '--no-warn-script-location', '--ignore-installed',
    '--target', "$bundle\runtime\Lib\site-packages", '-r', "$projectRoot\packaging\requirements-windows.txt")

Write-Host '[2/7] Intégration de FFmpeg, DeepFilterNet et du runtime Microsoft.'
# Bundle an LGPL build and its shared libraries.
$release = Invoke-RestMethod 'https://api.github.com/repos/FFmpeg-Builds/FFmpeg-Builds/releases/tags/latest'
$asset = $release.assets | Where-Object { $_.name -eq 'ffmpeg-master-latest-win64-lgpl-shared.zip' } | Select-Object -First 1
if (-not $asset) { throw 'Archive FFmpeg Windows LGPL shared introuvable.' }
$ffmpegZip = Join-Path $cache "$($release.id)-ffmpeg-lgpl-shared.zip"
Get-Download $asset.browser_download_url $ffmpegZip
$ffmpegExtract = Join-Path $buildRoot 'ffmpeg'
if (Test-Path -LiteralPath $ffmpegExtract) { Remove-Item -LiteralPath $ffmpegExtract -Recurse -Force }
Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpegExtract
$ffmpegBin = Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
if (-not $ffmpegBin) { throw "ffmpeg.exe absent de l'archive." }
Copy-Item -Path (Join-Path $ffmpegBin.Directory.FullName '*') -Destination "$bundle\bin" -Recurse
Copy-Item -LiteralPath $ffmpegBin.Directory.Parent.FullName -Destination "$bundle\licenses\ffmpeg-distribution" -Recurse
# The duplicate binary directory is unnecessary; keep the distributor's license,
# source/build links and documentation next to the installed runtime.
Remove-Item -LiteralPath "$bundle\licenses\ffmpeg-distribution\bin" -Recurse -Force
$deepfilter = Join-Path $cache 'deep-filter-0.5.6-x86_64-pc-windows-msvc.exe'
Get-Download 'https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-pc-windows-msvc.exe' $deepfilter
Copy-Item -LiteralPath $deepfilter -Destination "$bundle\bin\deep-filter.exe"
$vcRuntime = Join-Path $cache 'vc_redist.x64.exe'
Get-Download 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcRuntime
Copy-Item -LiteralPath $vcRuntime -Destination "$bundle\vc_redist.x64.exe"

Write-Host '[3/7] Copie des seuls fichiers applicatifs (aucune donnée personnelle).'
Copy-Item -LiteralPath "$projectRoot\app.py", "$projectRoot\index.html", "$projectRoot\packaging\windows_server.py" -Destination "$bundle\app"
Copy-Item -LiteralPath "$projectRoot\packaging\THIRD_PARTY.md" -Destination "$bundle\licenses"
$runtimePython = Join-Path $bundle 'runtime\python.exe'
$previousPath = $env:PATH
try {
    $env:PATH = "$bundle\bin;$env:PATH"
    Write-Host '[4/7] Téléchargement et validation des modèles embarqués (cela peut être long).'
    Invoke-Checked $runtimePython @("$projectRoot\packaging\prepare_models.py", '--bundle', $bundle, '--model', $Model)
} finally {
    $env:PATH = $previousPath
}

Write-Host '[5/7] Création du lanceur CorTranscript.exe.'
Invoke-Checked $buildPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'CorTranscript', '--distpath', "$buildRoot\launcher", '--workpath', "$buildRoot\pyinstaller",
    '--specpath', $buildRoot, "$projectRoot\packaging\launcher.py")
Copy-Item -Path "$buildRoot\launcher\CorTranscript\*" -Destination $bundle -Recurse -Force
# Save exact transitive dependency versions and binary provenance with each build.
$manifest = & $buildPython -m pip list --path "$bundle\runtime\Lib\site-packages" --format=json
if ($LASTEXITCODE -ne 0) { throw 'Impossible de créer le manifeste des dépendances.' }
@{ version=$Version; model=$Model; python='3.11.9'; ffmpeg=$asset.browser_download_url; packages=($manifest | ConvertFrom-Json) } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$bundle\build-manifest.json" -Encoding UTF8

Write-Host '[6/7] Démarrage et test des trois moteurs et de la réduction de bruit.'
Invoke-Checked $buildPython @("$projectRoot\packaging\launcher.py", '--smoke-test')

Write-Host "[7/7] Création de l'installateur."
Invoke-Checked $InnoSetupCompiler @("/DAppVersion=$Version", "/DBundleDir=$bundle", "/DOutputDir=$output", "$projectRoot\packaging\CorTranscript.iss")
Write-Host "Terminé : $output\CorTranscript-Setup-$Version.exe"
