@echo off
echo.
echo  ==========================================
echo   A.R.C.H.I.E. Node — Cleanup Old Install
echo  ==========================================
echo.
echo  This will:
echo    1. Stop ALL old ARCHIE containers
echo    2. Remove old images and volumes
echo    3. Free up disk space
echo.
echo  Your Ollama models will be re-downloaded
echo  on next start (they are stored in Docker volumes).
echo.
set /p CONFIRM="Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo Cancelled.
    pause
    exit /b
)
echo.
echo [1/4] Stopping old containers...
docker stop archie_starship_ollama archie_starship_db archie_starship_sync archie_starship_api archie_starship_comfyui archie_starship_tailscale 2>nul
docker stop archie_node_ollama archie_node_db archie_node_sync archie_node_api archie_node_comfyui 2>nul
echo.
echo [2/4] Removing old containers...
docker rm -f archie_starship_ollama archie_starship_db archie_starship_sync archie_starship_api archie_starship_comfyui archie_starship_tailscale 2>nul
docker rm -f archie_node_ollama archie_node_db archie_node_sync archie_node_api archie_node_comfyui 2>nul
echo.
echo [3/4] Pruning unused Docker data (images, volumes, build cache)...
docker system prune -af --volumes
echo.
echo [4/4] Done!
echo.
echo  Old install cleaned up. Now double-click start.bat to begin fresh.
echo.
pause
