@echo off
cd /d "%~dp0.."
uv run python -m onetab_saver.onetab_saver
pause
