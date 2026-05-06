@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 && (py -3 launch.py %*) || (python launch.py %*)
endlocal
