[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '1.1.0',
    [ValidateSet('tiny', 'base', 'small', 'medium', 'large-v3')][string]$Model = 'small',
    [string]$InnoSetupCompiler = '',
    [string]$PythonExecutable = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
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
# Check the actual interpreter instead of trusting the launcher or folder name.
function Test-Python311 {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    try {
        & $Candidate -c "import struct, sys; sys.exit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

$python = $null
if ($PythonExecutable) {
    if (-not (Test-Python311 $PythonExecutable)) {
        throw "Le fichier indique par -PythonExecutable doit etre un Python 3.11 x64 : $PythonExecutable"
    }
    $python = (Resolve-Path -LiteralPath $PythonExecutable).Path
} else {
    $pythonCandidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    # Standard Python registrations also cover installations in a custom folder.
    foreach ($key in @(
        'HKCU:\Software\Python\PythonCore\3.11\InstallPath',
        'HKLM:\Software\Python\PythonCore\3.11\InstallPath'
    )) {
        if (Test-Path -LiteralPath $key) {
            $installPath = (Get-Item -LiteralPath $key).GetValue('')
            if ($installPath) { $pythonCandidates += Join-Path $installPath 'python.exe' }
        }
    }
    foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
        if (Test-Python311 $candidate) { $python = $candidate; break }
    }
    if (-not $python) {
        $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($launcher) {
            try {
                $reportedPaths = @(& $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null)
                if ($LASTEXITCODE -eq 0) {
                    foreach ($candidate in $reportedPaths) {
                        if (Test-Python311 ([string]$candidate)) { $python = [string]$candidate; break }
                    }
                }
            } catch { } # An absent 3.11 must produce the installation message below.
        }
    }
}
if (-not $python) {
    throw "Python 3.11 x64 introuvable. Installe https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe puis relance build-windows.cmd. Tu peux conserver Python 3.10."
}
$pythonCheck = "import struct, sys; assert sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'CPython 3.11 x64 requis'; print('Python :', sys.version.split()[0], sys.executable)"
Invoke-Checked $python @('-c', $pythonCheck)
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
# Always recreate the tools environment: never reuse pip or launchers from a
# previous Python installation.
Invoke-Checked $python @('-m', 'venv', '--clear', $buildVenv)
$buildPython = Join-Path $buildVenv 'Scripts\python.exe'
Invoke-Checked $buildPython @('-c', $pythonCheck)
Invoke-Checked $buildPython @('-m', 'pip', '--isolated', 'install', '--upgrade', 'pip', 'pyinstaller==6.16.0')
# pip runs in the tools environment, but its target is the private CPython
# 3.11 x64 runtime. Specify every wheel compatibility tag explicitly.
Invoke-Checked $buildPython @('-m', 'pip', '--isolated', 'install', '--no-warn-script-location', '--ignore-installed',
    '--only-binary=:all:', '--platform', 'win_amd64', '--implementation', 'cp',
    '--python-version', '3.11.9', '--abi', 'cp311',
    '--target', "$bundle\runtime\Lib\site-packages", '-r', "$projectRoot\packaging\requirements-windows.txt")
$runtimePython = Join-Path $bundle 'runtime\python.exe'
Invoke-Checked $runtimePython @('-c', $pythonCheck)
# Catch an absent/incompatible PyAV extension before downloading the models.
$pyavCheck = "import pathlib, sys; print('Modules natifs PyAV :', [p.name for p in (pathlib.Path(sys.prefix) / 'Lib' / 'site-packages' / 'av').glob('_core*.pyd')]); import av, av._core; print('PyAV disponible :', av.__version__)"
Invoke-Checked $runtimePython @('-c', $pyavCheck)

Write-Host '[2/7] Intégration de DeepFilterNet et du runtime Microsoft.'
$deepfilter = Join-Path $cache 'deep-filter-0.5.6-x86_64-pc-windows-msvc.exe'
Get-Download 'https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-pc-windows-msvc.exe' $deepfilter
Copy-Item -LiteralPath $deepfilter -Destination "$bundle\bin\deep-filter.exe"
$vcRuntime = Join-Path $cache 'vc_redist.x64.exe'
Get-Download 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcRuntime
Copy-Item -LiteralPath $vcRuntime -Destination "$bundle\vc_redist.x64.exe"

Write-Host '[3/7] Copie des seuls fichiers applicatifs (aucune donnée personnelle).'
Copy-Item -LiteralPath "$projectRoot\app.py", "$projectRoot\index.html", "$projectRoot\audio-inputs.js", "$projectRoot\packaging\windows_server.py" -Destination "$bundle\app"
Copy-Item -LiteralPath "$projectRoot\packaging\THIRD_PARTY.md" -Destination "$bundle\licenses"
Write-Host '[4/7] Téléchargement et validation des modèles embarqués (cela peut être long).'
Invoke-Checked $runtimePython @("$projectRoot\packaging\prepare_models.py", '--bundle', $bundle, '--model', $Model)

Write-Host '[5/7] Création du lanceur CorTranscript.exe.'
Invoke-Checked $buildPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'CorTranscript', '--distpath', "$buildRoot\launcher", '--workpath', "$buildRoot\pyinstaller",
    '--specpath', $buildRoot, "$projectRoot\packaging\launcher.py")
Copy-Item -Path "$buildRoot\launcher\CorTranscript\*" -Destination $bundle -Recurse -Force
# Save exact transitive dependency versions and binary provenance with each build.
$manifest = & $buildPython -m pip list --path "$bundle\runtime\Lib\site-packages" --format=json
if ($LASTEXITCODE -ne 0) { throw 'Impossible de créer le manifeste des dépendances.' }
@{ version=$Version; model=$Model; python='3.11.9'; deepfilter='0.5.6'; packages=($manifest | ConvertFrom-Json) } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$bundle\build-manifest.json" -Encoding UTF8

Write-Host '[6/7] Démarrage et test de Kroko et de la réduction de bruit.'
Invoke-Checked $buildPython @("$projectRoot\packaging\launcher.py", '--smoke-test')

Write-Host "[7/7] Création de l'installateur."
Invoke-Checked $InnoSetupCompiler @("/DAppVersion=$Version", "/DBundleDir=$bundle", "/DOutputDir=$output", "$projectRoot\packaging\CorTranscript.iss")
Write-Host "Terminé : $output\CorTranscript-Setup-$Version.exe"
