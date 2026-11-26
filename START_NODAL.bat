@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_nodal.ps1"
set "NODAL_EXIT=%ERRORLEVEL%"
if not "%NODAL_EXIT%"=="0" echo NODAL startup did not complete. Review the message above.
pause
exit /b %NODAL_EXIT%
