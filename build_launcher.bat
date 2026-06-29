@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHON_CMD="
py -3 --version >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  echo [ERROR] Instala Python 3 en la maquina de construccion.
  pause
  exit /b 1
)
if not exist ".venv_build\Scripts\python.exe" %PYTHON_CMD% -m venv .venv_build
call ".venv_build\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -r requirements_build.txt
if not exist "assets\futonhub.ico" certutil -decode "assets\futonhub.ico.b64" "assets\futonhub.ico" >nul
if not exist "assets\launcher_icon.png" certutil -decode "assets\launcher_icon.png.b64" "assets\launcher_icon.png" >nul
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "FutonHUB Launcher" ^
  --icon "assets\futonhub.ico" ^
  --version-file "assets\version_info.txt" ^
  --add-data "assets\launcher_icon.png;assets" ^
  main.py
if errorlevel 1 (
  echo RESULTADO FINAL: BUILD CON ERROR
  pause
  exit /b 1
)
for /f "usebackq tokens=*" %%H in (`certutil -hashfile "dist\FutonHUB Launcher.exe" SHA256 ^| findstr /R /V "hash CertUtil"`) do set "EXE_SHA=%%H"
>"dist\FutonHUB-Launcher.exe.sha256" echo %EXE_SHA: =%  FutonHUB-Launcher.exe
copy /Y "dist\FutonHUB Launcher.exe" "dist\FutonHUB-Launcher.exe" >nul
if exist "dist\FutonHUB Launcher.exe" del /Q "dist\FutonHUB Launcher.exe"
echo.
echo EXE generado en: %CD%\dist\FutonHUB-Launcher.exe
echo SHA-256: %CD%\dist\FutonHUB-Launcher.exe.sha256
echo RESULTADO FINAL: LAUNCHER EXE CREADO
pause
