@echo off
setlocal
cd /d "%~dp0"
title CivicRouteAD - Community Infrastructure Reporting

echo ======================================================================
echo           CivicRouteAD - Community Infrastructure Reporting
echo      Resident Reports ^| Staff Dashboard ^| Video Analysis
echo ======================================================================
echo.

where python >nul 2>&1
if errorlevel 1 goto python_error
where npm >nul 2>&1
if errorlevel 1 goto node_error

echo [1/3] Checking backend Python packages...
python -c "import fastapi, uvicorn, cv2, gpxpy, ultralytics, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 (
  echo Installing backend packages for first run. Internet is required...
  python -m pip install -r backend\requirements.txt
  if errorlevel 1 goto backend_error
)

echo.
echo [Road model] Checking the optional RDD2022 pothole/road-crack detector...
python backend\download_road_model.py

echo.
echo [2/3] Checking frontend packages...
if not exist "frontend\node_modules\vite\bin\vite.js" (
  echo Installing frontend packages for first run. Internet is required...
  pushd frontend
  call npm install
  if errorlevel 1 (
    popd
    goto frontend_error
  )
  popd
)

echo.
echo Building the latest frontend files...
pushd frontend
call npm run build
if errorlevel 1 (
  popd
  goto build_error
)
call node scripts\verify-build.mjs
if errorlevel 1 (
  popd
  goto build_error
)
popd

echo.
echo [3/3] Starting CivicRouteAD. Browser: http://localhost:8000
echo Keep this window open while using the app. Press Ctrl+C to stop.
echo.
python run.py
pause
goto end

:python_error
echo ERROR: Python is not installed or not available in PATH.
echo Install Python 3.10 or newer, then reopen this file.
pause
goto end

:node_error
echo ERROR: Node.js/npm is not installed or not available in PATH.
echo Install the Node.js LTS version, then reopen this file.
pause
goto end

:backend_error
echo ERROR: Backend package installation failed. Check your internet connection and Python setup.
pause
goto end

:frontend_error
echo ERROR: Frontend package installation failed. Check your internet connection and npm setup.
pause
goto end

:build_error
echo ERROR: Frontend build failed. The error above should show the reason.
pause
goto end

:end
endlocal
