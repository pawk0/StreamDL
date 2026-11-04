@echo off
setlocal
set "VIDEO_DL_DEBUG=1"
echo [DEBUG] Detailed server diagnostics enabled.
call "%~dp0run_server.bat"
endlocal
