@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHON_CMD="
py -3 --version >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD python --version >nul 2>&1 && set "PYTHON_CMD=python"
if not defined PYTHON_CMD exit /b 1
%PYTHON_CMD% -m unittest discover -s tests -v
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (echo RESULTADO FINAL: TESTS OK) else (echo RESULTADO FINAL: TESTS CON ERROR)
if /I not "%CI%"=="true" pause
exit /b %CODE%
