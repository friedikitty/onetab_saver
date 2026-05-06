@echo off
cd /d "%~dp0"

uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.stop()" 2>nul
if not exist "%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe" (
    echo Installing Playwright Chromium...
    uv run playwright install chromium
)

uv run python .\onetab_saver.py
pause
