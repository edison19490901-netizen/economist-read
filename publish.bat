@echo off
chcp 65001 >nul
title Economist Read - Publish to GitHub
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

echo ============================================
echo   Economist Read - Publish to GitHub
echo   Rebuild docs/ and push docs/ + output/
echo ============================================
echo.

"%PY%" tools\publish_site.py --push
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
    echo [FAILED] Publish failed with exit code %CODE%. See git output above.
) else (
    echo [DONE] Published. GitHub Pages updates in about 1 minute.
)

rem Pass --no-pause to skip the wait (useful for automation).
if /i not "%~1"=="--no-pause" pause
exit /b %CODE%
