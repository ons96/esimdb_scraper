@echo off
setlocal
title eSIM France Plan Analysis (uv)

echo ===================================
echo   eSIM Plan Analyzer for France (uv)
echo ===================================
echo.

REM Ensure uv is available
where uv >nul 2>&1
if errorlevel 1 (
    echo 'uv' not found on PATH. Attempting to install via pip...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install --user uv
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Could not find or install 'uv'. Please install it and re-run:
        echo   pipx install uv   ^(recommended^)
        echo   or: python -m pip install --user uv
        pause
        exit /b 1
    )
)

set VENV_DIR=.venv
set VENV_PY=%VENV_DIR%\Scripts\python.exe

if not exist "%VENV_DIR%" (
    echo Creating virtual environment with uv...
    uv venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create venv with uv.
        pause
        exit /b 1
    )
)

echo Installing/updating required packages with uv pip...
uv pip install --python "%VENV_PY%" requests beautifulsoup4 pandas numpy
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Starting France eSIM plan analysis...
echo.
"%VENV_PY%" workflow_france.py
if errorlevel 1 (
  echo.
  echo ###################################
  echo   ERROR: Analysis failed.
  echo ###################################
  echo.
  echo See the error above. No results were written.
  endlocal
  pause
  exit /b 1
)

echo.
echo ===================================
echo   Analysis complete!
echo ===================================
echo.
echo Results saved in: scraped_data\
echo.
endlocal
pause
