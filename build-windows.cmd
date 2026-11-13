@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo La construction a echoue. Consulte le message ci-dessus.
  pause
  exit /b 1
)
echo.
echo Installateur disponible dans le dossier dist.
pause
