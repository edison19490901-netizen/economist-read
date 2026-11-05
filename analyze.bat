@echo off
chcp 65001 >nul
title Economist Read - Analyze
cd /d "%~dp0"
setlocal

set "PYTHONIOENCODING=utf-8"
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found. Install Python and add it to PATH.
        pause
        exit /b 1
    )
    set "PY=py"
)

rem Usage:
rem   double-click        -> find the text file in this folder automatically
rem   drag a file onto it -> analyze that file
rem   analyze.bat file --no-pause -> analyze without waiting at the end
set "TARGET=%~1"
set "NOPAUSE="
if /i "%~1"=="--no-pause" (
    set "TARGET="
    set "NOPAUSE=1"
)
if /i "%~2"=="--no-pause" set "NOPAUSE=1"

echo ============================================
echo   Economist Read - Analyze
echo ============================================
echo.

if "%TARGET%"=="" (
    "%PY%" tools\analyze_text.py --auto
) else (
    "%PY%" tools\analyze_text.py "%TARGET%"
)
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
    echo [FAILED] Analysis failed with exit code %CODE%.
) else (
    echo [DONE] Workbook generated and opened in your browser.
)

if not defined NOPAUSE pause
exit /b %CODE%
