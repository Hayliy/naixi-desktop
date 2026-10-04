@echo off
REM ============================================================
REM Naixi Desktop - start backend + frontend dev server
REM Keep this window OPEN while developing.
REM Closing this window stops both processes.
REM
REM Backend port : 9845 (HTTP), 18400 (Gateway WS)
REM Frontend     : http://127.0.0.1:1420
REM ============================================================

setlocal

REM Resolve project root from this script's directory (ASCII-safe:
REM never hardcode a path with non-ASCII characters, cmd reads GBK).
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM Prefer the bundled embedded Python (has aiohttp). Fall back to system
REM python only if the embedded one is missing.
set "PY=%ROOT%\src-tauri\resources\python-embed\python.exe"
if not exist "%PY%" set "PY=python"

REM Already running?
netstat -ano | findstr /R /C:":9845 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Backend already listening on 9845
) else (
    echo [..] Starting backend...
    start "Naixi Backend" /D "%ROOT%\src-tauri\sidecar" "%PY%" naixi_api.py
)

REM Wait for the backend port
set /a WAITED=0
:WAIT_LOOP
netstat -ano | findstr /R /C:":9845 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto WAIT_OK
set /a WAITED+=1
if !WAITED! GEQ 30 (
    echo [FAIL] Backend did not open 9845 within 30s. Check the backend window.
    goto DONE
)
ping -n 2 127.0.0.1 >nul
goto WAIT_LOOP

:WAIT_OK
echo [OK] Backend is up

REM Frontend dev server
netstat -ano | findstr /R /C:":1420 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Frontend already listening on 1420
) else (
    echo [..] Starting frontend dev server...
    start "Naixi Frontend" /D "%ROOT%" cmd /c "npm run dev"
    set /a FWAITED=0
    :FWAIT_LOOP
    netstat -ano | findstr /R /C:":1420 .*LISTENING" >nul 2>&1
    if not errorlevel 1 goto FWAIT_OK
    set /a FWAITED+=1
    if !FWAITED! GEQ 40 (
        echo [WARN] Frontend not up yet. It may still be compiling.
        goto DONE
    )
    ping -n 2 127.0.0.1 >nul
    goto FWAIT_LOOP
    :FWAIT_OK
    echo [OK] Frontend is up
)

:DONE
echo.
echo ------------------------------------------------------------
echo  Open:  http://127.0.0.1:1420
echo  Then click the "Peering" item in the left nav.
echo  Keep this window open. Press Ctrl+C or close it to stop.
echo ------------------------------------------------------------
echo.

REM Keep the window alive so the child processes keep running
pause

endlocal